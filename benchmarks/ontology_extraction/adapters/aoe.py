"""Adapter that runs AOE's real extraction pipeline against a document.

Heavy dependency — requires the backend virtual environment, ArangoDB, and
(for non-mock LLMs) provider API keys. Import is lazy so that unit tests for
the harness don't require backend installation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from benchmarks.ontology_extraction.adapters.base import ExtractionAdapter, ExtractionResult
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


@dataclass
class AOEAdapter(ExtractionAdapter):
    """Calls :func:`backend.app.extraction.pipeline.run_pipeline` for each document.

    Parameters
    ----------
    chunk_size:
        Target chunk size in characters. Chunking here is intentionally naive;
        the harness is measuring the extractor, not the chunker.
    domain_context:
        Optional serialized domain ontology passed to the pipeline for Tier-2
        context-aware extraction.
    """

    chunk_size: int = 2000
    domain_context: str = ""
    name: str = "aoe"

    def extract(self, document_id: str, text: str) -> ExtractionResult:
        try:
            from backend.app.extraction.pipeline import run_pipeline
        except ImportError as exc:
            raise RuntimeError(
                "AOEAdapter requires the backend package — install backend deps "
                "and run from the repo root. Use --adapter mock for CI."
            ) from exc

        chunks = _chunk_text(text, self.chunk_size, document_id)
        run_id = f"bench-{uuid4().hex[:12]}"

        state: dict[str, Any] = asyncio.run(
            run_pipeline(
                run_id=run_id,
                document_id=document_id,
                chunks=chunks,
                domain_context=self.domain_context,
            )
        )

        return _pipeline_state_to_result(state)


def _chunk_text(text: str, chunk_size: int, document_id: str) -> list[dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[dict[str, Any]] = []
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        if size + len(para) > chunk_size and buf:
            chunks.append(_chunk_dict(document_id, len(chunks), "\n\n".join(buf)))
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        chunks.append(_chunk_dict(document_id, len(chunks), "\n\n".join(buf)))
    return chunks


def _chunk_dict(document_id: str, index: int, text: str) -> dict[str, Any]:
    return {
        "_key": f"{document_id}-chunk-{index:04d}",
        "document_id": document_id,
        "index": index,
        "text": text,
    }


def _pipeline_state_to_result(state: dict[str, Any]) -> ExtractionResult:
    """Flatten pipeline output into the harness's class + relation sets.

    AOE's state carries ``extraction_passes[*].classes`` and ``relationships``;
    we merge across passes (the consistency checker already filters noise).
    Missing fields are tolerated — the adapter should be robust to partial
    pipeline completion so benchmark runs don't abort on a single failure.
    """
    classes: set[ClassMention] = set()
    relations: set[Triple] = set()

    passes = state.get("extraction_passes", []) or []
    for p in passes:
        for cls in p.get("classes", []) or []:
            label = cls.get("label") or cls.get("name")
            if not label:
                continue
            classes.add(ClassMention.of(str(label), str(cls.get("rdf_type", "") or "")))
        for rel in p.get("relationships", []) or p.get("edges", []) or []:
            head = rel.get("source") or rel.get("from_label") or rel.get("head")
            tail = rel.get("target") or rel.get("to_label") or rel.get("tail")
            rtype = rel.get("type") or rel.get("edge_type") or rel.get("relation")
            if head and rtype and tail:
                relations.add(Triple.of(str(head), str(rtype), str(tail)))

    stats = state.get("stats") or {}
    token_usage = stats.get("token_usage") or {}
    return ExtractionResult(
        classes=classes,
        relations=relations,
        metadata={
            "model": stats.get("model") or state.get("model"),
            "prompt_version": stats.get("prompt_version") or state.get("prompt_version"),
            "input_tokens": token_usage.get("input_tokens") or token_usage.get("prompt_tokens"),
            "output_tokens": (
                token_usage.get("output_tokens") or token_usage.get("completion_tokens")
            ),
            "total_tokens": token_usage.get("total_tokens"),
            "estimated_cost_usd": stats.get("estimated_cost_usd") or stats.get("cost_usd"),
        },
    )
