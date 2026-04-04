"""Strategy Selector agent — analyzes document type + length to pick extraction config."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.extraction.state import ExtractionPipelineState, StepLog, StrategyConfig

log = logging.getLogger(__name__)

_SHORT_DOC_THRESHOLD = 10
_LONG_DOC_THRESHOLD = 50

_STRATEGIES: dict[str, StrategyConfig] = {
    "short_technical": StrategyConfig(
        model_name=settings.llm_extraction_model,
        prompt_template_key="tier1_technical",
        chunk_batch_size=5,
        num_passes=settings.extraction_passes,
        consistency_threshold=settings.extraction_consistency_threshold,
        document_type="short_technical",
    ),
    "long_narrative": StrategyConfig(
        model_name=settings.llm_extraction_model,
        prompt_template_key="tier1_standard",
        chunk_batch_size=3,
        num_passes=settings.extraction_passes,
        consistency_threshold=settings.extraction_consistency_threshold,
        document_type="long_narrative",
    ),
    "tabular_structured": StrategyConfig(
        model_name=settings.llm_extraction_model,
        prompt_template_key="tier1_technical",
        chunk_batch_size=8,
        num_passes=max(2, settings.extraction_passes - 1),
        consistency_threshold=settings.extraction_consistency_threshold,
        document_type="tabular_structured",
    ),
    "default": StrategyConfig(
        model_name=settings.llm_extraction_model,
        prompt_template_key="tier1_standard",
        chunk_batch_size=5,
        num_passes=settings.extraction_passes,
        consistency_threshold=settings.extraction_consistency_threshold,
        document_type="default",
    ),
}


def _classify_document(chunks: list[dict[str, Any]]) -> str:
    """Classify document type based on chunk content and count."""
    num_chunks = len(chunks)

    table_indicators = 0
    technical_indicators = 0
    total_text_length = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        total_text_length += len(text)

        if "|" in text and text.count("|") > 4:
            table_indicators += 1
        if any(kw in text.lower() for kw in ("specification", "requirement", "rfc", "iso")):
            technical_indicators += 1

    table_ratio = table_indicators / max(num_chunks, 1)
    technical_ratio = technical_indicators / max(num_chunks, 1)

    if table_ratio > 0.3:
        return "tabular_structured"
    if num_chunks <= _SHORT_DOC_THRESHOLD and technical_ratio > 0.2:
        return "short_technical"
    if num_chunks > _LONG_DOC_THRESHOLD:
        return "long_narrative"
    if technical_ratio > 0.2:
        return "short_technical"
    return "default"


def strategy_selector_node(state: ExtractionPipelineState) -> dict:
    """LangGraph node: select extraction strategy based on document characteristics.

    When domain_context is present in the state (Tier 2 extraction), the
    strategy overrides the prompt template to ``tier2_standard`` so the
    extractor uses context-aware prompts.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    chunks = state.get("document_chunks", [])
    domain_context = state.get("domain_context", "")

    log.info("strategy_selector started", extra={"run_id": run_id, "chunk_count": len(chunks)})

    doc_type = _classify_document(chunks)
    config = dict(_STRATEGIES.get(doc_type, _STRATEGIES["default"]))

    is_tier2 = bool(domain_context)
    if is_tier2:
        config["prompt_template_key"] = "tier2_standard"
        log.info(
            "tier 2 domain context detected, using tier2_standard template",
            extra={"run_id": run_id, "context_length": len(domain_context)},
        )

    duration = time.time() - start
    step_log = StepLog(
        step="strategy_selector",
        status="completed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=None,
        metadata={
            "document_type": doc_type,
            "chunk_count": len(chunks),
            "is_tier2": is_tier2,
        },
    )

    log.info(
        "strategy_selector completed",
        extra={
            "run_id": run_id,
            "document_type": doc_type,
            "model": config.get("model_name"),
            "num_passes": config.get("num_passes"),
            "prompt_template_key": config.get("prompt_template_key"),
            "duration_seconds": round(duration, 3),
        },
    )

    return {
        "strategy_config": config,
        "step_logs": [step_log],
    }
