"""Unit tests for the curator-driven revision action service (IBR.16).

Mocks ``revision_meta_repo`` and ``temporal_revisions_repo.supersede`` so
we can assert exact dispatch + idempotency behavior without touching
ArangoDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import revision_meta_repo as rev_repo
from app.db.temporal_revisions_repo import SupersedeResult
from app.services import revision_actions

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _pending_row(**overrides):
    """Return a sample pending FLAG_FOR_CURATION row with sensible defaults."""
    base = {
        "_key": "rev_1",
        "ontology_id": "onto_1",
        "verdict": rev_repo.VERDICT_GAP_FILLING,
        "action": rev_repo.ACTION_GAP_FILL,
        "status": rev_repo.STATUS_PENDING,
        "agent_type": rev_repo.AGENT_LLM,
        "agent_version": "gpt-5+prompt:v3",
        "triggering_doc_id": "doc_42",
        "existing_entity_id": "ontology_classes/Account",
        "evidence_quotes": ["the quote"],
        "reasoning": "name suffix Account suggests subclass",
        "confidence_before": 0.0,
        "confidence_after": 0.85,
    }
    base.update(overrides)
    return base


def _supersede_ok(**overrides):
    base = {
        "revision_meta_key": "rev_1",
        "action": rev_repo.ACTION_GAP_FILL,
        "status": rev_repo.STATUS_APPLIED,
        "new_version_key": None,
        "expired_version_key": None,
        "new_edge_key": "edge_99",
        "skipped": False,
        "skipped_reason": "",
        "extra": {"new_edge_id": "subclass_of/edge_99"},
    }
    base.update(overrides)
    return SupersedeResult(**base)


# ---------------------------------------------------------------------------
# accept_revision
# ---------------------------------------------------------------------------


class TestAcceptRevision:
    def test_pending_gap_fill_dispatches_to_supersede(self):
        row = _pending_row()
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch(
                "app.services.revision_actions.supersede_repo.supersede",
                return_value=_supersede_ok(),
            ) as mock_super,
            patch.object(
                rev_repo,
                "update_status",
                return_value={**row, "status": rev_repo.STATUS_ACCEPTED},
            ) as mock_update,
        ):
            result = revision_actions.accept_revision(
                "rev_1",
                decided_by="alice",
                note="LGTM",
                new_edge={
                    "_from": "ontology_classes/Account",
                    "_to": "ontology_classes/EscrowAccount",
                },
                new_edge_collection="subclass_of",
                db=MagicMock(),
            )

        assert result.decision == rev_repo.STATUS_ACCEPTED
        assert result.status == rev_repo.STATUS_ACCEPTED
        assert result.already_decided is False
        assert result.supersede_result is not None
        # The call into supersede must carry the row's identifying
        # fields verbatim -- otherwise the audit trail is wrong.
        kwargs = mock_super.call_args.kwargs
        assert kwargs["ontology_id"] == "onto_1"
        assert kwargs["existing_entity_id"] == "ontology_classes/Account"
        assert kwargs["verdict"] == rev_repo.VERDICT_GAP_FILLING
        assert kwargs["action"] == rev_repo.ACTION_GAP_FILL
        assert kwargs["new_edge_collection"] == "subclass_of"
        assert kwargs["created_by"] == "curator:alice"
        # update_status must be called with the curator id and note
        # so the decision_log row carries them.
        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["status"] == rev_repo.STATUS_ACCEPTED
        assert update_kwargs["decided_by"] == "alice"
        assert update_kwargs["note"] == "LGTM"

    def test_already_decided_returns_idempotent_result(self):
        accepted = _pending_row(status=rev_repo.STATUS_ACCEPTED)
        with (
            patch.object(rev_repo, "get_revision", return_value=accepted),
            patch("app.services.revision_actions.supersede_repo.supersede") as mock_super,
            patch.object(rev_repo, "update_status") as mock_update,
        ):
            result = revision_actions.accept_revision("rev_1", decided_by="alice", db=MagicMock())
        assert result.already_decided is True
        assert result.decision == rev_repo.STATUS_ACCEPTED
        # Critical: no supersede or status update must fire on idempotent path
        mock_super.assert_not_called()
        mock_update.assert_not_called()

    def test_missing_row_raises_not_found(self):
        with (
            patch.object(rev_repo, "get_revision", return_value=None),
            pytest.raises(revision_actions.RevisionNotFoundError),
        ):
            revision_actions.accept_revision("missing", decided_by="alice", db=MagicMock())

    def test_supersede_value_error_is_translated(self):
        row = _pending_row(action=rev_repo.ACTION_REVISE)
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch(
                "app.services.revision_actions.supersede_repo.supersede",
                side_effect=ValueError("REVISE requires new_vertex_data"),
            ),
            pytest.raises(revision_actions.RevisionActionError) as exc,
        ):
            revision_actions.accept_revision("rev_1", decided_by="alice", db=MagicMock())
        assert "new_vertex_data" in str(exc.value)

    def test_flag_for_curation_accepted_is_no_op_supersede(self):
        row = _pending_row(action=rev_repo.ACTION_FLAG_FOR_CURATION)
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch("app.services.revision_actions.supersede_repo.supersede") as mock_super,
            patch.object(
                rev_repo,
                "update_status",
                return_value={**row, "status": rev_repo.STATUS_ACCEPTED},
            ),
        ):
            result = revision_actions.accept_revision("rev_1", decided_by="alice", db=MagicMock())
        # FLAG_FOR_CURATION accept must NOT invoke supersede (no graph change)
        mock_super.assert_not_called()
        assert result.supersede_result is not None
        assert result.supersede_result["skipped"] is True


# ---------------------------------------------------------------------------
# reject_revision
# ---------------------------------------------------------------------------


class TestRejectRevision:
    def test_pending_row_marked_rejected_no_supersede(self):
        row = _pending_row()
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch("app.services.revision_actions.supersede_repo.supersede") as mock_super,
            patch.object(
                rev_repo,
                "update_status",
                return_value={**row, "status": rev_repo.STATUS_REJECTED},
            ) as mock_update,
        ):
            result = revision_actions.reject_revision(
                "rev_1", decided_by="bob", note="not in our scope", db=MagicMock()
            )
        assert result.decision == rev_repo.STATUS_REJECTED
        assert result.status == rev_repo.STATUS_REJECTED
        # Reject must NEVER touch the graph -- only the audit row flips.
        mock_super.assert_not_called()
        mock_update.assert_called_once()
        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["note"] == "not in our scope"
        assert update_kwargs["decided_by"] == "bob"

    def test_already_rejected_returns_idempotent(self):
        rejected = _pending_row(status=rev_repo.STATUS_REJECTED)
        with (
            patch.object(rev_repo, "get_revision", return_value=rejected),
            patch.object(rev_repo, "update_status") as mock_update,
        ):
            result = revision_actions.reject_revision("rev_1", decided_by="bob", db=MagicMock())
        assert result.already_decided is True
        mock_update.assert_not_called()

    def test_missing_row_raises_not_found(self):
        with (
            patch.object(rev_repo, "get_revision", return_value=None),
            pytest.raises(revision_actions.RevisionNotFoundError),
        ):
            revision_actions.reject_revision("missing", decided_by="bob", db=MagicMock())


# ---------------------------------------------------------------------------
# modify_revision
# ---------------------------------------------------------------------------


class TestModifyRevision:
    def test_override_action_dispatched_with_new_audit(self):
        row = _pending_row(action=rev_repo.ACTION_REVISE)
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch(
                "app.services.revision_actions.supersede_repo.supersede",
                return_value=_supersede_ok(action=rev_repo.ACTION_RETRACT),
            ) as mock_super,
            patch.object(
                rev_repo,
                "update_status",
                return_value={**row, "status": rev_repo.STATUS_MODIFIED},
            ) as mock_update,
        ):
            result = revision_actions.modify_revision(
                "rev_1",
                decided_by="alice",
                override_action=rev_repo.ACTION_RETRACT,
                note="not enough evidence; retracting instead of revising",
                db=MagicMock(),
            )

        assert result.decision == rev_repo.STATUS_MODIFIED
        # The supersede call must use the OVERRIDE action, not the row's
        kwargs = mock_super.call_args.kwargs
        assert kwargs["action"] == rev_repo.ACTION_RETRACT
        # agent_version must be suffixed with the curator id so post-hoc
        # analytics can distinguish this from the original LLM proposal.
        assert kwargs["agent_version"].endswith("curator:alice")
        # update_status must persist the override audit info into note
        update_kwargs = mock_update.call_args.kwargs
        assert "override_action=RETRACT" in update_kwargs["note"]

    def test_modify_with_no_override_or_payload_raises(self):
        with pytest.raises(revision_actions.RevisionActionError):
            revision_actions.modify_revision(
                "rev_1",
                decided_by="alice",
                db=MagicMock(),
            )

    def test_invalid_override_action_raises(self):
        with pytest.raises(revision_actions.RevisionActionError):
            revision_actions.modify_revision(
                "rev_1",
                decided_by="alice",
                override_action="NOT_A_REAL_ACTION",
                db=MagicMock(),
            )

    def test_already_modified_returns_idempotent(self):
        modified = _pending_row(status=rev_repo.STATUS_MODIFIED)
        with (
            patch.object(rev_repo, "get_revision", return_value=modified),
            patch("app.services.revision_actions.supersede_repo.supersede") as mock_super,
            patch.object(rev_repo, "update_status") as mock_update,
        ):
            result = revision_actions.modify_revision(
                "rev_1",
                decided_by="alice",
                override_action=rev_repo.ACTION_RETRACT,
                db=MagicMock(),
            )
        assert result.already_decided is True
        mock_super.assert_not_called()
        mock_update.assert_not_called()

    def test_modify_payload_only_dispatches_with_curator_suffix(self):
        """Curator override of the new_vertex_data without overriding action.

        Verifies the agent_version still gets the curator suffix so we
        can tell post-hoc that the LLM's vertex was modified before
        application.
        """
        row = _pending_row(action=rev_repo.ACTION_REVISE)
        with (
            patch.object(rev_repo, "get_revision", return_value=row),
            patch(
                "app.services.revision_actions.supersede_repo.supersede",
                return_value=_supersede_ok(action=rev_repo.ACTION_REVISE),
            ) as mock_super,
            patch.object(
                rev_repo,
                "update_status",
                return_value={**row, "status": rev_repo.STATUS_MODIFIED},
            ) as mock_update,
        ):
            revision_actions.modify_revision(
                "rev_1",
                decided_by="alice",
                new_vertex_data={"label": "Curator Override Label"},
                db=MagicMock(),
            )
        kwargs = mock_super.call_args.kwargs
        assert kwargs["action"] == rev_repo.ACTION_REVISE  # unchanged
        assert kwargs["agent_version"].endswith("curator:alice")
        assert kwargs["new_vertex_data"] == {"label": "Curator Override Label"}
        # The audit note must mention what was modified
        update_kwargs = mock_update.call_args.kwargs
        assert "new_vertex_keys" in update_kwargs["note"]
