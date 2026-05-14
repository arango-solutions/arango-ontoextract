"""Unit tests for ``app.services.revision_verdict`` (Stream 11 IBR.7).

Two layers of coverage:

1. **Rule-level**: each of the nine ``R7_*`` code paths gets a focused
   test asserting verdict + action + rule_id.
2. **Fixture-level**: every observed gap from
   ``docs/REMAINING_WORK_PLAN.md`` (Q.1, Q.2a/b/c, Q.3a/c) gets an
   end-to-end test that builds a realistic ``Touchpoint`` plus
   ``StructuralFeatures`` and asserts the classifier produces the
   verdict described in the work plan. Q.3b is covered indirectly --
   it requires class-creation which is IBR.13's extension.

When this suite passes, IBR.7 is ready to be wired into the LangGraph
node (IBR.10).
"""

from __future__ import annotations

import pytest

from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_GAP_FILL,
    ACTION_REINFORCE,
    ACTION_REVISE,
    VERDICT_CONTRADICTED,
    VERDICT_GAP_FILLING,
    VERDICT_REDUNDANT,
    VERDICT_REFINED,
    VERDICT_REINFORCED,
    VERDICT_UNCERTAIN,
)
from app.services.revision_verdict import (
    AUTO_APPLY_SCORE_THRESHOLD,
    CO_CLASSIFIER_SUFFIXES,
    LABEL_FUZZY_REFINED_FLOOR,
    REDUNDANT_LABEL_THRESHOLD,
    RULE_R7_CONTRADICTED_DIRECT,
    RULE_R7_GAP_POLYMORPHIC,
    RULE_R7_GAP_PROPERTY_OVERLAP,
    RULE_R7_GAP_SIBLING_PATTERN,
    RULE_R7_REDUNDANT_LABEL,
    RULE_R7_REDUNDANT_URI,
    RULE_R7_REFINED_NAMING,
    RULE_R7_REINFORCED_LINKED,
    RULE_R7_UNCERTAIN_LOW_SIGNAL,
    RULE_R7_UNCERTAIN_SUFFIX,
    MechanicalRevision,
    StructuralFeatures,
    VerdictReport,
    classify,
    classify_batch,
    label_co_classifier_suffix,
)
from app.services.touchpoint_discovery import Touchpoint, TouchpointSignals

# ---------------------------------------------------------------------------
# Test-only builders -- keep verdict tests readable.
# ---------------------------------------------------------------------------


def _signals(
    *,
    uri_exact: float = 0.0,
    label_exact: float = 0.0,
    label_fuzzy: float = 0.0,
    chunk_overlap: float = 0.0,
    embedding_sim: float | None = None,
) -> TouchpointSignals:
    return TouchpointSignals(
        uri_exact=uri_exact,
        label_exact=label_exact,
        label_fuzzy=label_fuzzy,
        chunk_overlap=chunk_overlap,
        embedding_sim=embedding_sim,
    )


