"""Tests for the consolidation admin endpoints (Stream 11 IBR.17)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.admin import (
    consolidate_ontology,
    get_circuit_breaker_state,
    get_consolidation_job,
    list_consolidation_jobs,
)
from app.services import consolidation, revision_safety


def _report(**overrides):
    rep = consolidation.ConsolidationReport(
        job_key="job_1",
        ontology_id="onto_1",
        dry_run=False,
        started_at=0.0,
        finished_at=1.0,
        status="completed",
    )
    for k, v in overrides.items():
        setattr(rep, k, v)
    return rep


class TestConsolidateOntologyEndpoint:
    @pytest.mark.asyncio
    async def test_passes_through_query_params_to_service(self):
        with patch("app.api.admin.run_consolidation", return_value=_report()) as mock_run:
            result = await consolidate_ontology(
                ontology_id="onto_1",
                dry_run=True,
                job_key="my_key",
                stale_after_days=30.0,
                stale_inbox_limit=100,
            )
        kwargs = mock_run.call_args.kwargs
        assert mock_run.call_args.args[0] == "onto_1"
        assert kwargs["dry_run"] is True
        assert kwargs["job_key"] == "my_key"
        assert kwargs["stale_after_days"] == 30.0
        assert kwargs["stale_inbox_limit"] == 100
        assert result["job_key"] == "job_1"
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_500_when_service_raises(self):
        with (
            patch(
                "app.api.admin.run_consolidation",
                side_effect=RuntimeError("DB down"),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await consolidate_ontology(ontology_id="onto_1")
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_dry_run_passed_as_false_writes_revisions(self):
        # When called via the test client we'd see Query(...) defaults
        # unwrap; here we pass dry_run=False explicitly to verify the
        # service receives a literal False.
        with patch("app.api.admin.run_consolidation", return_value=_report()) as mock_run:
            await consolidate_ontology(ontology_id="onto_1", dry_run=False)
        assert mock_run.call_args.kwargs["dry_run"] is False


class TestListConsolidationJobsEndpoint:
    @pytest.mark.asyncio
    async def test_passes_filter_to_service(self):
        with patch(
            "app.api.admin.list_recent_jobs",
            return_value=[{"_key": "job_1"}],
        ) as mock_list:
            result = await list_consolidation_jobs(ontology_id="onto_1", limit=5)
        kwargs = mock_list.call_args.kwargs
        assert kwargs["ontology_id"] == "onto_1"
        assert kwargs["limit"] == 5
        assert result["data"] == [{"_key": "job_1"}]
        assert result["ontology_id"] == "onto_1"

    @pytest.mark.asyncio
    async def test_no_ontology_filter(self):
        with patch(
            "app.api.admin.list_recent_jobs",
            return_value=[],
        ) as mock_list:
            result = await list_consolidation_jobs(ontology_id=None, limit=25)
        kwargs = mock_list.call_args.kwargs
        assert kwargs["ontology_id"] is None
        assert result["data"] == []


class TestGetConsolidationJobEndpoint:
    @pytest.mark.asyncio
    async def test_404_when_missing(self):
        with (
            patch("app.api.admin.load_cursor", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_consolidation_job("missing")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_cursor_doc(self):
        cursor = revision_safety.ConsolidationCursor(
            job_key="job_1",
            ontology_id="onto_1",
            stage="done",
            processed_count=5,
            status="completed",
        )
        with patch("app.api.admin.load_cursor", return_value=cursor):
            doc = await get_consolidation_job("job_1")
        assert doc["_key"] == "job_1"
        assert doc["status"] == "completed"
        assert doc["processed_count"] == 5


class TestCircuitBreakerStateEndpoint:
    @pytest.mark.asyncio
    async def test_returns_default_limiter_snapshot(self):
        revision_safety.reset_default_limiter()
        snap = await get_circuit_breaker_state()
        assert "max_per_window" in snap
        assert "window_seconds" in snap
        assert "tripped" in snap
        assert snap["tripped"] is False  # fresh limiter
        revision_safety.reset_default_limiter()
