"""Mechanical verdict classifier for the belief-revision pipeline (Stream 11 IBR.7).

Phase 2 of the four-phase Incremental Belief Revision (IBR) pipeline:
takes a :class:`~app.services.touchpoint_discovery.Touchpoint` (output of
Phase 1) plus optional :class:`StructuralFeatures` derived from the
existing ontology, and returns one :class:`MechanicalRevision` describing
the verdict, the action to take, and which rule fired.

This module is **deterministic and pure**. The same ``(touchpoint,
structural)`` inputs always produce the same output. All DB access lives
in the caller (IBR.10's LangGraph node), which is what lets the verdict
table below be tested against the ``Q.1``-``Q.3`` fixtures from
``docs/REMAINING_WORK_PLAN.md`` without standing up Arango.

Verdict / action contract
-------------------------

Every revision is one of six verdicts and one of five actions
(:mod:`app.db.revision_meta_repo` defines the constants). The mapping
this classifier produces:

| Verdict        | Action              | Auto-apply? | Typical trigger                     |
|----------------|---------------------|-------------|-------------------------------------|
| REINFORCED     | REINFORCE           | yes         | Already linked + new evidence       |
| REDUNDANT      | REVISE              | yes         | URI / label exact match (delegate   |
|                |                     |             | to ER for actual merge)             |
| GAP-FILLING    | GAP_FILL            | yes (high)  | Polymorphic-range usage OR property |
|                |                     |             | overlap >= 2 OR sibling pattern     |
| GAP-FILLING    | FLAG_FOR_CURATION   | no          | Same signals but combined score     |
|                |                     |             | below auto-apply threshold          |
| REFINED        | REVISE              | yes (high)  | (reserved for future R7 rules)      |
| REFINED        | FLAG_FOR_CURATION   | no          | Moderate naming signal, no          |
|                |                     |             | structural support                  |
| CONTRADICTED   | FLAG_FOR_CURATION   | **never**   | Direct contradiction evidence       |
|                |                     |             | (safety: never auto-retract)        |
| UNCERTAIN      | FLAG_FOR_CURATION   | no          | Co-classifier suffix OR signal      |
|                |                     |             | below threshold                     |

The ``auto_applicable`` property on :class:`MechanicalRevision` is true
exactly when ``action != FLAG_FOR_CURATION``. The downstream LangGraph
node uses this to decide which revisions go straight to the Levi-identity
supersede helper (IBR.9) and which get sent to Phase 3 (LLM agent,
IBR.8).

AGM / Levi identity mapping
---------------------------

The action-set encodes the AGM operators expressed via the Levi identity
(see ``docs/adr/008-belief-revision-substrate.md``):

* **Expansion** = GAP_FILL (add a belief that does not contradict any
  prior belief)
* **Contraction** = RETRACT (remove a belief; not produced mechanically
  -- requires LLM evidence-grounded justification, hence we map
  CONTRADICTED to FLAG_FOR_CURATION here)
* **Revision** = REVISE (contract the prior belief, then expand with a
  refined version; atomically performed via the supersede helper in
  IBR.9)

Co-classifier suffix list
-------------------------

Several name suffixes signal *related concept* rather than *subtype*
(e.g. ``AccountStatus`` is a vocabulary, not an Account subtype).
Mechanical classification refuses to propose ``subClassOf`` for these
and escalates to the LLM agent. Q.2c (`TransactionChannel`) and Q.3c
(`AccountStatus`, `MuleAccountActivity`) are the canonical negative
tests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

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
from app.services.touchpoint_discovery import Touchpoint

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunable thresholds (kept module-level so tests can monkeypatch + so a
# future operator console can expose them without code changes).
# ---------------------------------------------------------------------------

# Auto-apply gate: any GAP-FILLING / REFINED revision below this combined
# touchpoint score is downgraded to FLAG_FOR_CURATION even if structural
# signals are strong.
#
# Set to match touchpoint discovery's default threshold (0.30). The
# rationale: touchpoint discovery already filters out weak candidates,
# so the score floor here is a *belt-and-braces* check, not the primary
# precision filter -- the structural rules (polymorphic-range, shared-
# property, sibling-pattern) are. Note that GAP-FILLING touchpoints have
# uri_exact == label_exact == 0 by definition (the concepts are related,
# not identical), which caps their combined score around 0.45 even with
# maxed-out structural signals; setting this gate above ~0.4 would force
# every gap-filling revision to escalate, defeating the purpose of the
# pipeline.
AUTO_APPLY_SCORE_THRESHOLD = 0.30

# Label-fuzzy thresholds for GAP-FILLING via name signals alone.
LABEL_FUZZY_SUBTYPE_FLOOR = 0.50  # below this, naming alone cannot propose subtype
LABEL_FUZZY_REFINED_FLOOR = 0.40  # below this, no REFINED signal at all

# REDUNDANT-via-label gate. Same label, different URI is a "same concept"
# claim that can corrupt ontologies if wrong (the merge cascade is
# non-trivial), so we require a higher overall score than the auto-apply
# gate before we even propose REDUNDANT. This is intentionally NOT the
# auto-apply gate -- REDUNDANT is a different kind of claim than
# GAP-FILLING and deserves its own threshold.
REDUNDANT_LABEL_THRESHOLD = 0.55

# Below this combined score the verdict is UNCERTAIN regardless of
# structural signals (touchpoint discovery's own threshold is 0.30 so
# this should rarely fire in practice; defensive backstop).
LOW_SIGNAL_FLOOR = 0.30


# ---------------------------------------------------------------------------
# Stable rule ids (audit trail) -- one per code path that emits a revision.
# Keep these in sync with the docstring table.
# ---------------------------------------------------------------------------

RULE_R7_REINFORCED_LINKED = "R7_reinforced_already_linked"
RULE_R7_REDUNDANT_URI = "R7_redundant_uri_match"
RULE_R7_REDUNDANT_LABEL = "R7_redundant_label_match"
RULE_R7_GAP_POLYMORPHIC = "R7_gap_polymorphic_range"
RULE_R7_GAP_PROPERTY_OVERLAP = "R7_gap_shared_properties"
RULE_R7_GAP_SIBLING_PATTERN = "R7_gap_sibling_pattern"
RULE_R7_REFINED_NAMING = "R7_refined_naming_signal"
RULE_R7_UNCERTAIN_SUFFIX = "R7_uncertain_co_classifier_suffix"
RULE_R7_UNCERTAIN_LOW_SIGNAL = "R7_uncertain_low_signal"
RULE_R7_CONTRADICTED_DIRECT = "R7_contradicted_direct_evidence"


# ---------------------------------------------------------------------------
# Co-classifier suffixes (the Q.2c / Q.3c negative tests).
#
# Names ending in these tokens are *related concepts*, not subtypes.
# The mechanical classifier refuses to propose subClassOf and emits
# UNCERTAIN so the LLM agent (IBR.8) can decide what relationship --
# if any -- to propose instead. The list is intentionally conservative;
# adding a suffix here costs nothing (escalation is safe), removing one
# risks silent corruption of ontologies (escalation -> auto-apply of a
# wrong subClassOf).
# ---------------------------------------------------------------------------

CO_CLASSIFIER_SUFFIXES: tuple[str, ...] = (
    # Strong negatives (Q.2c, Q.3c, and general knowledge):
    "Status",     # AccountStatus, OrderStatus -- vocabulary/enum
    "Activity",   # MuleAccountActivity -- action observed on the entity
    "Channel",    # TransactionChannel -- modality/dimension
    "Code",       # CountryCode -- vocabulary
    "Role",       # CustomerRole -- relational role, not subtype
    "Category",   # ProductCategory -- classifier
    # Ambiguous (Q.2b -- TransactionDetail): could be subtype OR
    # composition. Always escalate so the LLM reads the source text.
    "Detail",
    "Profile",
    "Type",
    "Description",
)

# Pre-compile a single case-sensitive suffix regex for cheap matching.
# We deliberately match camel-case suffixes (e.g. "AccountStatus" not
# "account status") because the source labels in our extraction pipeline
# are PascalCase URIs / titlecase labels.
_SUFFIX_RE = re.compile(
    r"(" + "|".join(re.escape(s) for s in CO_CLASSIFIER_SUFFIXES) + r")$"
)


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuralFeatures:
    """DB-derived facts about the existing class that the touchpoint hits.

    Every field is optional; missing values default to "no signal" so
    the classifier remains correct when callers cannot or will not
    populate them. The IBR.10 LangGraph node populates these from the
    ontology graph; tests pass them directly.

    Attributes
    ----------
    is_already_linked:
        True iff the new concept is already attached to the existing
        class via ``subclass_of`` or ``equivalent_class``. Implies
        REINFORCED.
    polymorphic_range_count:
        Number of object properties on *other* classes that already
        use the existing class as a range AND would naturally accept
        the new concept (e.g. ``Alert.linked_transactions`` accepts
        both ``Transaction`` and ``ExtendedTransaction``). The Q.2a
        signal: strong evidence for GAP-FILLING(subClassOf).
    shared_property_names:
        Property labels (or normalised URIs) that exist on both the
        new concept and the existing class. >=2 is the Q.2a/Q.2b
        signal: the new concept reuses the parent's property set.
    existing_has_subclasses:
        True iff the existing class already has at least one
        ``subclass_of`` child. Combined with name-prefix overlap this
        is the Q.1/Q.3a sibling-pattern signal.
    contradiction_evidence:
        Human-readable strings describing direct contradictions
        (e.g. "new concept declared disjoint with existing class").
        Non-empty implies CONTRADICTED. The classifier never
        auto-retracts on this -- it always escalates.
    """

    is_already_linked: bool = False
    polymorphic_range_count: int = 0
    shared_property_names: tuple[str, ...] = ()
    existing_has_subclasses: bool = False
    contradiction_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class MechanicalRevision:
    """Verdict + action proposal for a single touchpoint.

    Created by :func:`classify`. The downstream node (IBR.10) calls
    :func:`auto_applicable` to decide whether to apply this directly
    via the Levi-identity helper (IBR.9) or escalate to Phase 3's LLM
    agent (IBR.8).
    """

    touchpoint: Touchpoint
    verdict: str
    action: str
    rule_id: str
    confidence: float
    reasoning: str

    @property
    def auto_applicable(self) -> bool:
        """True iff the action can be applied without LLM consultation.

        Equivalent to ``action != ACTION_FLAG_FOR_CURATION``. Kept as a
        method to centralise the contract -- if we ever introduce a new
        non-auto-applicable action, only this property changes.
        """
        return self.action != ACTION_FLAG_FOR_CURATION

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for logging / audit / API responses."""
        return {
            "verdict": self.verdict,
            "action": self.action,
            "rule_id": self.rule_id,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "auto_applicable": self.auto_applicable,
            "new_concept_label": self.touchpoint.new_concept_label,
            "existing_class_id": self.touchpoint.existing_class_id,
        }