def _touchpoint(
    *,
    new_label: str,
    existing_label: str = "Account",
    existing_id: str = "ontology_classes/Account",
    new_uri: str | None = None,
    combined_score: float = 0.30,
    signals: TouchpointSignals | None = None,
    reasoning: str = "",
) -> Touchpoint:
    return Touchpoint(
        new_concept_label=new_label,
        new_concept_uri=new_uri,
        existing_class_id=existing_id,
        existing_class_label=existing_label,
        signals=signals or _signals(),
        combined_score=combined_score,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Pure helper: label_co_classifier_suffix
# ---------------------------------------------------------------------------


class TestLabelCoClassifierSuffix:
    @pytest.mark.parametrize("suffix", CO_CLASSIFIER_SUFFIXES)
    def test_each_suffix_matches(self, suffix):
        # Add a non-empty prefix so the "label is only the suffix" guard
        # doesn't reject it.
        assert label_co_classifier_suffix(f"Customer{suffix}") == suffix

    def test_no_match_returns_none(self):
        assert label_co_classifier_suffix("Account") is None
        assert label_co_classifier_suffix("Customer") is None

    def test_empty_label_returns_none(self):
        assert label_co_classifier_suffix("") is None

    def test_label_that_is_only_the_suffix_does_not_match(self):
        # A class actually called "Status" is fine to subClass; the
        # negative test is for prefix+suffix patterns like "AccountStatus".
        assert label_co_classifier_suffix("Status") is None
        assert label_co_classifier_suffix("Detail") is None

    def test_case_sensitive(self):
        # The pipeline produces PascalCase URIs; lowercase free text
        # comes from a different code path with its own normalisation.
        assert label_co_classifier_suffix("accountstatus") is None
        assert label_co_classifier_suffix("AccountSTATUS") is None

    def test_suffix_in_middle_does_not_match(self):
        # "Statusly" does not end in "Status" (no boundary at the right
        # of the suffix is required, but the suffix must literally end
        # the string).
        assert label_co_classifier_suffix("Statusly") is None


# ---------------------------------------------------------------------------
# Each R7 rule emits the expected verdict / action / rule_id.
# ---------------------------------------------------------------------------


class TestR7ContradictedDirect:
    def test_contradiction_evidence_emits_contradicted(self):
        tp = _touchpoint(new_label="EscrowAccount", combined_score=0.9)
        s = StructuralFeatures(
            contradiction_evidence=("declared disjoint with Account",),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_CONTRADICTED
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_CONTRADICTED_DIRECT
        assert rev.auto_applicable is False
        assert "declared disjoint" in rev.reasoning

    def test_contradiction_dominates_other_signals(self):
        # Even when the new concept is exactly the existing class
        # (uri_exact=1), a contradiction wins.
        tp = _touchpoint(
            new_label="Account",
            new_uri="http://example.org/Account",
            combined_score=1.0,
            signals=_signals(uri_exact=1.0, label_exact=1.0),
        )
        s = StructuralFeatures(contradiction_evidence=("foo",))
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_CONTRADICTED


class TestR7Reinforced:
    def test_already_linked_emits_reinforced(self):
        tp = _touchpoint(new_label="Account", combined_score=0.5)
        s = StructuralFeatures(is_already_linked=True)
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_REINFORCED
        assert rev.action == ACTION_REINFORCE
        assert rev.rule_id == RULE_R7_REINFORCED_LINKED
        assert rev.auto_applicable is True

    def test_reinforced_beats_naming_signals(self):
        tp = _touchpoint(
            new_label="EscrowAccount",
            combined_score=0.4,
            signals=_signals(label_fuzzy=0.5),
        )
        s = StructuralFeatures(
            is_already_linked=True,
            existing_has_subclasses=True,
        )
        # Already-linked beats sibling-pattern; otherwise we'd be
        # reinforcing a redundant subClassOf edge.
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_REINFORCED


class TestR7Redundant:
    def test_uri_exact_emits_redundant_revise(self):
        tp = _touchpoint(
            new_label="Account",
            new_uri="http://example.org/Account",
            combined_score=0.95,
            signals=_signals(uri_exact=1.0, label_exact=1.0),
        )
        rev = classify(tp)
        assert rev.verdict == VERDICT_REDUNDANT
        assert rev.action == ACTION_REVISE
        assert rev.rule_id == RULE_R7_REDUNDANT_URI
        assert rev.auto_applicable is True

    def test_uri_exact_with_low_score_still_redundant(self):
        # URI match dominates -- the score floor for URI-redundant is
        # tighter than the auto-apply gate.
        tp = _touchpoint(
            new_label="Account",
            new_uri="http://example.org/Account",
            combined_score=0.30,
            signals=_signals(uri_exact=1.0),
        )
        rev = classify(tp)
        assert rev.verdict == VERDICT_REDUNDANT
        assert rev.rule_id == RULE_R7_REDUNDANT_URI

    def test_label_exact_above_threshold_emits_redundant_label(self):
        tp = _touchpoint(
            new_label="Account",
            combined_score=REDUNDANT_LABEL_THRESHOLD + 0.01,
            signals=_signals(label_exact=1.0, label_fuzzy=1.0),
        )
        rev = classify(tp)
        assert rev.verdict == VERDICT_REDUNDANT
        assert rev.rule_id == RULE_R7_REDUNDANT_LABEL
        assert rev.auto_applicable is True

    def test_label_exact_below_threshold_falls_through(self):
        # Same label but low overall confidence (e.g. no embedding,
        # no chunk overlap) -- might be a coincidental name collision.
        # Falls through to lower-priority rules. With label_fuzzy=1.0
        # and no structural signals, lands in REFINED.
        tp = _touchpoint(
            new_label="Account",
            combined_score=REDUNDANT_LABEL_THRESHOLD - 0.01,
            signals=_signals(label_exact=1.0, label_fuzzy=1.0),
        )
        rev = classify(tp)
        assert rev.verdict != VERDICT_REDUNDANT


class TestR7UncertainSuffix:
    @pytest.mark.parametrize(
        "label, expected_suffix",
        [
            ("AccountStatus", "Status"),
            ("MuleAccountActivity", "Activity"),
            ("TransactionChannel", "Channel"),
            ("TransactionDetail", "Detail"),
            ("CountryCode", "Code"),
        ],
    )
    def test_suffix_emits_uncertain_with_suffix_rule(self, label, expected_suffix):
        tp = _touchpoint(
            new_label=label,
            existing_label=label.replace(expected_suffix, ""),
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.5),
        )
        # Even with strong structural signals, the suffix wins.
        s = StructuralFeatures(
            polymorphic_range_count=5,
            shared_property_names=("foo", "bar", "baz"),
            existing_has_subclasses=True,
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_UNCERTAIN_SUFFIX
        assert expected_suffix in rev.reasoning
        assert rev.auto_applicable is False

    def test_suffix_with_zero_label_fuzzy_does_not_trigger_uncertain_suffix(self):
        # If there's no naming overlap at all, the suffix rule doesn't
        # fire -- there's nothing to be cautious about.
        tp = _touchpoint(
            new_label="OrderStatus",
            existing_label="Account",
            combined_score=0.30,
            signals=_signals(label_fuzzy=0.0),
        )
        rev = classify(tp)
        # Falls through to UNCERTAIN low-signal, not UNCERTAIN suffix.
        assert rev.rule_id == RULE_R7_UNCERTAIN_LOW_SIGNAL


class TestR7GapPolymorphic:
    def test_polymorphic_with_label_fuzzy_emits_gap_fill(self):
        tp = _touchpoint(
            new_label="ExtendedTransaction",
            existing_label="Transaction",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.58),
        )
        s = StructuralFeatures(
            polymorphic_range_count=2,
            shared_property_names=("originator", "beneficiary"),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.action == ACTION_GAP_FILL
        assert rev.rule_id == RULE_R7_GAP_POLYMORPHIC
        assert rev.auto_applicable is True

    def test_polymorphic_with_low_score_escalates(self):
        tp = _touchpoint(
            new_label="ExtendedTransaction",
            existing_label="Transaction",
            combined_score=AUTO_APPLY_SCORE_THRESHOLD - 0.05,
            signals=_signals(label_fuzzy=0.58),
        )
        s = StructuralFeatures(polymorphic_range_count=1)
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_GAP_POLYMORPHIC
        assert rev.auto_applicable is False

    def test_polymorphic_with_zero_label_fuzzy_does_not_fire(self):
        # Polymorphic-range alone (no naming overlap) is not enough.
        tp = _touchpoint(
            new_label="Foobar",
            existing_label="Transaction",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.0, embedding_sim=0.5),
        )
        s = StructuralFeatures(polymorphic_range_count=5)
        rev = classify(tp, s)
        assert rev.rule_id != RULE_R7_GAP_POLYMORPHIC


class TestR7GapPropertyOverlap:
    def test_two_shared_properties_with_label_fuzzy_emits_gap_fill(self):
        tp = _touchpoint(
            new_label="TransactionLite",
            existing_label="Transaction",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.65),
        )
        s = StructuralFeatures(
            shared_property_names=("originator", "beneficiary"),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.rule_id == RULE_R7_GAP_PROPERTY_OVERLAP
        assert rev.action == ACTION_GAP_FILL

    def test_one_shared_property_does_not_fire(self):
        # Threshold is >=2 shared properties; one is too weak.
        tp = _touchpoint(
            new_label="Foo",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.4),
        )
        s = StructuralFeatures(shared_property_names=("name",))
        rev = classify(tp, s)
        assert rev.rule_id != RULE_R7_GAP_PROPERTY_OVERLAP


