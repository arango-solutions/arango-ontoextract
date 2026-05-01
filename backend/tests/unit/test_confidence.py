"""Unit tests for multi-signal confidence scoring."""

from __future__ import annotations

import pytest

from app.services.confidence import (
    WEIGHT_AGREEMENT,
    WEIGHT_DESCRIPTION,
    WEIGHT_FAITHFULNESS,
    WEIGHT_PROPERTY_AGREEMENT,
    WEIGHT_PROVENANCE,
    WEIGHT_SEMANTIC_VALIDITY,
    WEIGHT_STRUCTURAL,
    _description_score,
    _property_agreement_score,
    _provenance_score,
    _structural_score,
    compute_class_confidence,
)


class TestStructuralScore:
    def test_all_signals_present(self):
        score = _structural_score(
            datatype_property_count=2,
            object_property_count=3,
            has_parent=True,
            has_children=True,
            has_lateral_edges=True,
        )
        assert score == 1.0

    def test_no_signals(self):
        assert _structural_score() == 0.0

    def test_datatype_only(self):
        assert _structural_score(datatype_property_count=5) == pytest.approx(0.15)

    def test_object_properties_scale(self):
        assert _structural_score(object_property_count=1) == pytest.approx(0.10)
        assert _structural_score(object_property_count=2) == pytest.approx(0.20)
        assert _structural_score(object_property_count=3) == pytest.approx(0.30)
        # Capped at 0.30
        assert _structural_score(object_property_count=5) == pytest.approx(0.30)

    def test_parent_and_children_no_properties(self):
        score = _structural_score(has_parent=True, has_children=True)
        assert score == pytest.approx(0.35)

    def test_lateral_edges_contribute(self):
        assert _structural_score(has_lateral_edges=True) == pytest.approx(0.20)

    def test_capped_at_one(self):
        score = _structural_score(
            datatype_property_count=10,
            object_property_count=10,
            has_parent=True,
            has_children=True,
            has_lateral_edges=True,
        )
        assert score == 1.0


class TestPropertyAgreementScore:
    def test_single_pass_returns_one(self):
        assert _property_agreement_score([{"a", "b"}]) == 1.0

    def test_empty_list_returns_one(self):
        assert _property_agreement_score([]) == 1.0

    def test_identical_passes(self):
        sets = [{"a", "b", "c"}, {"a", "b", "c"}, {"a", "b", "c"}]
        assert _property_agreement_score(sets) == pytest.approx(1.0)

    def test_disjoint_passes(self):
        sets = [{"a", "b"}, {"c", "d"}]
        assert _property_agreement_score(sets) == pytest.approx(0.0)

    def test_partial_overlap(self):
        sets = [{"a", "b", "c"}, {"b", "c", "d"}]
        # Jaccard = 2/4 = 0.5
        assert _property_agreement_score(sets) == pytest.approx(0.5)

    def test_all_empty_passes(self):
        sets: list[set[str]] = [set(), set()]
        assert _property_agreement_score(sets) == pytest.approx(1.0)

    def test_three_passes_pairwise_average(self):
        sets = [{"a", "b"}, {"a", "b"}, {"a"}]
        # pair(0,1) = 2/2 = 1.0, pair(0,2) = 1/2 = 0.5, pair(1,2) = 1/2 = 0.5
        expected = (1.0 + 0.5 + 0.5) / 3
        assert _property_agreement_score(sets) == pytest.approx(expected)


class TestDescriptionScore:
    def test_long_unique_description(self):
        desc = "A comprehensive description of a network firewall class with detailed semantics"
        score = _description_score(desc, [desc, "Something else entirely"])
        assert score > 0.5

    def test_short_description_penalized(self):
        score = _description_score("Short", ["Short", "Other thing"])
        assert score < 0.2

    def test_duplicate_description_loses_uniqueness(self):
        desc = "A reasonably long description that is duplicated across classes"
        score_unique = _description_score(desc, [desc])
        score_dup = _description_score(desc, [desc, desc])
        assert score_dup < score_unique

    def test_empty_description(self):
        score = _description_score("", ["", "Other"])
        assert score == 0.0


class TestProvenanceScore:
    def test_zero_chunks(self):
        assert _provenance_score(0) == 0.0

    def test_one_chunk(self):
        assert _provenance_score(1) == pytest.approx(1 / 3)

    def test_three_or_more_chunks(self):
        assert _provenance_score(3) == 1.0
        assert _provenance_score(10) == 1.0


