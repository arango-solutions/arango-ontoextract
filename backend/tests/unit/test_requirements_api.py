"""Unit tests for the requirements/CQ API (Stream 22 / CQ-PR1).

Patches the repo + registry lookup so route wiring + request validation are
exercised without a database (mirrors the other ontology sub-router tests).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.db import requirements_repo
from app.main import app
from app.services import cq_coverage, cq_formalize

client = TestClient(app)

_SPEC = {
    "purpose": "Support fraud investigation",
    "use_cases": [
        {
            "name": "Trace mule networks",
            "priority": "high",
            "competency_questions": [
                {"text": "Which accounts are mule accounts?", "priority": "high"}
            ],
        }
    ],
}


class TestPutRequirements:
    def test_put_creates_when_ontology_exists(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(_shared.registry_repo, "get_registry_entry", return_value={"_key": "o1"}),
            patch.object(
                requirements_repo,
                "upsert_requirements",
                return_value={"_key": "o1", "ontology_id": "o1", **_SPEC},
            ) as mk,
        ):
            resp = client.put("/api/v1/ontology/o1/requirements", json=_SPEC)
        assert resp.status_code == 200
        assert resp.json()["ontology_id"] == "o1"
        assert mk.call_args.args[1] == "o1"

    def test_put_404_when_ontology_missing(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(_shared.registry_repo, "get_registry_entry", return_value=None),
        ):
            resp = client.put("/api/v1/ontology/nope/requirements", json=_SPEC)
        assert resp.status_code == 404

    def test_put_422_on_invalid_priority(self) -> None:
        bad = {"use_cases": [{"name": "x", "priority": "urgent", "competency_questions": []}]}
        resp = client.put("/api/v1/ontology/o1/requirements", json=bad)
        assert resp.status_code == 422

    def test_put_422_on_empty_cq_text(self) -> None:
        bad = {"use_cases": [{"name": "x", "competency_questions": [{"text": ""}]}]}
        resp = client.put("/api/v1/ontology/o1/requirements", json=bad)
        assert resp.status_code == 422


class TestGetDeleteRequirements:
    def test_get_returns_spec(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(requirements_repo, "get_requirements", return_value={"_key": "o1"}),
        ):
            resp = client.get("/api/v1/ontology/o1/requirements")
        assert resp.status_code == 200

    def test_get_404_when_absent(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(requirements_repo, "get_requirements", return_value=None),
        ):
            resp = client.get("/api/v1/ontology/o1/requirements")
        assert resp.status_code == 404

    def test_delete_ok(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(requirements_repo, "delete_requirements", return_value=True),
        ):
            resp = client.delete("/api/v1/ontology/o1/requirements")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_404_when_absent(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(requirements_repo, "delete_requirements", return_value=False),
        ):
            resp = client.delete("/api/v1/ontology/o1/requirements")
        assert resp.status_code == 404


class TestFormalizeEndpoint:
    def test_formalize_runs(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                cq_formalize,
                "formalize_spec",
                new=AsyncMock(return_value={"ontology_id": "o1", "formalized": 2, "total": 3}),
            ) as mk,
        ):
            resp = client.post("/api/v1/ontology/o1/requirements/formalize")
        assert resp.status_code == 200
        assert resp.json()["formalized"] == 2
        mk.assert_awaited_once()

    def test_formalize_404_when_no_spec(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                cq_formalize,
                "formalize_spec",
                new=AsyncMock(side_effect=ValueError("no requirements spec")),
            ),
        ):
            resp = client.post("/api/v1/ontology/o1/requirements/formalize")
        assert resp.status_code == 404


class TestCoverageEndpoint:
    def test_coverage_returns_report(self) -> None:
        report = {"ontology_id": "o1", "total": 3, "answerable": 2, "coverage_pct": 66.7}
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(cq_coverage, "run_coverage", return_value=report) as mk,
        ):
            resp = client.post("/api/v1/ontology/o1/coverage")
        assert resp.status_code == 200
        assert resp.json()["coverage_pct"] == 66.7
        assert mk.call_args.kwargs["ontology_id"] == "o1"

    def test_coverage_404_when_no_spec(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                cq_coverage, "run_coverage", side_effect=ValueError("no requirements spec")
            ),
        ):
            resp = client.post("/api/v1/ontology/o1/coverage")
        assert resp.status_code == 404

    def test_coverage_persist_gaps_and_gate(self) -> None:
        report = {"ontology_id": "o1", "total": 2, "answerable": 1, "gaps": []}
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(cq_coverage, "run_coverage", return_value=dict(report)),
            patch.object(
                cq_coverage, "route_gaps_to_backlog", return_value={"opened": 1, "resolved": 0}
            ) as mk_route,
            patch.object(
                cq_coverage, "evaluate_release_gate", return_value={"passed": False}
            ) as mk_gate,
        ):
            resp = client.post("/api/v1/ontology/o1/coverage?persist_gaps=true&gate=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["backlog"] == {"opened": 1, "resolved": 0}
        assert body["release_gate"] == {"passed": False}
        mk_route.assert_called_once()
        mk_gate.assert_called_once()

    def test_coverage_no_gate_or_persist_by_default(self) -> None:
        report = {"ontology_id": "o1", "total": 0, "gaps": []}
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(cq_coverage, "run_coverage", return_value=dict(report)),
            patch.object(cq_coverage, "route_gaps_to_backlog") as mk_route,
            patch.object(cq_coverage, "evaluate_release_gate") as mk_gate,
        ):
            resp = client.post("/api/v1/ontology/o1/coverage")
        assert resp.status_code == 200
        assert "backlog" not in resp.json()
        assert "release_gate" not in resp.json()
        mk_route.assert_not_called()
        mk_gate.assert_not_called()


class TestCoverageGapsEndpoint:
    def test_lists_open_gaps(self) -> None:
        from app.db import cq_gap_repo

        gaps = [{"_key": "k1", "cq_text": "q", "status": "open"}]
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(cq_gap_repo, "list_gaps", return_value=gaps) as mk,
        ):
            resp = client.get("/api/v1/ontology/o1/coverage/gaps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["status"] == "open"
        assert mk.call_args.kwargs["status"] == "open"

    def test_rejects_bad_status(self) -> None:
        resp = client.get("/api/v1/ontology/o1/coverage/gaps?status=bogus")
        assert resp.status_code == 422
