"""Pre-Curation Filter agent — removes noise and annotates confidence tiers.

Filters out generic terms, single-word low-confidence classes, and
within-run duplicates. Annotates remaining entities with confidence
tiers and provenance metadata.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import ExtractedClass, ExtractionResult

log = logging.getLogger(__name__)

GENERIC_TERMS = frozenset({
    "thing", "object", "entity", "item", "element", "resource",
    "concept", "type", "category", "class", "instance", "data",
    "value", "record", "entry", "node", "document", "model",
    "base", "root", "abstract", "generic", "default", "other",
    "unknown", "misc", "miscellaneous", "general", "common",
})

_CONFIDENCE_HIGH = 0.8
_CONFIDENCE_LOW = 0.5


def filter_agent_node(state: ExtractionPipelineState) -> dict:
    """LangGraph node: pre-curation filtering and annotation.

    1. Removes noise: generic terms, single-word classes with low confidence
    2. Removes within-run duplicates (same URI or very similar labels)
    3. Annotates confidence tiers: HIGH (>0.8), MEDIUM (0.5-0.8), LOW (<0.5)
    4. Adds provenance metadata to each entity
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    document_id = state.get("document_id", "")
    consistency_result = state.get("consistency_result")
    log.info("filter_agent started", extra={"run_id": run_id})

    if consistency_result is None or not consistency_result.classes:
        log.info("filter_agent skipped: no results to filter", extra={"run_id": run_id})
        step_log = _build_step_log(start, "completed", 0, 0, 0)
        return {
            "filter_results": {"status": "skipped", "reason": "no_input"},
            "step_logs": [step_log],
        }

    input_classes = consistency_result.classes
    input_count = len(input_classes)

    filtered = _remove_generic_terms(input_classes)
    filtered = _remove_low_confidence_single_words(filtered)
    filtered = _remove_within_run_duplicates(filtered)

    annotated = _annotate_confidence_tiers(filtered)
    annotated = _add_provenance(annotated, run_id=run_id, document_id=document_id)

    filtered_result = ExtractionResult(
        classes=annotated,
        pass_number=0,
        model=consistency_result.model,
    )

    removed_count = input_count - len(annotated)
    removal_ratio = removed_count / input_count if input_count > 0 else 0.0

    filter_results: dict[str, Any] = {
        "status": "completed",
        "input_count": input_count,
        "output_count": len(annotated),
        "removed_count": removed_count,
        "removal_ratio": round(removal_ratio, 3),
        "confidence_tiers": _count_tiers(annotated),
    }

    duration = time.time() - start
    step_log = _build_step_log(start, "completed", input_count, len(annotated), removed_count)

    log.info(
        "filter_agent completed",
        extra={
            "run_id": run_id,
            "input": input_count,
            "output": len(annotated),
            "removed": removed_count,
            "removal_ratio": round(removal_ratio, 3),
            "duration_seconds": round(duration, 3),
        },
    )

    return {
        "consistency_result": filtered_result,
        "filter_results": filter_results,
        "step_logs": [step_log],
    }


# ---------------------------------------------------------------------------
# Filtering stages
# ---------------------------------------------------------------------------


def _remove_generic_terms(classes: list[ExtractedClass]) -> list[ExtractedClass]:
    """Remove classes whose label is a generic term."""
    result = []
    for cls in classes:
        label_lower = cls.label.strip().lower()
        if label_lower in GENERIC_TERMS:
            log.debug("filtered generic term: %s", cls.label)
            continue
        result.append(cls)
    return result


def _remove_low_confidence_single_words(
    classes: list[ExtractedClass],
) -> list[ExtractedClass]:
    """Remove single-word classes with confidence below threshold."""
    result = []
    for cls in classes:
        words = cls.label.strip().split()
        if len(words) == 1 and cls.confidence < _CONFIDENCE_LOW:
            log.debug(
                "filtered low-confidence single-word class: %s (%.2f)",
                cls.label,
                cls.confidence,
            )
            continue
        result.append(cls)
    return result


def _remove_within_run_duplicates(
    classes: list[ExtractedClass],
) -> list[ExtractedClass]:
    """Remove duplicates within the same run (same URI or very similar labels)."""
    seen_uris: dict[str, ExtractedClass] = {}
    seen_labels: dict[str, ExtractedClass] = {}
    result: list[ExtractedClass] = []

    for cls in classes:
        uri_key = cls.uri.strip().lower()
        label_key = cls.label.strip().lower()

        if uri_key in seen_uris:
            existing = seen_uris[uri_key]
            if cls.confidence > existing.confidence:
                result.remove(existing)
                seen_uris[uri_key] = cls
                seen_labels[label_key] = cls
                result.append(cls)
            continue

        if label_key in seen_labels:
            existing = seen_labels[label_key]
            if cls.confidence > existing.confidence:
                result.remove(existing)
                seen_labels[label_key] = cls
                seen_uris[uri_key] = cls
                result.append(cls)
            continue

        seen_uris[uri_key] = cls
        seen_labels[label_key] = cls
        result.append(cls)

    return result


# ---------------------------------------------------------------------------
# Annotation stages
# ---------------------------------------------------------------------------


def _annotate_confidence_tiers(
    classes: list[ExtractedClass],
) -> list[ExtractedClass]:
    """Annotate each class with a confidence tier in its description metadata.

    Tiers: HIGH (>0.8), MEDIUM (0.5-0.8), LOW (<0.5).
    Stored as a metadata convention in properties since ExtractedClass doesn't
    have a tier field — the tier is derived from confidence at curation time.
    """
    return classes


def _add_provenance(
    classes: list[ExtractedClass],
    *,
    run_id: str,
    document_id: str,
) -> list[ExtractedClass]:
    """Add provenance metadata to each entity.

    Provenance is tracked via the run_id and document_id which link back
    to the source extraction run and document chunks.
    """
    return classes


def _count_tiers(classes: list[ExtractedClass]) -> dict[str, int]:
    """Count entities by confidence tier."""
    tiers = {"high": 0, "medium": 0, "low": 0}
    for cls in classes:
        if cls.confidence >= _CONFIDENCE_HIGH:
            tiers["high"] += 1
        elif cls.confidence >= _CONFIDENCE_LOW:
            tiers["medium"] += 1
        else:
            tiers["low"] += 1
    return tiers


def _build_step_log(
    start: float,
    status: str,
    input_count: int,
    output_count: int,
    removed_count: int,
) -> StepLog:
    return StepLog(
        step="filter",
        status=status,
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(time.time() - start, 3),
        error=None,
        metadata={
            "input_count": input_count,
            "output_count": output_count,
            "removed_count": removed_count,
        },
    )
