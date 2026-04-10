"""Semantic Validator — LLM-based OWL logical consistency checker.

Runs after the consistency checker. For each extracted class, the LLM checks
for domain/range mismatches, disjointness violations, range type mismatches,
and redundant class definitions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.agents.extractor import _get_llm
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)

_DEFAULT_SCORE = 0.8

_SYSTEM_PROMPT = (
    "You are an OWL ontology validator. Review the following extracted ontology "
    "classes. Each class lists **attributes** (owl:DatatypeProperty, scalar ranges) "
    "and **relationships** (owl:ObjectProperty, target class URIs). "
    "Legacy extractions may only show a flat `properties` list with "
    "`property_type` and `range`.\n\n"
    "Check each class for:\n"
    "1. Domain/range mismatches: Does any property have a semantically "
    "nonsensical range for its domain class?\n"
    "2. Disjointness violations: Is a class declared as subclass of two "
    "classes that should logically be disjoint?\n"
    "3. Range type mismatches: Does an object property point to an XSD "
    "datatype, or a datatype property point to a class?\n"
    "4. Redundant classes: Are two classes essentially the same concept "
    "with different names?\n\n"
    "Return ONLY valid JSON, no markdown fences."
)


def _class_fields_for_validation(c: ExtractedClass) -> dict[str, list[dict[str, str]]]:
    """Normalize PGT attributes/relationships (or legacy properties) for the LLM."""
    attributes: list[dict[str, str]] = []
    relationships: list[dict[str, str]] = []

    if c.attributes or c.relationships:
        for a in c.attributes:
            attributes.append({
                "uri": a.uri,
                "label": a.label,
                "range_datatype": a.range_datatype,
            })
        for r in c.relationships:
            relationships.append({
                "uri": r.uri,
                "label": r.label,
                "target_class_uri": r.target_class_uri,
            })
        return {"attributes": attributes, "relationships": relationships}

    for p in c.properties:
        if p.property_type == "object":
            relationships.append({
                "uri": p.uri,
                "label": p.label,
                "target_class_uri": p.range,
            })
        else:
            attributes.append({
                "uri": p.uri,
                "label": p.label,
                "range_datatype": p.range,
            })
    return {"attributes": attributes, "relationships": relationships}


def _build_user_prompt(classes: list[ExtractedClass]) -> str:
    class_list = []
    for c in classes:
        shapes = _class_fields_for_validation(c)
        class_list.append({
            "uri": c.uri,
            "label": c.label,
            "description": c.description,
            "parent_uri": c.parent_uri,
            "attributes": shapes["attributes"],
            "relationships": shapes["relationships"],
        })

    return (
        f"Classes:\n{json.dumps(class_list, indent=2)}\n\n"
        'Return JSON: {"results": [{"uri": "...", "score": 0.0-1.0, '
        '"issues": ["issue description", ...]}]}\n\n'
        "Score meaning: 1.0 = no issues found, 0.7 = minor issues, "
        "0.4 = significant issues, 0.1 = fundamentally flawed"
    )


def _parse_response(raw_text: str, class_uris: set[str]) -> dict[str, float]:
    """Parse the LLM response into {uri: score}, falling back to defaults on error."""
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()

    data = json.loads(text)
    results: list[dict[str, Any]] = data.get("results", [])

    scores: dict[str, float] = {}
    for entry in results:
        uri = entry.get("uri", "")
        score = entry.get("score", _DEFAULT_SCORE)
        if uri:
            scores[uri] = max(0.0, min(1.0, float(score)))

    for uri in class_uris:
        if uri not in scores:
            scores[uri] = _DEFAULT_SCORE

    return scores


async def validate_semantics(
    classes: list[ExtractedClass],
    model_name: str | None = None,
) -> dict[str, float]:
    """Return {class_uri: validity_score} for each class.

    Sends all classes in a single LLM call to minimize cost.
    Returns default scores of 0.8 for all classes if the call fails.
    """
    if not classes:
        return {}

    class_uris = {c.uri for c in classes}
    resolved_model = model_name or settings.llm_extraction_model

    try:
        llm = _get_llm(resolved_model)
        user_prompt = _build_user_prompt(classes)

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = await llm.ainvoke(messages)
        raw_text = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )

        scores = _parse_response(raw_text, class_uris)
        log.info(
            "semantic validator completed",
            extra={"class_count": len(classes), "scores": scores},
        )
        return scores

    except Exception:
        log.warning(
            "semantic validator failed, returning default scores",
            exc_info=True,
        )
        return {uri: _DEFAULT_SCORE for uri in class_uris}
