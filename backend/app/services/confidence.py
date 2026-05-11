"""Multi-signal confidence scoring for extracted ontology classes.

Blends nine independent signals into a single [0, 1] confidence score
(PRD §6.13.1; weights rescaled in Stream 11 IBR.2 to make room for
two evidence-aware signals that the belief-revision pipeline will
read):

  1. Cross-pass agreement       (weight 0.18)
  2. Faithfulness (LLM judge)   (weight 0.18)
  3. Semantic validity          (weight 0.13)
  4. Structural quality         (weight 0.13)
  5. Description quality        (weight 0.09)
  6. Provenance strength        (weight 0.09)
  7. Property agreement         (weight 0.09)
  8. Evidence count             (weight 0.06)  -- NEW
  9. Evidence age (recency)     (weight 0.05)  -- NEW

Signals 8 and 9 default to a neutral-positive score (1.0) when the
caller does not provide them, so legacy callers see a near-identical
score (back-compat). Phase 2 of belief revision will start passing
real values, and the consolidation job (IBR.3) layers a confidence-
decay function on top of signal 9.
"""

from __future__ import annotations

import math
from itertools import combinations

# Weights sum to 1.0; verified by ``test_weights_sum_to_one``.
WEIGHT_AGREEMENT = 0.18
WEIGHT_FAITHFULNESS = 0.18
WEIGHT_SEMANTIC_VALIDITY = 0.13
WEIGHT_STRUCTURAL = 0.13
WEIGHT_DESCRIPTION = 0.09
WEIGHT_PROVENANCE = 0.09
WEIGHT_PROPERTY_AGREEMENT = 0.09
WEIGHT_EVIDENCE_COUNT = 0.06
WEIGHT_EVIDENCE_AGE = 0.05

# Default half-life for the evidence-age signal: 90 days. Tuned for
# semi-stable knowledge graphs (corporate ontologies, regulatory KGs)
# where a fact ~3 months old is still credible but starts to drift.
# Override via the ``half_life_days`` arg on ``_evidence_age_score``
# when calling from the consolidation job for a more aggressive decay.
DEFAULT_EVIDENCE_HALF_LIFE_DAYS = 90.0

# Above this many distinct evidence quotes, the evidence-count signal
# saturates at 1.0. Five is the empirical "well-corroborated" mark
# from spot-checking the demo ontologies; keep it tunable as the
# corpus grows.
EVIDENCE_COUNT_SATURATION = 5


def _structural_score(
    datatype_property_count: int = 0,
    object_property_count: int = 0,
    has_parent: bool = False,
    has_children: bool = False,
    has_lateral_edges: bool = False,
) -> float:
    """Score in [0, 1] based on graph connectivity of the class.

    Differentiates between datatype properties (basic data modelling)
    and object properties (lateral connections — most valuable).
    """
    score = 0.0
    if datatype_property_count > 0:
        score += 0.15
    if object_property_count > 0:
        score += min(object_property_count * 0.10, 0.30)
    if has_parent:
        score += 0.20
    if has_children:
        score += 0.15
    if has_lateral_edges:
        score += 0.20
    return min(score, 1.0)


def _property_agreement_score(
    property_uris_per_pass: list[set[str]],
) -> float:
    """Jaccard similarity of property URIs across passes.

    Returns 1.0 when only a single pass exists (no comparison possible).
    For multiple passes, computes pairwise Jaccard and averages.
    """
    if len(property_uris_per_pass) < 2:
        return 1.0

    jaccard_values: list[float] = []
    for a, b in combinations(property_uris_per_pass, 2):
        union = a | b
        if not union:
            jaccard_values.append(1.0)
        else:
            jaccard_values.append(len(a & b) / len(union))

    return sum(jaccard_values) / len(jaccard_values) if jaccard_values else 1.0


def _description_score(
    description: str,
    all_descriptions: list[str],
) -> float:
    """Score in [0, 1] based on description length and uniqueness.

    A description is considered non-unique when it is very short (<20 chars)
    or when an identical copy exists among the other class descriptions.
    """
    length_score = min(len(description) / 100, 1.0) * 0.7

    is_duplicate = False
    if len(description) < 20:
        is_duplicate = True
    else:
        seen_self = False
        for other in all_descriptions:
            if other == description:
                if not seen_self:
                    seen_self = True
                    continue
                is_duplicate = True
                break
    uniqueness = 0.0 if is_duplicate else 1.0

    return length_score + uniqueness * 0.3


def _provenance_score(provenance_count: int) -> float:
    """Score in [0, 1] based on how many source chunks support this class."""
    return min(provenance_count / 3, 1.0)


def _evidence_count_score(count: int | None) -> float:
    """Score in [0, 1] based on the number of distinct evidence quotes.

    Distinct from :func:`_provenance_score`: provenance counts *chunks*
    (sources), evidence counts *quotes* (textual support recorded on
    the class). Strongly correlated in practice but not identical --
    a class can be mentioned in five chunks while only one of them
    yielded a citable quote.

    ``None`` (the back-compat default) returns 1.0 so legacy callers
    are not retroactively penalised. Explicit ``0`` returns ``0.0``.
    Linear ramp to ``EVIDENCE_COUNT_SATURATION`` quotes.
    """
    if count is None:
        return 1.0
    if count <= 0:
        return 0.0
    return min(count / EVIDENCE_COUNT_SATURATION, 1.0)


