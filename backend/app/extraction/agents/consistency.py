"""Consistency Checker agent — compares N extraction pass results and filters by agreement."""

from __future__ import annotations

import logging
import time
from collections import Counter

from app.config import settings
from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import (
    ExtractedAttribute,
    ExtractedClass,
    ExtractedProperty,
    ExtractedRelationship,
    ExtractionResult,
    SourceEvidence,
)
from app.services.confidence import _property_agreement_score

log = logging.getLogger(__name__)


def _clamp_confidence(value: float) -> float:
    """Normalize any confidence-like value into the valid [0, 1] range."""
    return max(0.0, min(1.0, float(value)))


def _class_key(cls: ExtractedClass) -> str:
    """Canonical key for matching classes across passes."""
    return cls.uri.strip().lower()


def _property_key(prop: ExtractedProperty) -> str:
    """Canonical key for matching properties across passes."""
    return prop.uri.strip().lower()


def _attribute_key(attr: ExtractedAttribute) -> str:
    """Canonical key for matching attributes across passes."""
    return attr.uri.strip().lower()


def _relationship_key(rel: ExtractedRelationship) -> str:
    """Canonical key for matching relationships across passes."""
    return rel.uri.strip().lower()


def _merge_descriptions(descriptions: list[str]) -> str:
    """Merge multiple descriptions — longest wins."""
    if not descriptions:
        return ""
    return max(descriptions, key=len)


