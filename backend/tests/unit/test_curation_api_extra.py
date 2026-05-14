"""Additional unit tests for curation API route handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.curation import (
    batch_decide,
    curation_throughput,
    execute_merge,
    get_curation_diff,
    get_decision,
    get_promotion_status,
    list_decisions,
    promote_staging,
    record_decision,
)
from app.api.errors import NotFoundError, ValidationError
from app.models.curation import (
    BatchDecisionItem,
    BatchDecisionRequest,
    CurationAction,
    CurationDecisionCreate,
    CurationIssueReason,
    EntityType,
    MergeRequest,
    PromotionRequest,
)


class TestCurationRoutes:
    @pytest.mark.asyncio
    async def test_record_and_batch_decision_map_enums(self):
        body = CurationDecisionCreate(
            run_id="r1",
            entity_key="c1",
            entity_type=EntityType.CLASS,
            action=CurationAction.APPROVE,
            curator_id="u1",
            issue_reasons=[CurationIssueReason.MISSING_EVIDENCE],
        )
        batch = BatchDecisionRequest(
            run_id="r1",
            decisions=[
                BatchDecisionItem(
                    entity_key="c1",
                    entity_type=EntityType.CLASS,
                    action=CurationAction.REJECT,
                    curator_id="u1",
                    issue_reasons=[CurationIssueReason.HALLUCINATED],
                )
            ],
        )
        with (
            patch(
                "app.api.curation.curation_svc.record_decision", return_value={"ok": True}
            ) as mock_record,
            patch(
                "app.api.curation.curation_svc.batch_decide", return_value={"processed": 1}
            ) as mock_batch,
        ):
            result = await record_decision(body)
            batch_result = await batch_decide(batch)
        assert result == {"ok": True}
        assert batch_result == {"processed": 1}
        assert mock_record.call_args.kwargs["entity_type"] == "class"
        assert mock_record.call_args.kwargs["issue_reasons"] == ["missing_evidence"]
        assert mock_batch.call_args.kwargs["decisions"][0]["action"] == "reject"
        assert mock_batch.call_args.kwargs["decisions"][0]["issue_reasons"] == ["hallucinated"]

    @pytest.mark.asyncio
    async def test_list_and_get_decision(self):
        with (
            patch(
                "app.api.curation.curation_svc.get_decisions", return_value={"data": []}
            ) as mock_list,
            patch("app.api.curation.curation_svc.get_decision", return_value={"_key": "d1"}),
        ):
            listing = await list_decisions(run_id="r1", status="approve", cursor="c1", limit=5)
            decision = await get_decision("d1")
        mock_list.assert_called_once_with(run_id="r1", status="approve", cursor="c1", limit=5)
        assert listing == {"data": []}
        assert decision == {"_key": "d1"}

    @pytest.mark.asyncio
    async def test_get_decision_raises_when_missing(self):
        with (
            patch("app.api.curation.curation_svc.get_decision", return_value=None),
            pytest.raises(NotFoundError),
        ):
            await get_decision("missing")

    @pytest.mark.asyncio
    async def test_execute_merge_validates_target(self):
        body = MergeRequest(
            source_keys=["a", "b"],
            target_key="a",
            merged_data={},
            curator_id="u1",
        )
        with pytest.raises(ValidationError):
            await execute_merge(body)

    @pytest.mark.asyncio
    async def test_execute_merge_and_promote(self):
        body = MergeRequest(
            source_keys=["a"],
            target_key="b",
            merged_data={"label": "Merged"},
            curator_id="u1",
        )
        with (
            patch(
                "app.api.curation.curation_svc.merge_entities", return_value={"target_key": "b"}
            ) as mock_merge,
            patch(
                "app.api.curation.promotion_svc.promote_staging",
                return_value={"status": "completed"},
            ) as mock_promote,
        ):
            merge_result = await execute_merge(body)
            promote_result = await promote_staging("r1", PromotionRequest(ontology_id="onto1"))
        assert merge_result == {"target_key": "b"}
        assert promote_result == {"status": "completed"}
        assert mock_merge.call_args.kwargs["target_key"] == "b"
        assert mock_promote.call_args.kwargs["ontology_id"] == "onto1"

    @pytest.mark.asyncio
    async def test_get_curation_diff_computes_added_removed_changed(self):
        db = MagicMock()
        db.has_collection.return_value = True
        results_doc = {
            "extraction_result": {
                "classes": [
                    {"uri": "u:new", "label": "New"},
                    {"uri": "u:changed", "label": "Changed", "description": "new"},
                ]
            }
        }
        col = MagicMock()
        col.has.return_value = True
        db.collection.return_value = col
        with (
            patch("app.api.curation.get_db", return_value=db),
            patch("app.api.curation.doc_get", return_value=results_doc),
            patch(
                "app.api.curation.run_aql",
                return_value=[
                    {"uri": "u:changed", "label": "Changed", "description": "old"},
                    {"uri": "u:removed", "label": "Removed", "description": "gone"},
                ],
            ),
        ):
            diff = await get_curation_diff("r1", ontology_id="onto1")
        assert len(diff["added"]) == 1
        assert len(diff["removed"]) == 1
        assert len(diff["changed"]) == 1

    @pytest.mark.asyncio
    async def test_record_decision_forwards_latency(self):
        """Q.5 — latency must reach the service so it is persisted."""
        body = CurationDecisionCreate(
            run_id="r1",
            entity_key="c1",
            entity_type=EntityType.CLASS,
            action=CurationAction.APPROVE,
            curator_id="u1",
            decision_latency_ms=2_750,
        )
        with patch(
            "app.api.curation.curation_svc.record_decision",
            return_value={"ok": True},
        ) as mock_record:
            await record_decision(body)
        assert mock_record.call_args.kwargs["decision_latency_ms"] == 2_750

    @pytest.mark.asyncio
    async def test_batch_decide_forwards_latency(self):
        body = BatchDecisionRequest(
            run_id="r1",
            decisions=[
                BatchDecisionItem(
                    entity_key="c1",
                    entity_type=EntityType.CLASS,
                    action=CurationAction.APPROVE,
                    curator_id="u1",
                    decision_latency_ms=1_000,
                )
            ],
        )
        with patch(
            "app.api.curation.curation_svc.batch_decide",
            return_value={"processed": 1},
        ) as mock_batch:
            await batch_decide(body)
        assert mock_batch.call_args.kwargs["decisions"][0]["decision_latency_ms"] == 1_000

    @pytest.mark.asyncio
    async def test_throughput_endpoint_forwards_filters(self):
        """Q.5 — the /throughput route must forward query params verbatim
        and return the service payload."""
        with patch(
            "app.api.curation.curation_svc.compute_curation_throughput",
            return_value={
                "decisions_in_window": 5,
                "decisions_per_hour": 30.0,
                "active_time_seconds": 600.0,
                "wall_clock_seconds": 600.0,
                "first_decision_at": 1.0,
                "last_decision_at": 2.0,
                "source": "active_time",
                "window_seconds": 1800,
                "run_id": "r1",
                "ontology_id": "onto1",
            },
        ) as mock_compute:
            payload = await curation_throughput(
                run_id="r1",
                ontology_id="onto1",
                window_seconds=1800,
            )
        assert payload["decisions_per_hour"] == 30.0
        assert payload["source"] == "active_time"
        kwargs = mock_compute.call_args.kwargs
        assert kwargs == {"run_id": "r1", "ontology_id": "onto1", "window_seconds": 1800}

    @pytest.mark.asyncio
    async def test_get_promotion_status_handles_missing_and_present(self):
        with patch(
            "app.api.curation.promotion_svc.get_promotion_status",
            side_effect=[None, {"status": "completed"}],
        ):
            not_started = await get_promotion_status("r1")
            started = await get_promotion_status("r1")
        assert not_started["status"] == "not_started"
        assert started["status"] == "completed"
