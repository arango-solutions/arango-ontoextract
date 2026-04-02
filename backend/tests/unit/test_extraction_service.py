"""Unit tests for app.services.extraction -- covering start_run, execute_run,
retry_run, _materialize_to_graph, _recompute_multi_signal_confidence,
_auto_register_ontology, _update_existing_ontology, and helpers.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

NEVER_EXPIRES: int = sys.maxsize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db(
    *,
    has_chunks: bool = True,
    chunk_keys: list[str] | None = None,
    existing_collections: set[str] | None = None,
) -> tuple[MagicMock, dict[str, MagicMock]]:
    """Return a mock StandardDatabase and dict of named mock collections."""
    mock = MagicMock()

    all_names = {
        "extraction_runs",
        "ontology_classes",
        "ontology_properties",
        "has_property",
        "subclass_of",
        "related_to",
        "extracted_from",
        "has_chunk",
        "produced_by",
        "chunks",
        "ontology_registry",
    }
    if existing_collections is None:
        existing_collections = all_names

    mock.has_collection.side_effect = lambda n: n in existing_collections

    cols: dict[str, MagicMock] = {}
    for name in all_names:
        col = MagicMock()
        col.name = name
        col.insert.return_value = {"_key": "stub"}
        col.update.return_value = {}
        cols[name] = col

    mock.collection.side_effect = lambda n: cols.get(n, MagicMock())
    mock.create_collection.return_value = MagicMock()

    if chunk_keys is not None:
        mock.aql.execute.return_value = iter(chunk_keys)
    elif has_chunks:
        mock.aql.execute.return_value = iter([])
    else:
        mock.aql.execute.return_value = iter([])

    return mock, cols


def _make_result(
    classes: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a mock extraction result with .classes list of mock objects."""
    result = MagicMock()
    if classes is None:
        classes = []

    mock_classes = []
    for cls_data in classes:
        mc = MagicMock()
        mc.model_dump.return_value = cls_data
        props = cls_data.get("properties", [])
        mc.properties = props
        mc.label = cls_data.get("label", "Unknown")
        mc.uri = cls_data.get("uri", "")
        mc.confidence = cls_data.get("confidence", 0.5)
        mc.llm_confidence = cls_data.get("llm_confidence", 0.5)
        mc.property_agreement = cls_data.get("property_agreement", 1.0)
        mc.description = cls_data.get("description", "")
        mock_classes.append(mc)

    result.classes = mock_classes
    return result


# ---------------------------------------------------------------------------
# _compute_agreement_rate
# ---------------------------------------------------------------------------


class TestComputeAgreementRate:
    def test_single_pass_returns_one(self):
        from app.services.extraction import _compute_agreement_rate

        pr = MagicMock()
        pr.classes = [MagicMock(uri="http://ex.org#A")]
        assert _compute_agreement_rate([pr]) == 1.0

    def test_empty_passes(self):
        from app.services.extraction import _compute_agreement_rate

        assert _compute_agreement_rate([]) == 1.0

    def test_two_identical_passes(self):
        from app.services.extraction import _compute_agreement_rate

        def _mk(uris):
            pr = MagicMock()
            cls_list = []
            for u in uris:
                c = MagicMock()
                c.uri = u
                cls_list.append(c)
            pr.classes = cls_list
            return pr

        p1 = _mk(["http://ex.org#A", "http://ex.org#B"])
        p2 = _mk(["http://ex.org#A", "http://ex.org#B"])
        assert _compute_agreement_rate([p1, p2]) == 1.0

    def test_no_overlap(self):
        from app.services.extraction import _compute_agreement_rate

        def _mk(uris):
            pr = MagicMock()
            cls_list = []
            for u in uris:
                c = MagicMock()
                c.uri = u
                cls_list.append(c)
            pr.classes = cls_list
            return pr

        p1 = _mk(["http://ex.org#A"])
        p2 = _mk(["http://ex.org#B"])
        assert _compute_agreement_rate([p1, p2]) == 0.0

    def test_partial_overlap(self):
        from app.services.extraction import _compute_agreement_rate

        def _mk(uris):
            pr = MagicMock()
            cls_list = []
            for u in uris:
                c = MagicMock()
                c.uri = u
                cls_list.append(c)
            pr.classes = cls_list
            return pr

        p1 = _mk(["http://ex.org#A", "http://ex.org#B"])
        p2 = _mk(["http://ex.org#B", "http://ex.org#C"])
        rate = _compute_agreement_rate([p1, p2])
        # intersection={B}, union={A,B,C} -> 1/3
        assert 0.3 < rate < 0.4


# ---------------------------------------------------------------------------
# _serialize_step_log
# ---------------------------------------------------------------------------


