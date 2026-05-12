"""Unit tests for the Pre-Curation Filter agent."""

from __future__ import annotations

from app.extraction.agents.filter import (
    _count_tiers,
    _remove_generic_terms,
    _remove_low_confidence_single_words,
    _remove_within_run_duplicates,
    _summarise_revision_actions,
    filter_agent_node,
)
from app.extraction.state import ExtractionPipelineState
from app.models.ontology import ExtractedClass, ExtractionResult


def _cls(
    uri: str,
    label: str,
    confidence: float = 0.9,
    description: str = "A test class",
) -> ExtractedClass:
    return ExtractedClass(
        uri=uri,
        label=label,
        description=description,
        confidence=confidence,
    )


def _make_state(
    classes: list[ExtractedClass] | None = None,
) -> ExtractionPipelineState:
    result = None
    if classes is not None:
        result = ExtractionResult(classes=classes, pass_number=0, model="test")
    return {
        "run_id": "test_run",
        "document_id": "doc1",
        "document_chunks": [],
        "extraction_passes": [],
        "consistency_result": result,
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "consistency_checker",
        "metadata": {},
        "er_results": {},
        "filter_results": {},
        "merge_candidates": [],
    }


class TestRemoveGenericTerms:
    def test_removes_generic_single_term(self):
        classes = [
            _cls("http://ex.org#Thing", "Thing"),
            _cls("http://ex.org#Vehicle", "Vehicle"),
        ]
        filtered = _remove_generic_terms(classes)
        assert len(filtered) == 1
        assert filtered[0].label == "Vehicle"

    def test_case_insensitive(self):
        classes = [_cls("http://ex.org#OBJECT", "OBJECT")]
        filtered = _remove_generic_terms(classes)
        assert len(filtered) == 0

    def test_preserves_non_generic(self):
        classes = [
            _cls("http://ex.org#Customer", "Customer"),
            _cls("http://ex.org#Invoice", "Invoice"),
        ]
        filtered = _remove_generic_terms(classes)
        assert len(filtered) == 2


class TestRemoveLowConfidenceSingleWords:
    def test_removes_single_word_low_confidence(self):
        classes = [
            _cls("http://ex.org#Foo", "Foo", confidence=0.3),
            _cls("http://ex.org#Bar", "Important Bar", confidence=0.3),
        ]
        filtered = _remove_low_confidence_single_words(classes)
        assert len(filtered) == 1
        assert filtered[0].label == "Important Bar"

    def test_keeps_single_word_high_confidence(self):
        classes = [_cls("http://ex.org#Foo", "Foo", confidence=0.9)]
        filtered = _remove_low_confidence_single_words(classes)
        assert len(filtered) == 1

    def test_keeps_multi_word_low_confidence(self):
        classes = [_cls("http://ex.org#Foo", "Foo Bar", confidence=0.3)]
        filtered = _remove_low_confidence_single_words(classes)
        assert len(filtered) == 1


class TestRemoveWithinRunDuplicates:
    def test_removes_duplicate_uris(self):
        classes = [
            _cls("http://ex.org#A", "ClassA", confidence=0.8),
            _cls("http://ex.org#A", "ClassA_v2", confidence=0.9),
        ]
        filtered = _remove_within_run_duplicates(classes)
        assert len(filtered) == 1
        assert filtered[0].confidence == 0.9

    def test_removes_duplicate_labels(self):
        classes = [
            _cls("http://ex.org#A1", "Customer", confidence=0.7),
            _cls("http://ex.org#A2", "Customer", confidence=0.9),
        ]
        filtered = _remove_within_run_duplicates(classes)
        assert len(filtered) == 1
        assert filtered[0].confidence == 0.9

    def test_keeps_unique_entries(self):
        classes = [
            _cls("http://ex.org#A", "Customer"),
            _cls("http://ex.org#B", "Invoice"),
            _cls("http://ex.org#C", "Product"),
        ]
        filtered = _remove_within_run_duplicates(classes)
        assert len(filtered) == 3


