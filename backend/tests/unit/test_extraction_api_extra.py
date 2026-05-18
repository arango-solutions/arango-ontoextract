"""Additional unit tests for extraction API route handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.extraction import (
    StartRunRequest,
    _resolve_doc_ids,
    delete_run,
    get_run,
    get_run_cost,
    get_run_results,
    get_run_steps,
    list_runs,
    retry_run,
    start_extraction,
)


class TestResolveDocIds:
    def test_raises_when_no_document_ids(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_doc_ids(StartRunRequest())
        assert exc.value.status_code == 422

    def test_raises_when_document_missing(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.doc_get", return_value=None),
            pytest.raises(HTTPException) as exc,
        ):
            _resolve_doc_ids(StartRunRequest(document_id="d1"))
        assert "not found" in exc.value.detail

    def test_raises_when_document_not_ready(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.doc_get", return_value={"_key": "d1", "status": "processing"}
            ),
            pytest.raises(HTTPException) as exc,
        ):
            _resolve_doc_ids(StartRunRequest(document_id="d1"))
        assert "not ready" in exc.value.detail

    def test_returns_unique_ready_ids(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.doc_get", return_value={"_key": "d1", "status": "ready"}),
        ):
            result = _resolve_doc_ids(StartRunRequest(document_id="d1", document_ids=["d1", "d2"]))
        assert result == ["d1", "d2"]


class TestExtractionRoutes:
    @pytest.mark.asyncio
    async def test_start_extraction_creates_run_and_background_task(self):
        body = StartRunRequest(document_id="d1", config={"passes": 2}, target_ontology_id="onto1")
        background_tasks = BackgroundTasks()
        with (
            patch("app.api.extraction._resolve_doc_ids", return_value=["d1"]),
            patch("app.api.extraction.get_db", return_value=MagicMock()),
            patch(
                "app.api.extraction.extraction_service.create_run_record",
                return_value={"_key": "r1", "status": "queued"},
            ) as mock_create,
        ):
            result = await start_extraction(body, background_tasks)
        mock_create.assert_called_once()
        assert result.run_id == "r1"
        assert result.doc_id == "d1"
        assert len(background_tasks.tasks) == 1

    @pytest.mark.asyncio
    async def test_list_runs_enriches_documents_and_per_run_stats(self):
        """Document name + chunk count come from doc_get; per-run
        ``classes_extracted`` / ``properties_extracted`` come from
        ``run.stats`` (set by the extractor agent during the run)
        and MUST NOT be overwritten by ontology-wide totals.

        The earlier shape of this test asserted the buggy behaviour
        where the route re-counted the live target ontology and
        clobbered the per-run values; see the route's enrichment
        comment for the bug rationale.
        """
        db = MagicMock()
        db.has_collection.return_value = True
        documents = MagicMock()
        db.collection.return_value = documents
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": [
                {
                    "_key": "r1",
                    "doc_ids": ["d1"],
                    "stats": {
                        "errors": [],
                        "classes_extracted": 7,
                        "properties_extracted": 11,
                    },
                    "started_at": 1,
                    "completed_at": 2,
                }
            ],
            "cursor": None,
            "has_more": False,
            "total_count": 1,
        }
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.list_runs",
                return_value=paginated,
            ),
            patch(
                "app.api.extraction.doc_get",
                return_value={
                    "_key": "d1",
                    "filename": "doc.md",
                    "chunk_count": 4,
                },
            ),
            # Exactly ONE run_aql call is now expected: the
            # ontology_registry lookup that resolves ontology_id.
            # If a future refactor re-adds count overrides, this
            # side_effect will run out and the test fails loudly.
            patch(
                "app.api.extraction.run_aql",
                side_effect=[["onto1"]],
            ),
        ):
            result = await list_runs(limit=10)
        run = result["data"][0]
        assert run["document_name"] == "doc.md"
        assert run["chunk_count"] == 4
        # Per-run stats survive untouched.
        assert run["classes_extracted"] == 7
        assert run["properties_extracted"] == 11
        assert run["duration_ms"] == 1000
        # Ontology link still enriched.
        assert run["ontology_id"] == "onto1"

    @pytest.mark.asyncio
    async def test_list_runs_does_not_query_legacy_ontology_properties(self):
        """Regression: the previous override block queried
        ``ontology_properties`` (the empty pre-PGT-split collection),
        which always returned 0 and silently zeroed every run's
        ``properties_extracted``. The new enrichment should only
        touch ``ontology_registry`` -- if a future change reintroduces
        a query against ``ontology_properties`` (or any other
        collection), this test fails because the captured AQL doesn't
        match the expected single registry lookup.
        """
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = MagicMock()
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": [
                {
                    "_key": "r1",
                    "doc_ids": [],
                    "stats": {
                        "errors": [],
                        "classes_extracted": 42,
                        "properties_extracted": 99,
                    },
                }
            ],
            "cursor": None,
            "has_more": False,
            "total_count": 1,
        }

        captured_queries: list[str] = []

        def capture_aql(_db, query, bind_vars=None, **_kw):
            captured_queries.append(query)
            return iter(["onto1"])

        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.list_runs",
                return_value=paginated,
            ),
            patch("app.api.extraction.doc_get", return_value=None),
            patch("app.api.extraction.run_aql", side_effect=capture_aql),
        ):
            result = await list_runs(limit=10)

        run = result["data"][0]
        # Per-run stats never overwritten by a "live count" query.
        assert run["classes_extracted"] == 42
        assert run["properties_extracted"] == 99
        # No query against the legacy property collections, no query
        # against ontology_classes for a count.
        joined = "\n".join(captured_queries)
        assert "ontology_properties" not in joined
        assert "ontology_object_properties" not in joined
        assert "ontology_datatype_properties" not in joined
        assert "COLLECT WITH COUNT" not in joined
        # And exactly one query: the registry lookup.
        assert len(captured_queries) == 1
        assert "ontology_registry" in captured_queries[0]

    @pytest.mark.asyncio
    async def test_list_runs_falls_back_to_target_ontology_id(self):
        """When the registry lookup yields no row (e.g. an in-flight
        run before the registry write happens, or a failed run that
        never produced an ontology), ``ontology_id`` should fall back
        to the user-requested ``target_ontology_id`` so the Pipeline
        Monitor can still link the run card to a sensible ontology."""
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = MagicMock()
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": [
                {
                    "_key": "r1",
                    "doc_ids": [],
                    "stats": {"errors": []},
                    "target_ontology_id": "target-onto",
                }
            ],
            "cursor": None,
            "has_more": False,
            "total_count": 1,
        }
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.list_runs",
                return_value=paginated,
            ),
            patch("app.api.extraction.doc_get", return_value=None),
            # Empty cursor -- no registry row exists yet.
            patch("app.api.extraction.run_aql", side_effect=[[]]),
        ):
            result = await list_runs(limit=10)
        assert result["data"][0]["ontology_id"] == "target-onto"

    @pytest.mark.asyncio
    async def test_get_run_delegates(self):
        expected = {"_key": "r1", "status": "completed"}
        with (
            patch("app.api.extraction.get_db", return_value=MagicMock()),
            patch("app.api.extraction.extraction_service.get_run", return_value=expected),
        ):
            result = await get_run("r1")
        assert result is expected

    @pytest.mark.asyncio
    async def test_delete_run_deletes_run_and_results(self):
        db = MagicMock()
        col = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = col
        col.has.side_effect = lambda key: True
        with patch("app.api.extraction.get_db", return_value=db):
            result = await delete_run("r1")
        assert result == {"deleted": True, "run_id": "r1"}
        assert col.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_run_raises_when_missing(self):
        db = MagicMock()
        col = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = col
        col.has.return_value = False
        with (
            patch("app.api.extraction.get_db", return_value=db),
            pytest.raises(HTTPException) as exc,
        ):
            await delete_run("r1")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_steps_results_retry_and_cost_delegate(self):
        db = MagicMock()
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.get_run_steps",
                return_value=[{"step": "extractor"}],
            ),
            patch(
                "app.api.extraction.extraction_service.get_run_results",
                return_value={"classes": []},
            ),
            patch(
                "app.api.extraction.extraction_service.retry_run",
                new=AsyncMock(return_value={"_key": "r2", "status": "queued"}),
            ),
            patch("app.api.extraction.extraction_service.get_run_cost", return_value={"usd": 1.23}),
        ):
            steps = await get_run_steps("r1")
            results = await get_run_results("r1")
            retry = await retry_run("r1")
            cost = await get_run_cost("r1")
        assert steps == {"run_id": "r1", "steps": [{"step": "extractor"}]}
        assert results == {"classes": []}
        assert retry.new_run_id == "r2"
        assert cost == {"usd": 1.23}

    @pytest.mark.asyncio
    async def test_get_run_cost_passes_refresh_flag(self):
        """Stream 12 T7 -- ``?refresh=true`` must be threaded through
        to the service so the cache can be bypassed on demand."""
        db = MagicMock()
        mock_cost = MagicMock(return_value={"quality_from_cache": False})
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.extraction_service.get_run_cost", mock_cost),
        ):
            cached = await get_run_cost("r1")
            refreshed = await get_run_cost("r1", refresh=True)

        assert cached == {"quality_from_cache": False}
        assert refreshed == {"quality_from_cache": False}

        # Default call -> refresh=False
        assert mock_cost.call_args_list[0].kwargs["refresh"] is False
        # Explicit -> refresh=True
        assert mock_cost.call_args_list[1].kwargs["refresh"] is True
