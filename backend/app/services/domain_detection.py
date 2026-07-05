"""Domain-detection helpers (Stream 16 DD.2 / DD.3).

Pure functions that turn the ``domain_segments`` produced by the
``domain_segmenter`` pipeline node into:

* ``detected_domains`` -- the distinct topical domains in a run (DD.2),
* per-class ``domain_tag`` stamping via evidence chunk-id mapping (DD.2),
* a non-blocking ``multi_domain`` run warning (DD.3).

Kept free of any LLM / DB / pipeline-state coupling so they are trivially
unit-testable and reusable by both ``execute_run`` and future Option-C
"split by domain" routing (DD.4).
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _segment_domain(segment: dict[str, Any]) -> str:
    return str(segment.get("domain") or "").strip()


def _segment_chunk_ids(segment: dict[str, Any]) -> list[str]:
    return [str(c) for c in (segment.get("chunk_ids") or [])]


def _segment_confidence(segment: dict[str, Any]) -> float:
    try:
        return float(segment.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0


def domain_chunk_counts(segments: list[dict[str, Any]]) -> dict[str, int]:
    """Total chunk count per domain name across all segments."""
    counts: Counter[str] = Counter()
    for seg in segments:
        domain = _segment_domain(seg)
        if not domain:
            continue
        counts[domain] += len(_segment_chunk_ids(seg))
    return dict(counts)


def dominant_domain(
    segments: list[dict[str, Any]],
    candidates: list[str] | None = None,
) -> str | None:
    """Return the domain with the most chunks (deterministic tiebreak).

    When ``candidates`` is given, only those domain names are considered.
    Ties are broken by higher aggregate confidence, then by domain name
    (ascending) so the result is stable across runs.
    """
    per_domain_chunks = domain_chunk_counts(segments)
    per_domain_conf: dict[str, float] = {}
    for seg in segments:
        domain = _segment_domain(seg)
        if not domain:
            continue
        per_domain_conf[domain] = per_domain_conf.get(domain, 0.0) + _segment_confidence(seg)

    names = [n for n in per_domain_chunks if candidates is None or n in candidates]
    if not names:
        return None
    # max on (chunks, confidence) then min on name for the tiebreak: negate
    # the name by sorting so the smallest name wins on a full tie.
    return max(
        sorted(names),
        key=lambda n: (per_domain_chunks.get(n, 0), per_domain_conf.get(n, 0.0)),
    )


def detected_domains_from_segments(
    segments: list[dict[str, Any]],
    min_confidence: float,
) -> list[str]:
    """Distinct topical domains for a run (DD.2), sorted for stability.

    A domain counts as distinct only when it has at least one chunk and a
    segment confidence at or above ``min_confidence`` -- this keeps a single
    low-signal chunk from spuriously creating a second domain. When nothing
    clears the bar, the run collapses to its single dominant domain rather
    than reporting zero.
    """
    qualifying = {
        _segment_domain(s)
        for s in segments
        if _segment_domain(s) and _segment_chunk_ids(s) and _segment_confidence(s) >= min_confidence
    }
    if qualifying:
        return sorted(qualifying)
    dom = dominant_domain(segments)
    return [dom] if dom else []


def build_chunk_domain_map(
    segments: list[dict[str, Any]],
    allowed_domains: set[str],
    fallback_domain: str,
) -> dict[str, str]:
    """Map each chunk id to its effective domain.

    Chunks whose raw segment domain did not clear the detection bar (i.e.
    not in ``allowed_domains``) are remapped to ``fallback_domain`` so a
    class citing such a chunk still receives a coherent, reportable tag.
    """
    mapping: dict[str, str] = {}
    for seg in segments:
        raw = _segment_domain(seg)
        effective = raw if raw in allowed_domains else fallback_domain
        for chunk_id in _segment_chunk_ids(seg):
            mapping[chunk_id] = effective
    return mapping


def _evidence_chunk_ids(entry: Any) -> list[str]:
    if isinstance(entry, dict):
        return [str(c) for c in (entry.get("source_chunk_ids") or [])]
    ids = getattr(entry, "source_chunk_ids", None) or []
    return [str(c) for c in ids]


def _class_chunk_ids(cls: Any) -> list[str]:
    """All source chunk ids a class (and its parent link) cite as evidence."""
    if isinstance(cls, dict):
        evidence = cls.get("evidence") or []
        parent_evidence = cls.get("parent_evidence") or []
    else:
        evidence = getattr(cls, "evidence", None) or []
        parent_evidence = getattr(cls, "parent_evidence", None) or []
    chunk_ids: list[str] = []
    for entry in (*evidence, *parent_evidence):
        chunk_ids.extend(_evidence_chunk_ids(entry))
    return chunk_ids


def _set_domain_tag(cls: Any, tag: str | None) -> None:
    if isinstance(cls, dict):
        cls["domain_tag"] = tag
    else:
        cls.domain_tag = tag


def assign_domain_tags(
    classes: list[Any],
    segments: list[dict[str, Any]],
    *,
    min_confidence: float,
) -> dict[str, int]:
    """Stamp ``domain_tag`` on each class by majority vote of its evidence.

    A class is tagged with the domain that the majority of its cited chunks
    belong to; classes with no usable evidence fall back to the run's
    dominant domain. Mutates the class objects in place (supporting both
    Pydantic ``ExtractedClass`` and plain dicts) and returns per-domain
    class counts for the DD.3 warning.
    """
    detected = detected_domains_from_segments(segments, min_confidence)
    if not detected:
        return {}
    allowed = set(detected)
    fallback = dominant_domain(segments, candidates=detected) or detected[0]
    chunk_map = build_chunk_domain_map(segments, allowed, fallback)

    counts: Counter[str] = Counter()
    for cls in classes:
        domains = [chunk_map[c] for c in _class_chunk_ids(cls) if c in chunk_map]
        tag = Counter(domains).most_common(1)[0][0] if domains else fallback
        _set_domain_tag(cls, tag)
        counts[tag] += 1
    return dict(counts)


def build_multi_domain_warning(
    *,
    detected_domains: list[str],
    segments: list[dict[str, Any]],
    class_domain_counts: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """Return a non-blocking ``multi_domain`` warning, or ``None`` (DD.3).

    Mirrors the IMG.7 ``visual_heavy_orphans`` warning shape so the curator
    UI can render it through the same ``stats.warnings[]`` surface. Returns
    ``None`` for single-domain (or empty) runs so healthy runs stay quiet.
    """
    if len(detected_domains) <= 1:
        return None

    chunk_counts = {d: domain_chunk_counts(segments).get(d, 0) for d in detected_domains}
    domains_str = ", ".join(detected_domains)
    return {
        "type": "multi_domain",
        "severity": "warning",
        "message": (
            f"This document appears to span {len(detected_domains)} topical "
            f"domains ({domains_str}). Extracted classes are tagged by domain; "
            "review the mix or use \u201cSplit by domain\u201d to route each domain "
            "into its own ontology."
        ),
        "detected_domains": list(detected_domains),
        "domain_chunk_counts": chunk_counts,
        "domain_class_counts": dict(class_domain_counts or {}),
    }
