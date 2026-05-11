"""Touchpoint discovery for the belief-revision pipeline (Stream 11 IBR.5).

Given the freshly-extracted concepts from a new document, find every
existing ontology class that the new concept *might* be about. Each
``(new_concept, existing_class)`` pair is a *touchpoint* and Phase 2's
mechanical classifier turns the touchpoint signals into a verdict
(REINFORCED / REFINED / GAP-FILLING / REDUNDANT / CONTRADICTED /
UNCERTAIN -- see :mod:`app.db.revision_meta_repo`).

Signal contract
---------------

Four cheap deterministic signals plus one optional semantic signal:

* ``uri_exact``     -- URIs match byte-for-byte; 1.0 when equal.
* ``label_exact``   -- Normalised labels match (case + punct insensitive).
* ``label_fuzzy``   -- Substring containment between normalised labels;
  ratio of shorter-to-longer length when one contains the other.
* ``chunk_overlap`` -- Jaccard over ``extracted_from`` chunk IDs;
  1.0 when the same chunks support both.
* ``embedding_sim`` -- Cosine similarity of the two embedding vectors
  (optional; ``None`` when either side is missing).

When ``embedding_sim`` cannot be computed (no embedding on the new
concept, no embedding on the existing class, or vector lengths
differ), the signal is treated as *absent* and the remaining weights
are renormalised to sum to 1.0. Absent != 0 -- a missing signal must
not punish the touchpoint.

Scaling note
------------

Phase 1 implementation is O(N_new * N_existing) per call -- fine for
the demo ontologies (~100 classes). When ontologies grow into the
thousands, swap the per-pair scan for an ArangoSearch view (label /
chunk) plus the existing Faiss IVF (embedding); the
:func:`discover_touchpoints` signature does not change.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.edge_repair import _normalise

log = logging.getLogger(__name__)


# Weights for each signal. Sum to 1.0; renormalised by the blender
# whenever a signal is absent (e.g. ``embedding_sim is None``).
WEIGHT_URI_EXACT = 0.30
WEIGHT_LABEL_EXACT = 0.25
WEIGHT_LABEL_FUZZY = 0.15
WEIGHT_CHUNK_OVERLAP = 0.15
WEIGHT_EMBEDDING_SIM = 0.15

# Default cutoff: pairs scoring below this are dropped from the result.
# Tuned to surface "plausibly the same concept" without flooding the
# Phase 2 classifier; raise to 0.5+ for high-precision audits.
DEFAULT_TOUCHPOINT_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Input / output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewConcept:
    """Single newly-extracted concept fed into touchpoint discovery."""

    label: str
    uri: str | None = None
    chunk_ids: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class TouchpointSignals:
    uri_exact: float
    label_exact: float
    label_fuzzy: float
    chunk_overlap: float
    embedding_sim: float | None


@dataclass(frozen=True)
class Touchpoint:
    new_concept_label: str
    new_concept_uri: str | None
    existing_class_id: str
    existing_class_label: str
    signals: TouchpointSignals
    combined_score: float
    reasoning: str


@dataclass
class TouchpointReport:
    ontology_id: str
    new_concept_count: int
    candidates_examined: int  # total (new x existing) pairs scored
    touchpoints: list[Touchpoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ontology_id": self.ontology_id,
            "new_concept_count": self.new_concept_count,
            "candidates_examined": self.candidates_examined,
            "touchpoint_count": len(self.touchpoints),
            "touchpoints": [
                {
                    "new_concept_label": t.new_concept_label,
                    "new_concept_uri": t.new_concept_uri,
                    "existing_class_id": t.existing_class_id,
                    "existing_class_label": t.existing_class_label,
                    "signals": asdict(t.signals),
                    "combined_score": t.combined_score,
                    "reasoning": t.reasoning,
                }
                for t in self.touchpoints
            ],
        }


# ---------------------------------------------------------------------------
# Pure signal helpers
# ---------------------------------------------------------------------------


def _label_fuzzy_score(a: str, b: str) -> float:
    """Substring-containment score in [0, 1] over normalised labels.

    Returns ``len(shorter) / len(longer)`` when one normalised string
    contains the other; ``0.0`` otherwise. Ranks longer overlaps higher
    so ``CustomerRiskProfile`` ⊂ ``CustomerRiskProfile`` scores 1.0
    while ``Risk`` ⊂ ``CustomerRiskProfile`` scores 4 / 19 ≈ 0.21.
    """
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb:
        return len(na) / len(nb)
    if nb in na:
        return len(nb) / len(na)
    return 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity; both empty -> 0 (no signal, not a perfect match)."""
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float | None:
    """Cosine similarity in [-1, 1] -> clamped to [0, 1]; None on shape mismatch."""
    if len(a) != len(b) or not a:
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _blend(signals: TouchpointSignals) -> float:
    """Renormalising weighted blend; missing embedding rescales the rest."""
    weights = {
        "uri_exact": WEIGHT_URI_EXACT,
        "label_exact": WEIGHT_LABEL_EXACT,
        "label_fuzzy": WEIGHT_LABEL_FUZZY,
        "chunk_overlap": WEIGHT_CHUNK_OVERLAP,
    }
    values = {
        "uri_exact": signals.uri_exact,
        "label_exact": signals.label_exact,
        "label_fuzzy": signals.label_fuzzy,
        "chunk_overlap": signals.chunk_overlap,
    }
    if signals.embedding_sim is not None:
        weights["embedding_sim"] = WEIGHT_EMBEDDING_SIM
        values["embedding_sim"] = signals.embedding_sim
    total_weight = sum(weights.values()) or 1.0
    return round(
        sum(weights[k] * values[k] for k in weights) / total_weight,
        4,
    )


