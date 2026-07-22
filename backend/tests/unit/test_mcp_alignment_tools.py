"""Unit tests for the alignment MCP tools (Stream 20 / AL-PR6).

Mirrors ``test_mcp_belief_revision_tools.py``: captures the tool functions from
``register_alignment_tools`` via a fake MCP server and invokes them with the
service layer mocked. Includes a P1 flow test (align -> confirm -> master).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.mcp.tools.alignment import register_alignment_tools


def _capture_tools(register_fn):
    captured = {}

    class _Mcp:
        def tool(self):
            def decorator(fn):
                captured[fn.__name__] = fn
                return fn

            return decorator

    register_fn(_Mcp())
    return captured


TOOLS = _capture_tools(register_alignment_tools)


class TestAlignOntologies:
    def test_threads_params_and_returns_session(self) -> None:
        session = {"_key": "s1", "candidate_count": 3}
        with patch("app.services.alignment.create_alignment_session", return_value=session) as mk:
            out = TOOLS["align_ontologies"](["o1", "o2"], min_score=0.6, weights={"label": 1.0})
        assert out == session
        kwargs = mk.call_args.kwargs
        assert kwargs["source_ontology_ids"] == ["o1", "o2"]
        assert kwargs["min_score"] == 0.6
        assert kwargs["weights"] == {"label": 1.0}

    def test_value_error_becomes_validation_envelope(self) -> None:
        with patch(
            "app.services.alignment.create_alignment_session",
            side_effect=ValueError("alignment requires at least 2 distinct source ontologies"),
        ):
            out = TOOLS["align_ontologies"](["o1"])
        assert out["error"] == "validation_error"
        assert "2 distinct" in out["message"]


class TestAdjudicate:
    async def test_awaits_service_and_threads_band(self) -> None:
        result = {"auto_accepted": 2, "llm_adjudicated": 1}
        with patch(
            "app.services.alignment.adjudicate_session",
            new=AsyncMock(return_value=result),
        ) as mk:
            out = await TOOLS["adjudicate_alignment"]("s1", auto_accept_band=0.9)
        assert out == result
        assert mk.call_args.kwargs["auto_accept_band"] == 0.9
        assert mk.call_args.kwargs["session_id"] == "s1"

    async def test_error_envelope(self) -> None:
        with patch(
            "app.services.alignment.adjudicate_session",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ):
            out = await TOOLS["adjudicate_alignment"]("s1")
        assert out["error"] == "llm down"
        assert out["session_id"] == "s1"


class TestListCorrespondences:
    def test_wraps_rows_with_count(self) -> None:
        rows = [{"_key": "c1"}, {"_key": "c2"}]
        with patch("app.services.alignment.list_session_candidates", return_value=rows) as mk:
            out = TOOLS["list_correspondences"]("s1", status="candidate", limit=50)
        assert out == {"session_id": "s1", "correspondences": rows, "count": 2}
        assert mk.call_args.kwargs["status"] == "candidate"
        assert mk.call_args.kwargs["limit"] == 50

    def test_invalid_status_rejected(self) -> None:
        out = TOOLS["list_correspondences"]("s1", status="bogus")
        assert out["error"] == "validation_error"
        assert "valid_statuses" in out


class TestAcceptReject:
    def test_accept_sets_accepted(self) -> None:
        with patch(
            "app.services.alignment.set_candidate_status", return_value={"_key": "c1"}
        ) as mk:
            out = TOOLS["accept_correspondence"]("c1")
        assert out == {"_key": "c1"}
        assert mk.call_args.args[2] == "accepted"

    def test_reject_sets_rejected(self) -> None:
        with patch(
            "app.services.alignment.set_candidate_status", return_value={"_key": "c1"}
        ) as mk:
            TOOLS["reject_correspondence"]("c1")
        assert mk.call_args.args[2] == "rejected"

    def test_not_found_envelope(self) -> None:
        with patch("app.services.alignment.set_candidate_status", return_value=None):
            out = TOOLS["accept_correspondence"]("nope")
        assert out["error"] == "not_found"
        assert out["correspondence_key"] == "nope"


class TestMaterialize:
    def test_threads_name(self) -> None:
        master = {"master_ontology_id": "master_1", "class_count": 2}
        with patch("app.services.alignment.materialize_master", return_value=master) as mk:
            out = TOOLS["materialize_master"]("s1", name="Unified")
        assert out == master
        assert mk.call_args.kwargs["name"] == "Unified"

    def test_missing_session_not_found(self) -> None:
        with patch(
            "app.services.alignment.materialize_master",
            side_effect=ValueError("alignment session 's1' not found"),
        ):
            out = TOOLS["materialize_master"]("s1")
        assert out["error"] == "not_found"


class TestP1Flow:
    def test_align_confirm_materialize(self) -> None:
        """Seed 2 ontologies -> candidates -> confirm -> master, through the tools."""
        session = {"_key": "s1", "candidate_count": 2}
        candidates = [
            {"_key": "c1", "confidence": 0.95},
            {"_key": "c2", "confidence": 0.88},
        ]
        master = {"master_ontology_id": "master_1", "class_count": 2, "session_id": "s1"}
        with (
            patch("app.services.alignment.create_alignment_session", return_value=session),
            patch("app.services.alignment.list_session_candidates", return_value=candidates),
            patch(
                "app.services.alignment.set_candidate_status",
                side_effect=lambda _db, key, status: {"_key": key, "status": status},
            ) as mk_status,
            patch("app.services.alignment.materialize_master", return_value=master) as mk_mat,
        ):
            created = TOOLS["align_ontologies"](["o1", "o2"])
            sid = created["_key"]
            listed = TOOLS["list_correspondences"](sid, status="candidate")
            for c in listed["correspondences"]:
                TOOLS["accept_correspondence"](c["_key"])
            result = TOOLS["materialize_master"](sid)

        assert created["candidate_count"] == 2
        assert listed["count"] == 2
        assert {c.args[1] for c in mk_status.call_args_list} == {"c1", "c2"}
        assert all(c.args[2] == "accepted" for c in mk_status.call_args_list)
        assert mk_mat.call_args.kwargs["session_id"] == "s1"
        assert result["master_ontology_id"] == "master_1"


class TestRegistration:
    def test_all_six_tools_registered(self) -> None:
        assert set(TOOLS.keys()) == {
            "align_ontologies",
            "adjudicate_alignment",
            "list_correspondences",
            "accept_correspondence",
            "reject_correspondence",
            "materialize_master",
        }