class TestR7GapSiblingPattern:
    def test_sibling_with_high_fuzzy_and_existing_subclasses_emits_gap_fill(self):
        tp = _touchpoint(
            new_label="EscrowAccount",
            existing_label="Account",
            combined_score=0.35,
            signals=_signals(label_fuzzy=0.54),
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.rule_id == RULE_R7_GAP_SIBLING_PATTERN
        assert rev.action == ACTION_GAP_FILL

    def test_sibling_without_existing_subclasses_falls_through(self):
        tp = _touchpoint(
            new_label="EscrowAccount",
            existing_label="Account",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.54),
        )
        s = StructuralFeatures(existing_has_subclasses=False)
        rev = classify(tp, s)
        # No structural anchor -> REFINED naming-only -> escalate
        assert rev.verdict == VERDICT_REFINED
        assert rev.rule_id == RULE_R7_REFINED_NAMING

    def test_sibling_with_low_fuzzy_falls_through(self):
        tp = _touchpoint(
            new_label="Foo",
            existing_label="Account",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.40),  # below SUBTYPE_FLOOR=0.50
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev = classify(tp, s)
        assert rev.rule_id != RULE_R7_GAP_SIBLING_PATTERN


class TestR7RefinedNaming:
    def test_naming_only_above_refined_floor_escalates(self):
        tp = _touchpoint(
            new_label="AccountSomething",
            existing_label="Account",
            combined_score=0.35,
            signals=_signals(label_fuzzy=LABEL_FUZZY_REFINED_FLOOR + 0.01),
        )
        rev = classify(tp)  # no structural features
        assert rev.verdict == VERDICT_REFINED
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_REFINED_NAMING


