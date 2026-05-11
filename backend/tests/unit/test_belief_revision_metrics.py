"""Unit tests for ``app.services.belief_revision_metrics`` (Stream 11 IBR.6).

Read-only aggregation helpers powering the Quality Dashboard belief-
revision tile (PRD FR-13.26). Tested with MagicMock + patched
``run_aql`` so the AQL contract is asserted without needing live
ArangoDB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.db.revision_meta_repo import (
    ACTION_REINFORCE,
    ACTIONS,
    STATUS_APPLIED,
    STATUSES,
    VERDICT_REINFORCED,
    VERDICTS,
)
from app.services import belief_revision_metrics as metrics


def _patch_run_aql(monkeypatch, *, by_aql: dict[str, list[Any]]):
    """Return a different row set for each query identified by substring."""

    def fake(_db, aql, *, bind_vars=None):
        for needle, rows in by_aql.items():
            if needle in aql:
                return iter(rows)
        raise AssertionError(f"unexpected AQL in test: {aql!r}")

    monkeypatch.setattr(metrics, "run_aql", fake)


# ---------------------------------------------------------------------------
# revisions_summary
# ---------------------------------------------------------------------------


class TestRevisionsSummary:
    def test_missing_collection_returns_zero_filled(self):
        db = MagicMock()
        db.has_collection.return_value = False
        out = metrics.revisions_summary("OID", db=db)
        assert out["total"] == 0
        # Every known bucket key must appear with zero count -- the
        # dashboard relies on a stable shape.
        assert set(out["by_verdict"].keys()) == set(VERDICTS)
        assert set(out["by_action"].keys()) == set(ACTIONS)
        assert set(out["by_status"].keys()) == set(STATUSES)
        assert all(v == 0 for v in out["by_verdict"].values())

    def test_empty_collection_returns_zero_filled(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = True
        _patch_run_aql(monkeypatch, by_aql={"COLLECT verdict =": []})
        out = metrics.revisions_summary("OID", db=db)
        assert out["total"] == 0
        # Stable shape preserved.
        assert all(out["by_verdict"][v] == 0 for v in VERDICTS)

    def test_aggregates_counts_by_each_dimension(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            {
                "verdict": VERDICT_REINFORCED,
                "action": ACTION_REINFORCE,
                "status": STATUS_APPLIED,
                "n": 7,
            },
            {
                "verdict": "REFINED",
                "action": "REVISE",
                "status": "applied",
                "n": 3,
            },
            {
                "verdict": "CONTRADICTED",
                "action": "FLAG_FOR_CURATION",
                "status": "pending",
                "n": 2,
            },
        ]
        _patch_run_aql(monkeypatch, by_aql={"COLLECT verdict =": rows})
        out = metrics.revisions_summary("OID", db=db)
        assert out["total"] == 12
        assert out["by_verdict"][VERDICT_REINFORCED] == 7
        assert out["by_verdict"]["REFINED"] == 3
        assert out["by_action"][ACTION_REINFORCE] == 7
        assert out["by_action"]["FLAG_FOR_CURATION"] == 2
        assert out["by_status"][STATUS_APPLIED] == 10
        assert out["by_status"]["pending"] == 2

    def test_unknown_bucket_values_ignored(self, monkeypatch):
        # If a row carries an out-of-vocabulary verdict (e.g. legacy
        # data from before a constant rename), it must not crash and
        # must not silently inflate counts of known buckets.
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            {"verdict": "MAYBE", "action": "DUNNO", "status": "limbo", "n": 5},
        ]
        _patch_run_aql(monkeypatch, by_aql={"COLLECT verdict =": rows})
        out = metrics.revisions_summary("OID", db=db)
        # Total still reflects the row -- but no known bucket gained.
        assert out["total"] == 5
        assert all(c == 0 for c in out["by_verdict"].values())
        assert all(c == 0 for c in out["by_action"].values())
        assert all(c == 0 for c in out["by_status"].values())


# ---------------------------------------------------------------------------
# recent_revisions
# ---------------------------------------------------------------------------


class TestRecentRevisions:
    def test_missing_collection_returns_empty(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert metrics.recent_revisions("OID", db=db) == []

    def test_returns_compact_projection_in_order(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"_key": "a", "created": 100}, {"_key": "b", "created": 50}]
        _patch_run_aql(
            monkeypatch,
            by_aql={
                "FOR r IN revision_meta": rows,
            },
        )
        out = metrics.recent_revisions("OID", limit=5, db=db)
        assert out == rows  # passthrough preserves DB ordering


# ---------------------------------------------------------------------------
# decay_status
# ---------------------------------------------------------------------------


class TestDecayStatus:
    def test_missing_classes_collection_returns_settings_only(self, monkeypatch):
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_enabled", True
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_half_life_days", 30.0
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_floor", 0.05
        )
        db = MagicMock()
        db.has_collection.return_value = False
        out = metrics.decay_status("OID", db=db)
        assert out["enabled"] is True
        assert out["half_life_days"] == 30.0
        assert out["floor"] == 0.05
        # Decay-state fields use sentinel defaults.
        assert out["last_decay_run_at"] is None
        assert out["decayed_classes"] == 0

    def test_aggregates_over_decayed_classes(self, monkeypatch):
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_enabled", True
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_half_life_days", 90.0
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_floor", 0.05
        )
        db = MagicMock()
        db.has_collection.return_value = True
        _patch_run_aql(
            monkeypatch,
            by_aql={
                "FOR c IN ontology_classes": [
                    {"count": 12, "last_run": 1_700_000_000.0}
                ],
            },
        )
        out = metrics.decay_status("OID", db=db)
        assert out["decayed_classes"] == 12
        assert out["last_decay_run_at"] == 1_700_000_000.0

    def test_no_decayed_classes_keeps_last_run_none(self, monkeypatch):
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_enabled", False
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_half_life_days", 90.0
        )
        monkeypatch.setattr(
            metrics.settings, "belief_revision_decay_floor", 0.05
        )
        db = MagicMock()
        db.has_collection.return_value = True
        # Empty aggregation -- pre-decay ontology.
        _patch_run_aql(
            monkeypatch,
            by_aql={"FOR c IN ontology_classes": []},
        )
        out = metrics.decay_status("OID", db=db)
        assert out["decayed_classes"] == 0
        # Critical: must remain None (not 0) so the dashboard renders
        # "Never run" rather than 1970-01-01.
        assert out["last_decay_run_at"] is None


# ---------------------------------------------------------------------------
# inbox_size
# ---------------------------------------------------------------------------


class TestInboxSize:
    def test_missing_collection_returns_zero(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert metrics.inbox_size("OID", db=db) == 0

    def test_returns_count_from_aql(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = True
        _patch_run_aql(
            monkeypatch,
            by_aql={"FOR r IN revision_meta": [4]},
        )
        assert metrics.inbox_size("OID", db=db) == 4

    def test_empty_count_returns_zero(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = True
        _patch_run_aql(
            monkeypatch,
            by_aql={"FOR r IN revision_meta": []},
        )
        assert metrics.inbox_size("OID", db=db) == 0
