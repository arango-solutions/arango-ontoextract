"""Consistency Checker agent — compares N extraction pass results and filters by agreement."""

from __future__ import annotations

import logging
import time
from collections import Counter

from app.config import settings
from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import ExtractedClass, ExtractedProperty, ExtractionResult
from app.services.confidence import _property_agreement_score

log = logging.getLogger(__name__)


def _class_key(cls: ExtractedClass) -> str:
    """Canonical key for matching classes across passes."""
    return cls.uri.strip().lower()


def _property_key(prop: ExtractedProperty) -> str:
    """Canonical key for matching properties across passes."""
    return prop.uri.strip().lower()


def _merge_descriptions(descriptions: list[str]) -> str:
    """Merge multiple descriptions — longest wins."""
    if not descriptions:
        return ""
    return max(descriptions, key=len)


def _merge_properties(
    property_lists: list[list[ExtractedProperty]],
) -> list[ExtractedProperty]:
    """Union properties across passes, averaging confidence for duplicates."""
    seen: dict[str, list[ExtractedProperty]] = {}
    for prop_list in property_lists:
        for prop in prop_list:
            key = _property_key(prop)
            seen.setdefault(key, []).append(prop)

    merged: list[ExtractedProperty] = []
    for _key, props in seen.items():
        best = max(props, key=lambda p: len(p.description))
        avg_confidence = sum(p.confidence for p in props) / len(props)
        merged.append(
            ExtractedProperty(
                uri=best.uri,
                label=best.label,
                description=best.description,
                property_type=best.property_type,
                range=best.range,
                confidence=round(avg_confidence, 3),
            )
        )
    return merged


def consistency_checker_node(state: ExtractionPipelineState) -> dict:
    """LangGraph node: filter extraction results by cross-pass agreement.

    Keeps concepts appearing in >= M of N passes and assigns confidence
    scores based on agreement ratio.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    pass_results = state.get("extraction_passes", [])
    config = state.get("strategy_config", {})
    errors = list(state.get("errors", []))

    threshold = config.get(
        "consistency_threshold",
        settings.extraction_consistency_threshold,
    )
    num_passes = len(pass_results)

    log.info(
        "consistency_checker started",
        extra={
            "run_id": run_id,
            "num_passes": num_passes,
            "threshold": threshold,
        },
    )

    if not pass_results:
        errors.append("No extraction passes to check for consistency")
        step_log = StepLog(
            step="consistency_checker",
            status="failed",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error="No extraction passes available",
        )
        existing_logs = list(state.get("step_logs", []))
        existing_logs.append(step_log)
        return {
            "consistency_result": None,
            "current_step": "consistency_checker",
            "errors": errors,
            "step_logs": existing_logs,
        }

    uri_counter: Counter[str] = Counter()
    uri_to_classes: dict[str, list[ExtractedClass]] = {}

    for result in pass_results:
        for cls in result.classes:
            key = _class_key(cls)
            uri_counter[key] += 1
            uri_to_classes.setdefault(key, []).append(cls)

    filtered_classes: list[ExtractedClass] = []
    for uri_key, count in uri_counter.items():
        if count < threshold:
            continue

        variants = uri_to_classes[uri_key]
        agreement_ratio = count / num_passes

        descriptions = [v.description for v in variants]
        merged_desc = _merge_descriptions(descriptions)

        all_property_lists = [v.properties for v in variants]
        merged_props = _merge_properties(all_property_lists)

        prop_uris_per_pass: list[set[str]] = [
            {_property_key(p) for p in v.properties} for v in variants
        ]
        prop_agreement = round(_property_agreement_score(prop_uris_per_pass), 3)

        best_variant = max(variants, key=lambda v: len(v.description))
        parent_uris = [v.parent_uri for v in variants if v.parent_uri]
        parent_uri = Counter(parent_uris).most_common(1)[0][0] if parent_uris else None

        llm_confidences = [v.confidence for v in variants]
        avg_llm_confidence = (
            sum(llm_confidences) / len(llm_confidences) if llm_confidences else 0.5
        )

        filtered_classes.append(
            ExtractedClass(
                uri=best_variant.uri,
                label=best_variant.label,
                description=merged_desc,
                parent_uri=parent_uri,
                classification=best_variant.classification,
                confidence=round(agreement_ratio, 3),
                llm_confidence=round(avg_llm_confidence, 3),
                property_agreement=prop_agreement,
                properties=merged_props,
            )
        )

    filtered_classes.sort(key=lambda c: c.confidence, reverse=True)

    consistency_result = ExtractionResult(
        classes=filtered_classes,
        pass_number=0,
        model=pass_results[0].model if pass_results else "unknown",
        token_usage=None,
    )

    duration = time.time() - start
    step_log = StepLog(
        step="consistency_checker",
        status="completed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=None,
        metadata={
            "input_classes": sum(len(r.classes) for r in pass_results),
            "output_classes": len(filtered_classes),
            "threshold": threshold,
            "agreement_rates": {
                _class_key(c): uri_counter[_class_key(c)] / num_passes
                for c in filtered_classes
            },
        },
    )

    existing_logs = list(state.get("step_logs", []))
    existing_logs.append(step_log)

    log.info(
        "consistency_checker completed",
        extra={
            "run_id": run_id,
            "input_classes": sum(len(r.classes) for r in pass_results),
            "output_classes": len(filtered_classes),
            "duration_seconds": round(duration, 3),
        },
    )

    return {
        "consistency_result": consistency_result,
        "current_step": "consistency_checker",
        "step_logs": existing_logs,
    }
