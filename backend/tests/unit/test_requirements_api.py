"""Unit tests for the requirements/CQ API (Stream 22 / CQ-PR1).

Patches the repo + registry lookup so route wiring + request validation are
exercised without a database (mirrors the other ontology sub-router tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.db import requirements_repo
from app.main import app
from app.services import cq_coverage

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
