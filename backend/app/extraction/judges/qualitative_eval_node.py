"""Qualitative Evaluation Agent — map-reduce LLM-based strengths/weaknesses.

Phase 1 (map): For each chunk batch, the LLM sees the actual source text
alongside the classes extracted from it and produces evidence-grounded
observations (what was captured well, what was missed, what looks hallucinated).

Phase 2 (reduce): A single LLM call synthesises all per-batch observations
into a final strengths/weaknesses summary with cross-batch patterns.

Runs async (fire-and-forget) so it never blocks staging graph creation.
The result is stored in ``extraction_runs.stats.qualitative_evaluation``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from app.config import settings
from app.extraction.agents.extractor import _batch_chunks, _get_llm
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RESPONSE_SCHEMA = {
    "title": "qualitative_evaluation",
    "type": "object",
    "properties": {
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Markdown bullet points describing extraction strengths",
        },
        "weaknesses": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Markdown bullet points describing extraction weaknesses",
        },
    },
    "required": ["strengths", "weaknesses"],
    "additionalProperties": False,
}

_MAP_OBSERVATIONS_SCHEMA = {
    "title": "batch_observations",
    "type": "object",
    "properties": {
        "observations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence-grounded observations about extraction quality for this batch",
        },
    },
    "required": ["observations"],
    "additionalProperties": False,
}


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse an LLM response, stripping markdown fences if present."""
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1:last_fence].strip()
    return json.loads(text)