@dataclass
class VerdictReport:
    """Aggregate output of :func:`classify_batch`.

    ``verdict_counts`` and ``action_counts`` mirror the buckets exposed
    by :mod:`app.services.belief_revision_metrics` so a single dict can
    be merged into the run-level metrics without further translation.
    """

    revisions: list[MechanicalRevision] = field(default_factory=list)
    verdict_counts: dict[str, int] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)

    @property
    def has_contested(self) -> bool:
        """True iff any verdict is CONTRADICTED or UNCERTAIN.

        The IBR.10 LangGraph node uses this to implement FR-11.15:
        skip Phase 3 (LLM agent) when no verdict is contested.
        """
        return self.verdict_counts.get(VERDICT_CONTRADICTED, 0) + self.verdict_counts.get(
            VERDICT_UNCERTAIN, 0
        ) > 0


# ---------------------------------------------------------------------------
# Pure label helpers
# ---------------------------------------------------------------------------


def label_co_classifier_suffix(label: str) -> str | None:
    """Return the matched co-classifier suffix or ``None``.

    Case-sensitive on purpose: ``AccountStatus`` matches but ``status``
    or ``account status`` do not, because the extraction pipeline
    consistently produces camel-case URIs. Lowercased free-text labels
    are intentionally *not* in scope -- those come from a different
    code path and have their own normalisation.

    Returns the suffix when one of :data:`CO_CLASSIFIER_SUFFIXES` ends
    the label AND the label has a non-empty prefix (so a label that is
    *only* a suffix, e.g. ``Status``, does not match -- a class actually
    called ``Status`` is fine to subClass).
    """
    if not label:
        return None
    m = _SUFFIX_RE.search(label)
    if m is None:
        return None
    suffix = m.group(1)
    if len(label) <= len(suffix):
        return None  # label is *only* the suffix (e.g. "Status")
    return suffix


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify(
    touchpoint: Touchpoint,
    structural: StructuralFeatures | None = None,
) -> MechanicalRevision:
    """Map a touchpoint (+ optional structural features) to a verdict + action.

    Pure function, deterministic. Order matters: rules are checked in
    priority sequence and the first match wins. Priority encodes the
    safety contract:

    1. ``CONTRADICTED`` first -- a contradiction overrides everything
       else and is *never* auto-applied.
    2. ``REINFORCED`` second -- if the link already exists, all other
       signals are noise.
    3. ``REDUNDANT`` third -- exact URI / label match dominates the
       "is this the same concept?" question; ER will handle the merge.
    4. ``UNCERTAIN`` (suffix) fourth -- co-classifier suffix is a
       *negative* test that prevents wrong subClassOf proposals
       regardless of how strong the score looks.
    5. ``GAP-FILLING`` (structural) fifth -- polymorphic-range or
       property-set overlap is the strongest positive signal short of
       a name-collision.
    6. ``GAP-FILLING`` (sibling pattern) sixth -- name prefix + an
       existing class with known subclasses (Q.1, Q.3a).
    7. ``REFINED`` seventh -- moderate naming signal without structural
       support; always escalates to the LLM agent.
    8. ``UNCERTAIN`` (low signal) last -- the safety net.

    Auto-applicability is gated separately by
    :data:`AUTO_APPLY_SCORE_THRESHOLD`. A high-priority verdict
    (``GAP_FILL``, ``REVISE``) downgrades to ``FLAG_FOR_CURATION`` when
    the touchpoint score is below the threshold, even if the structural
    rule fired. This protects against high-confidence rules firing on
    low-confidence touchpoints.
    """
    s = structural or StructuralFeatures()
    sig = touchpoint.signals
    score = touchpoint.combined_score

    # Rule 1 -- CONTRADICTED. Always escalates; never auto-retracts.
    if s.contradiction_evidence:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_CONTRADICTED,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id=RULE_R7_CONTRADICTED_DIRECT,
            confidence=score,
            reasoning=(
                "Direct contradiction with existing belief: "
                + "; ".join(s.contradiction_evidence)
            ),
        )

    # Rule 2 -- REINFORCED. The link already exists, the new evidence
    # confirms it. Always auto-applied (REINFORCE just bumps confidence
    # and appends evidence; nothing structural changes).
    if s.is_already_linked:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_REINFORCED,
            action=ACTION_REINFORCE,
            rule_id=RULE_R7_REINFORCED_LINKED,
            confidence=score,
            reasoning=(
                f"Already linked to {touchpoint.existing_class_label!r}; "
                f"new evidence reinforces (score={score:.2f})."
            ),
        )

    # Rule 3a -- REDUNDANT via URI exact match. Same URI = same concept.
    # Action is REVISE rather than dropped because ER may need to
    # reconcile the per-class metadata; ER then decides whether to
    # actually merge.
    if sig.uri_exact >= 0.99:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_REDUNDANT,
            action=ACTION_REVISE,
            rule_id=RULE_R7_REDUNDANT_URI,
            confidence=max(score, sig.uri_exact),
            reasoning=(
                "URI matches existing class exactly; same concept "
                "(delegating to ER)."
            ),
        )

    # Rule 3b -- REDUNDANT via normalised-label exact match. Slightly
    # weaker than URI match (different URIs with same label can be
    # legitimate), so we require a higher overall score before claiming
    # REDUNDANT and downgrade to UNCERTAIN if it's marginal. Uses its
    # own threshold (REDUNDANT_LABEL_THRESHOLD) rather than the GAP-
    # FILLING auto-apply gate -- this is a "same concept" call, not a
    # "related concept" call, and the bar should be much higher.
    if sig.label_exact >= 0.99 and score >= REDUNDANT_LABEL_THRESHOLD:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_REDUNDANT,
            action=ACTION_REVISE,
            rule_id=RULE_R7_REDUNDANT_LABEL,
            confidence=score,
            reasoning=(
                f"Normalised label matches existing class exactly "
                f"(score={score:.2f}); same concept (delegating to ER)."
            ),
        )

    # Rule 4 -- UNCERTAIN due to co-classifier suffix (Q.2c, Q.3c
    # negative tests). The label looks like a subtype but the suffix
    # tells us it's a *related* concept. Always escalate.
    #
    # Gate on ``label_fuzzy > 0`` rather than the REFINED floor: the
    # suffix is a *hard* guardrail. If there's ANY naming overlap (so
    # the touchpoint plausibly looks subtype-shaped), the suffix wins.
    # Without the lower gate, a polymorphic-range or property-overlap
    # rule could fire below us and silently emit GAP-FILLING for a
    # known co-classifier (e.g. ``MuleAccountActivity`` with shared
    # ``name`` / ``id`` properties).
    suffix = label_co_classifier_suffix(touchpoint.new_concept_label)
    if suffix is not None and sig.label_fuzzy > 0:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_UNCERTAIN,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id=RULE_R7_UNCERTAIN_SUFFIX,
            confidence=score,
            reasoning=(
                f"Label ends in co-classifier suffix {suffix!r}; this is "
                f"likely a related concept, not a subtype. Escalating to "
                f"LLM agent for relationship choice."
            ),
        )

    # Rule 5 -- GAP-FILLING from polymorphic-range usage (Q.2a).
    # Other classes already use the existing class as a range AND
    # would naturally accept the new concept; missing subClassOf is
    # the obvious explanation.
    if s.polymorphic_range_count >= 1 and sig.label_fuzzy > 0:
        action = (
            ACTION_GAP_FILL
            if score >= AUTO_APPLY_SCORE_THRESHOLD
            else ACTION_FLAG_FOR_CURATION
        )
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_GAP_FILLING,
            action=action,
            rule_id=RULE_R7_GAP_POLYMORPHIC,
            confidence=score,
            reasoning=(
                f"Polymorphic range usage: {s.polymorphic_range_count} "
                f"existing edge(s) treat the existing class as a range AND "
                f"would accept this new concept. Combined with label fuzzy "
                f"match ({sig.label_fuzzy:.2f}), this is gap-filling "
                f"(score={score:.2f})."
            ),
        )

    # Rule 6 -- GAP-FILLING from shared-property overlap (Q.2a, Q.2b).
    # The new concept reuses >=2 properties of the existing class, which
    # almost always means it's a subtype (or composition -- the LLM
    # decides on FLAG_FOR_CURATION cases).
    if len(s.shared_property_names) >= 2 and sig.label_fuzzy > 0:
        action = (
            ACTION_GAP_FILL
            if score >= AUTO_APPLY_SCORE_THRESHOLD
            else ACTION_FLAG_FOR_CURATION
        )
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_GAP_FILLING,
            action=action,
            rule_id=RULE_R7_GAP_PROPERTY_OVERLAP,
            confidence=score,
            reasoning=(
                f"Shares {len(s.shared_property_names)} property "
                f"name(s) with existing class "
                f"({', '.join(s.shared_property_names[:3])}). "
                f"Label fuzzy={sig.label_fuzzy:.2f}, score={score:.2f}."
            ),
        )

    # Rule 7 -- GAP-FILLING from sibling pattern (Q.1, Q.3a).
    # Label is a clear suffix/prefix of the existing class AND the
    # existing class already has subclasses, so the new concept slots
    # in as another sibling.
    if (
        sig.label_fuzzy >= LABEL_FUZZY_SUBTYPE_FLOOR
        and s.existing_has_subclasses
    ):
        action = (
            ACTION_GAP_FILL
            if score >= AUTO_APPLY_SCORE_THRESHOLD
            else ACTION_FLAG_FOR_CURATION
        )
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_GAP_FILLING,
            action=action,
            rule_id=RULE_R7_GAP_SIBLING_PATTERN,
            confidence=score,
            reasoning=(
                f"Label fuzzy match {sig.label_fuzzy:.2f} indicates subtype "
                f"naming; existing class already has subclasses (sibling "
                f"pattern). Score={score:.2f}."
            ),
        )

    # Rule 8 -- REFINED from naming signal alone (no structural
    # support). Always escalates to LLM; never auto-applied.
    if sig.label_fuzzy >= LABEL_FUZZY_REFINED_FLOOR:
        return MechanicalRevision(
            touchpoint=touchpoint,
            verdict=VERDICT_REFINED,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id=RULE_R7_REFINED_NAMING,
            confidence=score,
            reasoning=(
                f"Naming signal (label fuzzy={sig.label_fuzzy:.2f}) "
                f"without structural support; escalating to LLM agent."
            ),
        )

    # Rule 9 -- UNCERTAIN backstop. Below all signal floors.
    return MechanicalRevision(
        touchpoint=touchpoint,
        verdict=VERDICT_UNCERTAIN,
        action=ACTION_FLAG_FOR_CURATION,
        rule_id=RULE_R7_UNCERTAIN_LOW_SIGNAL,
        confidence=score,
        reasoning=(
            f"Combined score {score:.2f} below all rule thresholds; "
            f"insufficient signal to act mechanically."
        ),
    )


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------