class TestR7UncertainLowSignal:
    def test_below_all_floors_emits_uncertain(self):
        tp = _touchpoint(
            new_label="Foo",
            combined_score=0.10,
            signals=_signals(label_fuzzy=0.10),
        )
        rev = classify(tp)
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_UNCERTAIN_LOW_SIGNAL

    def test_zero_signals(self):
        tp = _touchpoint(new_label="Foo", combined_score=0.0)
        rev = classify(tp)
        assert rev.verdict == VERDICT_UNCERTAIN

    def test_no_structural_features_uses_default(self):
        tp = _touchpoint(
            new_label="Foo",
            combined_score=0.20,
            signals=_signals(label_fuzzy=0.20),
        )
        rev_default = classify(tp)
        rev_explicit = classify(tp, StructuralFeatures())
        assert rev_default == rev_explicit


# ---------------------------------------------------------------------------
# MechanicalRevision shape / contract
# ---------------------------------------------------------------------------


class TestMechanicalRevision:
    def test_auto_applicable_property_matches_action(self):
        for action in (
            ACTION_REINFORCE,
            ACTION_REVISE,
            ACTION_GAP_FILL,
        ):
            rev = MechanicalRevision(
                touchpoint=_touchpoint(new_label="x"),
                verdict=VERDICT_GAP_FILLING,
                action=action,
                rule_id="x",
                confidence=0.5,
                reasoning="",
            )
            assert rev.auto_applicable is True

        rev_flag = MechanicalRevision(
            touchpoint=_touchpoint(new_label="x"),
            verdict=VERDICT_GAP_FILLING,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id="x",
            confidence=0.5,
            reasoning="",
        )
        assert rev_flag.auto_applicable is False

    def test_to_dict_serialises_expected_keys(self):
        tp = _touchpoint(new_label="A", existing_id="ontology_classes/B")
        rev = classify(tp)
        d = rev.to_dict()
        assert set(d.keys()) == {
            "verdict",
            "action",
            "rule_id",
            "confidence",
            "reasoning",
            "auto_applicable",
            "new_concept_label",
            "existing_class_id",
        }
        assert d["new_concept_label"] == "A"
        assert d["existing_class_id"] == "ontology_classes/B"


# ---------------------------------------------------------------------------
# Batch helper -- ordering, count buckets, has_contested
# ---------------------------------------------------------------------------


