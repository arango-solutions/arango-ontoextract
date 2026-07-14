"""Unit tests for the shared candidate matcher (SF.2, app.services.matching)."""

from __future__ import annotations

import pytest

from app.services.matching import (
    DEFAULT_WEIGHTS,
    cosine_sim,
    jaro_winkler_sim,
    score_candidate,
    token_overlap,
)


class TestPrimitives:
    def test_jaro_winkler_identical_is_one(self) -> None:
        assert jaro_winkler_sim("Account", "Account") == 1.0

    def test_jaro_winkler_case_insensitive_equal_is_one(self) -> None:
        assert jaro_winkler_sim("Account", "account") == 1.0

    def test_jaro_winkler_empty_is_zero(self) -> None:
        assert jaro_winkler_sim("", "Account") == 0.0
        assert jaro_winkler_sim("Account", "") == 0.0

    def test_jaro_winkler_similar_beats_dissimilar(self) -> None:
        near = jaro_winkler_sim("Checking Account", "Checkings Account")
        far = jaro_winkler_sim("Checking Account", "Zebra")
        assert near > far
        assert 0.0 <= far < near <= 1.0

    def test_token_overlap_jaccard(self) -> None:
        # {a,b,c} vs {b,c,d} -> intersection 2 / union 4 = 0.5
        assert token_overlap("a b c", "b c d") == 0.5

    def test_token_overlap_disjoint_and_empty(self) -> None:
        assert token_overlap("a b", "c d") == 0.0
        assert token_overlap("", "a b") == 0.0

    def test_cosine_identical_and_orthogonal(self) -> None:
        assert cosine_sim([1.0, 0.0], [1.0, 0.0]) == 1.0
        assert cosine_sim([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_cosine_opposite_clamped_to_zero(self) -> None:
        assert cosine_sim([1.0, 0.0], [-1.0, 0.0]) == 0.0

    def test_cosine_length_mismatch_and_empty_and_zero_vector(self) -> None:
        assert cosine_sim([1.0, 2.0], [1.0]) == 0.0
        assert cosine_sim([], [1.0]) == 0.0
        assert cosine_sim([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestScoreCandidate:
    def test_er_equivalence_blend(self) -> None:
        """weights {label:0.6, description:0.4} reproduces the pre-SF.2 ER blend."""
        a = {"label": "Checking Account", "description": "a bank account for daily use"}
        b = {"label": "Checking Acct", "description": "bank account for everyday use"}
        res = score_candidate(a, b, weights={"label": 0.6, "description": 0.4})
        expected = round(0.6 * res["label"] + 0.4 * res["description"], 4)
        assert res["combined"] == expected
        assert "embedding" not in res  # no embeddings supplied

    def test_default_weights_with_embeddings_normalise_over_one(self) -> None:
        a = {"label": "Account", "description": "x y", "embedding": [1.0, 0.0, 0.0]}
        b = {"label": "Account", "description": "x y", "embedding": [1.0, 0.0, 0.0]}
        res = score_candidate(a, b)  # DEFAULT_WEIGHTS = 0.4/0.2/0.4, all present
        assert res["label"] == 1.0
        assert res["description"] == 1.0
        assert res["embedding"] == 1.0
        assert res["combined"] == 1.0
        assert pytest.approx(sum(DEFAULT_WEIGHTS.values())) == 1.0

    def test_missing_embedding_renormalises_over_available_signals(self) -> None:
        """No embedding => combined blends only label+description, renormalised."""
        a = {"label": "Account", "description": "a b"}
        b = {"label": "Acct", "description": "a c"}
        res = score_candidate(a, b)  # DEFAULT_WEIGHTS, but no embeddings present
        assert "embedding" not in res
        # renormalise over label(0.4) + description(0.2) = 0.6
        expected = round((0.4 * res["label"] + 0.2 * res["description"]) / 0.6, 4)
        assert res["combined"] == expected

    def test_embedding_skipped_when_only_one_side_has_it(self) -> None:
        a = {"label": "A", "description": "x", "embedding": [1.0, 0.0]}
        b = {"label": "A", "description": "x"}
        res = score_candidate(a, b)
        assert "embedding" not in res

    def test_embedding_skipped_on_length_mismatch(self) -> None:
        a = {"label": "A", "description": "x", "embedding": [1.0, 0.0, 0.0]}
        b = {"label": "A", "description": "x", "embedding": [1.0, 0.0]}
        res = score_candidate(a, b)
        assert "embedding" not in res

    def test_structural_only_when_neighbors_supplied(self) -> None:
        a = {"label": "A", "description": "x"}
        b = {"label": "B", "description": "y"}
        weights = {"label": 0.5, "structural": 0.5}
        # no neighbours -> structural absent, blend over label only
        res_none = score_candidate(a, b, weights=weights)
        assert "structural" not in res_none
        assert res_none["combined"] == res_none["label"]
        # neighbours supplied -> structural computed (Jaccard {p,q} vs {q,r} = 1/3)
        res = score_candidate(a, b, weights=weights, a_neighbors=["p", "q"], b_neighbors=["q", "r"])
        assert res["structural"] == pytest.approx(1 / 3, abs=1e-4)
        # combined is rounded once from the *unrounded* signals, so compare
        # against the raw structural value (1/3), not the rounded field.
        assert res["combined"] == round(0.5 * res["label"] + 0.5 * (1 / 3), 4)

    def test_all_signals_empty_combined_zero(self) -> None:
        res = score_candidate({}, {})
        assert res["combined"] == 0.0
