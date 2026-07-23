"""Alignment evaluation metrics (Stream 20 / AL-PR9, PRD §6.17 FR-17.11).

Reusable, DB-free metric functions for scoring a produced alignment against a
reference (gold) alignment and for reporting human-effort efficiency:

* :func:`prf1` — precision / recall / F1 of a predicted correspondence set vs a
  reference set.
* :func:`interaction_curve` — the OAEI-Interactive / DualLoop curve: high-confidence
  candidates auto-accept with zero interactions, then a human oracle confirms the
  borderline candidates in ranked order; F1 is recorded after each confirmation, so
  the curve shows how quickly quality rises per unit of human effort.
* :func:`interactions_to_target` — the headline efficiency number: how many human
  confirmations are needed to reach a target F1.

Correspondences are compared as *normalized pairs* — a frozen, order-independent
``((ontology_id, entity_key), (ontology_id, entity_key))`` — so A↔B and B↔A match.
The heavy benchmark runner + seeded fixture live in
``benchmarks/operations/bench_alignment.py``, which imports these functions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

Node = tuple[str, str]  # (ontology_id, entity_key)
Pair = tuple[Node, Node]  # normalized: the two nodes sorted


def norm_pair(a_oid: Any, a_key: Any, b_oid: Any, b_key: Any) -> Pair:
    """Order-independent correspondence pair key."""
    a: Node = (str(a_oid), str(a_key))
    b: Node = (str(b_oid), str(b_key))
    return (a, b) if a <= b else (b, a)


def pair_from_correspondence(c: Mapping[str, Any]) -> Pair:
    """Normalize a correspondence dict (``source_a``/``source_b``) to a pair key."""
    a = c.get("source_a") or {}
    b = c.get("source_b") or {}
    return norm_pair(
        a.get("ontology_id"), a.get("entity_key"), b.get("ontology_id"), b.get("entity_key")
    )


def prf1(predicted: set[Pair], reference: set[Pair]) -> dict[str, Any]:
    """Precision / recall / F1 of ``predicted`` vs ``reference`` (plus tp/fp/fn)."""
    tp = len(predicted & reference)
    fp = len(predicted - reference)
    fn = len(reference - predicted)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def interaction_curve(
    candidates: Iterable[Mapping[str, Any]],
    reference: set[Pair],
    *,
    auto_accept_band: float,
    priority_key: Callable[[Mapping[str, Any]], Any] | None = None,
) -> list[dict[str, Any]]:
    """OAEI-Interactive interaction-count-vs-F-measure curve.

    Each candidate is a mapping with a ``pair`` (normalized) and a ``confidence``.
    Candidates at/above ``auto_accept_band`` enter the alignment with **zero**
    interactions (trusted — false positives among them persist, dragging
    precision, exactly as in a real interactive run). The rest are presented to a
    human oracle in ranked order (default: confidence descending); each
    presentation is one interaction, and a candidate is added iff its pair is in
    the reference (the oracle accepts true matches, rejects the rest). F1 is
    recorded after every interaction.

    Returns ``[{interactions, precision, recall, f1, tp, fp, fn}, ...]`` starting
    at ``interactions == 0`` (auto-accept baseline).
    """
    cands = list(candidates)
    auto = [c for c in cands if float(c["confidence"]) >= auto_accept_band]
    borderline = [c for c in cands if float(c["confidence"]) < auto_accept_band]
    borderline.sort(key=priority_key or (lambda c: -float(c["confidence"])))

    aligned: set[Pair] = {c["pair"] for c in auto}
    curve: list[dict[str, Any]] = [{"interactions": 0, **prf1(aligned, reference)}]
    for i, c in enumerate(borderline, start=1):
        if c["pair"] in reference:  # oracle confirms a true match
            aligned.add(c["pair"])
        curve.append({"interactions": i, **prf1(aligned, reference)})
    return curve


def interactions_to_target(curve: list[dict[str, Any]], target_f1: float) -> int | None:
    """Fewest interactions at which F1 first reaches ``target_f1`` (``None`` if never)."""
    for point in curve:
        if point["f1"] >= target_f1:
            return int(point["interactions"])
    return None
