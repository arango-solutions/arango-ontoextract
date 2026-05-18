"""Unit tests for the ER API router (Stream 2 PR 1).

Pins the wire contract that the workspace ``MergeCandidatesOverlay``
binds to: per-pair accept / reject / explain routes, error-status
translation, and the ``include_resolved`` flag on the candidates list.

These tests patch the service layer so we exercise route wiring +
request/response models without touching the database.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import er as er_svc

client = TestClient(app)


class TestAcceptCandidateRoute:
    def test_accept_returns_service_payload(self):
        with patch.object(
            er_svc,
            "accept_candidate",
            return_value={
                "pair_id": "p1",
                "status": "accepted",
                "accepted_at": 12345.0,
                "merge_result": {"target_key": "tgt", "source_key": "src"},
            },
        ) as mock_accept:
            resp = client.post(
                "/api/v1/er/candidates/p1/accept",
                json={"strategy": "most_complete"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pair_id"] == "p1"
        assert body["status"] == "accepted"
        mock_accept.assert_called_once_with(pair_id="p1", strategy="most_complete")

    def test_accept_defaults_strategy(self):
        with patch.object(
            er_svc,
            "accept_candidate",
            return_value={"pair_id": "p1", "status": "accepted", "accepted_at": 1.0},
        ) as mock_accept:
            # No body -- the route should default strategy to most_complete.
            resp = client.post("/api/v1/er/candidates/p1/accept")
        assert resp.status_code == 200
        mock_accept.assert_called_once_with(pair_id="p1", strategy="most_complete")

    def test_accept_not_found_returns_404(self):
        with patch.object(
            er_svc,
            "accept_candidate",
            side_effect=ValueError("Candidate pair 'ghost' not found"),
        ):
            resp = client.post("/api/v1/er/candidates/ghost/accept")
        # App-wide error envelope (see app/api/errors.py): the HTTPException
        # detail is normalised to {"error": {"code": "ENTITY_NOT_FOUND", ...}}
        # so the original message is intentionally not surfaced to clients.
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ENTITY_NOT_FOUND"

    def test_accept_after_reject_returns_409(self):
        with patch.object(
            er_svc,
            "accept_candidate",
            side_effect=ValueError("Candidate pair 'p1' was already rejected at 100.0"),
        ):
            resp = client.post("/api/v1/er/candidates/p1/accept")
        assert resp.status_code == 409


class TestRejectCandidateRoute:
    def test_reject_returns_service_payload(self):
        with patch.object(
            er_svc,
            "reject_candidate",
            return_value={"pair_id": "p1", "status": "rejected", "rejected_at": 99.0},
        ) as mock_reject:
            resp = client.post("/api/v1/er/candidates/p1/reject")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        mock_reject.assert_called_once_with(pair_id="p1")

    def test_reject_not_found_returns_404(self):
        with patch.object(
            er_svc,
            "reject_candidate",
            side_effect=ValueError("Candidate pair 'ghost' not found"),
        ):
            resp = client.post("/api/v1/er/candidates/ghost/reject")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ENTITY_NOT_FOUND"

    def test_reject_after_accept_returns_409(self):
        with patch.object(
            er_svc,
            "reject_candidate",
            side_effect=ValueError(
                "Candidate pair 'p1' was already accepted at 50.0; cannot reject after merge"
            ),
        ):
            resp = client.post("/api/v1/er/candidates/p1/reject")
        assert resp.status_code == 409


class TestExplainCandidateRoute:
    def test_explain_returns_service_payload(self):
        with patch.object(
            er_svc,
            "explain_candidate",
            return_value={
                "pair_id": "p1",
                "combined_score": 0.88,
                "field_scores": {"label_jaro_winkler": 0.95},
                "class_1": {"label": "Customer", "uri": "u1"},
                "class_2": {"label": "Client", "uri": "u2"},
            },
        ) as mock_explain:
            resp = client.get("/api/v1/er/candidates/p1/explain")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pair_id"] == "p1"
        assert body["combined_score"] == 0.88
        mock_explain.assert_called_once_with(pair_id="p1")

    def test_explain_not_found_returns_404(self):
        with patch.object(
            er_svc,
            "explain_candidate",
            side_effect=ValueError("Candidate pair 'ghost' not found"),
        ):
            resp = client.get("/api/v1/er/candidates/ghost/explain")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ENTITY_NOT_FOUND"


class TestListCandidatesIncludeResolvedFlag:
    def test_list_candidates_threads_include_resolved(self):
        """The route exposes ``?include_resolved=true``; verify it lands
        in the service call so curators can audit prior decisions
        without writing AQL."""
        run = MagicMock()
        run.config.ontology_id = "o1"
        with (
            patch.object(er_svc, "get_run_status", return_value=run),
            patch.object(er_svc, "get_candidates", return_value=[]) as mock_get,
        ):
            resp = client.get(
                "/api/v1/er/runs/r1/candidates",
                params={"include_resolved": "true"},
            )
        assert resp.status_code == 200
        mock_get.assert_called_once()
        kwargs = mock_get.call_args.kwargs
        assert kwargs["include_resolved"] is True

    def test_list_candidates_defaults_include_resolved_false(self):
        run = MagicMock()
        run.config.ontology_id = "o1"
        with (
            patch.object(er_svc, "get_run_status", return_value=run),
            patch.object(er_svc, "get_candidates", return_value=[]) as mock_get,
        ):
            client.get("/api/v1/er/runs/r1/candidates")
        kwargs = mock_get.call_args.kwargs
        assert kwargs["include_resolved"] is False