class TestSerializeStepLog:
    def test_dict_passthrough(self):
        from app.services.extraction import _serialize_step_log

        d = {"step": "extractor", "status": "ok"}
        assert _serialize_step_log(d) is d

    def test_model_dump(self):
        from app.services.extraction import _serialize_step_log

        obj = MagicMock()
        obj.model_dump.return_value = {"step": "x"}
        assert _serialize_step_log(obj) == {"step": "x"}


# ---------------------------------------------------------------------------
# _load_document_chunks
# ---------------------------------------------------------------------------


class TestLoadDocumentChunks:
    @patch("app.services.extraction.run_aql")
    def test_returns_chunks(self, mock_run_aql):
        from app.services.extraction import _load_document_chunks

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = [{"_key": "c1"}, {"_key": "c2"}]

        result = _load_document_chunks(db, "doc_1")
        assert len(result) == 2

    def test_returns_empty_when_no_collection(self):
        from app.services.extraction import _load_document_chunks

        db = MagicMock()
        db.has_collection.return_value = False

        result = _load_document_chunks(db, "doc_1")
        assert result == []


# ---------------------------------------------------------------------------
# _store_results
# ---------------------------------------------------------------------------


class TestStoreResults:
    def test_inserts_results_doc(self):
        from app.services.extraction import _store_results

        db, cols = _mock_db()
        result = MagicMock()
        result.model_dump.return_value = {"classes": []}

        _store_results(db, run_id="run_1", result=result)

        cols["extraction_runs"].insert.assert_called_once()
        inserted = cols["extraction_runs"].insert.call_args[0][0]
        assert inserted["_key"] == "results_run_1"
        assert inserted["run_id"] == "run_1"
        assert "stored_at" in inserted

    def test_falls_back_to_update_on_conflict(self):
        from app.services.extraction import _store_results

        db, cols = _mock_db()
        cols["extraction_runs"].insert.side_effect = Exception("conflict")
        result = MagicMock()
        result.model_dump.return_value = {"classes": []}

        _store_results(db, run_id="run_1", result=result)

        cols["extraction_runs"].update.assert_called_once()


# ---------------------------------------------------------------------------
# start_run
# ---------------------------------------------------------------------------


class TestStartRun:
    @patch("app.services.extraction.execute_run", new_callable=AsyncMock)
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_creates_record_and_executes(
        self,
        mock_get_db,
        mock_get_col,
        mock_load,
        mock_execute,
    ):
        from app.services.extraction import start_run

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        mock_execute.return_value = {"status": "completed"}

        result = await start_run(
            mock_db,
            document_id="doc_1",
            event_callback=MagicMock(),
        )

        mock_col.insert.assert_called_once()
        mock_execute.assert_called_once()
        assert result == {"status": "completed"}

    @patch("app.services.extraction.execute_run", new_callable=AsyncMock)
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_passes_target_ontology_id(
        self,
        mock_get_db,
        mock_get_col,
        mock_load,
        mock_execute,
    ):
        from app.services.extraction import start_run

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        mock_execute.return_value = {}

        await start_run(
            mock_db,
            document_id="doc_1",
            target_ontology_id="onto_99",
        )

        _, kwargs = mock_execute.call_args
        assert kwargs["target_ontology_id"] == "onto_99"

    @patch("app.services.extraction.execute_run", new_callable=AsyncMock)
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_passes_domain_ontology_ids(
        self,
        mock_get_db,
        mock_get_col,
        mock_load,
        mock_execute,
    ):
        from app.services.extraction import start_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        mock_execute.return_value = {}

        await start_run(
            mock_db,
            document_id="doc_1",
            domain_ontology_ids=["d1", "d2"],
        )

        _, kwargs = mock_execute.call_args
        assert kwargs["domain_ontology_ids"] == ["d1", "d2"]


# ---------------------------------------------------------------------------
# execute_run -- success path
# ---------------------------------------------------------------------------


