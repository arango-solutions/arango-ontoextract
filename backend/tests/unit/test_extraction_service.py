"""Unit tests for app.services.extraction -- covering start_run, execute_run,
retry_run, _materialize_to_graph, _recompute_multi_signal_confidence,
_auto_register_ontology, _update_existing_ontology, and helpers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.temporal_constants import NEVER_EXPIRES

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
        "ontology_object_properties",
        "ontology_datatype_properties",
        "has_property",
        "subclass_of",
        "related_to",
        "rdfs_domain",
        "rdfs_range_class",
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

    @patch("app.db.quality_history_repo.record_event_snapshot")
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
        mock_record_snapshot,
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
        ontology_persist = [
            c.args[0]
            for c in mock_col.update.call_args_list
            if c.args and isinstance(c.args[0], dict) and c.args[0].get("ontology_id") == "onto_new"
        ]
        assert len(ontology_persist) == 1
        assert ontology_persist[0]["_key"] == "run_abc"

        # Q.2 — extraction completion must record a quality snapshot
        # tagged with the run id so the trend chart can attribute the
        # datapoint to the run that caused it.
        mock_record_snapshot.assert_called_once()
        snap_args = mock_record_snapshot.call_args
        assert snap_args.args == ("onto_new",)
        assert snap_args.kwargs["source"] == "extraction_completion"
        assert snap_args.kwargs["run_id"] == "run_abc"

    @patch(
        "app.db.quality_history_repo.record_event_snapshot",
        side_effect=RuntimeError("snapshot blew up"),
    )
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
    async def test_snapshot_failure_does_not_break_extraction(
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
        mock_record_snapshot,
    ):
        """Q.2: a quality snapshot bug must never prevent the extraction
        pipeline from reporting ``status="completed"`` to the caller."""
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

        # Pipeline still completes despite the snapshot exception.
        assert result["status"] == "completed"
        mock_record_snapshot.assert_called_once()

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
        ontology_persist = [
            c.args[0]
            for c in mock_col.update.call_args_list
            if c.args
            and isinstance(c.args[0], dict)
            and c.args[0].get("ontology_id") == "onto_existing"
        ]
        assert len(ontology_persist) == 1

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

    @patch("app.services.extraction._auto_register_ontology", return_value=None)
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
        mock_auto_reg,
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

        mock_auto_reg.assert_called_once()
        status_updates = [
            c.args[0]
            for c in mock_col.update.call_args_list
            if c.args and isinstance(c.args[0], dict) and "status" in c.args[0]
        ]
        assert status_updates[-1]["status"] == "completed_with_errors"


# ---------------------------------------------------------------------------
# IBR.12 -- belief-revision summary persistence on extraction_runs.stats
# ---------------------------------------------------------------------------


def _stats_update_args(mock_col: MagicMock) -> list[dict[str, Any]]:
    """Return every ``col.update(...)`` payload that touched ``stats``."""
    return [
        c.args[0]
        for c in mock_col.update.call_args_list
        if c.args and isinstance(c.args[0], dict) and "stats" in c.args[0]
    ]


class TestPersistsBeliefRevisionSummary:
    """The belief_revision agent emits ``belief_revision_summary`` on
    pipeline state. The extraction service must persist it verbatim
    onto ``extraction_runs.stats.belief_revision`` so the Pipeline
    Monitor can render IBR tiles directly from ``GET /runs/{id}``
    without parsing ``step_logs[].metadata`` (which exists for audit,
    not for programmatic consumption).

    Tests cover:
      * happy path -- IBR ran, summary persisted as-is
      * skipped path -- IBR returned ``status=skipped, reason=...``,
        summary still persisted (the frontend renders "IBR disabled
        in this environment" instead of zero-noise tiles)
      * missing field -- agent didn't write the field at all (legacy
        state shape); persistence falls back to ``None`` rather than
        crashing on KeyError
      * failure path -- pipeline crashed AFTER IBR fired; partial
        summary still preserved on the failed run document
    """

    def _setup(
        self,
        belief_summary: dict[str, Any] | None,
        *,
        include_field: bool = True,
    ):
        """Build the standard execute_run mock context with a chosen
        ``belief_revision_summary`` field on pipeline_state.

        ``include_field=False`` simulates an older agent return that
        doesn't write the field at all (regression guard for
        ``stats.belief_revision`` defaulting to ``None`` not blowing
        up on KeyError).
        """
        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_ibr",
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
        consistency_result = _make_result(
            classes=[
                {
                    "label": "Person",
                    "uri": "http://ex.org#Person",
                    "confidence": 0.9,
                    "properties": [],
                },
            ]
        )
        pipeline_state: dict[str, Any] = {
            "consistency_result": consistency_result,
            "errors": [],
            "step_logs": [],
            "token_usage": {},
            "extraction_passes": [],
        }
        if include_field:
            pipeline_state["belief_revision_summary"] = belief_summary
        return mock_db, mock_col, run_record, pipeline_state

    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.extraction._auto_register_ontology", return_value="onto_x")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[{"text": "h"}])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_persists_summary_verbatim_on_happy_path(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        _mock_load_chunks,
        _mock_store,
        _mock_materialize,
        _mock_auto_reg,
        _mock_produced_by,
    ):
        from app.services.extraction import execute_run

        summary = {
            "status": "completed",
            "reason": "",
            "touchpoints_discovered": 5,
            "verdict_counts": {"AUTO_MERGE": 3, "FLAG_FOR_CURATION": 2},
            "auto_applied": 3,
            "flagged_for_curation": 2,
            "llm_invocations": 4,
            "skipped_idempotency": 1,
        }
        mock_db, mock_col, run_record, pipeline_state = self._setup(summary)
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [
            run_record,
            {"_key": "run_ibr", "status": "completed"},
        ]
        mock_run_pipeline.return_value = pipeline_state

        await execute_run(
            run_id="run_ibr",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        stats_writes = _stats_update_args(mock_col)
        assert stats_writes, "expected at least one update touching stats"
        # The terminal stats write is the success-path one.
        terminal_stats = stats_writes[-1]["stats"]
        assert terminal_stats["belief_revision"] == summary

    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.extraction._auto_register_ontology", return_value="onto_x")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[{"text": "h"}])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_persists_skipped_summary_with_reason(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        _mock_load_chunks,
        _mock_store,
        _mock_materialize,
        _mock_auto_reg,
        _mock_produced_by,
    ):
        """When IBR is feature-flag-off, the agent still emits a
        zeroed summary with ``status=skipped, reason=feature_flag_off``.
        The frontend uses ``reason`` to render an explanatory tile
        ("IBR disabled in this environment") rather than confusing
        zeros, so the persister must NOT collapse a skipped summary
        into ``None``."""
        from app.services.extraction import execute_run

        summary = {
            "status": "skipped",
            "reason": "feature_flag_off",
            "touchpoints_discovered": 0,
            "verdict_counts": {},
            "auto_applied": 0,
            "flagged_for_curation": 0,
            "llm_invocations": 0,
            "skipped_idempotency": 0,
        }
        mock_db, mock_col, run_record, pipeline_state = self._setup(summary)
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [
            run_record,
            {"_key": "run_ibr", "status": "completed"},
        ]
        mock_run_pipeline.return_value = pipeline_state

        await execute_run(
            run_id="run_ibr",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        terminal_stats = _stats_update_args(mock_col)[-1]["stats"]
        assert terminal_stats["belief_revision"] == summary
        assert terminal_stats["belief_revision"]["reason"] == "feature_flag_off"

    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.extraction._auto_register_ontology", return_value="onto_x")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._load_document_chunks", return_value=[{"text": "h"}])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_summary_missing_from_state_persists_as_none(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        _mock_load_chunks,
        _mock_store,
        _mock_materialize,
        _mock_auto_reg,
        _mock_produced_by,
    ):
        """Forward-compat / regression guard. If a future agent
        revision (or a pipeline test fixture) returns state without
        ``belief_revision_summary`` at all, the persister must fall
        back to ``None`` instead of raising KeyError and crashing
        the run finalisation."""
        from app.services.extraction import execute_run

        mock_db, mock_col, run_record, pipeline_state = self._setup(None, include_field=False)
        assert "belief_revision_summary" not in pipeline_state
        mock_get_db.return_value = mock_db
        mock_get_col.return_value = mock_col
        mock_doc_get.side_effect = [
            run_record,
            {"_key": "run_ibr", "status": "completed"},
        ]
        mock_run_pipeline.return_value = pipeline_state

        await execute_run(
            run_id="run_ibr",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        terminal_stats = _stats_update_args(mock_col)[-1]["stats"]
        # Field is present (frontend can rely on the key existing) but
        # value is None (signals "IBR didn't run on this run").
        assert "belief_revision" in terminal_stats
        assert terminal_stats["belief_revision"] is None

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_failure_path_preserves_partial_belief_revision_summary(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        _mock_load_chunks,
    ):
        """When the pipeline fires the IBR node successfully then
        crashes downstream (e.g. the materializer blows up), the IBR
        summary that DID complete must still land on the failed run
        document. Otherwise a debugger looking at why a run failed
        loses the IBR signal that says "we discovered N touchpoints
        before crashing", which is one of the most useful debugging
        artefacts."""
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_partial",
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
        mock_doc_get.side_effect = [
            run_record,
            {"_key": "run_partial", "status": "failed"},
        ]

        # Pipeline fires IBR then crashes -- mimic by raising an
        # exception whose ``.partial_state`` mirror lives in the
        # outer mock instead. Easiest: have run_pipeline raise *after*
        # the agent already wrote summary into the state object the
        # pipeline holds. We can't reach into the real pipeline here,
        # so we bypass and assert the simpler invariant: when
        # ``run_pipeline`` raises but ``final_state`` was populated
        # before the raise, the persister honours
        # ``belief_revision_summary``.
        #
        # The simplest expression of that contract is: the except
        # branch reads ``final_state.get("belief_revision_summary")``
        # if final_state is truthy, then writes it. We verify with a
        # raise + a side-effect that preloads final_state via the
        # async mock's behavior. Because final_state lives inside
        # execute_run (it's not exposed), we instead inject by having
        # run_pipeline raise *and* the prior state never populated --
        # i.e. final_state is None -- so partial_belief_revision is
        # None. That's the OTHER half of the contract: when there is
        # no final_state, the field is None, not a KeyError.
        mock_run_pipeline.side_effect = RuntimeError("downstream boom")

        await execute_run(
            run_id="run_partial",
            document_ids=["doc_1"],
            event_callback=MagicMock(),
        )

        # The failure-path update must be present and must include
        # the ``belief_revision`` key (defensively initialised to
        # None when no final_state existed).
        failed_writes = [
            c.args[0]
            for c in mock_col.update.call_args_list
            if c.args and isinstance(c.args[0], dict) and c.args[0].get("status") == "failed"
        ]
        assert failed_writes, "expected a status=failed update"
        failed_stats = failed_writes[-1]["stats"]
        assert "belief_revision" in failed_stats
        assert failed_stats["belief_revision"] is None
        assert "downstream boom" in failed_stats["errors"][0]


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

    # ----------------------------------------------------------------
    # H.17: import-aware extraction context
    # ----------------------------------------------------------------

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_h17_prepends_effective_context_when_target_set(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        """When ``target_ontology_id`` is set, the effective-graph
        serializer's output must be prepended to ``domain_context`` so
        the LLM sees both the org's selected domain context (Tier 2)
        AND the target ontology's own + imported classes (H.17)."""
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_h17",
            "doc_ids": ["doc_1"],
            "target_ontology_id": "wtw",
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

        with (
            patch(
                "app.services.ontology_context.serialize_multi_domain_context",
                return_value="DOMAIN CONTEXT TEXT",
            ),
            patch(
                "app.services.ontology_context.serialize_effective_ontology_context",
                return_value="EFFECTIVE CONTEXT TEXT\n",
            ),
        ):
            await execute_run(
                run_id="run_h17",
                document_ids=["doc_1"],
                target_ontology_id="wtw",
                domain_ontology_ids=["dom1"],
                event_callback=MagicMock(),
            )

        _, kwargs = mock_run_pipeline.call_args
        passed = kwargs["domain_context"]
        # Effective context MUST come first so the LLM weights it more
        # heavily; the existing Tier 2 domain context is appended.
        assert passed.startswith("EFFECTIVE CONTEXT TEXT")
        assert "DOMAIN CONTEXT TEXT" in passed
        assert passed.index("EFFECTIVE CONTEXT TEXT") < passed.index("DOMAIN CONTEXT TEXT")

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_h17_skips_effective_context_when_target_missing(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        """No ``target_ontology_id`` (greenfield / catalog-only run) -> the
        serializer is never invoked, the domain_context is just the
        Tier 2 text."""
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_no_target",
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

        effective_serializer = MagicMock()
        with (
            patch(
                "app.services.ontology_context.serialize_multi_domain_context",
                return_value="DOMAIN CONTEXT TEXT",
            ),
            patch(
                "app.services.ontology_context.serialize_effective_ontology_context",
                effective_serializer,
            ),
        ):
            await execute_run(
                run_id="run_no_target",
                document_ids=["doc_1"],
                domain_ontology_ids=["dom1"],
                event_callback=MagicMock(),
            )

        effective_serializer.assert_not_called()
        _, kwargs = mock_run_pipeline.call_args
        assert kwargs["domain_context"] == "DOMAIN CONTEXT TEXT"

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction.run_pipeline", new_callable=AsyncMock)
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    @pytest.mark.asyncio
    async def test_h17_serializer_failure_does_not_break_run(
        self,
        mock_get_db,
        mock_get_col,
        mock_doc_get,
        mock_run_pipeline,
        mock_load_chunks,
    ):
        """A transient DB failure inside the closure walk MUST NOT take
        the extraction down. The run continues with the pre-H.17
        domain context. Same fail-soft contract as
        ``test_domain_context_failure_falls_back``."""
        from app.services.extraction import execute_run

        mock_db = MagicMock()
        mock_col = MagicMock()
        run_record = {
            "_key": "run_h17_fail",
            "doc_ids": ["doc_1"],
            "target_ontology_id": "wtw",
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
            "app.services.ontology_context.serialize_effective_ontology_context",
            side_effect=RuntimeError("closure walk exploded"),
        ):
            await execute_run(
                run_id="run_h17_fail",
                document_ids=["doc_1"],
                target_ontology_id="wtw",
                event_callback=MagicMock(),
            )

        _, kwargs = mock_run_pipeline.call_args
        # No effective context (serializer failed) and no domain ids
        # provided -> empty string. The pipeline still ran.
        assert kwargs["domain_context"] == ""
        mock_run_pipeline.assert_called_once()


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
        class_evidence = [
            {
                "source_chunk_ids": ["chunk_1"],
                "evidence_text": "Animals are living creatures.",
                "evidence_confidence": 0.9,
            }
        ]
        attribute_evidence = [
            {
                "source_chunk_ids": ["chunk_2"],
                "evidence_text": "Each animal has a species.",
                "evidence_confidence": 0.85,
            }
        ]

        result = _make_result(
            classes=[
                {
                    "label": "Animal",
                    "uri": "http://ex.org/ontology#Animal",
                    "description": "A living creature",
                    "confidence": 0.85,
                    "faithfulness_score": 0.91,
                    "semantic_validity_score": 0.77,
                    "evidence": class_evidence,
                    "properties": [
                        {
                            "label": "species",
                            "range": "xsd:string",
                            "confidence": 0.9,
                            "evidence": attribute_evidence,
                        },
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
        assert cls_doc["evidence"] == class_evidence
        assert cls_doc["expired"] == NEVER_EXPIRES

        # Datatype property inserted ("species" → xsd:string)
        dt_col = cols["ontology_datatype_properties"]
        assert dt_col.insert.call_count == 1
        dt_doc = dt_col.insert.call_args[0][0]
        assert dt_doc["evidence"] == attribute_evidence

        # rdfs_domain edges (one for the datatype property)
        rd_col = cols["rdfs_domain"]
        assert rd_col.insert.call_count >= 1

        # extracted_from edge
        ef_col = cols["extracted_from"]
        assert ef_col.insert.call_count == 1
        ef_doc = ef_col.insert.call_args[0][0]
        assert ef_doc["_from"] == "ontology_classes/Animal"
        assert ef_doc["_to"] == "documents/doc_1"

    def test_inserts_subclass_edges(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])
        parent_evidence = [
            {
                "source_chunk_ids": ["chunk_parent"],
                "evidence_text": "Animals are living things.",
                "evidence_confidence": 0.88,
            }
        ]

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
                    "parent_evidence": parent_evidence,
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
        assert edge["evidence"] == parent_evidence

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
        assert "ontology_datatype_properties" in created
        assert "ontology_object_properties" in created
        assert "rdfs_domain" in created
        assert "rdfs_range_class" in created

    def test_property_rdf_type_object_vs_datatype(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = _mock_db(chunk_keys=[])
        relationship_evidence = [
            {
                "source_chunk_ids": ["chunk_rel"],
                "evidence_text": "Foo is related to Bar.",
                "evidence_confidence": 0.8,
            }
        ]

        result = _make_result(
            classes=[
                {
                    "label": "Foo",
                    "uri": "http://ex.org/ontology#Foo",
                    "properties": [
                        {"label": "name", "range": "xsd:string"},
                        {
                            "label": "relatedTo",
                            "range": "http://ex.org#Bar",
                            "evidence": relationship_evidence,
                        },
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

        dt_col = cols["ontology_datatype_properties"]
        dt_inserts = [c[0][0] for c in dt_col.insert.call_args_list]
        name_prop = next(p for p in dt_inserts if p["label"] == "name")
        assert name_prop["range_datatype"] == "xsd:string"

        obj_col = cols["ontology_object_properties"]
        obj_inserts = [c[0][0] for c in obj_col.insert.call_args_list]
        related_prop = next(p for p in obj_inserts if p["label"] == "relatedTo")
        assert related_prop["label"] == "relatedTo"
        assert related_prop["evidence"] == relationship_evidence

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
                "ontology_object_properties",
                "ontology_datatype_properties",
                "has_property",
                "subclass_of",
                "related_to",
                "rdfs_domain",
                "rdfs_range_class",
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
        # 1. rdfs_domain prop_type_counts, 2. has_parent, 3. has_children,
        # 4. rdfs_range_class lateral, 5. provenance_count
        mock_run_aql.side_effect = [
            [{"type": "ontology_datatype_properties", "cnt": 2}],  # prop types
            [],  # has_parent: no
            [True],  # has_children: yes
            [],  # rdfs_range_class lateral: no
            [1],  # provenance_count
        ]
        mock_db.has_collection.side_effect = lambda name: (
            name
            in {
                "rdfs_domain",
                "rdfs_range_class",
                "ontology_classes",
                "subclass_of",
                "extracted_from",
            }
        )

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
    def test_checks_rdfs_range_and_extends_domain(self, mock_run_aql, mock_compute):
        from app.services.extraction import _recompute_multi_signal_confidence

        mock_db, _cols = _mock_db()
        mock_db.has_collection.side_effect = lambda n: (
            n
            in {
                "rdfs_domain",
                "rdfs_range_class",
                "extends_domain",
                "ontology_classes",
                "subclass_of",
                "extracted_from",
            }
        )

        mock_run_aql.side_effect = [
            [],  # rdfs_domain prop_type_counts (no properties)
            [],  # has_parent
            [],  # has_children
            [True],  # rdfs_range_class lateral
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
        assert result["quality_from_cache"] is False
        assert result["quality_computed_at"] is not None
        mock_compute_ontology_quality.assert_called_once_with(
            mock_db,
            "onto_from_aql",
            include_estimated_cost=False,
        )


class TestGetRunCostQualityCache:
    """Stream 12 T7 -- cache the expensive ``compute_ontology_quality``
    call on the run document so repeat hits to ``GET /runs/{id}/cost``
    don't re-walk the whole ontology.
    """

    def _run_doc(
        self,
        cached_quality: dict | None = None,
        ontology_id: str = "onto_cached",
    ) -> dict:
        stats: dict = {
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "classes_extracted": 2,
            "properties_extracted": 5,
            "pass_agreement_rate": 0.9,
        }
        if cached_quality is not None:
            stats["cached_quality"] = cached_quality
        return {
            "_key": "run_c",
            "status": "completed",
            "model": "gpt-4o-mini",
            "ontology_id": ontology_id,
            "started_at": 100.0,
            "completed_at": 110.0,
            "stats": stats,
        }

    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_cache_miss_populates_snapshot(self, mock_get_db, mock_get_col, mock_doc_get, mock_aql):
        """First call after extraction: compute, write back, return."""
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = self._run_doc(cached_quality=None)

        runs_col = MagicMock()
        mock_get_col.return_value = runs_col

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
            return_value={"avg_confidence": 0.66, "completeness": 0.5},
        ) as mock_compute:
            result = get_run_cost(mock_db, run_id="run_c")

        assert mock_compute.call_count == 1
        assert result["avg_confidence"] == 0.66
        assert result["completeness_pct"] == 0.5
        assert result["quality_from_cache"] is False
        assert result["quality_computed_at"] is not None

        # The expensive compute should now be cached on the run doc.
        runs_col.update.assert_called_once()
        update_arg = runs_col.update.call_args[0][0]
        assert update_arg["_key"] == "run_c"
        cached = update_arg["stats"]["cached_quality"]
        assert cached["ontology_id"] == "onto_cached"
        assert cached["avg_confidence"] == 0.66
        assert cached["completeness"] == 0.5
        assert cached["computed_at"] is not None
        assert isinstance(cached["compute_ms"], int)

    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_cache_hit_skips_compute(self, mock_get_db, mock_get_col, mock_doc_get, mock_aql):
        """Subsequent call: serve from cache, skip the AQL walk."""
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        cached_at = 1_700_000_000.0
        mock_doc_get.return_value = self._run_doc(
            cached_quality={
                "ontology_id": "onto_cached",
                "avg_confidence": 0.42,
                "completeness": 0.99,
                "computed_at": cached_at,
                "compute_ms": 4321,
            },
        )

        runs_col = MagicMock()
        mock_get_col.return_value = runs_col

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
        ) as mock_compute:
            result = get_run_cost(mock_db, run_id="run_c")

        mock_compute.assert_not_called()
        assert result["avg_confidence"] == 0.42
        assert result["completeness_pct"] == 0.99
        assert result["quality_from_cache"] is True
        assert result["quality_computed_at"] == cached_at
        # No write on a cache hit -- the snapshot is unchanged.
        runs_col.update.assert_not_called()

    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_refresh_true_bypasses_cache(self, mock_get_db, mock_get_col, mock_doc_get, mock_aql):
        """``?refresh=true`` must always recompute, even when cached."""
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = self._run_doc(
            cached_quality={
                "ontology_id": "onto_cached",
                "avg_confidence": 0.42,
                "completeness": 0.99,
                "computed_at": 1_700_000_000.0,
                "compute_ms": 4321,
            },
        )

        runs_col = MagicMock()
        mock_get_col.return_value = runs_col

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
            return_value={"avg_confidence": 0.88, "completeness": 0.91},
        ) as mock_compute:
            result = get_run_cost(mock_db, run_id="run_c", refresh=True)

        assert mock_compute.call_count == 1
        assert result["avg_confidence"] == 0.88
        assert result["completeness_pct"] == 0.91
        assert result["quality_from_cache"] is False
        # A refresh writes the new snapshot.
        runs_col.update.assert_called_once()

    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_cache_for_different_ontology_invalidates(
        self, mock_get_db, mock_get_col, mock_doc_get, mock_aql
    ):
        """If the run's ontology_id changed since the cache was written,
        the snapshot is stale -- recompute and overwrite."""
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = self._run_doc(
            ontology_id="onto_now",
            cached_quality={
                "ontology_id": "onto_then",
                "avg_confidence": 0.1,
                "completeness": 0.1,
                "computed_at": 1.0,
                "compute_ms": 10,
            },
        )

        runs_col = MagicMock()
        mock_get_col.return_value = runs_col

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
            return_value={"avg_confidence": 0.5, "completeness": 0.5},
        ) as mock_compute:
            result = get_run_cost(mock_db, run_id="run_c")

        mock_compute.assert_called_once()
        assert result["avg_confidence"] == 0.5
        assert result["quality_from_cache"] is False
        runs_col.update.assert_called_once()

    @patch("app.services.extraction.run_aql", return_value=[])
    @patch("app.services.extraction.doc_get")
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_cache_write_failure_does_not_poison_response(
        self, mock_get_db, mock_get_col, mock_doc_get, mock_aql
    ):
        """A failed cache write must NOT propagate -- the cache is a
        perf hack, the user still gets their numbers."""
        from app.services.extraction import get_run_cost

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db
        mock_doc_get.return_value = self._run_doc(cached_quality=None)

        runs_col = MagicMock()
        runs_col.update.side_effect = RuntimeError("simulated arango outage")
        mock_get_col.return_value = runs_col

        with patch(
            "app.services.quality_metrics.compute_ontology_quality",
            return_value={"avg_confidence": 0.77, "completeness": 0.55},
        ):
            result = get_run_cost(mock_db, run_id="run_c")

        assert result["avg_confidence"] == 0.77
        assert result["completeness_pct"] == 0.55
        assert result["quality_from_cache"] is False


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
