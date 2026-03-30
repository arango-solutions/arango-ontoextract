"""Multi-signal confidence scoring for extracted ontology classes.

Blends seven independent signals into a single [0, 1] confidence score:
  1. Cross-pass agreement       (weight 0.20)
  2. Faithfulness (LLM judge)   (weight 0.20)
  3. Semantic validity           (weight 0.15)
  4. Structural quality          (weight 0.15)
  5. Description quality         (weight 0.10)
  6. Provenance strength         (weight 0.10)
  7. Property agreement          (weight 0.10)
"""

from __future__ import annotations

from itertools import combinations

WEIGHT_AGREEMENT = 0.20
WEIGHT_FAITHFULNESS = 0.20
WEIGHT_SEMANTIC_VALIDITY = 0.15
WEIGHT_STRUCTURAL = 0.15
WEIGHT_DESCRIPTION = 0.10
WEIGHT_PROVENANCE = 0.10
WEIGHT_PROPERTY_AGREEMENT = 0.10


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
) -> float:
    """Compute blended multi-signal confidence for one ontology class.

    Parameters
    ----------
    agreement_ratio:
        Fraction of extraction passes in which this class appeared (0–1).
    faithfulness:
        LLM-judge faithfulness score (0–1).
    semantic_validity:
        Semantic validator score (0–1).
    datatype_property_count:
        Number of owl:DatatypeProperty instances on this class.
    object_property_count:
        Number of owl:ObjectProperty instances (lateral connections).
    has_parent:
        Whether a subclass_of edge exists FROM this class.
    has_children:
        Whether a subclass_of edge exists TO this class.
    has_lateral_edges:
        Whether related_to or extends_domain edges exist.
    description:
        The merged class description text.
    all_descriptions:
        Descriptions of *all* classes in the same ontology (for uniqueness check).
    provenance_count:
        Number of distinct source documents/chunks that produced this class.
    property_agreement:
        Cross-pass Jaccard similarity for this class's property URIs (0–1).
    llm_confidence:
        **Deprecated** — mapped to *faithfulness* for backward compatibility.
        When provided and *faithfulness* is at its default, this value is used
        as the faithfulness signal.
    has_properties:
        **Deprecated** — ignored when property counts are provided.
        When provided and both counts are zero, treated as 1 datatype property.

    Returns
    -------
    float in [0, 1] — the composite confidence score, rounded to 3 decimals.
    """
    # Backward-compatibility shims
    if llm_confidence is not None and faithfulness == 0.5:
        faithfulness = llm_confidence
    if has_properties is not None and datatype_property_count == 0 and object_property_count == 0:
        if has_properties:
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

    blended = (
        WEIGHT_AGREEMENT * agreement_ratio
        + WEIGHT_FAITHFULNESS * faithfulness
        + WEIGHT_SEMANTIC_VALIDITY * semantic_validity
        + WEIGHT_STRUCTURAL * s_structural
        + WEIGHT_DESCRIPTION * s_description
        + WEIGHT_PROVENANCE * s_provenance
        + WEIGHT_PROPERTY_AGREEMENT * property_agreement
    )
    return round(max(0.0, min(1.0, blended)), 3)