async def _invoke_llm_json(
    llm: Any,
    messages: list,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Invoke the LLM with structured output, falling back to text parsing."""
    try:
        structured = llm.with_structured_output(schema)
        result = await structured.ainvoke(messages)
        if isinstance(result, dict):
            return result
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        pass

    response = await llm.ainvoke(messages)
    raw = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_json_response(raw)


# ---------------------------------------------------------------------------
# Phase 1 — MAP: per-batch observations grounded in source text
# ---------------------------------------------------------------------------

_MAP_PROMPT_TEMPLATE = (
    "You are an ontology extraction quality reviewer. Below is a batch of "
    "source text chunks followed by the ontology classes that were extracted "
    "from them.\n\n"
    "Compare the extracted classes against the actual source text and produce "
    "**evidence-grounded** observations about extraction quality.\n\n"
    "Consider:\n"
    "- Are the extracted classes actually present in or supported by the text?\n"
    "- Were important concepts in the text missed by the extraction?\n"
    "- Are class descriptions accurate reflections of what the text says?\n"
    "- Are there hallucinated classes with no textual support?\n"
    "- Are properties and relationships grounded in the source?\n\n"
    "## Source Text (Batch {batch_number})\n{batch_text}\n\n"
    "## Extracted Classes ({class_count} classes)\n{class_json}\n\n"
    "Return ONLY valid JSON with this schema:\n"
    '{{"observations": ["observation 1", ...]}}\n\n'
    "Each observation should be 1-2 sentences, referencing specific class names "
    "and quoting or paraphrasing the source text where relevant. "
    "Aim for 3-6 observations per batch."
)


def _classes_for_batch(
    classes: list[ExtractedClass],
    batch_chunk_indices: list[int],
    chunks: list[dict[str, Any]],
) -> list[ExtractedClass]:
    """Return classes whose provenance overlaps with the given batch chunk indices.

    Falls back to returning all classes if provenance info is unavailable.
    """
    batch_chunk_ids = set()
    for idx in batch_chunk_indices:
        if idx < len(chunks):
            chunk = chunks[idx]
            batch_chunk_ids.add(chunk.get("_key", chunk.get("id", str(idx))))

    if not batch_chunk_ids:
        return classes

    matched = []
    for cls in classes:
        source_chunks = getattr(cls, "source_chunks", None) or []
        if source_chunks:
            if any(sc in batch_chunk_ids for sc in source_chunks):
                matched.append(cls)
        else:
            # No provenance — include all classes so the LLM can judge
            return classes
    return matched or classes


async def _map_single_batch(
    llm: Any,
    batch_text: str,
    batch_classes: list[ExtractedClass],
    batch_index: int,
) -> list[str]:
    """Run the map phase for a single chunk batch."""
    class_summaries = [
        {
            "label": cls.label,
            "description": cls.description or "",
            "properties": [p.label for p in cls.properties],
        }
        for cls in batch_classes
    ]

    prompt = _MAP_PROMPT_TEMPLATE.format(
        batch_number=batch_index + 1,
        batch_text=batch_text,
        class_count=len(class_summaries),
        class_json=json.dumps(class_summaries, indent=2),
    )

    try:
        result = await _invoke_llm_json(
            llm, [HumanMessage(content=prompt)], _MAP_OBSERVATIONS_SCHEMA,
        )
        observations = result.get("observations", [])
        log.debug(
            "qualitative map batch %d: %d observations",
            batch_index, len(observations),
        )
        return observations
    except Exception:
        log.warning("qualitative map batch %d failed", batch_index, exc_info=True)
        return []


async def _map_phase(
    llm: Any,
    classes: list[ExtractedClass],
    chunks: list[dict[str, Any]],
    batch_size: int,
) -> list[str]:
    """Run map phase across all chunk batches concurrently."""
    batch_texts = _batch_chunks(chunks, batch_size)

    tasks = []
    for batch_idx, batch_text in enumerate(batch_texts):
        start = batch_idx * batch_size
        batch_chunk_indices = list(range(start, min(start + batch_size, len(chunks))))
        batch_classes = _classes_for_batch(classes, batch_chunk_indices, chunks)
        tasks.append(_map_single_batch(llm, batch_text, batch_classes, batch_idx))

    results = await asyncio.gather(*tasks)
    all_observations: list[str] = []
    for obs_list in results:
        all_observations.extend(obs_list)
    return all_observations


# ---------------------------------------------------------------------------
# Phase 2 — REDUCE: synthesise observations into final evaluation
# ---------------------------------------------------------------------------

_REDUCE_PROMPT_TEMPLATE = (
    "You are an ontology quality evaluator producing a final assessment.\n\n"
    "Below are per-batch observations from reviewers who read the actual "
    "source text and compared it against extracted ontology classes.\n\n"
    "Synthesise these observations into a concise qualitative summary. "
    "Look for **cross-batch patterns** — recurring strengths or weaknesses "
    "that appear across multiple batches.\n\n"
    "## Per-Batch Reviewer Observations ({observation_count} total)\n"
    "{numbered_observations}\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    '{{"strengths": ["point 1", ...], "weaknesses": ["point 1", ...]}}\n\n'
    "Each point should be a concise markdown-formatted bullet (1-2 sentences). "
    "Include specific class names where relevant. "
    "Aim for 4 points per category."
)


async def _reduce_phase(
    llm: Any,
    observations: list[str],
) -> dict[str, list[str]]:
    """Synthesise per-batch observations into final strengths/weaknesses."""
    numbered_obs = "\n".join(
        f"{i + 1}. {obs}" for i, obs in enumerate(observations)
    )

    prompt = _REDUCE_PROMPT_TEMPLATE.format(
        observation_count=len(observations),
        numbered_observations=numbered_obs,
    )

    result = await _invoke_llm_json(
        llm, [HumanMessage(content=prompt)], _RESPONSE_SCHEMA,
    )
    return {
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_qualitative_evaluation(
    classes: list[ExtractedClass],
    chunks: list[dict[str, Any]],
    batch_size: int = 5,
    model_name: str | None = None,
) -> dict[str, list[str]]:
    """Produce a strengths/weaknesses evaluation using map-reduce over source text.

    Parameters
    ----------
    classes:
        The extracted (post-filter) ontology classes.
    chunks:
        The original document chunks (source text).
    batch_size:
        Number of chunks per map-phase batch (reuses extraction batch size).
    model_name:
        LLM model to use. Defaults to configured extraction model.
    """
    if not classes:
        return {"strengths": [], "weaknesses": ["No classes extracted"]}

    resolved_model = model_name or settings.llm_extraction_model
    llm = _get_llm(resolved_model)

    try:
        # Phase 1: map — per-batch observations grounded in source text
        observations = await _map_phase(llm, classes, chunks, batch_size)

        if not observations:
            return {
                "strengths": [],
                "weaknesses": ["Could not generate text-grounded observations"],
            }

        # Phase 2: reduce — synthesise into final evaluation
        result = await _reduce_phase(llm, observations)

        log.info(
            "qualitative evaluation completed (map-reduce)",
            extra={
                "class_count": len(classes),
                "batch_count": len(range(0, len(chunks), batch_size)),
                "observation_count": len(observations),
                "strengths": len(result.get("strengths", [])),
                "weaknesses": len(result.get("weaknesses", [])),
            },
        )
        return result

    except Exception:
        log.warning(
            "qualitative evaluation failed, returning empty result",
            exc_info=True,
        )
        return {
            "strengths": [],
            "weaknesses": ["Qualitative evaluation could not be completed"],
        }