class TestCountTiers:
    def test_all_high(self):
        classes = [_cls("a", "A", confidence=0.9), _cls("b", "B", confidence=0.85)]
        tiers = _count_tiers(classes)
        assert tiers["high"] == 2
        assert tiers["medium"] == 0
        assert tiers["low"] == 0

    def test_mixed_tiers(self):
        classes = [
            _cls("a", "A", confidence=0.9),
            _cls("b", "B", confidence=0.6),
            _cls("c", "C", confidence=0.3),
        ]
        tiers = _count_tiers(classes)
        assert tiers["high"] == 1
        assert tiers["medium"] == 1
        assert tiers["low"] == 1


class TestFilterAgentNode:
    def test_skips_when_no_results(self):
        state = _make_state(classes=None)
        result = filter_agent_node(state)
        assert result["filter_results"]["status"] == "skipped"

    def test_filters_generic_terms(self):
        classes = [
            _cls("http://ex.org#Thing", "Thing"),
            _cls("http://ex.org#Object", "Object"),
            _cls("http://ex.org#Vehicle", "Vehicle"),
            _cls("http://ex.org#Customer", "Customer"),
        ]
        state = _make_state(classes=classes)
        result = filter_agent_node(state)

        cr = result["consistency_result"]
        assert cr is not None
        remaining_labels = {c.label for c in cr.classes}
        assert "Thing" not in remaining_labels
        assert "Object" not in remaining_labels
        assert "Vehicle" in remaining_labels
        assert "Customer" in remaining_labels

    def test_removal_ratio_calculated(self):
        classes = [
            _cls("http://ex.org#Thing", "Thing"),
            _cls("http://ex.org#Entity", "Entity"),
            _cls("http://ex.org#Object", "Object"),
            _cls("http://ex.org#Vehicle", "Vehicle"),
            _cls("http://ex.org#Customer", "Customer"),
        ]
        state = _make_state(classes=classes)
        result = filter_agent_node(state)

        fr = result["filter_results"]
        assert fr["input_count"] == 5
        assert fr["removed_count"] >= 3
        assert fr["removal_ratio"] >= 0.5

    def test_achieves_minimum_20_percent_filtering(self):
        """Verify the PRD requirement: >= 20% noise filtered."""
        classes = [
            _cls("http://ex.org#Thing", "Thing"),
            _cls("http://ex.org#Data", "Data"),
            _cls("http://ex.org#Node", "Node"),
            _cls("http://ex.org#Item", "Item"),
            _cls("http://ex.org#Category", "Category"),
            _cls("http://ex.org#Vehicle", "Vehicle"),
            _cls("http://ex.org#Customer", "Customer"),
            _cls("http://ex.org#Order", "Order"),
            _cls("http://ex.org#Product", "Product"),
            _cls("http://ex.org#Invoice", "Invoice"),
        ]
        state = _make_state(classes=classes)
        result = filter_agent_node(state)

        fr = result["filter_results"]
        assert fr["removal_ratio"] >= 0.20

    def test_step_log_emitted(self):
        state = _make_state(classes=[_cls("http://ex.org#A", "A")])
        result = filter_agent_node(state)
        assert len(result["step_logs"]) == 1
        assert result["step_logs"][0]["step"] == "filter"

    def test_confidence_tiers_in_results(self):
        classes = [
            _cls("http://ex.org#A", "HighConf", confidence=0.95),
            _cls("http://ex.org#B", "MedConf", confidence=0.65),
            _cls("http://ex.org#C", "LowConf", confidence=0.35),
        ]
        state = _make_state(classes=classes)
        result = filter_agent_node(state)

        tiers = result["filter_results"]["confidence_tiers"]
        assert tiers["high"] >= 1