def classify_batch(
    touchpoints: list[Touchpoint],
    structural_lookup: dict[str, StructuralFeatures] | None = None,
) -> VerdictReport:
    """Classify a list of touchpoints, aggregating verdict / action counts.

    Parameters
    ----------
    touchpoints:
        Output of :func:`app.services.touchpoint_discovery.discover_touchpoints`.
    structural_lookup:
        Optional ``{existing_class_id: StructuralFeatures}`` map. When
        provided, the structural features for each touchpoint's existing
        class are merged into the classification. Missing entries fall
        back to default ``StructuralFeatures()`` -- no signal.

    Returns
    -------
    VerdictReport
        ``revisions`` is in the same order as the input. The
        ``verdict_counts`` / ``action_counts`` dicts are pre-filled
        with zeros for every constant so downstream metrics consumers
        get a stable shape.
    """
    # Pre-fill counts so consumers always see all buckets.
    verdict_counts = {
        v: 0
        for v in (
            VERDICT_REINFORCED,
            VERDICT_REFINED,
            VERDICT_GAP_FILLING,
            VERDICT_REDUNDANT,
            VERDICT_CONTRADICTED,
            VERDICT_UNCERTAIN,
        )
    }
    action_counts = {
        a: 0
        for a in (
            ACTION_REINFORCE,
            ACTION_REVISE,
            ACTION_GAP_FILL,
            ACTION_FLAG_FOR_CURATION,
        )
    }

    revisions: list[MechanicalRevision] = []
    lookup = structural_lookup or {}
    for tp in touchpoints:
        rev = classify(tp, lookup.get(tp.existing_class_id))
        revisions.append(rev)
        verdict_counts[rev.verdict] = verdict_counts.get(rev.verdict, 0) + 1
        action_counts[rev.action] = action_counts.get(rev.action, 0) + 1

    log.info(
        "revision_verdict: classified %d touchpoint(s); verdicts=%s actions=%s",
        len(revisions),
        verdict_counts,
        action_counts,
    )
    return VerdictReport(
        revisions=revisions,
        verdict_counts=verdict_counts,
        action_counts=action_counts,
    )