def _reasoning(signals: TouchpointSignals) -> str:
    """Human-readable why-this-matched -- joins the active signals."""
    parts: list[str] = []
    if signals.uri_exact > 0:
        parts.append("URI matches exactly")
    if signals.label_exact > 0:
        parts.append("label matches exactly")
    if 0 < signals.label_fuzzy < 1:
        parts.append(f"label fuzzy match ({signals.label_fuzzy:.2f})")
    if signals.chunk_overlap > 0:
        parts.append(f"shared evidence chunks ({signals.chunk_overlap:.2f} Jaccard)")
    if signals.embedding_sim is not None and signals.embedding_sim > 0:
        parts.append(f"embedding cosine {signals.embedding_sim:.2f}")
    return "; ".join(parts) if parts else "no specific signals fired"


# ---------------------------------------------------------------------------
# Per-pair scorer (pure)
# ---------------------------------------------------------------------------


def score_touchpoint(new: NewConcept, existing: dict[str, Any]) -> Touchpoint | None:
    """Score one (new_concept, existing_class) pair.

    Returns ``None`` when no class id is resolvable on the existing
    document; otherwise always returns a Touchpoint (even if combined
    score is 0). The caller filters by threshold.
    """
    existing_id = existing.get("_id")
    if not isinstance(existing_id, str):
        return None
    existing_label = str(existing.get("label") or existing.get("_key") or "")
    existing_uri = existing.get("uri")
    existing_chunks = existing.get("source_chunk_ids") or existing.get("chunk_ids") or []
    existing_emb = existing.get("embedding")

    uri_exact = (
        1.0 if (new.uri and existing_uri and new.uri == existing_uri) else 0.0
    )
    label_exact = (
        1.0
        if (new.label and existing_label and _normalise(new.label) == _normalise(existing_label))
        else 0.0
    )
    label_fuzzy = _label_fuzzy_score(new.label, existing_label)
    chunk_overlap = _jaccard(set(new.chunk_ids), set(existing_chunks))

    embedding_sim: float | None = None
    if new.embedding is not None and existing_emb is not None:
        try:
            embedding_sim = _cosine(tuple(new.embedding), tuple(existing_emb))
        except TypeError:
            embedding_sim = None

    signals = TouchpointSignals(
        uri_exact=uri_exact,
        label_exact=label_exact,
        label_fuzzy=label_fuzzy,
        chunk_overlap=chunk_overlap,
        embedding_sim=embedding_sim,
    )
    return Touchpoint(
        new_concept_label=new.label,
        new_concept_uri=new.uri,
        existing_class_id=existing_id,
        existing_class_label=existing_label,
        signals=signals,
        combined_score=_blend(signals),
        reasoning=_reasoning(signals),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def discover_touchpoints(
    db: Any,
    ontology_id: str,
    new_concepts: list[NewConcept],
    *,
    threshold: float = DEFAULT_TOUCHPOINT_THRESHOLD,
    limit_per_concept: int | None = None,
) -> TouchpointReport:
    """Find every plausible touchpoint between new concepts and existing classes.

    Parameters
    ----------
    db, ontology_id:
        Standard.
    new_concepts:
        Output of the latest extraction pass. Each one is compared
        against every live class in ``ontology_id``.
    threshold:
        Drop pairs whose ``combined_score`` is below this value.
        Default 0.30; tune higher for high-precision audits.
    limit_per_concept:
        Optional cap on touchpoints returned per new concept (after
        threshold). Useful when the caller wants only the top-K
        candidates per concept for the Phase 2 classifier.

    Returns
    -------
    TouchpointReport
        Always populated. Empty ``touchpoints`` when the ontology has
        no live classes or every pair is below threshold.
    """
    report = TouchpointReport(
        ontology_id=ontology_id,
        new_concept_count=len(new_concepts),
        candidates_examined=0,
    )

    if not new_concepts:
        return report
    if not db.has_collection("ontology_classes"):
        log.info(
            "touchpoint_discovery: ontology_classes missing -- nothing to compare against"
        )
        return report

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    existing_classes = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "RETURN c",
            bind_vars=bind,
        )
    )

    for new in new_concepts:
        scored: list[Touchpoint] = []
        for existing in existing_classes:
            report.candidates_examined += 1
            tp = score_touchpoint(new, existing)
            if tp is None:
                continue
            if tp.combined_score < threshold:
                continue
            scored.append(tp)
        scored.sort(key=lambda t: t.combined_score, reverse=True)
        if limit_per_concept is not None:
            scored = scored[:limit_per_concept]
        report.touchpoints.extend(scored)

    log.info(
        "touchpoint_discovery: ontology=%s new_concepts=%d examined=%d "
        "touchpoints=%d (threshold=%.2f)",
        ontology_id,
        report.new_concept_count,
        report.candidates_examined,
        len(report.touchpoints),
        threshold,
    )
    return report
