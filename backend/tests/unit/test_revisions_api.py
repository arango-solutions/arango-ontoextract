"""Unit tests for the revisions API router (Stream 11 IBR.16).

Mocks the service layer so we exercise route wiring + error
translation + request/response models without touching the database.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.revisions import (
    AcceptRevisionRequest,
    ModifyRevisionRequest,
    RejectRevisionRequest,
    accept_revision,
    get_inbox,
    get_revision,
    list_revisions,
    list_revisions_for_entity,
    modify_revision,
    reject_revision,
)
from app.db import revision_meta_repo as rev_repo
from app.main import app
from app.services import revision_actions


def _decision_result(**overrides):
    base = {
        "revision_key": "rev_1",
        "decision": rev_repo.STATUS_ACCEPTED,
        "status": rev_repo.STATUS_ACCEPTED,
        "already_decided": False,
        "supersede_result": {"action": rev_repo.ACTION_GAP_FILL, "skipped": False},
        "revision": {"_key": "rev_1", "status": rev_repo.STATUS_ACCEPTED},
    }
    base.update(overrides)
    return revision_actions.RevisionDecisionResult(
        revision_key=base["revision_key"],
        decision=base["decision"],
        status=base["status"],
        already_decided=base["already_decided"],
        supersede_result=base["supersede_result"],
        revision=base["revision"],
    )


# ---------------------------------------------------------------------------
# Direct route handler tests (no server, no DB)
# ---------------------------------------------------------------------------


class TestRouteHandlers:
    @pytest.mark.asyncio
    async def test_get_inbox_calls_repo_with_filters(self):
        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(
                rev_repo,
                "list_inbox",
                return_value=[{"_key": "rev_1"}],
            ) as mock_inbox,
        ):
            result = await get_inbox(ontology_id="onto_1", limit=25)
        mock_inbox.assert_called_once()
        kwargs = mock_inbox.call_args.kwargs
        assert kwargs["limit"] == 25
        assert mock_inbox.call_args.args[0] == "onto_1"
        assert result == {
            "data": [{"_key": "rev_1"}],
            "ontology_id": "onto_1",
            "count": 1,
        }

    @pytest.mark.asyncio
    async def test_list_revisions_passes_through_filters(self):
        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(
                rev_repo,
                "list_revisions",
                return_value=[],
            ) as mock_list,
        ):
            await list_revisions(
                ontology_id="onto_1",
                action=rev_repo.ACTION_REINFORCE,
                status=rev_repo.STATUS_APPLIED,
                since=1700000000.0,
                limit=10,
            )
        kwargs = mock_list.call_args.kwargs
        assert kwargs["action"] == rev_repo.ACTION_REINFORCE
        assert kwargs["status"] == rev_repo.STATUS_APPLIED
        assert kwargs["since"] == 1700000000.0
        assert kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_list_revisions_invalid_action_400(self):
        from app.api.errors import ValidationError

        with (
            patch("app.api.revisions.get_db", return_value=object()),
            pytest.raises(ValidationError),
        ):
            await list_revisions(
                ontology_id="onto_1",
                action="NOT_REAL",
                status=None,
            )

    @pytest.mark.asyncio
    async def test_list_revisions_invalid_status_400(self):
        from app.api.errors import ValidationError

        with (
            patch("app.api.revisions.get_db", return_value=object()),
            pytest.raises(ValidationError),
        ):
            await list_revisions(
                ontology_id="onto_1",
                action=None,
                status="NOT_REAL",
            )

    @pytest.mark.asyncio
    async def test_get_revision_404_when_missing(self):
        from app.api.errors import NotFoundError

        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(rev_repo, "get_revision", return_value=None),
            pytest.raises(NotFoundError),
        ):
            await get_revision("missing")

    @pytest.mark.asyncio
    async def test_get_revision_returns_row(self):
        row = {"_key": "rev_1", "status": rev_repo.STATUS_PENDING}
        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(rev_repo, "get_revision", return_value=row),
        ):
            assert await get_revision("rev_1") == row

    @pytest.mark.asyncio
    async def test_revisions_for_entity_requires_full_id(self):
        from app.api.errors import ValidationError

        with pytest.raises(ValidationError):
            await list_revisions_for_entity(entity_id="just_a_key", limit=10)

    @pytest.mark.asyncio
    async def test_revisions_for_entity_passes_through(self):
        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(
                rev_repo,
                "list_revisions_for_entity",
                return_value=[{"_key": "rev_1"}],
            ) as mock_list,
        ):
            result = await list_revisions_for_entity(entity_id="ontology_classes/Account", limit=5)
        mock_list.assert_called_once()
        assert result["entity_id"] == "ontology_classes/Account"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_accept_route_calls_service(self):
        body = AcceptRevisionRequest(decided_by="alice", note="LGTM")
        with patch.object(
            revision_actions,
            "accept_revision",
            return_value=_decision_result(),
        ) as mock_accept:
            response = await accept_revision(body, revision_key="rev_1")
        mock_accept.assert_called_once()
        kwargs = mock_accept.call_args.kwargs
        assert kwargs["decided_by"] == "alice"
        assert kwargs["note"] == "LGTM"
        assert response["decision"] == rev_repo.STATUS_ACCEPTED

    @pytest.mark.asyncio
    async def test_accept_route_translates_not_found_to_404(self):
        from app.api.errors import NotFoundError

        body = AcceptRevisionRequest(decided_by="alice")
        with (
            patch.object(
                revision_actions,
                "accept_revision",
                side_effect=revision_actions.RevisionNotFoundError("rev_1"),
            ),
            pytest.raises(NotFoundError),
        ):
            await accept_revision(body, revision_key="rev_1")

    @pytest.mark.asyncio
    async def test_accept_route_translates_action_error_to_400(self):
        from app.api.errors import ValidationError

        body = AcceptRevisionRequest(decided_by="alice")
        with (
            patch.object(
                revision_actions,
                "accept_revision",
                side_effect=revision_actions.RevisionActionError("REVISE requires new_vertex_data"),
            ),
            pytest.raises(ValidationError),
        ):
            await accept_revision(body, revision_key="rev_1")

    @pytest.mark.asyncio
    async def test_reject_route_calls_service(self):
        body = RejectRevisionRequest(decided_by="bob", note="not in scope")
        with patch.object(
            revision_actions,
            "reject_revision",
            return_value=_decision_result(
                decision=rev_repo.STATUS_REJECTED,
                status=rev_repo.STATUS_REJECTED,
                supersede_result=None,
            ),
        ) as mock_reject:
            response = await reject_revision(body, revision_key="rev_1")
        mock_reject.assert_called_once()
        assert response["decision"] == rev_repo.STATUS_REJECTED
        assert response["supersede_result"] is None

    @pytest.mark.asyncio
    async def test_modify_route_passes_override(self):
        body = ModifyRevisionRequest(
            decided_by="alice",
            override_action=rev_repo.ACTION_RETRACT,
            note="not enough evidence",
        )
        with patch.object(
            revision_actions,
            "modify_revision",
            return_value=_decision_result(
                decision=rev_repo.STATUS_MODIFIED,
                status=rev_repo.STATUS_MODIFIED,
            ),
        ) as mock_modify:
            response = await modify_revision(body, revision_key="rev_1")
        kwargs = mock_modify.call_args.kwargs
        assert kwargs["override_action"] == rev_repo.ACTION_RETRACT
        assert response["decision"] == rev_repo.STATUS_MODIFIED


# ---------------------------------------------------------------------------
# End-to-end via TestClient (no auth -- mounted directly on the app)
# ---------------------------------------------------------------------------


class TestRevisionsHttp:
    """Smoke tests through the TestClient.

    Verifies the routes are mounted, request/response shapes are
    correct, and error envelopes match the rest of the API. Service
    layer is mocked.
    """

    def test_inbox_endpoint(self):
        with (
            patch("app.api.revisions.get_db", return_value=object()),
            patch.object(
                rev_repo,
                "list_inbox",
                return_value=[
                    {
                        "_key": "rev_1",
                        "ontology_id": "onto_1",
                        "verdict": rev_repo.VERDICT_GAP_FILLING,
                        "action": rev_repo.ACTION_FLAG_FOR_CURATION,
                        "status": rev_repo.STATUS_PENDING,
                    }
                ],
            ),
        ):
            client = TestClient(app)
            r = client.get("/api/v1/revisions/inbox?ontology_id=onto_1&limit=10")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        assert body["data"][0]["_key"] == "rev_1"
        assert body["ontology_id"] == "onto_1"

    def test_accept_endpoint_happy_path(self):
        with patch.object(
            revision_actions,
            "accept_revision",
            return_value=_decision_result(),
        ):
            client = TestClient(app)
            r = client.post(
                "/api/v1/revisions/rev_1/accept",
                json={
                    "decided_by": "alice",
                    "note": "LGTM",
                    "new_edge": {
                        "_from": "ontology_classes/Account",
                        "_to": "ontology_classes/EscrowAccount",
                    },
                    "new_edge_collection": "subclass_of",
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"] == rev_repo.STATUS_ACCEPTED
        assert body["already_decided"] is False

    def test_reject_endpoint_returns_404_when_missing(self):
        with patch.object(
            revision_actions,
            "reject_revision",
            side_effect=revision_actions.RevisionNotFoundError("nope"),
        ):
            client = TestClient(app)
            r = client.post(
                "/api/v1/revisions/nope/reject",
                json={"decided_by": "bob"},
            )
        assert r.status_code == 404
        body = r.json()
        # Conforms to AOEError envelope: {"error": {"code": ..., "message": ...}}
        assert body["error"]["code"] == "ENTITY_NOT_FOUND"

    def test_modify_endpoint_validation_error_400(self):
        with patch.object(
            revision_actions,
            "modify_revision",
            side_effect=revision_actions.RevisionActionError("REVISE requires new_vertex_data"),
        ):
            client = TestClient(app)
            r = client.post(
                "/api/v1/revisions/rev_1/modify",
                json={
                    "decided_by": "alice",
                    "override_action": rev_repo.ACTION_REVISE,
                },
            )
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_accept_request_requires_decided_by(self):
        client = TestClient(app)
        r = client.post("/api/v1/revisions/rev_1/accept", json={"note": "no curator"})
        # Pydantic validation -- 422 from FastAPI's RequestValidationError handler
        assert r.status_code == 422