class TestSummariseRevisionActions:
    """IBR.11: filter must surface pending revisions and count outcomes."""

    def test_empty_returns_zero_counts_and_no_pending(self):
        out = _summarise_revision_actions([])
        assert out["applied"] == 0
        assert out["failed"] == 0
        assert out["skipped"] == 0
        assert out["pending"] == []

    def test_counts_each_status_kind(self):
        actions = [
            {"status": "applied", "skipped": False},
            {"status": "applied", "skipped": False},
            {"status": "pending", "skipped": False, "revision_meta_key": "r1",
             "verdict": "UNCERTAIN", "action": "FLAG_FOR_CURATION",
             "agent_type": "llm", "rule_id": "R7_UNCERTAIN_SUFFIX",
             "existing_entity_id": "oc/Account",
             "new_concept_label": "AccountStatus", "reasoning": "suffix"},
            {"status": "failed", "skipped": False, "error": "boom"},
            {"status": "applied", "skipped": True, "skipped_reason": "prior"},
        ]
        out = _summarise_revision_actions(actions)
        assert out["applied"] == 2
        assert out["pending_count"] == 1
        assert out["failed"] == 1
        assert out["skipped"] == 1
        assert len(out["pending"]) == 1
        assert out["pending"][0]["new_concept_label"] == "AccountStatus"
        assert out["pending"][0]["revision_meta_key"] == "r1"

    def test_pending_payload_only_curator_relevant_fields(self):
        actions = [
            {"status": "pending", "skipped": False, "revision_meta_key": "r1",
             "verdict": "UNCERTAIN", "action": "FLAG_FOR_CURATION",
             "agent_type": "llm", "rule_id": "R7", "existing_entity_id": "oc/X",
             "new_concept_label": "Y", "reasoning": "r",
             "private_field_we_dont_want": "secret"},
        ]
        out = _summarise_revision_actions(actions)
        assert "private_field_we_dont_want" not in out["pending"][0]


class TestFilterPropagatesRevisionSummary:
    """IBR.11: filter_results must include revision_summary + pending_revisions."""

    def _state_with_revisions(self, classes, revision_actions):
        s = _make_state(classes=classes)
        s["revision_actions"] = revision_actions
        return s

    def test_no_revisions_yields_zero_summary(self):
        state = _make_state(classes=[_cls("http://ex.org#X", "Foo", 0.9)])
        out = filter_agent_node(state)
        fr = out["filter_results"]
        assert fr["revision_summary"]["applied"] == 0
        assert fr["revision_summary"]["pending_count"] == 0
        assert fr["pending_revisions"] == []

    def test_pending_revision_surfaces_in_filter_results(self):
        actions = [
            {"status": "pending", "skipped": False, "revision_meta_key": "r1",
             "verdict": "UNCERTAIN", "action": "FLAG_FOR_CURATION",
             "agent_type": "llm", "rule_id": "R7_UNCERTAIN_SUFFIX",
             "existing_entity_id": "oc/Account",
             "new_concept_label": "AccountStatus", "reasoning": "suffix"},
        ]
        state = self._state_with_revisions(
            [_cls("http://ex.org#X", "Foo", 0.9)], actions
        )
        out = filter_agent_node(state)
        fr = out["filter_results"]
        assert fr["revision_summary"]["pending_count"] == 1
        assert len(fr["pending_revisions"]) == 1
        assert fr["pending_revisions"][0]["new_concept_label"] == "AccountStatus"

    def test_skip_path_still_reports_revisions(self):
        """If consistency_result is None the filter still surfaces revisions."""
        actions = [
            {"status": "pending", "skipped": False, "revision_meta_key": "r1",
             "verdict": "CONTRADICTED", "action": "FLAG_FOR_CURATION",
             "agent_type": "llm", "rule_id": "R7_CONTRADICTED",
             "existing_entity_id": "oc/X",
             "new_concept_label": "Y", "reasoning": "contradicts"},
        ]
        state = _make_state(classes=None)
        state["revision_actions"] = actions
        out = filter_agent_node(state)
        fr = out["filter_results"]
        assert fr["status"] == "skipped"
        assert fr["revision_summary"]["pending_count"] == 1
        assert len(fr["pending_revisions"]) == 1