class TestClassifyBatch:
    def test_empty_input_returns_empty_report(self):
        r = classify_batch([])
        assert isinstance(r, VerdictReport)
        assert r.revisions == []
        # Counts are pre-filled with all known buckets.
        assert set(r.verdict_counts.keys()) >= {
            VERDICT_REINFORCED,
            VERDICT_REFINED,
            VERDICT_GAP_FILLING,
            VERDICT_REDUNDANT,
            VERDICT_CONTRADICTED,
            VERDICT_UNCERTAIN,
        }
        assert all(v == 0 for v in r.verdict_counts.values())
        assert r.has_contested is False

    def test_preserves_input_order(self):
        tps = [
            _touchpoint(new_label="A", existing_id="ontology_classes/A1"),
            _touchpoint(new_label="B", existing_id="ontology_classes/B1"),
            _touchpoint(new_label="C", existing_id="ontology_classes/C1"),
        ]
        r = classify_batch(tps)
        assert [rev.touchpoint.new_concept_label for rev in r.revisions] == [
            "A",
            "B",
            "C",
        ]

    def test_aggregates_counts(self):
        # Construct a mix that should produce distinct verdicts.
        tps = [
            # REDUNDANT (uri exact)
            _touchpoint(
                new_label="Account",
                new_uri="u",
                existing_id="ontology_classes/A",
                signals=_signals(uri_exact=1.0),
                combined_score=0.95,
            ),
            # UNCERTAIN suffix
            _touchpoint(
                new_label="AccountStatus",
                existing_id="ontology_classes/B",
                signals=_signals(label_fuzzy=0.5),
                combined_score=0.40,
            ),
            # UNCERTAIN low signal
            _touchpoint(
                new_label="ZZZ",
                existing_id="ontology_classes/C",
                combined_score=0.05,
            ),
        ]
        r = classify_batch(tps)
        assert r.verdict_counts[VERDICT_REDUNDANT] == 1
        assert r.verdict_counts[VERDICT_UNCERTAIN] == 2
        assert r.action_counts[ACTION_REVISE] == 1
        assert r.action_counts[ACTION_FLAG_FOR_CURATION] == 2

    def test_has_contested_true_when_uncertain_present(self):
        tps = [_touchpoint(new_label="ZZZ", combined_score=0.05)]
        r = classify_batch(tps)
        assert r.has_contested is True

    def test_has_contested_false_when_only_auto_applies(self):
        tps = [
            _touchpoint(
                new_label="Account",
                new_uri="u",
                existing_id="ontology_classes/A",
                signals=_signals(uri_exact=1.0),
                combined_score=0.95,
            ),
        ]
        r = classify_batch(tps)
        assert r.has_contested is False

    def test_structural_lookup_applied_per_touchpoint(self):
        # Same touchpoint, but with structural info pulling it from
        # REFINED -> GAP_FILLING via the sibling-pattern rule.
        tp_no_struct = _touchpoint(
            new_label="EscrowAccount",
            existing_id="ontology_classes/Account",
            existing_label="Account",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.54),
        )
        tp_with_struct = _touchpoint(
            new_label="EscrowAccount",
            existing_id="ontology_classes/Account",
            existing_label="Account",
            combined_score=0.40,
            signals=_signals(label_fuzzy=0.54),
        )
        lookup = {
            "ontology_classes/Account": StructuralFeatures(existing_has_subclasses=True),
        }
        r = classify_batch([tp_no_struct], structural_lookup=None)
        assert r.revisions[0].verdict == VERDICT_REFINED

        r2 = classify_batch([tp_with_struct], structural_lookup=lookup)
        assert r2.revisions[0].verdict == VERDICT_GAP_FILLING


# ---------------------------------------------------------------------------
# Q.1 -- Q.3 fixtures from docs/REMAINING_WORK_PLAN.md
# ---------------------------------------------------------------------------


class TestFixtureQ1EscrowAccount:
    """Sibling-pattern subclass gap (Q.1 in REMAINING_WORK_PLAN.md)."""

    def test_emits_gap_filling_via_sibling_pattern(self):
        # EscrowAccount → Account; CheckingAccount already subClassOf Account.
        tp = _touchpoint(
            new_label="Escrow Account",
            existing_label="Account",
            existing_id="ontology_classes/Account",
            combined_score=0.35,  # realistic with embedding + label fuzzy
            signals=_signals(label_fuzzy=7 / 13, embedding_sim=0.85),
        )
        s = StructuralFeatures(existing_has_subclasses=True)  # CheckingAccount exists
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.rule_id == RULE_R7_GAP_SIBLING_PATTERN
        assert rev.action == ACTION_GAP_FILL  # auto-apply
        assert rev.auto_applicable is True