class TestExecuteRunSuccess:
    def _setup_mocks(self):
        """Shared setup: mocked DB, run_record, pipeline, etc."""
        mock_db = MagicMock()
        mock_col = MagicMock()

        run_record = {
            "_key": "run_abc",
            "doc_id": "doc_1",
            "doc_ids": ["doc_1"],
            "status": "running",
            "stats": {
                "passes": 2,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }

        consistency_result = _make_result(
            classes=[
                {
                    "label": "Person",
                    "uri": "http://ex.org#Person",
                    "confidence": 0.9,
                    "properties": [{"label": "name", "range": "xsd:string"}],
                },
            ]
        )

        pipeline_state = {
            "consistency_result": consistency_result,
            "errors": [],
            "step_logs": [],
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "extraction_passes": [],
        }

        return mock_db, mock_col, run_record, pipeline_state, consistency_result

    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.extraction._auto_register_ontology", return_value="onto_new")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[{"text": "hello"}])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_completes_with_auto_register(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
        mock_store,
        mock_materialize,
        mock_auto_reg,
        mock_produced_by,
    ):
        from app.services.extraction import execute_run

        mock_db, mock_col, run_record, pipeline_state, _ = self._setup_mocks()
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, {"_key": "run_abc", "status": "completed"}]
        mock_run_pipeline.return_value = pipeline_state

        result = await execute_run(
            run_id="run_abc",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        mock_store.assert_called_once()
        mock_auto_reg.assert_called_once()
        mock_materialize.assert_called_once()
        mock_produced_by.assert_called_once()
        assert result["status"] == "completed"

    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.extraction._update_existing_ontology", return_value="onto_existing")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_completes_with_target_ontology(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
        mock_store,
        mock_materialize,
        mock_update_existing,
        mock_produced_by,
    ):
        from app.services.extraction import execute_run

        mock_db, mock_col, run_record, pipeline_state, _ = self._setup_mocks()
        run_record["target_ontology_id"] = "onto_existing"
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, {"_key": "run_abc", "status": "completed"}]
        mock_run_pipeline.return_value = pipeline_state

        result = await execute_run(
            run_id="run_abc",
            document_ids=["doc_1"],
            target_ontology_id="onto_existing",
            event_callback=MagicMock(),
        )

        mock_update_existing.assert_called_once()
        mock_materialize.assert_called_once()
        assert result["status"] == "completed"

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_uses_doc_ids_from_record_when_not_provided(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_abc",
            "doc_id": "doc_from_record",
            "doc_ids": ["doc_from_record"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {"consistency_result": None, "errors": ["fail"]}

        await execute_run(run_id="run_abc", event_callback=MagicMock())

        mock_load_chunks.assert_called_once_with(mock_db, "doc_from_record")

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_falls_back_to_single_doc_id(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        """When doc_ids is empty but doc_id is set on the run record."""
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_abc",
            "doc_id": "fallback_doc",
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {"consistency_result": None, "errors": ["fail"]}

        await execute_run(run_id="run_abc", event_callback=MagicMock())

        mock_load_chunks.assert_called_once_with(mock_db, "fallback_doc")


# ---------------------------------------------------------------------------
# execute_run -- failure path
# ---------------------------------------------------------------------------


class TestExecuteRunFailure:
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_pipeline_exception_marks_failed(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_fail",
            "doc_ids": ["doc_1"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, {"_key": "run_fail", "status": "failed"}]
        mock_run_pipeline.side_effect = RuntimeError("LLM timeout")

        await execute_run(
            run_id="run_fail",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        # Verify the update was called with status=failed
        mock_col.update.assert_called()
        update_arg = mock_col.update.call_args[0][0]
        assert update_arg["status"] == "failed"
        assert "LLM timeout" in update_arg["stats"]["errors"][0]

    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_run_not_found_raises(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
    ):
        from app.api.errors import NotFoundError
        from app.services.extraction import execute_run

        mock_get_db.return_value = MagicMock()
        mock_get_col.return_value = MagicMock()
        mock_doc_get.return_value = None

        with pytest.raises(NotFoundError):
            await execute_run(run_id="nonexistent", event_callback=MagicMock())

    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_null_consistency_sets_failed(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
        mock_store,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_null",
            "doc_ids": ["doc_1"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {
            "consistency_result": None,
            "errors": [],
            "step_logs": [],
            "token_usage": {},
            "extraction_passes": [],
        }

        await execute_run(
            run_id="run_null",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        update_arg = mock_col.update.call_args[0][0]
        assert update_arg["status"] == "failed"

    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_completed_with_errors(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
        mock_store,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_err",
            "doc_ids": ["doc_1"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        consistency = _make_result(classes=[])
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {
            "consistency_result": consistency,
            "errors": ["partial failure"],
            "step_logs": [],
            "token_usage": {},
            "extraction_passes": [],
        }

        await execute_run(
            run_id="run_err",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        update_arg = mock_col.update.call_args[0][0]
        assert update_arg["status"] == "completed_with_errors"


# ---------------------------------------------------------------------------
# execute_run -- domain context / tier2
# ---------------------------------------------------------------------------


class TestExecuteRunDomainContext:
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_serializes_domain_context(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_tier2",
            "doc_ids": ["doc_1"],
            "domain_ontology_ids": ["dom1"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {
            "consistency_result": None,
            "errors": [],
            "step_logs": [],
            "token_usage": {},
            "extraction_passes": [],
        }

        with patch(
            "app.services.ontology_context.serialize_multi_domain_context",
            return_value="domain context text",
        ):
            await execute_run(
                run_id="run_tier2",
                document_ids=["doc_1"],
                domain_ontology_ids=["dom1"],
                event_callback=MagicMock(),
            )

        _, kwargs = mock_run_pipeline.call_args
        assert kwargs["domain_context"] == "domain context text"

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_domain_context_failure_falls_back(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_t2f",
            "doc_ids": ["doc_1"],
            "domain_ontology_ids": ["dom1"],
            "status": "running",
            "stats": {
                "passes": 1,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]
        mock_run_pipeline.return_value = {
            "consistency_result": None,
            "errors": [],
            "step_logs": [],
            "token_usage": {},
            "extraction_passes": [],
        }

        with patch(
            "app.services.ontology_context.serialize_multi_domain_context",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            await execute_run(
                run_id="run_t2f",
                document_ids=["doc_1"],
                domain_ontology_ids=["dom1"],
                event_callback=MagicMock(),
            )

        _, kwargs = mock_run_pipeline.call_args
        assert kwargs["domain_context"] == ""


# ---------------------------------------------------------------------------
# retry_run
# ---------------------------------------------------------------------------


class TestRetryRun:
    @patch("app.services.extraction.start_run", new_callable=AsyncMock)
    @patch("app.services.extraction.get_run")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_retries_failed_run(self, mock_get_db, mock_get_run, mock_start_run):
        from app.services.extraction import retry_run

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_get_run.return_value = {
            "_key": "run_old",
            "status": "failed",
            "doc_id": "doc_1",
            "doc_ids": ["doc_1", "doc_2"],
            "target_ontology_id": "onto_5",
            "domain_ontology_ids": ["dom_1"],
        }
        mock_start_run.return_value = {"_key": "run_new", "status": "completed"}

        await retry_run(mock_db, run_id="run_old", event_callback=MagicMock())

        mock_start_run.assert_called_once()
        _, kwargs = mock_start_run.call_args
        assert kwargs["document_id"] == "doc_1"
        assert kwargs["target_ontology_id"] == "onto_5"
        assert kwargs["domain_ontology_ids"] == ["dom_1"]

    @patch("app.services.extraction.get_run")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_cannot_retry_running(self, mock_get_db, mock_get_run):
        from app.services.extraction import retry_run

        mock_get_db.return_value = MagicMock()
        mock_get_run.return_value = {
            "_key": "run_x",
            "status": "running",
            "doc_id": "doc_1",
        }

        with pytest.raises(ValueError, match="Can only retry failed runs"):
            await retry_run(run_id="run_x")

    @patch("app.services.extraction.start_run", new_callable=AsyncMock)
    @patch("app.services.extraction.get_run")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_retries_completed_with_errors(
        self,
        mock_get_db,
        mock_get_run,
        mock_start_run,
    ):
        from app.services.extraction import retry_run

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_get_run.return_value = {
            "_key": "run_e",
            "status": "completed_with_errors",
            "doc_id": "doc_1",
            "doc_ids": ["doc_1"],
        }
        mock_start_run.return_value = {}

        await retry_run(mock_db, run_id="run_e")

        mock_start_run.assert_called_once()

    @patch("app.services.extraction.start_run", new_callable=AsyncMock)
    @patch("app.services.extraction.get_run")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_fallback_to_single_doc_id(
        self,
        mock_get_db,
        mock_get_run,
        mock_start_run,
    ):
        """When doc_ids is missing, uses doc_id field."""
        from app.services.extraction import retry_run

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_get_run.return_value = {
            "_key": "run_old2",
            "status": "failed",
            "doc_id": "fallback_doc",
        }
        mock_start_run.return_value = {}

        await retry_run(mock_db, run_id="run_old2")

        _, kwargs = mock_start_run.call_args
        assert kwargs["document_id"] == "fallback_doc"


# ---------------------------------------------------------------------------
# _materialize_to_graph -- classes and properties
# ---------------------------------------------------------------------------


class TestMaterializeToGraph:
    def test_inserts_classes_and_properties(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])

        result = _make_result(
            classes=[
                {
                    "label": "Animal",
                    "uri": "http://ex.org/ontology#Animal",
                    "description": "A living creature",
                    "confidence": 0.85,
                    "faithfulness_score": 0.91,
                    "semantic_validity_score": 0.77,
                    "properties": [
                        {"label": "species", "range": "xsd:string", "confidence": 0.9},
                        {"label": "habitat", "range": "http://ex.org#Habitat", "confidence": 0.7},
                    ],
                },
            ]
        )

        _materialize_to_graph(
            mock_db,
            run_id="run_1",
            document_id="doc_1",
            ontology_id="onto_1",
            result=result,
        )

        # Class inserted
        cls_col = cols["ontology_classes"]
        assert cls_col.insert.call_count == 1
        cls_doc = cls_col.insert.call_args[0][0]
        assert cls_doc["_key"] == "Animal"
        assert cls_doc["label"] == "Animal"
        assert cls_doc["ontology_id"] == "onto_1"
        assert cls_doc["confidence"] == 0.85
        assert cls_doc["faithfulness_score"] == 0.91
        assert cls_doc["semantic_validity_score"] == 0.77
        assert cls_doc["expired"] == NEVER_EXPIRES

        # Two properties inserted
        prop_col = cols["ontology_properties"]
        assert prop_col.insert.call_count == 2

        # has_property edges
        hp_col = cols["has_property"]
        assert hp_col.insert.call_count == 2

        # extracted_from edge
        ef_col = cols["extracted_from"]
        assert ef_col.insert.call_count == 1
        ef_doc = ef_col.insert.call_args[0][0]
        assert ef_doc["_from"] == "ontology_classes/Animal"
        assert ef_doc["_to"] == "documents/doc_1"

    def test_inserts_subclass_edges(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])

        result = _make_result(
            classes=[
                {
                    "label": "LivingThing",
                    "uri": "http://ex.org/ontology#LivingThing",
                    "description": "Base class",
                    "properties": [],
                },
                {
                    "label": "Animal",
                    "uri": "http://ex.org/ontology#Animal",
                    "description": "A creature",
                    "parent_uri": "http://ex.org/ontology#LivingThing",
                    "properties": [],
                },
            ]
        )

        _materialize_to_graph(
            mock_db,
            run_id="run_1",
            document_id="doc_1",
            ontology_id="onto_1",
            result=result,
        )

        sub_col = cols["subclass_of"]
        assert sub_col.insert.call_count == 1
        edge = sub_col.insert.call_args[0][0]
        assert edge["_from"] == "ontology_classes/Animal"
        assert edge["_to"] == "ontology_classes/LivingThing"

    def test_handles_class_insert_failure_gracefully(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])
        cols["ontology_classes"].insert.side_effect = Exception("duplicate key")

        result = _make_result(
            classes=[
                {"label": "Broken", "uri": "http://ex.org#Broken", "properties": []},
            ]
        )

        # Should not raise
        _materialize_to_graph(
            mock_db,
            run_id="r",
            document_id="d",
            ontology_id="o",
            result=result,
        )

    def test_creates_missing_collections(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, _ = _mock_db(
            chunk_keys=[],
            existing_collections=set(),  # none exist
        )

        result = _make_result(classes=[])

        _materialize_to_graph(
            mock_db,
            run_id="r",
            document_id="d",
            ontology_id="o",
            result=result,
        )

        # Should have called create_collection for each missing collection
        created = {c[0][0] for c in mock_db.create_collection.call_args_list}
        assert "ontology_classes" in created
        assert "ontology_properties" in created
        assert "has_property" in created

    def test_property_rdf_type_object_vs_datatype(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])

        result = _make_result(
            classes=[
                {
                    "label": "Foo",
                    "uri": "http://ex.org/ontology#Foo",
                    "properties": [
                        {"label": "name", "range": "xsd:string"},
                        {"label": "relatedTo", "range": "http://ex.org#Bar"},
                    ],
                },
            ]
        )

        _materialize_to_graph(
            mock_db,
            run_id="r",
            document_id="d",
            ontology_id="o",
            result=result,
        )

        prop_col = cols["ontology_properties"]
        inserts = [c[0][0] for c in prop_col.insert.call_args_list]
        name_prop = next(p for p in inserts if p["label"] == "name")
        related_prop = next(p for p in inserts if p["label"] == "relatedTo")

        assert name_prop["rdf_type"] == "owl:DatatypeProperty"
        assert related_prop["rdf_type"] == "owl:ObjectProperty"

    def test_has_chunk_edges_created(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=["ck_0", "ck_1"])

        result = _make_result(classes=[])

        _materialize_to_graph(
            mock_db,
            run_id="r",
            document_id="doc_1",
            ontology_id="o",
            result=result,
        )

        hc = cols["has_chunk"]
        assert hc.insert.call_count == 2
        edges = [c[0][0] for c in hc.insert.call_args_list]
        assert {e["_to"] for e in edges} == {"chunks/ck_0", "chunks/ck_1"}

    def test_no_chunks_collection(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(
            has_chunks=False,
            existing_collections={
                "ontology_classes",
                "ontology_properties",
                "has_property",
                "subclass_of",
                "related_to",
                "extracted_from",
                "has_chunk",
                "produced_by",
            },
        )

        result = _make_result(classes=[])
        _materialize_to_graph(
            mock_db,
            run_id="r",
            document_id="d",
            ontology_id="o",
            result=result,
        )

        cols["has_chunk"].insert.assert_not_called()


# ---------------------------------------------------------------------------
# _recompute_multi_signal_confidence
# ---------------------------------------------------------------------------


class TestRecomputeMultiSignalConfidence:
    @patch("app.services.extraction.compute_class_confidence", return_value=0.88)
    @patch("app.services.extraction.run_aql")
    def test_updates_confidence(self, mock_run_aql, mock_compute):
        from app.services.extraction import _recompute_multi_signal_confidence

        mock_db, cols = _mock_db()
        # Return values for each run_aql call per class:
        # 1. prop_type_counts, 2. has_parent, 3. has_children,
        # 4. related_to probe, 5. provenance_count
        mock_run_aql.side_effect = [
            [{"rdf": "owl:DatatypeProperty", "cnt": 2}],  # prop types
            [],  # has_parent: no
            [True],  # has_children: yes
            [],  # has_lateral via related_to: no
            [1],  # provenance_count
        ]
        mock_db.has_collection.side_effect = lambda name: name != "extends_domain"

        classes = [
            MagicMock(
                **{
                    "model_dump.return_value": {
                        "label": "Person",
                        "uri": "http://ex.org#Person",
                        "confidence": 0.7,
                        "description": "A person",
                        "llm_confidence": 0.8,
                        "property_agreement": 0.9,
                    },
                },
            ),
        ]

        _recompute_multi_signal_confidence(
            mock_db,
            ontology_id="onto_1",
            classes=classes,
            class_keys={"Person": "Person"},
            uri_to_key={"http://ex.org#Person": "Person"},
            faithfulness_scores={"http://ex.org#Person": 0.85},
            validity_scores={"http://ex.org#Person": 0.9},
        )

        mock_compute.assert_called_once()
        kwargs = mock_compute.call_args[1]
        assert kwargs["faithfulness"] == 0.85
        assert kwargs["semantic_validity"] == 0.9
        assert kwargs["datatype_property_count"] == 2
        assert kwargs["has_children"] is True
        assert kwargs["has_parent"] is False

        cols["ontology_classes"].update.assert_called_once_with(
            {
                "_key": "Person",
                "confidence": 0.88,
                "faithfulness_score": 0.85,
                "semantic_validity_score": 0.9,
            },
        )

    @patch("app.services.extraction.compute_class_confidence", return_value=0.5)
    @patch("app.services.extraction.run_aql")
    def test_skips_unknown_key(self, mock_run_aql, mock_compute):
        from app.services.extraction import _recompute_multi_signal_confidence

        mock_db, _cols = _mock_db()
        mock_db.has_collection.return_value = False

        classes = [
            MagicMock(
                **{
                    "model_dump.return_value": {
                        "label": "Ghost",
                        "uri": "http://ex.org#Ghost",
                    },
                },
            ),
        ]

        _recompute_multi_signal_confidence(
            mock_db,
            ontology_id="onto_1",
            classes=classes,
            class_keys={},
            uri_to_key={},
        )

        mock_compute.assert_not_called()

    @patch("app.services.extraction.compute_class_confidence", return_value=0.6)
    @patch("app.services.extraction.run_aql")
    def test_checks_related_to_and_extends_domain(self, mock_run_aql, mock_compute):
        from app.services.extraction import _recompute_multi_signal_confidence

        mock_db, _cols = _mock_db()
        # related_to and extends_domain both exist
        mock_db.has_collection.side_effect = lambda n: (
            n
            in {
                "related_to",
                "extends_domain",
                "ontology_classes",
                "ontology_properties",
                "has_property",
                "subclass_of",
                "extracted_from",
            }
        )

        mock_run_aql.side_effect = [
            [],  # prop_type_counts
            [],  # has_parent
            [],  # has_children
            [True],  # related_to lateral
            [1],  # provenance
        ]

        classes = [
            MagicMock(
                **{
                    "model_dump.return_value": {
                        "label": "Cls",
                        "uri": "http://ex.org#Cls",
                        "confidence": 0.5,
                        "description": "test",
                    },
                },
            ),
        ]

        _recompute_multi_signal_confidence(
            mock_db,
            ontology_id="onto_1",
            classes=classes,
            class_keys={"Cls": "Cls"},
            uri_to_key={"http://ex.org#Cls": "Cls"},
        )

        kwargs = mock_compute.call_args[1]
        assert kwargs["has_lateral_edges"] is True


# ---------------------------------------------------------------------------
# _auto_register_ontology
# ---------------------------------------------------------------------------


class TestAutoRegisterOntology:
    @patch("app.db.registry_repo.create_registry_entry")
    @patch("app.db.documents_repo.get_document")
    def test_registers_ontology(self, mock_get_doc, mock_create):
        from app.services.extraction import _auto_register_ontology

        mock_get_doc.return_value = {"filename": "my-research-paper.pdf"}
        mock_create.return_value = {"_key": "onto_abc"}

        result_mock = _make_result(
            classes=[
                {
                    "label": "Concept",
                    "uri": "http://ex.org#Concept",
                    "properties": [{"label": "name"}],
                },
            ]
        )

        oid = _auto_register_ontology(
            MagicMock(),
            run_id="run_1",
            document_id="doc_1",
            result=result_mock,
        )

        assert oid == "onto_abc"
        mock_create.assert_called_once()
        entry = mock_create.call_args[0][0]
        assert entry["name"] == "My Research Paper"
        assert entry["class_count"] == 1
        assert entry["property_count"] == 1
        assert entry["source_document_id"] == "doc_1"

    @patch("app.db.registry_repo.create_registry_entry")
    @patch("app.db.documents_repo.get_document")
    def test_returns_none_on_failure(self, mock_get_doc, mock_create):
        from app.services.extraction import _auto_register_ontology

        mock_get_doc.side_effect = RuntimeError("db error")

        oid = _auto_register_ontology(
            MagicMock(),
            run_id="r",
            document_id="d",
            result=MagicMock(),
        )

        assert oid is None

    @patch("app.db.registry_repo.create_registry_entry")
    @patch("app.db.documents_repo.get_document")
    def test_handles_missing_document(self, mock_get_doc, mock_create):
        from app.services.extraction import _auto_register_ontology

        mock_get_doc.return_value = None
        mock_create.return_value = {"_key": "onto_fallback"}

        result_mock = _make_result(classes=[])

        oid = _auto_register_ontology(
            MagicMock(),
            run_id="run_1",
            document_id="missing",
            result=result_mock,
        )

        assert oid == "onto_fallback"
        entry = mock_create.call_args[0][0]
        assert entry["name"] == "Unknown"


# ---------------------------------------------------------------------------
# _update_existing_ontology
# ---------------------------------------------------------------------------


class TestUpdateExistingOntology:
    @patch("app.db.registry_repo.update_registry_entry")
    @patch("app.db.registry_repo.get_registry_entry")
    def test_increments_counts(self, mock_get, mock_update):
        from app.services.extraction import _update_existing_ontology

        mock_get.return_value = {
            "_key": "onto_1",
            "class_count": 3,
            "property_count": 5,
        }
        mock_update.return_value = {}

        result_mock = _make_result(
            classes=[
                {
                    "label": "A",
                    "uri": "http://ex.org#A",
                    "properties": [{"label": "p1"}, {"label": "p2"}],
                },
                {"label": "B", "uri": "http://ex.org#B", "properties": [{"label": "p3"}]},
            ]
        )

        oid = _update_existing_ontology(
            MagicMock(),
            ontology_id="onto_1",
            run_id="run_new",
            result=result_mock,
        )

        assert oid == "onto_1"
        mock_update.assert_called_once_with(
            "onto_1",
            {
                "class_count": 5,
                "property_count": 8,
                "extraction_run_id": "run_new",
            },
        )

    @patch("app.db.registry_repo.get_registry_entry")
    def test_returns_none_when_not_found(self, mock_get):
        from app.services.extraction import _update_existing_ontology

        mock_get.return_value = None

        oid = _update_existing_ontology(
            MagicMock(),
            ontology_id="missing",
            run_id="run_x",
            result=MagicMock(),
        )

        assert oid is None

    @patch("app.db.registry_repo.get_registry_entry")
    def test_returns_none_on_exception(self, mock_get):
        from app.services.extraction import _update_existing_ontology

        mock_get.side_effect = RuntimeError("db down")

        oid = _update_existing_ontology(
            MagicMock(),
            ontology_id="onto_1",
            run_id="r",
            result=MagicMock(),
        )

        assert oid is None


# ---------------------------------------------------------------------------
# get_run and get_run_results
# ---------------------------------------------------------------------------


class TestGetRun:
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_returns_run(self, mock_get_db, mock_get_col, mock_doc_get):
        from app.services.extraction import get_run

        mock_doc_get.return_value = {"_key": "run_1", "status": "completed"}
        result = get_run(run_id="run_1")
        assert result["_key"] == "run_1"

    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_raises_when_not_found(self, mock_get_db, mock_get_col, mock_doc_get):
        from app.api.errors import NotFoundError
        from app.services.extraction import get_run

        mock_doc_get.return_value = None
        with pytest.raises(NotFoundError):
            get_run(run_id="missing")


class TestGetRunResults:
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_returns_stored_results(self, mock_get_db, mock_get_col, mock_doc_get):
        from app.services.extraction import get_run_results

        mock_doc_get.side_effect = [
            {"_key": "run_1", "status": "completed", "stats": {}},  # get_run
            {"_key": "results_run_1", "extraction_result": {"classes": [{"label": "X"}]}},
        ]
        result = get_run_results(run_id="run_1")
        assert result == {"classes": [{"label": "X"}]}

    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_returns_empty_when_no_results(self, mock_get_db, mock_get_col, mock_doc_get):
        from app.services.extraction import get_run_results

        mock_doc_get.side_effect = [
            {"_key": "run_1", "status": "completed", "stats": {}},
            None,
        ]
        result = get_run_results(run_id="run_1")
        assert result["classes"] == []
        assert result["run_id"] == "run_1"


# ---------------------------------------------------------------------------
# get_run_cost
# ---------------------------------------------------------------------------


class TestGetRunCost:
    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_computes_cost(self, mock_get_db, mock_get_col, mock_doc_get, mock_aql):
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = {
            "_key": "run_1",
            "status": "completed",
            "model": "gpt-4o-mini",
            "started_at": 1000.0,
            "completed_at": 1010.0,
            "stats": {
                "token_usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 200,
                    "total_tokens": 700,
                },
                "classes_extracted": 3,
                "properties_extracted": 7,
                "pass_agreement_rate": 0.85,
            },
        }

        result = get_run_cost(mock_db, run_id="run_1")

        assert result["run_id"] == "run_1"
        assert result["total_tokens"] == 700
        assert result["total_duration_ms"] == 10000
        assert result["input_cost_per_million_tokens"] == 0.15
        assert result["output_cost_per_million_tokens"] == 0.60
        assert result["estimated_cost"] == round(
            (500 / 1_000_000 * 0.15) + (200 / 1_000_000 * 0.60),
            6,
        )

    @patch("app.services.extraction.run_aql")
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_includes_quality_metrics(self, mock_get_db, mock_get_col, mock_doc_get, mock_aql):
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = {
            "_key": "run_q",
            "status": "completed",
            "model": "gpt-4o",
            "started_at": 0,
            "completed_at": 0,
            "stats": {
                "token_usage": {},
                "classes_extracted": 0,
                "properties_extracted": 0,
                "pass_agreement_rate": 0,
            },
        }
        mock_aql.return_value = ["onto_from_aql"]

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
            return_value={"avg_confidence": 0.75, "completeness": 0.8},
        ) as mock_compute_ontology_quality:
            result = get_run_cost(mock_db, run_id="run_q")

        assert result["avg_confidence"] == 0.75
        assert result["completeness_pct"] == 0.8
        mock_compute_ontology_quality.assert_called_once_with(
            mock_db,
            "onto_from_aql",
            include_estimated_cost=False,
        )


# ---------------------------------------------------------------------------
# _get_collection
# ---------------------------------------------------------------------------


class TestGetCollection:
    def test_returns_existing(self):
        from app.services.extraction import _get_collection

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        db.collection.return_value = col

        result = _get_collection(db, "foo")
        assert result is col
        db.create_collection.assert_not_called()

    def test_creates_if_missing(self):
        from app.services.extraction import _get_collection

        db = MagicMock()
        db.has_collection.return_value = False
        col = MagicMock()
        db.collection.return_value = col

        _get_collection(db, "bar")
        db.create_collection.assert_called_once_with("bar")


# ---------------------------------------------------------------------------
# _generate_run_id
# ---------------------------------------------------------------------------


class TestGenerateRunId:
    def test_format(self):
        from app.services.extraction import _generate_run_id

        rid = _generate_run_id()
        assert rid.startswith("run_")
        assert len(rid) == 16  # "run_" + 12 hex chars


# ---------------------------------------------------------------------------
# execute_run -- agreement rate from step_logs
# ---------------------------------------------------------------------------


class TestExecuteRunAgreementRateFromStepLogs:
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._auto_register_ontology", return_value=None)
    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_extracts_agreement_from_step_logs(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
        mock_auto_reg,
        mock_store,
    ):
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_sl",
            "doc_ids": ["doc_1"],
            "status": "running",
            "stats": {
                "passes": 2,
                "consistency_threshold": 0.7,
                "token_usage": {},
                "errors": [],
                "step_logs": [],
            },
        }
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [run_record, run_record]

        consistency = _make_result(classes=[])
        mock_run_pipeline.return_value = {
            "consistency_result": consistency,
            "errors": [],
            "step_logs": [
                {
                    "step": "consistency_checker",
                    "metadata": {"agreement_rates": {"class": 0.8, "prop": 0.6}},
                },
            ],
            "token_usage": {},
            "extraction_passes": [],
        }

        await execute_run(
            run_id="run_sl",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        update_arg = mock_col.update.call_args[0][0]
        # (0.8 + 0.6) / 2 = 0.7
        assert abs(update_arg["stats"]["pass_agreement_rate"] - 0.7) < 0.001
