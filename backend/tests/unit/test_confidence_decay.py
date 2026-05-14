"""Unit tests for ``app.services.confidence_decay`` (Stream 11 IBR.3).

Layered like ``test_edge_repair.py``:

* :func:`compute_decayed_confidence` is pure -- tested with hand inputs.
* :func:`apply_confidence_decay` is exercised against MagicMock DB
  collections with patched ``run_aql`` / ``settings`` so we can
  control the feature flag, examine the writes, and assert the
  report contract -- no live ArangoDB needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services import confidence_decay
from app.services.confidence_decay import (
    DecayedClass,
    DecayReport,
    apply_confidence_decay,
    compute_decayed_confidence,
)

# ---------------------------------------------------------------------------
# compute_decayed_confidence
# ---------------------------------------------------------------------------


class TestComputeDecayedConfidencePure:
    def test_zero_age_returns_input(self):
        assert compute_decayed_confidence(0.8, 0, half_life_days=90, floor=0.05) == 0.8

    def test_negative_age_returns_input(self):
        # Defensive: clock skew can produce negative ages; treat as fresh.
        assert compute_decayed_confidence(0.8, -10, half_life_days=90, floor=0.05) == 0.8

    def test_one_half_life_halves_confidence(self):
        seconds_90d = 90 * 86400
        out = compute_decayed_confidence(0.8, seconds_90d, half_life_days=90, floor=0.05)
        assert out == pytest.approx(0.4, rel=1e-3)

    def test_two_half_lives_quarters_confidence(self):
        seconds_180d = 180 * 86400
        out = compute_decayed_confidence(0.8, seconds_180d, half_life_days=90, floor=0.05)
        assert out == pytest.approx(0.2, rel=1e-3)

    def test_floor_clamps_long_age(self):
        seconds_3y = 3 * 365 * 86400
        out = compute_decayed_confidence(0.8, seconds_3y, half_life_days=90, floor=0.1)
        assert out == 0.1

    def test_floor_does_not_raise_value_above_input(self):
        # If old confidence is already below the floor, decay must not
        # *increase* it. Decay never moves a value upward.
        out = compute_decayed_confidence(0.02, 10 * 86400, half_life_days=90, floor=0.1)
        assert out == 0.02

    def test_zero_half_life_does_not_divide_by_zero(self):
        # Defensive: a misconfigured half_life=0 must not crash.
        out = compute_decayed_confidence(0.8, 10, half_life_days=0, floor=0.05)
        assert 0.0 <= out <= 0.8


# ---------------------------------------------------------------------------
# apply_confidence_decay -- helpers
# ---------------------------------------------------------------------------


def _stub_db_with_classes(classes: list[dict[str, Any]]):
    db = MagicMock()
    db.has_collection.return_value = True
    cls_col = MagicMock()
    db.collection.return_value = cls_col
    return db, cls_col


def _patch_settings(monkeypatch, *, enabled: bool, half_life=90.0, floor=0.05):
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_enabled", enabled)
    monkeypatch.setattr(
        confidence_decay.settings, "belief_revision_decay_half_life_days", half_life
    )
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_floor", floor)


def _patch_run_aql(monkeypatch, classes: list[dict[str, Any]]):
    def fake(_db, _aql, *, bind_vars=None):
        return iter(classes)

    monkeypatch.setattr(confidence_decay, "run_aql", fake)


# ---------------------------------------------------------------------------
# apply_confidence_decay -- feature flag
# ---------------------------------------------------------------------------


class TestApplyDecayFeatureFlag:
    def test_disabled_and_not_dry_run_returns_empty_report(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=False)
        db, cls_col = _stub_db_with_classes([])
        report = apply_confidence_decay(db, "OID", dry_run=False)
        assert isinstance(report, DecayReport)
        assert report.enabled is False
        assert report.classes_examined == 0
        # No DB read attempted.
        db.collection.assert_not_called()
        cls_col.update.assert_not_called()

    def test_disabled_dry_run_still_computes(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=False)
        now = 1_700_000_000.0
        # One stale class.
        cls = {
            "_key": "Customer",
            "confidence": 0.8,
            "created": now - 180 * 86400,  # 2 half-lives old
        }
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", dry_run=True, now=now)
        assert report.enabled is False
        assert report.dry_run is True
        assert report.classes_examined == 1
        assert report.classes_decayed == 1
        # No write occurred even though decay was computed.
        cls_col.update.assert_not_called()

    def test_force_overrides_disabled(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=False)
        now = 1_700_000_000.0
        cls = {
            "_key": "Customer",
            "confidence": 0.8,
            "created": now - 180 * 86400,
        }
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", force=True, now=now)
        assert report.classes_decayed == 1
        # Live write happened despite disabled flag.
        assert cls_col.update.call_count == 1


# ---------------------------------------------------------------------------
# apply_confidence_decay -- enabled path
# ---------------------------------------------------------------------------


class TestApplyDecayEnabledPath:
    def test_enabled_writes_decayed_value_and_timestamp(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True, half_life=90.0, floor=0.05)
        now = 1_700_000_000.0
        cls = {
            "_key": "Customer",
            "confidence": 0.8,
            "created": now - 90 * 86400,  # exactly 1 half-life
        }
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)

        assert report.classes_decayed == 1
        write = cls_col.update.call_args.args[0]
        assert write["_key"] == "Customer"
        assert write["current_confidence"] == pytest.approx(0.4, rel=1e-3)
        assert write["confidence_decayed_at"] == now

    def test_skip_when_within_first_half_life_no_decay_recorded(self, monkeypatch):
        # An age of 1 day with 90-day half-life produces a decay
        # multiplier of ~0.992 -- the value DOES drop, just slightly.
        # Verify the orchestrator still records / writes when decayed
        # value is strictly less than the input (not "skip if within
        # first half-life" -- we previously considered that and rejected
        # it as too coarse).
        _patch_settings(monkeypatch, enabled=True, half_life=90.0, floor=0.05)
        now = 1_700_000_000.0
        cls = {"_key": "Fresh", "confidence": 0.8, "created": now - 86400}
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)
        assert report.classes_decayed == 1
        write = cls_col.update.call_args.args[0]
        assert write["current_confidence"] < 0.8
        assert write["current_confidence"] > 0.79

    def test_skip_class_with_no_age_increments_counter(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True)
        cls = {"_key": "NoAge", "confidence": 0.8}  # no created / last_evidenced_at
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=1_700_000_000.0)
        assert report.classes_examined == 1
        assert report.skipped_no_age == 1
        assert report.classes_decayed == 0
        cls_col.update.assert_not_called()

    def test_class_with_no_confidence_field_skipped_silently(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True)
        cls = {"_key": "X", "created": 1_600_000_000.0}  # no confidence
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=1_700_000_000.0)
        assert report.classes_examined == 1
        assert report.classes_decayed == 0
        assert report.skipped_no_age == 0  # no-confidence is not no-age
        cls_col.update.assert_not_called()

    def test_prefers_last_evidenced_at_over_created(self, monkeypatch):
        # last_evidenced_at is the freshness of the most recent revision,
        # so it must take precedence over created for age calculation.
        _patch_settings(monkeypatch, enabled=True, half_life=90.0)
        now = 1_700_000_000.0
        cls_recently_evidenced = {
            "_key": "RE",
            "confidence": 0.8,
            "created": now - 365 * 86400,  # very old
            "last_evidenced_at": now - 86400,  # but freshly re-evidenced
        }
        db, cls_col = _stub_db_with_classes([cls_recently_evidenced])
        _patch_run_aql(monkeypatch, [cls_recently_evidenced])
        report = apply_confidence_decay(db, "OID", now=now)
        # Age should be ~1 day, not ~365 days; confidence barely budges.
        assert report.classes_decayed == 1
        write = cls_col.update.call_args.args[0]
        assert write["current_confidence"] > 0.79  # barely decayed

    def test_uses_current_confidence_when_present(self, monkeypatch):
        # If a previous decay run already wrote current_confidence, the
        # next run must compound on THAT value, not on the original
        # extraction confidence.
        _patch_settings(monkeypatch, enabled=True, half_life=90.0)
        now = 1_700_000_000.0
        cls = {
            "_key": "X",
            "confidence": 0.8,  # immutable extraction confidence
            "current_confidence": 0.4,  # previously decayed to 0.4
            "created": now - 90 * 86400,
        }
        db, cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)
        assert report.classes_decayed == 1
        # 0.4 * 0.5 = 0.2, NOT 0.8 * 0.5 = 0.4
        write = cls_col.update.call_args.args[0]
        assert write["current_confidence"] == pytest.approx(0.2, rel=1e-3)

    def test_floor_floors_old_classes(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True, half_life=90.0, floor=0.1)
        now = 1_700_000_000.0
        cls = {"_key": "X", "confidence": 0.8, "created": now - 5 * 365 * 86400}
        db, _cls_col = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)
        assert report.decayed[0].confidence_after == 0.1


# ---------------------------------------------------------------------------
# apply_confidence_decay -- error handling + report contract
# ---------------------------------------------------------------------------


class TestApplyDecayContract:
    def test_missing_collection_returns_empty_report(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True)
        db = MagicMock()
        db.has_collection.return_value = False
        report = apply_confidence_decay(db, "OID")
        assert report.classes_examined == 0
        assert report.decayed == []

    def test_write_failure_rolls_back_report_entry(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True)
        now = 1_700_000_000.0
        cls = {"_key": "X", "confidence": 0.8, "created": now - 180 * 86400}
        db = MagicMock()
        db.has_collection.return_value = True
        cls_col = MagicMock()
        cls_col.update.side_effect = RuntimeError("storage down")
        db.collection.return_value = cls_col
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)
        # Entry was provisionally added then rolled back when the write failed.
        assert report.classes_decayed == 0
        assert report.decayed == []

    def test_to_dict_round_trip(self, monkeypatch):
        _patch_settings(monkeypatch, enabled=True)
        now = 1_700_000_000.0
        cls = {"_key": "Customer", "confidence": 0.8, "created": now - 90 * 86400}
        db, _ = _stub_db_with_classes([cls])
        _patch_run_aql(monkeypatch, [cls])
        report = apply_confidence_decay(db, "OID", now=now)
        d = report.to_dict()
        for key in (
            "ontology_id",
            "enabled",
            "dry_run",
            "half_life_days",
            "floor",
            "classes_examined",
            "classes_decayed",
            "skipped_no_age",
            "decayed",
        ):
            assert key in d
        assert isinstance(d["decayed"], list)
        assert d["decayed"][0]["class_key"] == "Customer"

    def test_decayed_class_dataclass_fields(self):
        # Lock the contract so downstream consumers (admin endpoint,
        # consolidation report) can rely on the schema.
        d = DecayedClass(
            class_key="X",
            confidence_before=0.8,
            confidence_after=0.4,
            age_seconds=86400 * 90,
        )
        assert d.class_key == "X"
        assert d.confidence_before == 0.8
        assert d.confidence_after == 0.4
        assert d.age_seconds == 86400 * 90
