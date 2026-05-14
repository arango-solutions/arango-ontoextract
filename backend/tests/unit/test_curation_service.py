"""Unit tests for curation service — all DB operations mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRecordDecision:
    """Tests for curation_svc.record_decision."""

    @patch("app.services.curation.curation_repo")
    @patch("app.services.curation.update_entity")
    def test_approve_creates_decision_and_updates_entity(self, mock_update, mock_repo):
        from app.services.curation import record_decision

        mock_repo.create_decision.return_value = {
            "_key": "dec1",
            "_id": "curation_decisions/dec1",
            "run_id": "run_1",
            "entity_key": "cls1",
            "entity_type": "class",
            "action": "approve",
            "curator_id": "curator_a",
            "created_at": 1700000000.0,
        }
        mock_update.return_value = {"_key": "cls1_v2", "status": "approved"}

        mock_db = MagicMock()
        result = record_decision(
            mock_db,
            run_id="run_1",
            entity_key="cls1",
            entity_type="class",
            action="approve",
            curator_id="curator_a",
            issue_reasons=["missing_evidence"],
        )

        assert result["_key"] == "dec1"
        assert result["action"] == "approve"
        mock_repo.create_decision.assert_called_once()
        decision_doc = mock_repo.create_decision.call_args.kwargs["data"]
        assert decision_doc["issue_reasons"] == ["missing_evidence"]
        assert decision_doc["edit_diff"] is None
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["new_data"]["status"] == "approved"

    @patch("app.services.curation.curation_repo")
    @patch("app.db.ontology_repo.expire_class_cascade")
    def test_reject_cascades_class(self, mock_cascade, mock_repo):
        from app.services.curation import record_decision

        mock_repo.create_decision.return_value = {
            "_key": "dec2",
            "_id": "curation_decisions/dec2",
            "action": "reject",
            "entity_key": "cls2",
            "entity_type": "class",
            "run_id": "run_1",
            "curator_id": "curator_a",
            "created_at": 1700000000.0,
        }
        mock_cascade.return_value = {"_key": "cls2"}

        mock_db = MagicMock()
        result = record_decision(
            mock_db,
            run_id="run_1",
            entity_key="cls2",
            entity_type="class",
            action="reject",
            curator_id="curator_a",
        )

        assert result["action"] == "reject"
        mock_cascade.assert_called_once_with(mock_db, key="cls2")

    @patch("app.services.curation._get_current_by_key")
    @patch("app.services.curation.curation_repo")
    @patch("app.services.curation.update_entity")
    def test_edit_creates_new_version_with_data(self, mock_update, mock_repo, mock_current):
        from app.services.curation import record_decision

        mock_current.return_value = {
            "_key": "cls3",
            "label": "Old Label",
            "description": "Old description",
        }
        mock_repo.create_decision.return_value = {
            "_key": "dec3",
            "_id": "curation_decisions/dec3",
            "action": "edit",
            "entity_key": "cls3",
            "entity_type": "class",
            "run_id": "run_1",
            "curator_id": "curator_a",
            "created_at": 1700000000.0,
        }
        mock_update.return_value = {"_key": "cls3_v2", "label": "New Label"}

        mock_db = MagicMock()
        result = record_decision(
            mock_db,
            run_id="run_1",
            entity_key="cls3",
            entity_type="class",
            action="edit",
            curator_id="curator_a",
            issue_reasons=["bad_label", "bad_description"],
            edited_data={"label": "New Label", "description": "New description"},
        )

        assert result["action"] == "edit"
        decision_doc = mock_repo.create_decision.call_args.kwargs["data"]
        assert decision_doc["issue_reasons"] == ["bad_label", "bad_description"]
        assert decision_doc["edit_diff"] == {
            "changed_fields": ["description", "label"],
            "before": {
                "description": "Old description",
                "label": "Old Label",
            },
            "after": {
                "description": "New description",
                "label": "New Label",
            },
        }
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["new_data"]["label"] == "New Label"

    @patch("app.services.curation.curation_repo")
    def test_edge_decision_has_no_temporal_side_effect(self, mock_repo):
        from app.services.curation import record_decision

        mock_repo.create_decision.return_value = {
            "_key": "dec4",
            "_id": "curation_decisions/dec4",
            "action": "approve",
            "entity_key": "edge1",
            "entity_type": "edge",
            "run_id": "run_1",
            "curator_id": "curator_a",
            "created_at": 1700000000.0,
        }

        mock_db = MagicMock()
        result = record_decision(
            mock_db,
            run_id="run_1",
            entity_key="edge1",
            entity_type="edge",
            action="approve",
            curator_id="curator_a",
        )

        assert result["entity_type"] == "edge"

    def test_unsupported_entity_type_raises(self):
        from app.services.curation import _collection_for

        with pytest.raises(ValueError, match="Unsupported entity_type"):
            _collection_for("unknown")

    @patch("app.services.curation._resolve_property_collection")
    def test_property_entity_type_resolves_collection_via_db(self, mock_resolve):
        from app.services.curation import _collection_for

        mock_db = MagicMock()
        mock_resolve.return_value = "ontology_object_properties"
        col = _collection_for("property", db=mock_db, entity_key="k1")
        assert col == "ontology_object_properties"
        mock_resolve.assert_called_once_with(mock_db, "k1")

    def test_property_entity_type_defaults_without_db(self):
        from app.services.curation import _collection_for

        assert _collection_for("property") == "ontology_properties"


class TestBatchDecide:
    """Tests for curation_svc.batch_decide."""

    @patch("app.services.curation.record_decision")
    def test_processes_all_decisions(self, mock_record):
        from app.services.curation import batch_decide

        mock_record.side_effect = [
            {"_key": "d1", "action": "approve"},
            {"_key": "d2", "action": "reject"},
        ]

        mock_db = MagicMock()
        result = batch_decide(
            mock_db,
            run_id="run_1",
            decisions=[
                {
                    "entity_key": "cls1",
                    "entity_type": "class",
                    "action": "approve",
                    "curator_id": "curator",
                },
                {
                    "entity_key": "cls2",
                    "entity_type": "class",
                    "action": "reject",
                    "curator_id": "curator",
                    "issue_reasons": ["hallucinated"],
                },
            ],
        )

        assert result["processed"] == 2
        assert result["succeeded"] == 2
        assert result["failed"] == 0
        assert mock_record.call_args_list[1].kwargs["issue_reasons"] == ["hallucinated"]

    @patch("app.services.curation.record_decision")
    def test_captures_errors_without_aborting(self, mock_record):
        from app.services.curation import batch_decide

        mock_record.side_effect = [
            {"_key": "d1", "action": "approve"},
            ValueError("entity not found"),
        ]

        mock_db = MagicMock()
        result = batch_decide(
            mock_db,
            run_id="run_1",
            decisions=[
                {
                    "entity_key": "cls1",
                    "entity_type": "class",
                    "action": "approve",
                    "curator_id": "curator",
                },
                {
                    "entity_key": "missing",
                    "entity_type": "class",
                    "action": "approve",
                    "curator_id": "curator",
                },
            ],
        )

        assert result["processed"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert len(result["errors"]) == 1


class TestMergeEntities:
    """Tests for curation_svc.merge_entities."""

    @patch("app.services.curation.curation_repo")
    @patch("app.services.curation.re_create_edges")
    @patch("app.services.curation.expire_entity")
    @patch("app.services.curation.update_entity")
    @patch("app.services.curation._get_current_by_key")
    def test_merges_sources_into_target(
        self, mock_get, mock_update, mock_expire, mock_recreate, mock_repo
    ):
        from app.services.curation import merge_entities

        mock_get.side_effect = [
            {"_key": "tgt", "_id": "ontology_classes/tgt", "label": "Target"},
            {"_key": "src1", "_id": "ontology_classes/src1", "label": "Source 1"},
        ]
        mock_expire.return_value = {"_key": "src1", "expired": 1700000000.0}
        mock_recreate.return_value = 2
        mock_update.return_value = {
            "_key": "tgt_v2",
            "label": "Merged",
            "status": "approved",
        }
        mock_repo.create_decision.return_value = {"_key": "merge_dec"}

        mock_db = MagicMock()
        result = merge_entities(
            mock_db,
            source_keys=["src1"],
            target_key="tgt",
            merged_data={"label": "Merged"},
            curator_id="curator_a",
        )

        assert result["target_key"] == "tgt"
        assert "src1" in result["expired_sources"]
        assert result["edges_recreated"] > 0
        mock_expire.assert_called_once()

    @patch("app.services.curation._get_current_by_key")
    def test_raises_when_target_not_found(self, mock_get):
        from app.services.curation import merge_entities

        mock_get.return_value = None

        mock_db = MagicMock()
        with pytest.raises(ValueError, match="not found"):
            merge_entities(
                mock_db,
                source_keys=["src1"],
                target_key="missing",
                merged_data={},
                curator_id="curator_a",
            )


class TestGetDecisions:
    """Tests for curation_svc.get_decisions / get_decision."""

    @patch("app.services.curation.curation_repo")
    def test_get_decisions_delegates_to_repo(self, mock_repo):
        from app.models.common import PaginatedResponse
        from app.services.curation import get_decisions

        mock_repo.list_decisions.return_value = PaginatedResponse(
            data=[{"_key": "d1"}],
            cursor=None,
            has_more=False,
            total_count=1,
        )

        mock_db = MagicMock()
        result = get_decisions(mock_db, run_id="run_1")

        assert result["total_count"] == 1
        assert len(result["data"]) == 1

    @patch("app.services.curation.curation_repo")
    def test_get_decision_returns_none_for_missing(self, mock_repo):
        from app.services.curation import get_decision

        mock_repo.get_decision.return_value = None

        mock_db = MagicMock()
        result = get_decision(mock_db, decision_id="missing")
        assert result is None


class TestRecordDecisionLatency:
    """Q.5 — record_decision must persist the optional decision_latency_ms."""

    @patch("app.services.curation.curation_repo")
    @patch("app.services.curation.update_entity")
    def test_persists_latency_when_provided(self, mock_update, mock_repo):
        from app.services.curation import record_decision

        mock_repo.create_decision.return_value = {"_key": "d1"}

        record_decision(
            MagicMock(),
            run_id="run_1",
            entity_key="cls1",
            entity_type="class",
            action="approve",
            curator_id="curator_a",
            decision_latency_ms=4_500,
        )

        decision_doc = mock_repo.create_decision.call_args.kwargs["data"]
        assert decision_doc["decision_latency_ms"] == 4_500

    @patch("app.services.curation.curation_repo")
    @patch("app.services.curation.update_entity")
    def test_persists_none_latency_when_omitted(self, mock_update, mock_repo):
        from app.services.curation import record_decision

        mock_repo.create_decision.return_value = {"_key": "d2"}

        record_decision(
            MagicMock(),
            run_id="run_1",
            entity_key="cls1",
            entity_type="class",
            action="approve",
            curator_id="curator_a",
        )

        decision_doc = mock_repo.create_decision.call_args.kwargs["data"]
        # MUST be present as None so the field is queryable later, rather
        # than missing on the doc (which would force COALESCE in AQL).
        assert decision_doc["decision_latency_ms"] is None


class TestComputeCurationThroughput:
    """Q.5 — compute_curation_throughput aggregates active vs wall-clock."""

    def test_returns_empty_when_collection_missing(self):
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_curation_throughput(db)
        assert result["decisions_in_window"] == 0
        assert result["decisions_per_hour"] is None
        assert result["source"] == "none"
        assert result["window_seconds"] == 3600

    def test_returns_empty_when_no_decisions_in_window(self):
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter([{"count": 0, "active_ms_sum": None, "measured_count": 0}]),
        ):
            result = compute_curation_throughput(db, window_seconds=3600)
        assert result["decisions_in_window"] == 0
        assert result["source"] == "none"

    def test_uses_active_time_when_latencies_present(self):
        """Active-time path: 12 decisions, 600 s of active time → 72/h."""
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter(
                [
                    {
                        "count": 12,
                        "active_ms_sum": 600_000,
                        "measured_count": 12,
                        "first_ts": 1_700_000_000.0,
                        "last_ts": 1_700_000_900.0,
                    }
                ]
            ),
        ):
            result = compute_curation_throughput(db)
        assert result["decisions_in_window"] == 12
        assert result["active_time_seconds"] == pytest.approx(600.0)
        assert result["decisions_per_hour"] == pytest.approx(72.0)
        assert result["source"] == "active_time"

    def test_extrapolates_active_time_for_partial_measurements(self):
        """When only some decisions carry latencies, scale active time
        up so the rate doesn't undercount the unmeasured rows."""
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter(
                [
                    {
                        "count": 10,
                        "active_ms_sum": 300_000,  # 5 min across measured rows
                        "measured_count": 5,  # only half had latencies
                        "first_ts": 1_700_000_000.0,
                        "last_ts": 1_700_000_900.0,
                    }
                ]
            ),
        ):
            result = compute_curation_throughput(db)
        # Extrapolated active time = 300 s × (10 / 5) = 600 s ⇒ 60/h
        assert result["active_time_seconds"] == pytest.approx(600.0)
        assert result["decisions_per_hour"] == pytest.approx(60.0)
        assert result["source"] == "active_time"

    def test_falls_back_to_wall_clock_when_no_latencies(self):
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter(
                [
                    {
                        "count": 6,
                        "active_ms_sum": None,
                        "measured_count": 0,
                        "first_ts": 1_700_000_000.0,
                        "last_ts": 1_700_000_600.0,  # 600 s wall-clock span
                    }
                ]
            ),
        ):
            result = compute_curation_throughput(db)
        # 6 decisions over 600 s wall-clock ⇒ 36/h
        assert result["decisions_per_hour"] == pytest.approx(36.0)
        assert result["source"] == "wall_clock"
        assert result["active_time_seconds"] is None

    def test_source_none_when_count_one_and_no_latency(self):
        """A single unmeasured decision yields no rate at all (wall-clock
        span is zero), but we still report the count."""
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter(
                [
                    {
                        "count": 1,
                        "active_ms_sum": None,
                        "measured_count": 0,
                        "first_ts": 1_700_000_000.0,
                        "last_ts": 1_700_000_000.0,
                    }
                ]
            ),
        ):
            result = compute_curation_throughput(db)
        assert result["decisions_in_window"] == 1
        assert result["decisions_per_hour"] is None
        assert result["source"] == "none"

    def test_run_id_filter_passed_to_aql(self):
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter([{"count": 0}]),
        ) as mock_aql:
            compute_curation_throughput(db, run_id="run_42")
        bind_vars = mock_aql.call_args.kwargs["bind_vars"]
        assert bind_vars["run_id"] == "run_42"

    def test_ontology_id_filter_uses_extraction_runs_join(self):
        from app.services.curation import compute_curation_throughput

        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.curation.run_aql",
            return_value=iter([{"count": 0}]),
        ) as mock_aql:
            compute_curation_throughput(db, ontology_id="onto_99")
        query = mock_aql.call_args.args[1] if len(mock_aql.call_args.args) >= 2 else mock_aql.call_args.kwargs.get("query")
        # The AQL must join through extraction_runs to translate
        # ontology_id → run_id since curation_decisions stores run_id.
        assert "extraction_runs" in (query or "")
        assert mock_aql.call_args.kwargs["bind_vars"]["oid"] == "onto_99"
