"""Unit tests for the alignment API router (Stream 20 / AL-PR1).

Patches the service layer so we exercise route wiring + request/response models
without touching the database (mirrors test_er_api.py).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import alignment as alignment_svc

client = TestClient(app)


class TestCreateSession:
    def test_creates_session(self) -> None:
        with patch.object(
            alignment_svc,
            "create_alignment_session",
            return_value={"_key": "S1", "source_ontology_ids": ["a", "b"], "candidate_count": 3},
        ) as mk:
            resp = client.post(
                "/api/v1/alignment/sessions",
                json={"source_ontology_ids": ["a", "b"], "min_score": 0.6},
            )
        assert resp.status_code == 200
        assert resp.json()["candidate_count"] == 3
        assert mk.call_args.kwargs["source_ontology_ids"] == ["a", "b"]
        assert mk.call_args.kwargs["min_score"] == 0.6

    def test_fewer_than_two_sources_is_422(self) -> None:
        # min_length=2 on the request model -> FastAPI validation 422
        resp = client.post("/api/v1/alignment/sessions", json={"source_ontology_ids": ["a"]})
        assert resp.status_code == 422

    def test_service_valueerror_is_400(self) -> None:
        with patch.object(
            alignment_svc,
            "create_alignment_session",
            side_effect=ValueError("alignment requires at least 2 distinct source ontologies"),
        ):
            resp = client.post(
                "/api/v1/alignment/sessions",
                json={"source_ontology_ids": ["a", "b"]},
            )
        assert resp.status_code == 400


class TestGetSession:
    def test_404_when_missing(self) -> None:
        with patch.object(alignment_svc, "get_alignment_session", return_value=None):
            resp = client.get("/api/v1/alignment/sessions/nope")
        assert resp.status_code == 404

    def test_returns_session(self) -> None:
        with patch.object(
            alignment_svc, "get_alignment_session", return_value={"_key": "S1", "status": "x"}
        ):
            resp = client.get("/api/v1/alignment/sessions/S1")
        assert resp.status_code == 200
        assert resp.json()["_key"] == "S1"


class TestListCandidates:
    def test_lists_with_filters(self) -> None:
        with patch.object(
            alignment_svc,
            "list_session_candidates",
            return_value=[{"confidence": 0.9}],
        ) as mk:
            resp = client.get(
                "/api/v1/alignment/sessions/S1/candidates",
                params={"status": "candidate", "min_confidence": 0.5},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert mk.call_args.kwargs["status"] == "candidate"
        assert mk.call_args.kwargs["min_confidence"] == 0.5

    def test_invalid_status_is_422(self) -> None:
        resp = client.get("/api/v1/alignment/sessions/S1/candidates", params={"status": "bogus"})
        assert resp.status_code == 422


class TestDecideCandidate:
    def test_accept(self) -> None:
        with patch.object(
            alignment_svc,
            "set_candidate_status",
            return_value={"_key": "c1", "status": "accepted"},
        ) as mk:
            resp = client.post("/api/v1/alignment/candidates/c1/accept")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        assert mk.call_args[0][2] == "accepted"

    def test_reject(self) -> None:
        with patch.object(
            alignment_svc,
            "set_candidate_status",
            return_value={"_key": "c1", "status": "rejected"},
        ):
            resp = client.post("/api/v1/alignment/candidates/c1/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_bad_decision_is_400(self) -> None:
        resp = client.post("/api/v1/alignment/candidates/c1/frobnicate")
        assert resp.status_code == 400

    def test_missing_correspondence_is_404(self) -> None:
        with patch.object(alignment_svc, "set_candidate_status", return_value=None):
            resp = client.post("/api/v1/alignment/candidates/nope/accept")
        assert resp.status_code == 404
