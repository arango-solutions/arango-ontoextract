"""Domain Segmenter agent (Stream 16 DD.1).

A pre-extraction LangGraph node that clusters ``document_chunks`` into
topical domains via an LLM classification pass and writes one
``domain_segments`` entry per domain into pipeline state. Downstream
(``execute_run``) turns those segments into ``detected_domains``, per-class
``domain_tag`` stamping, and a non-blocking ``multi_domain`` warning.

The node is gated behind ``settings.domain_detection_enabled`` (default
OFF, mirroring the belief-revision and structural-gate nodes): when
disabled it is a transparent pass-through that emits no segments, so
existing runs stay byte-identical. Any classification/parse failure
degrades gracefully to "no segments" rather than failing the run.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.llm import get_chat_model
from app.extraction.prompts import get_template
from app.extraction.state import ExtractionPipelineState, StepLog

log = logging.getLogger(__name__)

#: Per-chunk character budget for the classification prompt. Domain
#: detection only needs the gist of each chunk, so we truncate to keep the
#: single classification call cheap even on long documents.
_CHUNK_PREVIEW_CHARS = 600


def _chunk_id(chunk: dict[str, Any], index0: int) -> str:
    """Stable chunk id matching the extractor's ``source_chunk_id`` scheme.

    The extractor labels chunks with ``_key`` (falling back to ``id`` /
    ``chunk_id`` / 1-based position), and the LLM cites those exact values
    as evidence ``source_chunk_ids``. Domain tagging maps those evidence
    ids back to domains, so this MUST derive ids the same way.
    """
    return str(chunk.get("_key") or chunk.get("id") or chunk.get("chunk_id") or (index0 + 1))


def _resolve_model() -> str:
    return settings.domain_detection_model or settings.llm_extraction_model


def _sample_indices(total: int, cap: int) -> list[int]:
    """Evenly spaced sample of ``cap`` indices across ``range(total)``."""
    if total <= cap:
        return list(range(total))
    step = total / cap
    seen: list[int] = []
    used: set[int] = set()
    for i in range(cap):
        idx = min(total - 1, int(i * step))
        if idx not in used:
            used.add(idx)
            seen.append(idx)
    return seen


def _build_chunks_text(chunks: list[dict[str, Any]], indices: list[int]) -> str:
    parts: list[str] = []
    for idx in indices:
        chunk = chunks[idx]
        text = (chunk.get("text") or "")[:_CHUNK_PREVIEW_CHARS]
        parts.append(f"[source_chunk_id={_chunk_id(chunk, idx)}]\n{text}")
    return "\n\n".join(parts)


def _single_segment(chunks: list[dict[str, Any]], domain: str = "General") -> list[dict[str, Any]]:
    return [
        {
            "domain": domain,
            "chunk_ids": [_chunk_id(c, i) for i, c in enumerate(chunks)],
            "confidence": 1.0,
        }
    ]


def _parse_domain_response(
    raw_text: str,
    known_ids: list[str],
) -> list[dict[str, Any]]:
    """Parse the LLM JSON into normalized, coverage-complete segments.

    Drops unknown chunk ids, clamps confidence, folds every known-but-
    unassigned chunk into the highest-confidence segment so the segments
    always cover the full document. Raises on malformed JSON so the caller
    can fall back to a single segment.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()

    data = json.loads(text)
    raw_domains = data.get("domains", []) if isinstance(data, dict) else []

    known = set(known_ids)
    assigned: set[str] = set()
    segments: list[dict[str, Any]] = []
    for entry in raw_domains:
        if not isinstance(entry, dict):
            continue
        domain = str(entry.get("domain") or "").strip()
        if not domain:
            continue
        chunk_ids = [
            str(c)
            for c in (entry.get("chunk_ids") or [])
            if str(c) in known and str(c) not in assigned
        ]
        if not chunk_ids:
            continue
        assigned.update(chunk_ids)
        try:
            confidence = max(0.0, min(1.0, float(entry.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        segments.append({"domain": domain, "chunk_ids": chunk_ids, "confidence": confidence})

    if not segments:
        raise ValueError("no valid domain segments in LLM response")

    leftover = [cid for cid in known_ids if cid not in assigned]
    if leftover:
        target = max(segments, key=lambda s: s["confidence"])
        target["chunk_ids"].extend(leftover)

    return segments


def _expand_sampled_segments(
    segments: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    sampled_indices: list[int],
) -> list[dict[str, Any]]:
    """Propagate sampled-chunk domains to every chunk (for capped documents).

    Each non-sampled chunk inherits the domain of the nearest preceding
    sampled chunk (or the first sampled chunk), then segments are rebuilt
    over the full chunk set.
    """
    id_to_domain: dict[str, str] = {}
    for seg in segments:
        for cid in seg["chunk_ids"]:
            id_to_domain[cid] = seg["domain"]

    confidence_by_domain = {seg["domain"]: seg["confidence"] for seg in segments}
    ordered_sampled = sorted(sampled_indices)
    domain_of_full: dict[int, str] = {}
    current_domain = segments[0]["domain"]
    sample_ptr = 0
    for idx in range(len(chunks)):
        while sample_ptr < len(ordered_sampled) and ordered_sampled[sample_ptr] <= idx:
            sampled_idx = ordered_sampled[sample_ptr]
            cid = _chunk_id(chunks[sampled_idx], sampled_idx)
            current_domain = id_to_domain.get(cid, current_domain)
            sample_ptr += 1
        domain_of_full[idx] = current_domain

    grouped: dict[str, list[str]] = {}
    for idx in range(len(chunks)):
        domain = domain_of_full[idx]
        grouped.setdefault(domain, []).append(_chunk_id(chunks[idx], idx))

    return [
        {
            "domain": domain,
            "chunk_ids": chunk_ids,
            "confidence": confidence_by_domain.get(domain, 0.5),
        }
        for domain, chunk_ids in grouped.items()
    ]


async def _segment_chunks_with_llm(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model_name = _resolve_model()
    indices = _sample_indices(len(chunks), settings.domain_detection_max_chunks)
    chunks_text = _build_chunks_text(chunks, indices)
    known_ids = [_chunk_id(chunks[i], i) for i in indices]

    template = get_template("domain_segmentation")
    system_prompt, user_prompt = template.render(chunks_text=chunks_text)
    llm = get_chat_model(model_name)
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    raw_text = response.content if isinstance(response.content, str) else str(response.content)

    segments = _parse_domain_response(raw_text, known_ids)
    if len(indices) < len(chunks):
        segments = _expand_sampled_segments(segments, chunks, indices)
    return segments


async def domain_segmenter_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node: cluster document chunks into topical domains (DD.1)."""
    start = time.time()
    run_id = state.get("run_id", "unknown")
    chunks = state.get("document_chunks", [])

    if not settings.domain_detection_enabled:
        step_log = StepLog(
            step="domain_segmenter",
            status="skipped",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error=None,
            metadata={"reason": "domain_detection_disabled", "chunk_count": len(chunks)},
        )
        return {"domain_segments": [], "step_logs": [step_log]}

    if not chunks:
        step_log = StepLog(
            step="domain_segmenter",
            status="completed",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error=None,
            metadata={"reason": "no_chunks", "domain_count": 0},
        )
        return {"domain_segments": [], "step_logs": [step_log]}

    log.info("domain_segmenter started", extra={"run_id": run_id, "chunk_count": len(chunks)})

    error: str | None = None
    try:
        segments = await _segment_chunks_with_llm(chunks)
    except Exception as exc:
        # Degrade gracefully: a segmentation failure must never fail the
        # extraction run. Emit no segments so downstream leaves classes
        # untagged (as if detection were off), and record the reason.
        error = str(exc)
        log.warning(
            "domain_segmenter failed, continuing without domain routing (run_id=%s): %s",
            run_id,
            exc,
            exc_info=True,
        )
        segments = []

    domain_names = sorted({str(s.get("domain")) for s in segments if s.get("domain")})
    duration = time.time() - start
    step_log = StepLog(
        step="domain_segmenter",
        status="failed" if error else "completed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=error,
        metadata={
            "chunk_count": len(chunks),
            "domain_count": len(domain_names),
            "domains": domain_names,
        },
    )
    log.info(
        "domain_segmenter completed",
        extra={
            "run_id": run_id,
            "domain_count": len(domain_names),
            "duration_seconds": round(duration, 3),
        },
    )
    return {"domain_segments": segments, "step_logs": [step_log]}