def _merge_evidence(evidence_lists: list[list[SourceEvidence]]) -> list[SourceEvidence]:
    """Deduplicate source evidence while preserving first-seen order."""
    merged: list[SourceEvidence] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    for evidence_list in evidence_lists:
        for evidence in evidence_list:
            key = (tuple(evidence.source_chunk_ids), evidence.evidence_text.strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(evidence)
    return merged


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
        avg_confidence = sum(_clamp_confidence(p.confidence) for p in props) / len(props)
        merged.append(
            ExtractedProperty(
                uri=best.uri,
                label=best.label,
                description=best.description,
                property_type=best.property_type,
                range=best.range,
                confidence=round(_clamp_confidence(avg_confidence), 3),
                evidence=_merge_evidence([p.evidence for p in props]),
            )
        )
    return merged


def _merge_attributes(
    attribute_lists: list[list[ExtractedAttribute]],
) -> list[ExtractedAttribute]:
    """Union attributes across passes, averaging confidence for duplicates."""
    seen: dict[str, list[ExtractedAttribute]] = {}
    for attr_list in attribute_lists:
        for attr in attr_list:
            key = _attribute_key(attr)
            seen.setdefault(key, []).append(attr)

    merged: list[ExtractedAttribute] = []
    for _key, attrs in seen.items():
        best = max(attrs, key=lambda a: len(a.description))
        avg_confidence = sum(_clamp_confidence(a.confidence) for a in attrs) / len(attrs)
        merged.append(
            ExtractedAttribute(
                uri=best.uri,
                label=best.label,
                description=best.description,
                range_datatype=best.range_datatype,
                confidence=round(_clamp_confidence(avg_confidence), 3),
                evidence=_merge_evidence([a.evidence for a in attrs]),
            )
        )
    return merged


def _merge_relationships(
    relationship_lists: list[list[ExtractedRelationship]],
) -> list[ExtractedRelationship]:
    """Union relationships across passes, averaging confidence for duplicates."""
    seen: dict[str, list[ExtractedRelationship]] = {}
    for rel_list in relationship_lists:
        for rel in rel_list:
            key = _relationship_key(rel)
            seen.setdefault(key, []).append(rel)

    merged: list[ExtractedRelationship] = []
    for _key, rels in seen.items():
        best = max(rels, key=lambda r: len(r.description))
        avg_confidence = sum(_clamp_confidence(r.confidence) for r in rels) / len(rels)
        merged.append(
            ExtractedRelationship(
                uri=best.uri,
                label=best.label,
                description=best.description,
                target_class_uri=best.target_class_uri,
                confidence=round(_clamp_confidence(avg_confidence), 3),
                evidence=_merge_evidence([r.evidence for r in rels]),
            )
        )
    return merged


def _convert_properties_to_pgt(
    properties: list[ExtractedProperty],
) -> tuple[list[ExtractedAttribute], list[ExtractedRelationship]]:
    """Convert legacy ExtractedProperty list to PGT-aligned attributes and relationships.

    Uses a simple heuristic: property_type == "object", or range starts with
    "http", or range contains "#" → relationship.  Everything else → attribute.
    """
    attributes: list[ExtractedAttribute] = []
    relationships: list[ExtractedRelationship] = []
    for prop in properties:
        is_object = (
            prop.property_type == "object" or prop.range.startswith("http") or "#" in prop.range
        )
        if is_object:
            relationships.append(
                ExtractedRelationship(
                    uri=prop.uri,
                    label=prop.label,
                    description=prop.description,
                    target_class_uri=prop.range,
                    confidence=prop.confidence,
                    evidence=prop.evidence,
                )
            )
        else:
            attributes.append(
                ExtractedAttribute(
                    uri=prop.uri,
                    label=prop.label,
                    description=prop.description,
                    range_datatype=prop.range,
                    confidence=prop.confidence,
                    evidence=prop.evidence,
                )
            )
    return attributes, relationships


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
        return {
            "consistency_result": None,
            "errors": errors,
            "step_logs": [step_log],
        }

    uri_counter: Counter[str] = Counter()
    uri_to_classes: dict[str, list[ExtractedClass]] = {}

    for result in pass_results:
        seen_in_pass: set[str] = set()
        for cls in result.classes:
            key = _class_key(cls)
            if key not in seen_in_pass:
                uri_counter[key] += 1
                seen_in_pass.add(key)
            uri_to_classes.setdefault(key, []).append(cls)

    filtered_classes: list[ExtractedClass] = []
    for uri_key, count in uri_counter.items():
        if count < threshold:
            continue

        variants = uri_to_classes[uri_key]
        agreement_ratio = _clamp_confidence(count / num_passes)

        descriptions = [v.description for v in variants]
        merged_desc = _merge_descriptions(descriptions)

        # Collect PGT-aligned attributes/relationships per variant,
        # converting legacy properties when the new fields are absent.
        all_attribute_lists: list[list[ExtractedAttribute]] = []
        all_relationship_lists: list[list[ExtractedRelationship]] = []
        for v in variants:
            if v.attributes or v.relationships:
                all_attribute_lists.append(v.attributes)
                all_relationship_lists.append(v.relationships)
            elif v.properties:
                attrs, rels = _convert_properties_to_pgt(v.properties)
                all_attribute_lists.append(attrs)
                all_relationship_lists.append(rels)
            else:
                all_attribute_lists.append([])
                all_relationship_lists.append([])

        merged_attributes = _merge_attributes(all_attribute_lists)
        merged_relationships = _merge_relationships(all_relationship_lists)

        # Keep legacy merged properties for backward compat
        all_property_lists = [v.properties for v in variants]
        merged_props = _merge_properties(all_property_lists)

        # Per-type agreement scores (Jaccard of URIs across passes)
        attr_uris_per_pass = [{_attribute_key(a) for a in attrs} for attrs in all_attribute_lists]
        rel_uris_per_pass = [
            {_relationship_key(r) for r in rels} for rels in all_relationship_lists
        ]
        combined_uris_per_pass = [
            au | ru for au, ru in zip(attr_uris_per_pass, rel_uris_per_pass, strict=True)
        ]

        attr_agreement = round(_property_agreement_score(attr_uris_per_pass), 3)
        rel_agreement = round(_property_agreement_score(rel_uris_per_pass), 3)
        prop_agreement = round(_property_agreement_score(combined_uris_per_pass), 3)

        best_variant = max(variants, key=lambda v: len(v.description))
        parent_uris = [v.parent_uri for v in variants if v.parent_uri]
        parent_uri = Counter(parent_uris).most_common(1)[0][0] if parent_uris else None

        llm_confidences = [v.confidence for v in variants]
        avg_llm_confidence = (
            sum(_clamp_confidence(c) for c in llm_confidences) / len(llm_confidences)
            if llm_confidences
            else 0.5
        )

        filtered_classes.append(
            ExtractedClass(
                uri=best_variant.uri,
                label=best_variant.label,
                description=merged_desc,
                parent_uri=parent_uri,
                parent_evidence=_merge_evidence([v.parent_evidence for v in variants]),
                classification=best_variant.classification,
                confidence=round(agreement_ratio, 3),
                evidence=_merge_evidence([v.evidence for v in variants]),
                llm_confidence=round(_clamp_confidence(avg_llm_confidence), 3),
                property_agreement=round(_clamp_confidence(prop_agreement), 3),
                attribute_agreement=round(_clamp_confidence(attr_agreement), 3),
                relationship_agreement=round(_clamp_confidence(rel_agreement), 3),
                properties=merged_props,
                attributes=merged_attributes,
                relationships=merged_relationships,
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
                _class_key(c): uri_counter[_class_key(c)] / num_passes for c in filtered_classes
            },
        },
    )

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
        "step_logs": [step_log],
    }
