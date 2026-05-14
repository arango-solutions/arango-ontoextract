"""Unit tests for the belief-revision safety guards (Stream 11 IBR.18).

Covers all four guards:

1. Published-item protection — :func:`should_flag_for_curation` and
   :func:`downgrade_action_for_published`.
2. Circuit breaker — :class:`RevisionRateLimiter`.
3. Dry-run plan dataclass — :class:`PlannedAction`.
4. Cursor resumption — :class:`ConsolidationCursor` + checkpoint /
   load helpers.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.db import revision_meta_repo as rev_repo
from app.services import revision_safety

# ---------------------------------------------------------------------------
# Guard #1 -- Published-item protection
# ---------------------------------------------------------------------------


class TestPublishedProtection:
    @pytest.mark.parametrize(
        "action",
        [
            rev_repo.ACTION_REVISE,
            rev_repo.ACTION_RETRACT,
            rev_repo.ACTION_GAP_FILL,
        ],
    )
    def test_structural_revisions_on_approved_are_flagged(self, action):
        approved = {"_key": "Account", "status": "approved"}
        assert revision_safety.should_flag_for_curation(entity=approved, proposed_action=action)
        assert (
            revision_safety.downgrade_action_for_published(entity=approved, proposed_action=action)
            == rev_repo.ACTION_FLAG_FOR_CURATION
        )

    def test_reinforce_on_approved_is_allowed(self):
        approved = {"_key": "Account", "status": "approved"}
        assert not revision_safety.should_flag_for_curation(
            entity=approved, proposed_action=rev_repo.ACTION_REINFORCE
        )
        assert (
            revision_safety.downgrade_action_for_published(
                entity=approved, proposed_action=rev_repo.ACTION_REINFORCE
            )
            == rev_repo.ACTION_REINFORCE
        )

    def test_structural_on_unapproved_passes_through(self):
        unapproved = {"_key": "Draft", "status": "staging"}
        assert not revision_safety.should_flag_for_curation(
            entity=unapproved, proposed_action=rev_repo.ACTION_REVISE
        )
        assert (
            revision_safety.downgrade_action_for_published(
                entity=unapproved, proposed_action=rev_repo.ACTION_REVISE
            )
            == rev_repo.ACTION_REVISE
        )

    def test_missing_entity_treated_as_unpublished(self):
        # A None entity (e.g. lookup failed) is NOT considered published
        # -- otherwise we'd silently turn every revision into a
        # FLAG_FOR_CURATION on transient lookup failures.
        assert not revision_safety.is_published(None)
        assert not revision_safety.should_flag_for_curation(
            entity=None, proposed_action=rev_repo.ACTION_REVISE
        )

    def test_entity_with_no_status_field_is_unpublished(self):
        assert not revision_safety.is_published({"_key": "X"})


# ---------------------------------------------------------------------------
# Guard #2 -- Circuit breaker
# ---------------------------------------------------------------------------


class TestRevisionRateLimiter:
    def test_under_cap_increments_returns_true(self):
        limiter = revision_safety.RevisionRateLimiter(max_per_window=3, window_seconds=10.0)
        assert limiter.check_and_increment() is True
        assert limiter.check_and_increment() is True
        assert limiter.check_and_increment() is True

    def test_over_cap_returns_false_and_stays_tripped(self):
        limiter = revision_safety.RevisionRateLimiter(max_per_window=2, window_seconds=10.0)
        assert limiter.check_and_increment() is True
        assert limiter.check_and_increment() is True
        # Third call within the window must trip the breaker
        assert limiter.check_and_increment() is False
        # Subsequent calls within the same window also fail
        assert limiter.check_and_increment() is False
        snapshot = limiter.current_rate()
        assert snapshot["tripped"] is True
        assert snapshot["tripped_at"] is not None

    def test_zero_cap_disables_breaker(self):
        limiter = revision_safety.RevisionRateLimiter(max_per_window=0, window_seconds=10.0)
        # Even 1000 calls must succeed when the breaker is disabled
        for _ in range(1000):
            assert limiter.check_and_increment() is True

    def test_window_rotation_resets_count(self):
        # Use a very small window so the rotation fires quickly
        limiter = revision_safety.RevisionRateLimiter(max_per_window=1, window_seconds=0.05)
        assert limiter.check_and_increment() is True
        assert limiter.check_and_increment() is False  # tripped
        time.sleep(0.06)  # rotate past the window
        # New window: counter resets, breaker un-trips
        assert limiter.check_and_increment() is True
        snapshot = limiter.current_rate()
        assert snapshot["tripped"] is False

    def test_reset_clears_state(self):
        limiter = revision_safety.RevisionRateLimiter(max_per_window=1, window_seconds=10.0)
        limiter.check_and_increment()
        limiter.check_and_increment()  # trip
        assert limiter.current_rate()["tripped"] is True
        limiter.reset()
        snap = limiter.current_rate()
        assert snap["tripped"] is False
        assert snap["current_count"] == 0

    def test_default_limiter_is_singleton(self):
        revision_safety.reset_default_limiter()
        first = revision_safety.get_default_limiter()
        second = revision_safety.get_default_limiter()
        assert first is second
        revision_safety.reset_default_limiter()


# ---------------------------------------------------------------------------
# Guard #3 -- PlannedAction dataclass
# ---------------------------------------------------------------------------


class TestPlannedAction:
    def test_to_dict_round_trip(self):
        plan = revision_safety.PlannedAction(
            entity_id="ontology_classes/Customer",
            verdict=rev_repo.VERDICT_REFINED,
            agent_type=rev_repo.AGENT_LLM,
            proposed_action=rev_repo.ACTION_REVISE,
            effective_action=rev_repo.ACTION_FLAG_FOR_CURATION,
            reason="entity is published",
            extra={"source_doc": "doc_42"},
        )
        d = plan.to_dict()
        assert d["entity_id"] == "ontology_classes/Customer"
        assert d["proposed_action"] == rev_repo.ACTION_REVISE
        assert d["effective_action"] == rev_repo.ACTION_FLAG_FOR_CURATION
        assert d["reason"] == "entity is published"
        assert d["extra"] == {"source_doc": "doc_42"}


# ---------------------------------------------------------------------------
# Guard #4 -- Cursor resumption
# ---------------------------------------------------------------------------


class _StubCollection:
    """Minimal in-memory stand-in for an Arango collection.

    We only need ``insert`` / ``update`` semantics keyed by ``_key`` so
    we can verify the checkpoint / load round trip. Keeps test setup
    straight-line with no need for the arango-python client.
    """

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def insert(self, doc, return_new=False):
        self.docs[doc["_key"]] = dict(doc)
        return {"new": dict(doc)} if return_new else dict(doc)

    def update(self, doc, return_new=False):
        self.docs[doc["_key"]].update(doc)
        return {"new": dict(self.docs[doc["_key"]])} if return_new else dict(doc)

    def get(self, key):
        return self.docs.get(key)


def _stub_db_with_cursor_collection():
    db = MagicMock()
    col = _StubCollection()
    db.has_collection.return_value = True
    db.collection.return_value = col

    def _doc_get(collection, key):
        return collection.get(key)

    return db, col, _doc_get


class TestConsolidationCursor:
    def test_to_doc_round_trip(self):
        cur = revision_safety.ConsolidationCursor(
            job_key="job_1",
            ontology_id="onto_1",
            stage="decay",
            last_processed_id="ontology_classes/Customer",
            processed_count=42,
            dry_run=True,
            extra={"batches": 3},
        )
        doc = cur.to_doc()
        recreated = revision_safety.ConsolidationCursor.from_doc(doc)
        assert recreated.job_key == "job_1"
        assert recreated.stage == "decay"
        assert recreated.last_processed_id == "ontology_classes/Customer"
        assert recreated.processed_count == 42
        assert recreated.dry_run is True
        assert recreated.extra == {"batches": 3}

    def test_checkpoint_inserts_then_updates(self):
        db, col, doc_get_fn = _stub_db_with_cursor_collection()
        cursor = revision_safety.ConsolidationCursor(job_key="job_1", ontology_id="onto_1")
        with patch("app.services.revision_safety.doc_get", side_effect=doc_get_fn):
            revision_safety.checkpoint_cursor(cursor, db=db)
            assert col.docs["job_1"]["ontology_id"] == "onto_1"
            assert col.docs["job_1"]["processed_count"] == 0
            # Bump state and checkpoint again -- second call should UPDATE
            cursor.processed_count = 5
            cursor.stage = "decay"
            revision_safety.checkpoint_cursor(cursor, db=db)
            assert col.docs["job_1"]["processed_count"] == 5
            assert col.docs["job_1"]["stage"] == "decay"

    def test_load_cursor_round_trip(self):
        db, col, doc_get_fn = _stub_db_with_cursor_collection()
        cursor = revision_safety.ConsolidationCursor(
            job_key="job_1",
            ontology_id="onto_1",
            stage="rules",
            last_processed_id="ontology_classes/X",
            processed_count=7,
        )
        with patch("app.services.revision_safety.doc_get", side_effect=doc_get_fn):
            revision_safety.checkpoint_cursor(cursor, db=db)
            # Sanity: prove the write half landed in the stub before we test
            # the read half — otherwise a bug in load_cursor + a no-op
            # checkpoint_cursor could both look "passing" together.
            assert col.docs["job_1"]["processed_count"] == 7
            assert col.docs["job_1"]["stage"] == "rules"
            loaded = revision_safety.load_cursor("job_1", db=db)
        assert loaded is not None
        assert loaded.job_key == "job_1"
        assert loaded.last_processed_id == "ontology_classes/X"
        assert loaded.processed_count == 7

    def test_load_cursor_returns_none_when_missing(self):
        db = MagicMock()
        db.has_collection.return_value = True
        col = _StubCollection()
        db.collection.return_value = col
        with patch("app.services.revision_safety.doc_get", side_effect=lambda c, k: c.get(k)):
            assert revision_safety.load_cursor("missing", db=db) is None

    def test_load_cursor_returns_none_when_collection_missing(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert revision_safety.load_cursor("any", db=db) is None

    def test_list_recent_jobs_passes_filters(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.revision_safety.run_aql",
            return_value=iter([{"_key": "job_1"}]),
        ) as mock_run:
            result = revision_safety.list_recent_jobs(ontology_id="onto_1", limit=5, db=db)
        assert result == [{"_key": "job_1"}]
        bind = mock_run.call_args.kwargs["bind_vars"]
        assert bind["oid"] == "onto_1"
        assert bind["limit"] == 5

    def test_list_recent_jobs_empty_when_collection_missing(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert revision_safety.list_recent_jobs(db=db) == []