class TestComputeClassConfidence:
    def test_perfect_signals_yield_high_confidence(self):
        score = compute_class_confidence(
            agreement_ratio=1.0,
            faithfulness=0.95,
            semantic_validity=0.95,
            datatype_property_count=3,
            object_property_count=3,
            has_parent=True,
            has_children=True,
            has_lateral_edges=True,
            description=(
                "A well-documented ontology class covering network"
                " infrastructure components in great detail"
            ),
            all_descriptions=[
                "A well-documented ontology class covering network"
                " infrastructure components in great detail",
                "Another unique class",
            ],
            provenance_count=5,
            property_agreement=1.0,
        )
        assert score >= 0.9

    def test_weak_signals_yield_low_confidence(self):
        score = compute_class_confidence(
            agreement_ratio=0.33,
            faithfulness=0.2,
            semantic_validity=0.2,
            datatype_property_count=0,
            object_property_count=0,
            has_parent=False,
            has_children=False,
            has_lateral_edges=False,
            description="x",
            all_descriptions=["x", "y"],
            provenance_count=0,
            property_agreement=0.0,
        )
        assert score < 0.2

    def test_mixed_signals_produce_differentiated_score(self):
        score_strong = compute_class_confidence(
            agreement_ratio=1.0,
            faithfulness=0.9,
            semantic_validity=0.9,
            datatype_property_count=2,
            object_property_count=2,
            has_parent=True,
            has_children=False,
            has_lateral_edges=True,
            description=("An important class representing customer entities with full provenance"),
            all_descriptions=[
                "An important class representing customer entities with full provenance",
            ],
            provenance_count=3,
            property_agreement=0.9,
        )
        score_weak = compute_class_confidence(
            agreement_ratio=0.67,
            faithfulness=0.4,
            semantic_validity=0.4,
            datatype_property_count=0,
            object_property_count=0,
            has_parent=False,
            has_children=False,
            has_lateral_edges=False,
            description="Unknown class",
            all_descriptions=["Unknown class"],
            provenance_count=1,
            property_agreement=0.3,
        )
        assert score_strong > score_weak

    def test_score_is_bounded(self):
        score = compute_class_confidence(
            agreement_ratio=1.0,
            faithfulness=1.0,
            semantic_validity=1.0,
            datatype_property_count=10,
            object_property_count=10,
            has_parent=True,
            has_children=True,
            has_lateral_edges=True,
            description="x" * 200,
            all_descriptions=["x" * 200],
            provenance_count=100,
            property_agreement=1.0,
        )
        assert 0.0 <= score <= 1.0

    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_AGREEMENT
            + WEIGHT_FAITHFULNESS
            + WEIGHT_SEMANTIC_VALIDITY
            + WEIGHT_STRUCTURAL
            + WEIGHT_DESCRIPTION
            + WEIGHT_PROVENANCE
            + WEIGHT_PROPERTY_AGREEMENT
        )
        assert total == pytest.approx(1.0)

    def test_backward_compat_llm_confidence_kwarg(self):
        """Legacy callers passing llm_confidence should still work."""
        score = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.9,
            has_properties=True,
            has_parent=True,
            has_children=False,
            description="A class with full structure and properties defined in the schema",
            all_descriptions=["A class with full structure and properties defined in the schema"],
            provenance_count=2,
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.5

    def test_backward_compat_has_properties_kwarg(self):
        """Legacy has_properties=True maps to 1 datatype property."""
        score_with = compute_class_confidence(
            agreement_ratio=1.0,
            has_properties=True,
            description="Some class",
            all_descriptions=["Some class"],
        )
        score_without = compute_class_confidence(
            agreement_ratio=1.0,
            has_properties=False,
            description="Some class",
            all_descriptions=["Some class"],
        )
        assert score_with > score_without

    def test_backward_compat_differentiates(self):
        """Backward-compat call with old kwargs still produces differentiated scores."""
        score_a = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.5,
            has_properties=True,
            has_parent=True,
            has_children=False,
            description="A class with full structure and properties defined in the schema",
            all_descriptions=["A class with full structure and properties defined in the schema"],
            provenance_count=2,
        )
        score_b = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.5,
            has_properties=False,
            has_parent=False,
            has_children=False,
            description="tiny",
            all_descriptions=["tiny"],
            provenance_count=0,
        )
        assert score_a > score_b
