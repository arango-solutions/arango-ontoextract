"""Unit tests for the belief-revision MCP tools (Stream 11 IBR.20).

Mirrors the pattern from ``test_mcp.py`` -- captures the tool functions
from ``register_belief_revision_tools`` via a fake MCP server so we can
invoke them directly with mocked services.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _capture_tools(register_fn):
    """Capture the tool functions registered on a fake MCP server.

    Returns a dict mapping ``tool_name -> callable``.
    """
    mcp = MagicMock()
    captured = {}

    def fake_tool():
        def decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return decorator

    mcp.tool = fake_tool
    register_fn(mcp)
    return captured


# ---------------------------------------------------------------------------
# list_revisions_inbox
# ---------------------------------------------------------------------------


class TestListRevisionsInboxTool:
    @patch("app.db.client.get_db", return_value=object())
    @patch("app.db.revision_meta_repo.list_inbox", return_value=[{"_key": "rev_1"}])
    def test_returns_data_with_count(self, mock_inbox, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["list_revisions_inbox"]("onto_1", limit=25)

        mock_inbox.assert_called_once()
        kwargs = mock_inbox.call_args.kwargs
        assert kwargs["limit"] == 25
        assert result == {
            "data": [{"_key": "rev_1"}],
            "ontology_id": "onto_1",
            "count": 1,
        }

    @patch(
        "app.db.client.get_db",
        side_effect=RuntimeError("DB unreachable"),
    )
    def test_returns_error_envelope_on_exception(self, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["list_revisions_inbox"]("onto_1")
        assert "error" in result
        assert result["ontology_id"] == "onto_1"


# ---------------------------------------------------------------------------
# list_recent_revisions
# ---------------------------------------------------------------------------


class TestListRecentRevisionsTool:
    @patch("app.db.client.get_db", return_value=object())
    @patch(
        "app.db.revision_meta_repo.list_revisions",
        return_value=[{"_key": "rev_1"}, {"_key": "rev_2"}],
    )
    def test_passes_filters(self, mock_list, _mock_db):
        from app.db import revision_meta_repo as rev_repo
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["list_recent_revisions"](
            "onto_1",
            limit=10,
            action=rev_repo.ACTION_REINFORCE,
            status=rev_repo.STATUS_APPLIED,
            since=1700000000.0,
        )
        kwargs = mock_list.call_args.kwargs
        assert kwargs["action"] == rev_repo.ACTION_REINFORCE
        assert kwargs["status"] == rev_repo.STATUS_APPLIED
        assert kwargs["since"] == 1700000000.0
        assert kwargs["limit"] == 10
        assert result["count"] == 2

    @patch("app.db.client.get_db", return_value=object())
    def test_invalid_action_returns_error(self, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["list_recent_revisions"]("onto_1", action="NOT_REAL")
        assert "error" in result
        assert "valid_actions" in result

    @patch("app.db.client.get_db", return_value=object())
    def test_invalid_status_returns_error(self, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["list_recent_revisions"]("onto_1", status="NOT_REAL")
        assert "error" in result
        assert "valid_statuses" in result


# ---------------------------------------------------------------------------
# get_revision
# ---------------------------------------------------------------------------


class TestGetRevisionTool:
    @patch("app.db.client.get_db", return_value=object())
    @patch(
        "app.db.revision_meta_repo.get_revision",
        return_value={"_key": "rev_1", "status": "pending"},
    )
    def test_returns_row(self, _mock_get, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        assert tools["get_revision"]("rev_1") == {
            "_key": "rev_1",
            "status": "pending",
        }

    @patch("app.db.client.get_db", return_value=object())
    @patch("app.db.revision_meta_repo.get_revision", return_value=None)
    def test_returns_not_found(self, _mock_get, _mock_db):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["get_revision"]("missing")
        assert result["error"] == "not_found"
        assert result["revision_key"] == "missing"


# ---------------------------------------------------------------------------
# decide_revision (single-tool dispatch)
# ---------------------------------------------------------------------------


@pytest.fixture
def _decision_result():
    from app.db import revision_meta_repo as rev_repo
    from app.services.revision_actions import RevisionDecisionResult

    return RevisionDecisionResult(
        revision_key="rev_1",
        decision=rev_repo.STATUS_ACCEPTED,
        status=rev_repo.STATUS_ACCEPTED,
        already_decided=False,
        supersede_result={"action": "GAP_FILL", "skipped": False},
        revision={"_key": "rev_1", "status": rev_repo.STATUS_ACCEPTED},
    )


class TestDecideRevisionTool:
    def test_accept_dispatches_to_accept_revision(self, _decision_result):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        with patch(
            "app.services.revision_actions.accept_revision",
            return_value=_decision_result,
        ) as mock_accept:
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["decide_revision"](
                "rev_1",
                decision="accept",
                decided_by="alice",
                note="LGTM",
                new_edge={"_from": "a/x", "_to": "a/y"},
                new_edge_collection="subclass_of",
            )
        mock_accept.assert_called_once()
        kwargs = mock_accept.call_args.kwargs
        assert kwargs["decided_by"] == "alice"
        assert kwargs["new_edge_collection"] == "subclass_of"
        assert result["decision"] == "accepted"

    def test_reject_dispatches_to_reject_revision(self, _decision_result):
        from app.db import revision_meta_repo as rev_repo
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services.revision_actions import RevisionDecisionResult

        rejected = RevisionDecisionResult(
            revision_key="rev_1",
            decision=rev_repo.STATUS_REJECTED,
            status=rev_repo.STATUS_REJECTED,
            revision={"_key": "rev_1", "status": rev_repo.STATUS_REJECTED},
        )
        with patch(
            "app.services.revision_actions.reject_revision", return_value=rejected
        ) as mock_reject:
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["decide_revision"](
                "rev_1", decision="reject", decided_by="bob", note="not in scope"
            )
        mock_reject.assert_called_once()
        assert result["decision"] == rev_repo.STATUS_REJECTED

    def test_modify_dispatches_to_modify_revision(self, _decision_result):
        from app.db import revision_meta_repo as rev_repo
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services.revision_actions import RevisionDecisionResult

        modified = RevisionDecisionResult(
            revision_key="rev_1",
            decision=rev_repo.STATUS_MODIFIED,
            status=rev_repo.STATUS_MODIFIED,
            revision={"_key": "rev_1", "status": rev_repo.STATUS_MODIFIED},
        )
        with patch(
            "app.services.revision_actions.modify_revision", return_value=modified
        ) as mock_mod:
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["decide_revision"](
                "rev_1",
                decision="modify",
                decided_by="alice",
                override_action=rev_repo.ACTION_RETRACT,
            )
        mock_mod.assert_called_once()
        kwargs = mock_mod.call_args.kwargs
        assert kwargs["override_action"] == rev_repo.ACTION_RETRACT
        assert result["decision"] == rev_repo.STATUS_MODIFIED

    def test_invalid_decision_returns_error(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        result = tools["decide_revision"](
            "rev_1", decision="please_accept", decided_by="alice"
        )
        assert "error" in result
        assert "valid" in result

    def test_not_found_translated_to_error_envelope(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services.revision_actions import RevisionNotFoundError

        with patch(
            "app.services.revision_actions.accept_revision",
            side_effect=RevisionNotFoundError("rev_1"),
        ):
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["decide_revision"](
                "rev_1", decision="accept", decided_by="alice"
            )
        assert result["error"] == "not_found"

    def test_action_error_translated_to_validation_envelope(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services.revision_actions import RevisionActionError

        with patch(
            "app.services.revision_actions.accept_revision",
            side_effect=RevisionActionError("REVISE requires new_vertex_data"),
        ):
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["decide_revision"](
                "rev_1", decision="accept", decided_by="alice"
            )
        assert result["error"] == "validation_error"
        assert "new_vertex_data" in result["message"]


# ---------------------------------------------------------------------------
# run_consolidation
# ---------------------------------------------------------------------------


class TestRunConsolidationTool:
    def test_dry_run_default_true(self):
        """The MCP tool must default to dry_run=True so agents preview by default."""
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services import consolidation

        report = consolidation.ConsolidationReport(
            job_key="job_1",
            ontology_id="onto_1",
            dry_run=True,
            started_at=0.0,
            finished_at=1.0,
            status="completed",
        )
        with patch(
            "app.services.consolidation.run_consolidation", return_value=report
        ) as mock_run:
            tools = _capture_tools(register_belief_revision_tools)
            tools["run_consolidation"]("onto_1")
        kwargs = mock_run.call_args.kwargs
        # CRITICAL: tool default must be True
        assert kwargs["dry_run"] is True

    def test_passes_through_overrides(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services import consolidation

        report = consolidation.ConsolidationReport(
            job_key="resume_me",
            ontology_id="onto_1",
            dry_run=False,
            started_at=0.0,
            finished_at=2.0,
            status="completed",
        )
        with patch(
            "app.services.consolidation.run_consolidation", return_value=report
        ) as mock_run:
            tools = _capture_tools(register_belief_revision_tools)
            result = tools["run_consolidation"](
                "onto_1",
                dry_run=False,
                job_key="resume_me",
                stale_after_days=30.0,
                stale_inbox_limit=50,
            )
        kwargs = mock_run.call_args.kwargs
        assert kwargs["dry_run"] is False
        assert kwargs["job_key"] == "resume_me"
        assert kwargs["stale_after_days"] == 30.0
        assert kwargs["stale_inbox_limit"] == 50
        assert result["job_key"] == "resume_me"


# ---------------------------------------------------------------------------
# get_circuit_breaker_state
# ---------------------------------------------------------------------------


class TestCircuitBreakerStateTool:
    def test_returns_snapshot(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools
        from app.services import revision_safety

        revision_safety.reset_default_limiter()
        tools = _capture_tools(register_belief_revision_tools)
        snap = tools["get_circuit_breaker_state"]()
        assert "max_per_window" in snap
        assert "tripped" in snap
        revision_safety.reset_default_limiter()


# ---------------------------------------------------------------------------
# All six tools registered
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_six_tools_registered(self):
        from app.mcp.tools.belief_revision import register_belief_revision_tools

        tools = _capture_tools(register_belief_revision_tools)
        assert set(tools.keys()) == {
            "list_revisions_inbox",
            "list_recent_revisions",
            "get_revision",
            "decide_revision",
            "run_consolidation",
            "get_circuit_breaker_state",
        }
