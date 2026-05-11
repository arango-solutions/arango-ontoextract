"""Unit tests for ``app.services.touchpoint_discovery`` (Stream 11 IBR.5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services import touchpoint_discovery as td
from app.services.touchpoint_discovery import (
    DEFAULT_TOUCHPOINT_THRESHOLD,
    WEIGHT_EMBEDDING_SIM,
    NewConcept,
    Touchpoint,
    TouchpointReport,
    TouchpointSignals,
    _blend,
    _cosine,
    _jaccard,
    _label_fuzzy_score,
    _reasoning,
    discover_touchpoints,
    score_touchpoint,
)

# ---------------------------------------------------------------------------
# Pure signal helpers
# ---------------------------------------------------------------------------


class TestLabelFuzzyScore:
    def test_identical_labels_score_one(self):
        assert _label_fuzzy_score("Customer", "Customer") == 1.0

    def test_case_and_punct_insensitive(self):
        assert _label_fuzzy_score("CUSTOMER!", "customer") == 1.0

    def test_substring_returns_ratio(self):
        # "risk" (4) ⊂ "customerriskprofile" (19) -> 4/19 ≈ 0.211
        assert _label_fuzzy_score("Risk", "Customer Risk Profile") == pytest.approx(
            4 / 19, rel=1e-3
        )

    def test_no_overlap_returns_zero(self):
        assert _label_fuzzy_score("Customer", "Vendor") == 0.0

    def test_empty_inputs_return_zero(self):
        assert _label_fuzzy_score("", "Customer") == 0.0
        assert _label_fuzzy_score("Customer", "") == 0.0


class TestJaccard:
    def test_identical_sets_score_one(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets_score_zero(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_both_empty_returns_zero(self):
        # Both-empty is "no information", not a perfect match.
        assert _jaccard(set(), set()) == 0.0


class TestCosine:
    def test_identical_vectors_score_one(self):
        assert _cosine((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == 1.0

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine((1.0, 0.0), (0.0, 1.0)) == 0.0

    def test_opposite_vectors_clamped_to_zero(self):
        # Cosine of opposite vectors is -1; we clamp to [0, 1] so
        # negative similarity is treated as "no signal".
        assert _cosine((1.0, 0.0), (-1.0, 0.0)) == 0.0

    def test_different_lengths_returns_none(self):
        assert _cosine((1.0, 0.0), (1.0, 0.0, 0.0)) is None

    def test_empty_returns_none(self):
        assert _cosine((), ()) is None

    def test_zero_vector_returns_zero(self):
        assert _cosine((0.0, 0.0), (1.0, 0.0)) == 0.0


# ---------------------------------------------------------------------------
# Blender
# ---------------------------------------------------------------------------


class TestBlend:
    def test_all_signals_zero_returns_zero(self):
        s = TouchpointSignals(
            uri_exact=0,
            label_exact=0,
            label_fuzzy=0,
            chunk_overlap=0,
            embedding_sim=0,
        )
        assert _blend(s) == 0.0

    def test_perfect_signals_score_one(self):
        s = TouchpointSignals(
            uri_exact=1.0,
            label_exact=1.0,
            label_fuzzy=1.0,
            chunk_overlap=1.0,
            embedding_sim=1.0,
        )
        assert _blend(s) == pytest.approx(1.0, abs=1e-4)

    def test_missing_embedding_renormalises_remaining(self):
        # Without embedding, the four remaining weights should sum to 1.0
        # so a perfect score on those 4 still returns 1.0.
        s = TouchpointSignals(
            uri_exact=1.0,
            label_exact=1.0,
            label_fuzzy=1.0,
            chunk_overlap=1.0,
            embedding_sim=None,
        )
        assert _blend(s) == pytest.approx(1.0, abs=1e-4)

    def test_zero_embedding_not_treated_as_missing(self):
        # Explicit 0.0 must drag the score down (cosine measured zero
        # is a weak signal); only None means "absent and renormalise".
        s_zero = TouchpointSignals(1.0, 1.0, 1.0, 1.0, embedding_sim=0.0)
        s_none = TouchpointSignals(1.0, 1.0, 1.0, 1.0, embedding_sim=None)
        assert _blend(s_zero) < _blend(s_none)


class TestReasoning:
    def test_no_signals_returns_no_signals_message(self):
        s = TouchpointSignals(0, 0, 0, 0, embedding_sim=None)
        assert _reasoning(s) == "no specific signals fired"

    def test_describes_uri_exact(self):
        s = TouchpointSignals(1.0, 0, 0, 0, embedding_sim=None)
        assert "URI matches exactly" in _reasoning(s)

    def test_describes_each_active_signal(self):
        s = TouchpointSignals(1.0, 1.0, 0.5, 0.4, embedding_sim=0.85)
        msg = _reasoning(s)
        assert "URI" in msg and "label" in msg and "chunk" in msg and "embedding" in msg


# ---------------------------------------------------------------------------
# score_touchpoint (per-pair scorer)
# ---------------------------------------------------------------------------


class TestScoreTouchpoint:
    def test_perfect_match_scores_high(self):
        new = NewConcept(
            label="Customer",
            uri="http://x#Customer",
            chunk_ids=("c1", "c2"),
        )
        existing = {
            "_id": "ontology_classes/Customer",
            "_key": "Customer",
            "label": "Customer",
            "uri": "http://x#Customer",
            "source_chunk_ids": ["c1", "c2"],
        }
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.signals.uri_exact == 1.0
        assert tp.signals.label_exact == 1.0
        assert tp.signals.chunk_overlap == 1.0
        assert tp.combined_score == pytest.approx(1.0, abs=1e-3)

    def test_label_only_match(self):
        new = NewConcept(label="Customer", uri="http://different#Customer")
        existing = {
            "_id": "ontology_classes/x",
            "label": "Customer",
            "uri": "http://x#Customer",
        }
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.signals.uri_exact == 0.0
        assert tp.signals.label_exact == 1.0
        assert tp.combined_score > 0.2

    def test_no_signals_scores_zero(self):
        new = NewConcept(label="Quux")
        existing = {"_id": "ontology_classes/Customer", "label": "Customer"}
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.combined_score == 0.0

    def test_existing_without_id_returns_none(self):
        new = NewConcept(label="Customer")
        tp = score_touchpoint(new, {"label": "Customer"})  # no _id
        assert tp is None

    def test_embedding_signal_present_when_both_provided(self):
        new = NewConcept(label="x", embedding=(1.0, 0.0))
        existing = {
            "_id": "ontology_classes/y",
            "label": "x",
            "embedding": [1.0, 0.0],
        }
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.signals.embedding_sim == pytest.approx(1.0)

    def test_embedding_signal_absent_when_either_missing(self):
        new = NewConcept(label="x")  # no embedding
        existing = {
            "_id": "ontology_classes/y",
            "label": "x",
            "embedding": [1.0, 0.0],
        }
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.signals.embedding_sim is None

    def test_embedding_dimension_mismatch_safe(self):
        new = NewConcept(label="x", embedding=(1.0, 0.0))
        existing = {
            "_id": "ontology_classes/y",
            "label": "x",
            "embedding": [1.0, 0.0, 0.0],  # wrong dim
        }
        tp = score_touchpoint(new, existing)
        assert tp is not None
        assert tp.signals.embedding_sim is None


# ---------------------------------------------------------------------------
# discover_touchpoints orchestrator
# ---------------------------------------------------------------------------


def _stub_db_with_classes(classes: list[dict[str, Any]]) -> MagicMock:
    db = MagicMock()
    db.has_collection.return_value = True
    return db


def _patch_run_aql(monkeypatch, classes: list[dict[str, Any]]):
    def fake(_db, _aql, *, bind_vars=None):
        return iter(classes)

    monkeypatch.setattr(td, "run_aql", fake)


class TestDiscoverTouchpointsOrchestrator:
    def test_empty_new_concepts_returns_empty_report(self):
        db = MagicMock()
        report = discover_touchpoints(db, "OID", [])
        assert isinstance(report, TouchpointReport)
        assert report.touchpoints == []
        assert report.candidates_examined == 0

    def test_missing_collection_returns_empty(self, monkeypatch):
        db = MagicMock()
        db.has_collection.return_value = False
        report = discover_touchpoints(db, "OID", [NewConcept("Customer")])
        assert report.touchpoints == []
        assert report.candidates_examined == 0

    def test_below_threshold_pairs_dropped(self, monkeypatch):
        existing = [
            {"_id": "ontology_classes/Vendor", "label": "Vendor", "uri": "http://x#Vendor"},
        ]
        db = _stub_db_with_classes(existing)
        _patch_run_aql(monkeypatch, existing)
        new = [NewConcept(label="Customer", uri="http://x#Customer")]
        report = discover_touchpoints(db, "OID", new, threshold=DEFAULT_TOUCHPOINT_THRESHOLD)
        assert report.candidates_examined == 1
        assert report.touchpoints == []  # below threshold

    def test_above_threshold_pairs_returned_sorted(self, monkeypatch):
        existing = [
            # weak match (only label fuzzy)
            {
                "_id": "ontology_classes/Customer",
                "label": "Customer Group",
                "uri": "http://x#CustomerGroup",
            },
            # strong match (URI + label exact)
            {
                "_id": "ontology_classes/Customer",
                "label": "Customer",
                "uri": "http://x#Customer",
            },
        ]
        db = _stub_db_with_classes(existing)
        _patch_run_aql(monkeypatch, existing)
        new = [NewConcept(label="Customer", uri="http://x#Customer")]
        report = discover_touchpoints(db, "OID", new, threshold=0.0)
        # All examined; both above 0 threshold but the strong one ranks first.
        assert report.candidates_examined == 2
        assert len(report.touchpoints) >= 1
        scores = [t.combined_score for t in report.touchpoints]
        assert scores == sorted(scores, reverse=True)

    def test_limit_per_concept_caps_results(self, monkeypatch):
        existing = [
            {"_id": f"ontology_classes/c{i}", "label": "Customer", "uri": "http://x#Customer"}
            for i in range(5)
        ]
        db = _stub_db_with_classes(existing)
        _patch_run_aql(monkeypatch, existing)
        report = discover_touchpoints(
            db,
            "OID",
            [NewConcept(label="Customer", uri="http://x#Customer")],
            threshold=0.0,
            limit_per_concept=2,
        )
        assert len(report.touchpoints) == 2

    def test_to_dict_round_trip(self, monkeypatch):
        existing = [
            {"_id": "ontology_classes/Customer", "label": "Customer", "uri": "http://x#Customer"},
        ]
        db = _stub_db_with_classes(existing)
        _patch_run_aql(monkeypatch, existing)
        report = discover_touchpoints(
            db,
            "OID",
            [NewConcept(label="Customer", uri="http://x#Customer")],
            threshold=0.0,
        )
        d = report.to_dict()
        for key in (
            "ontology_id",
            "new_concept_count",
            "candidates_examined",
            "touchpoint_count",
            "touchpoints",
        ):
            assert key in d
        assert d["touchpoints"][0]["existing_class_id"] == "ontology_classes/Customer"
        assert "signals" in d["touchpoints"][0]


# ---------------------------------------------------------------------------
# Public weight contract
# ---------------------------------------------------------------------------


class TestWeightContract:
    def test_weights_sum_to_one(self):
        from app.services.touchpoint_discovery import (
            WEIGHT_CHUNK_OVERLAP,
            WEIGHT_LABEL_EXACT,
            WEIGHT_LABEL_FUZZY,
            WEIGHT_URI_EXACT,
        )

        total = (
            WEIGHT_URI_EXACT
            + WEIGHT_LABEL_EXACT
            + WEIGHT_LABEL_FUZZY
            + WEIGHT_CHUNK_OVERLAP
            + WEIGHT_EMBEDDING_SIM
        )
        assert total == pytest.approx(1.0)


def test_touchpoint_dataclass_immutable():
    from dataclasses import FrozenInstanceError

    s = TouchpointSignals(0, 0, 0, 0, embedding_sim=None)
    t = Touchpoint(
        new_concept_label="x",
        new_concept_uri=None,
        existing_class_id="ontology_classes/x",
        existing_class_label="x",
        signals=s,
        combined_score=0.0,
        reasoning="",
    )
    with pytest.raises(FrozenInstanceError):
        t.combined_score = 1.0  # type: ignore[misc]
