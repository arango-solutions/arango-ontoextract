"""Faithfulness Judge — LLM-as-judge grounding check against source text.

Runs after the consistency checker. For each extracted class, the LLM rates
whether the concept is explicitly mentioned, reasonably inferred, plausible
but ungrounded, or hallucinated.
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

_RATING_SCORES: dict[str, float] = {
    "EXPLICIT": 1.0,
    "INFERRED": 0.7,
    "PLAUSIBLE": 0.4,
    "HALLUCINATED": 0.1,
}

_DEFAULT_SCORE = 0.5

_SYSTEM_PROMPT = (
    "You are evaluating whether ontology classes extracted from a document "
    "are faithfully grounded in the source text.\n\n"
    "For each class below, rate its faithfulness to the source text:\n"
    "- EXPLICIT (1.0): The concept is explicitly mentioned in the text\n"
    "- INFERRED (0.7): The concept is reasonably inferred from the text\n"
    "- PLAUSIBLE (0.4): A reasonable domain concept but not directly grounded in the text\n"
    "- HALLUCINATED (0.1): Not supported by the text at all\n\n"
    "Return ONLY valid JSON, no markdown fences."
)


def _build_user_prompt(classes: list[ExtractedClass], chunks: list[dict[str, Any]]) -> str:
    chunks_text = "\n\n".join(
        f"[Chunk {i + 1}]\n{chunk.get('text', '')}"
        for i, chunk in enumerate(chunks)
    )

    class_list = [
        {"uri": c.uri, "label": c.label, "description": c.description}
        for c in classes
    ]

    return (
        f"Source text:\n{chunks_text}\n\n"
        f"Classes to evaluate:\n{json.dumps(class_list, indent=2)}\n\n"
        'Return JSON: {"results": [{"uri": "...", "rating": '
        '"EXPLICIT|INFERRED|PLAUSIBLE|HALLUCINATED", "reason": "brief explanation"}]}'
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
        rating = entry.get("rating", "").upper()
        score = _RATING_SCORES.get(rating, _DEFAULT_SCORE)
        if uri:
            scores[uri] = score

    for uri in class_uris:
        if uri not in scores:
            scores[uri] = _DEFAULT_SCORE

    return scores


async def judge_faithfulness(
    classes: list[ExtractedClass],
    chunks: list[dict[str, Any]],
    model_name: str | None = None,
) -> dict[str, float]:
    """Return {class_uri: faithfulness_score} for each class.

    Sends all classes in a single LLM call to minimize cost.
    Returns default scores of 0.5 for all classes if the call fails.
    """
    if not classes:
        return {}

    class_uris = {c.uri for c in classes}

    if not chunks:
        log.warning("faithfulness judge: no chunks available, returning defaults")
        return {uri: _DEFAULT_SCORE for uri in class_uris}

    resolved_model = model_name or settings.llm_extraction_model

    try:
        llm = _get_llm(resolved_model)
        user_prompt = _build_user_prompt(classes, chunks)

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = llm.invoke(messages)
        raw_text = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )

        scores = _parse_response(raw_text, class_uris)
        log.info(
            "faithfulness judge completed",
            extra={"class_count": len(classes), "scores": scores},
        )
        return scores

    except Exception:
        log.warning(
            "faithfulness judge failed, returning default scores",
            exc_info=True,
        )
        return {uri: _DEFAULT_SCORE for uri in class_uris}