def _evidence_age_score(
    age_seconds: float | None,
    *,
    half_life_days: float = DEFAULT_EVIDENCE_HALF_LIFE_DAYS,
) -> float:
    """Exponential-decay score in [0, 1] from the most recent evidence age.

    ``age_seconds=0`` (just observed) returns 1.0. After one
    ``half_life_days`` the score has halved (~0.5); after two half-
    lives ~0.25; etc. Negative ages are clamped to 0 (treat
    future-dated evidence as fresh).

    ``None`` (back-compat default) returns 1.0 so legacy callers see
    no change. ``half_life_days`` is overridable for the consolidation
    job (IBR.3) which may want a faster decay for low-confidence beliefs.
    """
    if age_seconds is None:
        return 1.0
    if age_seconds <= 0:
        return 1.0
    half_life_seconds = max(half_life_days * 86400.0, 1.0)
    # exp(-age/half_life * ln(2)) gives the standard half-life curve.
    return math.exp(-age_seconds * math.log(2) / half_life_seconds)


def compute_class_confidence(
    agreement_ratio: float,
    faithfulness: float = 0.5,
    semantic_validity: float = 0.5,
    datatype_property_count: int = 0,
    object_property_count: int = 0,
    has_parent: bool = False,
    has_children: bool = False,
    has_lateral_edges: bool = False,
    description: str = "",
    all_descriptions: list[str] | None = None,
    provenance_count: int = 0,
    property_agreement: float = 1.0,
    *,
    llm_confidence: float | None = None,
    has_properties: bool | None = None,
    evidence_count: int | None = None,
    evidence_age_seconds: float | None = None,
    evidence_half_life_days: float = DEFAULT_EVIDENCE_HALF_LIFE_DAYS,
) -> float:
    """Compute blended multi-signal confidence for one ontology class.

    Parameters
    ----------
    agreement_ratio:
        Fraction of extraction passes in which this class appeared (0-1).
    faithfulness:
        LLM-judge faithfulness score (0-1).
    semantic_validity:
        Semantic validator score (0-1).
    datatype_property_count:
        Number of owl:DatatypeProperty instances on this class.
    object_property_count:
        Number of owl:ObjectProperty instances (lateral connections).
    has_parent:
        Whether a subclass_of edge exists FROM this class.
    has_children:
        Whether a subclass_of edge exists TO this class.
    has_lateral_edges:
        Whether rdfs_range_class or extends_domain edges connect this class.
    description:
        The merged class description text.
    all_descriptions:
        Descriptions of *all* classes in the same ontology (for uniqueness check).
    provenance_count:
        Number of distinct source documents/chunks that produced this class.
    property_agreement:
        Cross-pass Jaccard similarity for this class's property URIs (0-1).
    llm_confidence:
        **Deprecated** — mapped to *faithfulness* for backward compatibility.
        When provided and *faithfulness* is at its default, this value is used
        as the faithfulness signal.
    has_properties:
        **Deprecated** — ignored when property counts are provided.
        When provided and both counts are zero, treated as 1 datatype property.
    evidence_count:
        Number of distinct evidence quotes recorded on this class.
        ``None`` (default) skips the signal as 1.0 for back-compat;
        explicit ``0`` scores 0.0.
    evidence_age_seconds:
        Age of the most recent evidence quote, in seconds. ``None``
        (default) skips the signal as 1.0 for back-compat. Used by
        the belief-revision consolidation job to decay stale beliefs.
    evidence_half_life_days:
        Override the default 90-day half-life for the evidence-age
        decay; rarely needed outside the consolidation job.

    Returns
    -------
    float in [0, 1] — the composite confidence score, rounded to 3 decimals.
    """
    # Backward-compatibility shims
    if llm_confidence is not None and faithfulness == 0.5:
        faithfulness = llm_confidence
    if (
        has_properties is not None
        and datatype_property_count == 0
        and object_property_count == 0
        and has_properties
    ):
        datatype_property_count = 1

    if all_descriptions is None:
        all_descriptions = []

    s_structural = _structural_score(
        datatype_property_count=datatype_property_count,
        object_property_count=object_property_count,
        has_parent=has_parent,
        has_children=has_children,
        has_lateral_edges=has_lateral_edges,
    )
    s_description = _description_score(description, all_descriptions)
    s_provenance = _provenance_score(provenance_count)
    s_evidence_count = _evidence_count_score(evidence_count)
    s_evidence_age = _evidence_age_score(
        evidence_age_seconds,
        half_life_days=evidence_half_life_days,
    )

    blended = (
        WEIGHT_AGREEMENT * agreement_ratio
        + WEIGHT_FAITHFULNESS * faithfulness
        + WEIGHT_SEMANTIC_VALIDITY * semantic_validity
        + WEIGHT_STRUCTURAL * s_structural
        + WEIGHT_DESCRIPTION * s_description
        + WEIGHT_PROVENANCE * s_provenance
        + WEIGHT_PROPERTY_AGREEMENT * property_agreement
        + WEIGHT_EVIDENCE_COUNT * s_evidence_count
        + WEIGHT_EVIDENCE_AGE * s_evidence_age
    )
    return round(max(0.0, min(1.0, blended)), 3)
