"""Unit tests for ``app.db.revision_meta_repo`` (Stream 11 IBR.1).

Uses MagicMock for the DB / collection -- same pattern as
``test_quality_history_repo.py`` -- so we can assert exact AQL inputs
and inserted documents without needing a live ArangoDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import revision_meta_repo as repo

# ---------------------------------------------------------------------------
# record_revision
# ---------------------------------------------------------------------------


def _stub_db():
    db = MagicMock()
    db.has_collection.return_value = True
    collection = MagicMock()
    collection.insert.return_value = {
        "new": {
            "_key": "rev_1",
            "ontology_id": "onto_1",
            "verdict": repo.VERDICT_REINFORCED,
            "action": repo.ACTION_REINFORCE,
            "status": repo.STATUS_APPLIED,
        }
    }
    db.collection.return_value = collection
    return db, collection


class TestRecordRevisionDefaults:
    def test_reinforce_defaults_to_status_applied(self):
        db, collection = _stub_db()
        result = repo.record_revision(
            ontology_id="onto_1",
            verdict=repo.VERDICT_REINFORCED,
            action=repo.ACTION_REINFORCE,
            agent_type=repo.AGENT_MECHANICAL,
            agent_version="rules-v1",
            triggering_doc_id="doc_42",
            existing_entity_id="ontology_classes/Customer",
            db=db,
        )
        assert result["_key"] == "rev_1"
        inserted = collection.insert.call_args.args[0]
        assert inserted["status"] == repo.STATUS_APPLIED
        assert inserted["verdict"] == repo.VERDICT_REINFORCED
        assert inserted["evidence_quotes"] == []
        assert "created" in inserted

    def test_flag_for_curation_defaults_to_status_pending(self):
        db, collection = _stub_db()
        repo.record_revision(
            ontology_id="onto_1",
            verdict=repo.VERDICT_CONTRADICTED,
            action=repo.ACTION_FLAG_FOR_CURATION,
            agent_type=repo.AGENT_LLM,
            agent_version="gpt-4o-mini@prompt-v3",
            triggering_doc_id="doc_42",
            existing_entity_id="ontology_classes/Customer",
            db=db,
        )
        inserted = collection.insert.call_args.args[0]
        assert inserted["status"] == repo.STATUS_PENDING

    def test_explicit_status_overrides_default(self):
        db, collection = _stub_db()
        repo.record_revision(
            ontology_id="onto_1",
            verdict=repo.VERDICT_REFINED,
            action=repo.ACTION_REVISE,
            agent_type=repo.AGENT_LLM,
            agent_version="gpt-4o-mini@prompt-v3",
            triggering_doc_id="doc_42",
            existing_entity_id="ontology_classes/Customer",
            new_version="Customer_v2",
            status=repo.STATUS_PENDING,  # caller forces pending despite REVISE action
            db=db,
        )
        inserted = collection.insert.call_args.args[0]
        assert inserted["status"] == repo.STATUS_PENDING


class TestRecordRevisionValidation:
    def test_rejects_unknown_verdict(self):
        db, _ = _stub_db()
        with pytest.raises(ValueError, match="unknown verdict"):
            repo.record_revision(
                ontology_id="onto_1",
                verdict="MAYBE",
                action=repo.ACTION_REINFORCE,
                agent_type=repo.AGENT_MECHANICAL,
                agent_version="rules-v1",
                triggering_doc_id="doc_42",
                existing_entity_id="ontology_classes/Customer",
                db=db,
            )

    def test_rejects_unknown_action(self):
        db, _ = _stub_db()
        with pytest.raises(ValueError, match="unknown action"):
            repo.record_revision(
                ontology_id="onto_1",
                verdict=repo.VERDICT_REINFORCED,
                action="DELETE",
                agent_type=repo.AGENT_MECHANICAL,
                agent_version="rules-v1",
                triggering_doc_id="doc_42",
                existing_entity_id="ontology_classes/Customer",
                db=db,
            )

    def test_rejects_unknown_agent_type(self):
        db, _ = _stub_db()
        with pytest.raises(ValueError, match="unknown agent_type"):
            repo.record_revision(
                ontology_id="onto_1",
                verdict=repo.VERDICT_REINFORCED,
                action=repo.ACTION_REINFORCE,
                agent_type="oracle",
                agent_version="?",
                triggering_doc_id="doc_42",
                existing_entity_id="ontology_classes/Customer",
                db=db,
            )

    def test_rejects_unknown_status(self):
        db, _ = _stub_db()
        with pytest.raises(ValueError, match="unknown status"):
            repo.record_revision(
                ontology_id="onto_1",
                verdict=repo.VERDICT_REINFORCED,
                action=repo.ACTION_REINFORCE,
                agent_type=repo.AGENT_MECHANICAL,
                agent_version="rules-v1",
                triggering_doc_id="doc_42",
                existing_entity_id="ontology_classes/Customer",
                status="archived",
                db=db,
            )


# ---------------------------------------------------------------------------
# get_revision
# ---------------------------------------------------------------------------


class TestGetRevision:
    def test_missing_collection_returns_none(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.get_revision("rev_1", db=db) is None

    def test_returns_doc_via_doc_get(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "doc_get", return_value={"_key": "rev_1"}) as p:
            result = repo.get_revision("rev_1", db=db)
        assert result == {"_key": "rev_1"}
        p.assert_called_once()


# ---------------------------------------------------------------------------
# list_revisions
# ---------------------------------------------------------------------------


class TestListRevisions:
    def test_missing_collection_returns_empty(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_revisions("onto_1", db=db) == []

    def test_no_filters_uses_only_ontology_filter(self):
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"_key": "rev_1"}, {"_key": "rev_2"}]
        with patch.object(repo, "run_aql", return_value=iter(rows)) as run:
            result = repo.list_revisions("onto_1", db=db)
        assert result == rows
        aql_str, kwargs = run.call_args.args[1], run.call_args.kwargs
        assert "r.ontology_id == @oid" in aql_str
        # No optional filter clauses bled into the query.
        assert "@action" not in aql_str
        assert "@status" not in aql_str
        assert "@since" not in aql_str
        bind = kwargs["bind_vars"]
        assert bind == {"oid": "onto_1", "limit": 100}

    def test_action_filter_adds_clause_and_bind(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([])) as run:
            repo.list_revisions("onto_1", action=repo.ACTION_FLAG_FOR_CURATION, db=db)
        aql_str = run.call_args.args[1]
        bind = run.call_args.kwargs["bind_vars"]
        assert "r.action == @action" in aql_str
        assert bind["action"] == repo.ACTION_FLAG_FOR_CURATION

    def test_status_and_since_filters_compose(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([])) as run:
            repo.list_revisions(
                "onto_1",
                status=repo.STATUS_PENDING,
                since=1700000000.0,
                limit=25,
                db=db,
            )
        aql_str = run.call_args.args[1]
        bind = run.call_args.kwargs["bind_vars"]
        assert "r.status == @status" in aql_str
        assert "r.created >= @since" in aql_str
        assert bind["status"] == repo.STATUS_PENDING
        assert bind["since"] == 1700000000.0
        assert bind["limit"] == 25


class TestListInbox:
    def test_inbox_uses_pending_flag_for_curation_filter(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([])) as run:
            repo.list_inbox("onto_1", limit=10, db=db)
        bind = run.call_args.kwargs["bind_vars"]
        assert bind["action"] == repo.ACTION_FLAG_FOR_CURATION
        assert bind["status"] == repo.STATUS_PENDING
        assert bind["limit"] == 10


class TestListRevisionsForEntity:
    def test_filters_by_entity_id(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([])) as run:
            repo.list_revisions_for_entity("ontology_classes/Customer", db=db)
        aql_str = run.call_args.args[1]
        bind = run.call_args.kwargs["bind_vars"]
        assert "r.existing_entity_id == @eid" in aql_str
        assert bind["eid"] == "ontology_classes/Customer"

    def test_missing_collection_returns_empty(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_revisions_for_entity("ontology_classes/x", db=db) == []


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_appends_to_decision_log(self):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        db.collection.return_value = col
        col.update.return_value = {
            "new": {
                "_key": "rev_1",
                "status": repo.STATUS_ACCEPTED,
                "decision_log": [{"to_status": "accepted"}],
            }
        }
        with patch.object(
            repo,
            "doc_get",
            return_value={"_key": "rev_1", "status": repo.STATUS_PENDING, "decision_log": []},
        ):
            result = repo.update_status(
                "rev_1",
                status=repo.STATUS_ACCEPTED,
                decided_by="alice",
                note="LGTM",
                db=db,
            )
        assert result is not None
        assert result["status"] == repo.STATUS_ACCEPTED
        update_arg = col.update.call_args.args[0]
        assert update_arg["_key"] == "rev_1"
        assert update_arg["status"] == repo.STATUS_ACCEPTED
        # Decision log was extended with the new transition.
        log_entry = update_arg["decision_log"][-1]
        assert log_entry["from_status"] == repo.STATUS_PENDING
        assert log_entry["to_status"] == repo.STATUS_ACCEPTED
        assert log_entry["decided_by"] == "alice"
        assert log_entry["note"] == "LGTM"

    def test_preserves_existing_decision_log(self):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        db.collection.return_value = col
        col.update.return_value = {"new": {"_key": "rev_1", "status": repo.STATUS_REJECTED}}
        prior = [{"from_status": None, "to_status": "pending"}]
        with patch.object(
            repo,
            "doc_get",
            return_value={
                "_key": "rev_1",
                "status": repo.STATUS_PENDING,
                "decision_log": prior,
            },
        ):
            repo.update_status("rev_1", status=repo.STATUS_REJECTED, db=db)
        update_arg = col.update.call_args.args[0]
        # First entry preserved, plus the new transition appended.
        assert len(update_arg["decision_log"]) == 2
        assert update_arg["decision_log"][0] == prior[0]

    def test_missing_revision_returns_none(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = MagicMock()
        with patch.object(repo, "doc_get", return_value=None):
            assert repo.update_status("rev_x", status=repo.STATUS_ACCEPTED, db=db) is None

    def test_missing_collection_returns_none(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.update_status("rev_1", status=repo.STATUS_ACCEPTED, db=db) is None

    def test_rejects_unknown_status(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="unknown status"):
            repo.update_status("rev_1", status="vaporised", db=db)
