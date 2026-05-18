"""Unit tests for Stream 1 H.8 -- base ontology imports recording.

Two surfaces are covered:

* ``_record_base_ontology_imports`` -- the post-success helper that
  writes ``imports`` edges from a newly-registered ontology to every
  base the user declared on the extraction request. Defensive: a bad
  base id skips that one edge, never the whole batch.
* ``create_run_record`` -- now persists ``base_ontology_ids`` alongside
  ``domain_ontology_ids`` so retries and post-restart resumes pick them
  up.
* ``start_extraction`` route -- passes ``base_ontology_ids`` through
  separately from the (existing) ``domain_ontology_ids``.

The execute_run integration (the helper being called post-success)
is covered structurally here via a focused execute_run unit test; a
full end-to-end integration test lives under
``tests/integration/`` and runs against ArangoDB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.db.temporal_constants import NEVER_EXPIRES

# --- _record_base_ontology_imports -----------------------------------------


def _mock_db_for_imports(
    *,
    has_imports: bool = True,
    registry_entries: dict[str, dict[str, Any]] | None = None,
    aql_responses: dict[str, list[Any]] | None = None,
) -> MagicMock:
    """Mock DB tuned for ``_record_base_ontology_imports``.

    ``aql_responses`` keys are substrings of the query text; the first
    matching key wins. Other queries return an empty cursor so future
    helper additions don't crash.
    """
    db = MagicMock()
    db.has_collection.side_effect = lambda n: not (n == "imports" and not has_imports)

    registry_entries = registry_entries or {}

    aql_responses = aql_responses or {}

    def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        for needle, rows in aql_responses.items():
            if needle in query:
                return iter(list(rows))
        return iter([])

    db.aql.execute.side_effect = _execute
    return db


@pytest.fixture()
def _patch_repos():
    with (
        patch("app.db.registry_repo.get_registry_entry") as mock_get_entry,
        patch("app.db.ontology_repo.create_edge") as mock_create_edge,
    ):
        mock_create_edge.return_value = {"_key": "edge-stub"}
        yield mock_get_entry, mock_create_edge


class TestRecordBaseOntologyImports:
    def test_empty_base_ids_is_noop(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        db = _mock_db_for_imports()
        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=[],
            run_id="run-1",
        )

        assert summary == {
            "created": [],
            "missing": [],
            "self": [],
            "duplicate": [],
            "cycle": [],
        }
        _, mock_create_edge = _patch_repos
        mock_create_edge.assert_not_called()

    def test_missing_imports_collection_buckets_everything_as_missing(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        db = _mock_db_for_imports(has_imports=False)
        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf", "skos"],
            run_id="run-2",
        )

        # When the substrate is gone, every base lands in `missing` so
        # the run summary reflects reality rather than silently dropping.
        assert summary["missing"] == ["foaf", "skos"]
        _, mock_create_edge = _patch_repos
        mock_create_edge.assert_not_called()

    def test_creates_edge_for_each_valid_base(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, mock_create_edge = _patch_repos
        mock_get_entry.side_effect = lambda key, **kw: {
            "_key": key,
            "uri": f"http://example.org/{key}#",
        }
        db = _mock_db_for_imports()

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf", "dcterms"],
            run_id="run-3",
        )

        assert summary["created"] == ["foaf", "dcterms"]
        assert mock_create_edge.call_count == 2
        # Each edge must record the target's URI for OWL serialization.
        kwargs_seen = [c.kwargs for c in mock_create_edge.mock_calls]
        iris = [k["data"]["import_iri"] for k in kwargs_seen]
        assert iris == ["http://example.org/foaf#", "http://example.org/dcterms#"]

    def test_self_import_is_skipped(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, _mock_create_edge = _patch_repos
        mock_get_entry.return_value = {"_key": "new_ont", "uri": "http://x/"}
        db = _mock_db_for_imports()

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["new_ont", "foaf"],
            run_id="run-4",
        )

        assert summary["self"] == ["new_ont"]
        # `foaf` was missing in registry (default mock returns the same
        # entry shape regardless of key -- here the registry mock would
        # still treat foaf as present). Override to confirm:
        mock_get_entry.side_effect = lambda key, **kw: (
            {"_key": key, "uri": "u"} if key == "foaf" else None
        )
        summary2 = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["new_ont", "foaf"],
            run_id="run-4b",
        )
        assert summary2["self"] == ["new_ont"]
        assert "foaf" in summary2["created"]

    def test_missing_base_is_skipped(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, mock_create_edge = _patch_repos
        mock_get_entry.return_value = None
        db = _mock_db_for_imports()

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["ghost"],
            run_id="run-5",
        )

        assert summary["missing"] == ["ghost"]
        mock_create_edge.assert_not_called()

    def test_duplicate_base_is_skipped(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, mock_create_edge = _patch_repos
        mock_get_entry.return_value = {"_key": "foaf", "uri": "http://x/"}
        # First AQL needle the helper hits is the duplicate-check; return
        # a non-empty result so the helper treats it as duplicate.
        db = _mock_db_for_imports(
            aql_responses={"FILTER e._from == @f AND e._to == @t": ["existing_edge"]}
        )

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf"],
            run_id="run-6",
        )

        assert summary["duplicate"] == ["foaf"]
        mock_create_edge.assert_not_called()

    def test_cycle_creating_base_is_skipped(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, mock_create_edge = _patch_repos
        mock_get_entry.return_value = {"_key": "foaf", "uri": "http://x/"}
        db = _mock_db_for_imports(
            aql_responses={
                # Duplicate-check empty -> proceeds to cycle-check.
                "FILTER e._from == @f AND e._to == @t": [],
                # Cycle check finds the source in the target's downstream
                # closure; helper must skip.
                "FOR v IN 1..10 OUTBOUND": [True],
            }
        )

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf"],
            run_id="run-7",
        )

        assert summary["cycle"] == ["foaf"]
        mock_create_edge.assert_not_called()

    def test_one_bad_base_does_not_block_the_rest(self, _patch_repos) -> None:
        from app.services.extraction import _record_base_ontology_imports

        mock_get_entry, mock_create_edge = _patch_repos
        mock_get_entry.side_effect = lambda key, **kw: (
            None if key == "ghost" else {"_key": key, "uri": f"http://{key}/"}
        )
        db = _mock_db_for_imports()

        summary = _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf", "ghost", "skos"],
            run_id="run-8",
        )

        # foaf + skos succeed, ghost is the only one bucketed missing.
        assert summary["created"] == ["foaf", "skos"]
        assert summary["missing"] == ["ghost"]
        assert mock_create_edge.call_count == 2

    def test_edge_uses_never_expires_filter(self, _patch_repos) -> None:
        """The dedupe query must filter by expired==NEVER_EXPIRES so a
        previously-removed (soft-deleted) edge does not block a fresh
        creation.
        """
        from app.services.extraction import _record_base_ontology_imports

        captured: list[dict[str, Any]] = []

        mock_get_entry, _ = _patch_repos
        mock_get_entry.return_value = {"_key": "foaf", "uri": "http://x/"}

        db = MagicMock()
        db.has_collection.return_value = True

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append({"query": query, "bind_vars": bind_vars or {}})
            return iter([])

        db.aql.execute.side_effect = _execute
        _record_base_ontology_imports(
            db,
            ontology_id="new_ont",
            base_ontology_ids=["foaf"],
            run_id="run-9",
        )

        dedupe = next(c for c in captured if "FILTER e._from == @f AND e._to == @t" in c["query"])
        assert dedupe["bind_vars"]["never"] == NEVER_EXPIRES


# --- create_run_record persistence -----------------------------------------


class TestCreateRunRecordBaseOntologyIds:
    """``base_ontology_ids`` must be persisted distinctly so an
    extraction retry (which re-reads the run record) sees them.
    """

    def test_base_ontology_ids_persisted_when_provided(self) -> None:
        from app.services.extraction import create_run_record

        inserted: list[dict[str, Any]] = []

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()

        def _insert(record: dict[str, Any]) -> dict[str, str]:
            inserted.append(record)
            return {"_key": record["_key"]}

        col.insert.side_effect = _insert
        db.collection.return_value = col

        with patch("app.services.extraction._load_document_chunks", return_value=[]):
            create_run_record(
                db,
                document_ids=["doc-1"],
                base_ontology_ids=["foaf", "dcterms"],
            )

        assert inserted, "run record was never inserted"
        assert inserted[0].get("base_ontology_ids") == ["foaf", "dcterms"]

    def test_base_ontology_ids_absent_when_not_provided(self) -> None:
        from app.services.extraction import create_run_record

        inserted: list[dict[str, Any]] = []

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.insert.side_effect = lambda r: (inserted.append(r), {"_key": r["_key"]})[1]
        db.collection.return_value = col

        with patch("app.services.extraction._load_document_chunks", return_value=[]):
            create_run_record(db, document_ids=["doc-2"])

        # No empty-list noise on the record -- absent means absent.
        assert "base_ontology_ids" not in inserted[0]


# --- /api/v1/extraction/run route ------------------------------------------


class TestStartExtractionPassesBaseOntologyIds:
    def test_route_passes_base_ontology_ids_to_service(self) -> None:
        """Two service entrypoints must receive the same list: the
        synchronous record-creation and the background execute.
        """
        from fastapi.testclient import TestClient

        with (
            patch("app.api.extraction.get_db") as mock_get_db,
            patch("app.api.extraction.extraction_service") as mock_service,
            patch("app.api.extraction._resolve_doc_ids", return_value=["doc-1"]),
        ):
            mock_get_db.return_value = MagicMock()
            mock_service.create_run_record.return_value = {
                "_key": "run-42",
                "status": "running",
            }

            from app.main import app

            client = TestClient(app)
            resp = client.post(
                "/api/v1/extraction/run",
                json={
                    "document_id": "doc-1",
                    "base_ontology_ids": ["foaf", "dcterms"],
                },
            )

        assert resp.status_code == 200
        assert resp.json()["run_id"] == "run-42"

        create_kwargs = mock_service.create_run_record.call_args.kwargs
        assert create_kwargs["base_ontology_ids"] == ["foaf", "dcterms"]

        # Execute is registered as a BackgroundTask -- BackgroundTasks
        # in TestClient are invoked synchronously after the response, so
        # the mock's execute_run gets called.
        execute_kwargs = mock_service.execute_run.call_args.kwargs
        assert execute_kwargs["base_ontology_ids"] == ["foaf", "dcterms"]
