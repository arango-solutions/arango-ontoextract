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
        """Stream 12 T8 -- document name + chunk count are now bulk
        fetched via a single AQL query (not a per-run ``doc_get``)
        and the ontology_id lookup is similarly bulk-fetched. Per-run
        ``classes_extracted`` / ``properties_extracted`` come from
        ``run.stats`` and MUST NOT be overwritten by ontology-wide
        totals (see the route's enrichment comment for the bug
        rationale).
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
            # Stream 12 T8: doc_get is no longer called from list_runs;
            # the patch is a tripwire -- if a future refactor re-adds a
            # per-row doc_get, this assertion fires.
            patch("app.api.extraction.doc_get") as mock_doc_get,
            # Two AQL calls now: (1) bulk docs, (2) bulk registry. The
            # iter() wrappers mimic the cursor that run_aql returns.
            patch(
                "app.api.extraction.run_aql",
                side_effect=[
                    iter([{"key": "d1", "filename": "doc.md", "chunk_count": 4}]),
                    iter([{"rid": "r1", "oid": "onto1"}]),
                ],
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
        # T8 invariant: no per-row doc_get.
        mock_doc_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_runs_does_not_query_legacy_ontology_properties(self):
        """Regression: the previous override block queried
        ``ontology_properties`` (the empty pre-PGT-split collection),
        which always returned 0 and silently zeroed every run's
        ``properties_extracted``. The new enrichment should only
        touch ``documents`` (bulk) and ``ontology_registry`` (bulk).

        Stream 12 T8 also enforces: exactly TWO AQL calls per page
        (one for docs, one for registry), independent of page size.
        """
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = MagicMock()
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": [
                {
                    "_key": "r1",
                    "doc_ids": ["d1"],
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
            if "documents" in query:
                return iter([])
            return iter([{"rid": "r1", "oid": "onto1"}])

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
        # T8: exactly two queries -- documents + ontology_registry.
        assert len(captured_queries) == 2
        assert any("documents" in q for q in captured_queries)
        assert any("ontology_registry" in q for q in captured_queries)

    @pytest.mark.asyncio
    async def test_list_runs_bulk_enrichment_scales_with_page_size(self):
        """Stream 12 T8 invariant: AQL count stays at 2 even when the
        page has many runs spanning many documents. Pre-T8 this would
        have been 1 (paginate) + N (per-run registry) + M (per-doc
        doc_get) -- ~50 round-trips for a typical 25-row page.
        """
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = MagicMock()

        # 5 runs, each referencing 2 documents (10 unique docs total).
        rows: list[dict] = []
        for i in range(5):
            rows.append(
                {
                    "_key": f"r{i}",
                    "doc_ids": [f"d{i}a", f"d{i}b"],
                    "stats": {
                        "errors": [],
                        "classes_extracted": i,
                        "properties_extracted": 2 * i,
                    },
                }
            )
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": rows,
            "cursor": None,
            "has_more": False,
            "total_count": 5,
        }

        captured_queries: list[str] = []
        captured_bind_vars: list[dict] = []

        def capture_aql(_db, query, bind_vars=None, **_kw):
            captured_queries.append(query)
            captured_bind_vars.append(bind_vars or {})
            if "documents" in query:
                # Return enriched docs for every requested id.
                return iter(
                    [
                        {"key": did, "filename": f"{did}.md", "chunk_count": 3}
                        for did in bind_vars["ids"]
                    ]
                )
            # ontology_registry -- map every run to its own ontology.
            return iter([{"rid": rid, "oid": f"onto_{rid}"} for rid in bind_vars["rids"]])

        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.list_runs",
                return_value=paginated,
            ),
            patch("app.api.extraction.doc_get") as mock_doc_get,
            patch("app.api.extraction.run_aql", side_effect=capture_aql),
        ):
            result = await list_runs(limit=25)

        # The invariant.
        assert len(captured_queries) == 2, (
            f"T8 broken: expected 2 AQL queries (docs + registry), "
            f"got {len(captured_queries)}: {captured_queries}"
        )
        mock_doc_get.assert_not_called()

        # Every run got its bulk-fetched name + ontology link.
        for i, run in enumerate(result["data"]):
            assert run["document_name"] == f"d{i}a.md, d{i}b.md"
            assert run["chunk_count"] == 6  # 2 docs x chunk_count=3
            assert run["ontology_id"] == f"onto_r{i}"
            assert run["classes_extracted"] == i

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
            # Only the registry AQL runs (no doc_ids -> docs query
            # skipped). Empty cursor -- no registry row exists yet.
            patch("app.api.extraction.run_aql", side_effect=[iter([])]),
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