class TestFixtureQ2aExtendedTransaction:
    """Polymorphic-range usage (Q.2a in REMAINING_WORK_PLAN.md)."""

    def test_emits_gap_filling_via_polymorphic(self):
        # ExtendedTransaction → Transaction; Alert.linked_transactions
        # and SuspiciousActivityReport.describes both range over both.
        tp = _touchpoint(
            new_label="ExtendedTransaction",
            existing_label="Transaction",
            existing_id="ontology_classes/Transaction",
            combined_score=0.40,
            signals=_signals(label_fuzzy=11 / 19, embedding_sim=0.90),
        )
        s = StructuralFeatures(
            polymorphic_range_count=2,
            shared_property_names=("originator", "beneficiary"),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.rule_id == RULE_R7_GAP_POLYMORPHIC
        assert rev.action == ACTION_GAP_FILL
        assert rev.auto_applicable is True


class TestFixtureQ2bTransactionDetail:
    """Subclass-vs-composition ambiguity (Q.2b in REMAINING_WORK_PLAN.md)."""

    def test_detail_suffix_forces_uncertain(self):
        # TransactionDetail → Transaction; the "Detail" suffix signals
        # ambiguity (could be subClassOf OR hasDetail composition).
        tp = _touchpoint(
            new_label="TransactionDetail",
            existing_label="Transaction",
            existing_id="ontology_classes/Transaction",
            combined_score=0.42,
            signals=_signals(label_fuzzy=11 / 17, embedding_sim=0.85),
        )
        # Even with shared properties (originator, beneficiary), the
        # suffix rule wins -- Phase 3 LLM agent must read source to choose.
        s = StructuralFeatures(
            shared_property_names=("originator", "beneficiary"),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.rule_id == RULE_R7_UNCERTAIN_SUFFIX
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert "Detail" in rev.reasoning


class TestFixtureQ2cTransactionChannel:
    """Co-classifier (Q.2c in REMAINING_WORK_PLAN.md) -- relationship, not subtype."""

    def test_channel_suffix_forces_uncertain(self):
        # TransactionChannel is NOT a subtype of Transaction; it's a
        # related concept (Transaction --channel--> TransactionChannel).
        # The mechanical classifier must NOT propose subClassOf.
        tp = _touchpoint(
            new_label="TransactionChannel",
            existing_label="Transaction",
            existing_id="ontology_classes/Transaction",
            combined_score=0.42,
            signals=_signals(label_fuzzy=11 / 18, embedding_sim=0.80),
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.rule_id == RULE_R7_UNCERTAIN_SUFFIX
        assert "Channel" in rev.reasoning


class TestFixtureQ3aBankingAccountSubtypes:
    """Batch of siblings (Q.3a in REMAINING_WORK_PLAN.md).

    Mechanical classifier handles short compound names where ``Account``
    is a substantial fraction of the label (Nostro/Vostro/Escrow have
    label_fuzzy ~0.54). Long compound names like
    ``MerchantSettlementAccount`` have label_fuzzy ~0.28 and fall below
    the SUBTYPE_FLOOR -- those escalate to the LLM agent (IBR.8). This
    is the documented mechanical/LLM split, not a bug.
    """

    @pytest.mark.parametrize(
        "label",
        ["NostroAccount", "VostroAccount"],  # both 13 chars, fuzzy ~0.54
    )
    def test_short_compound_siblings_emit_gap_filling(self, label):
        norm_new = len(label)
        norm_existing = len("Account")
        fuzzy = norm_existing / norm_new
        tp = _touchpoint(
            new_label=label,
            existing_label="Account",
            existing_id="ontology_classes/Account",
            combined_score=0.35,
            signals=_signals(label_fuzzy=fuzzy, embedding_sim=0.85),
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_GAP_FILLING
        assert rev.rule_id == RULE_R7_GAP_SIBLING_PATTERN
        assert rev.action == ACTION_GAP_FILL

    def test_long_compound_sibling_falls_below_floor_and_escalates(self):
        # MerchantSettlementAccount: label_fuzzy = 7/25 = 0.28, well
        # below LABEL_FUZZY_SUBTYPE_FLOOR (0.50). The mechanical
        # classifier deliberately does NOT propose subClassOf here --
        # the LLM agent (IBR.8) reads source text and decides.
        tp = _touchpoint(
            new_label="MerchantSettlementAccount",
            existing_label="Account",
            existing_id="ontology_classes/Account",
            combined_score=0.30,
            signals=_signals(label_fuzzy=7 / 25, embedding_sim=0.80),
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev = classify(tp, s)
        # Below all positive rules -> UNCERTAIN backstop -> escalate.
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.auto_applicable is False

    def test_batch_classifier_mixes_auto_and_escalated(self):
        # Realistic Q.3a batch: 2 short names auto-apply, 1 long name
        # escalates. The point is that classify_batch produces a
        # contested verdict count so IBR.10 knows to invoke the LLM.
        labels = [
            "NostroAccount",  # fuzzy 0.54 -> sibling pattern -> GAP_FILL
            "VostroAccount",  # fuzzy 0.54 -> sibling pattern -> GAP_FILL
            "MerchantSettlementAccount",  # fuzzy 0.28 -> UNCERTAIN
        ]
        tps = []
        for label in labels:
            fuzzy = len("Account") / len(label)
            tps.append(
                _touchpoint(
                    new_label=label,
                    existing_label="Account",
                    existing_id="ontology_classes/Account",
                    combined_score=0.35,
                    signals=_signals(label_fuzzy=fuzzy, embedding_sim=0.85),
                )
            )
        lookup = {"ontology_classes/Account": StructuralFeatures(existing_has_subclasses=True)}
        report = classify_batch(tps, lookup)
        assert report.verdict_counts[VERDICT_GAP_FILLING] == 2
        assert report.verdict_counts[VERDICT_UNCERTAIN] == 1
        assert report.action_counts[ACTION_GAP_FILL] == 2
        assert report.action_counts[ACTION_FLAG_FOR_CURATION] == 1
        # has_contested is True -> IBR.10 will invoke the LLM agent
        # (Phase 3) for the MerchantSettlementAccount case.
        assert report.has_contested is True


class TestFixtureQ3cNegativeAccountStatus:
    """Negative test (Q.3c in REMAINING_WORK_PLAN.md).

    AccountStatus and MuleAccountActivity share the Account name prefix
    but are NOT subtypes. The classifier must NOT emit GAP-FILLING.
    """

    @pytest.mark.parametrize(
        "label, expected_suffix",
        [
            ("AccountStatus", "Status"),
            ("MuleAccountActivity", "Activity"),
        ],
    )
    def test_co_classifier_suffix_blocks_gap_filling(self, label, expected_suffix):
        norm_existing = len("Account")
        fuzzy = norm_existing / len(label)
        tp = _touchpoint(
            new_label=label,
            existing_label="Account",
            existing_id="ontology_classes/Account",
            combined_score=0.40,
            signals=_signals(label_fuzzy=fuzzy, embedding_sim=0.80),
        )
        # Even with a strong sibling pattern, the suffix wins.
        s = StructuralFeatures(
            existing_has_subclasses=True,
            polymorphic_range_count=2,
            shared_property_names=("name", "id"),
        )
        rev = classify(tp, s)
        assert rev.verdict == VERDICT_UNCERTAIN
        assert rev.action == ACTION_FLAG_FOR_CURATION
        assert rev.rule_id == RULE_R7_UNCERTAIN_SUFFIX
        assert expected_suffix in rev.reasoning
        # And critically: the verdict is NOT GAP-FILLING.
        assert rev.verdict != VERDICT_GAP_FILLING


# ---------------------------------------------------------------------------
# Determinism contract -- same inputs always yield same outputs.
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_yield_identical_revision(self):
        tp = _touchpoint(
            new_label="Foo",
            existing_id="ontology_classes/Bar",
            combined_score=0.5,
            signals=_signals(label_fuzzy=0.5),
        )
        s = StructuralFeatures(existing_has_subclasses=True)
        rev_a = classify(tp, s)
        rev_b = classify(tp, s)
        # Frozen dataclasses with same fields compare equal.
        assert rev_a == rev_b
