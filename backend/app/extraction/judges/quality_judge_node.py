"""Quality Judge pipeline node — orchestrates faithfulness and semantic validation.

Runs after the consistency checker, before the ER agent. Calls both LLM judges
in parallel via asyncio.gather and stores per-class scores in pipeline state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.extraction.judges.faithfulness import judge_faithfulness
from app.extraction.judges.semantic_validator import validate_semantics
from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)


async def quality_judge_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node: run faithfulness + semantic validation judges in parallel.

    Reads the merged class list from consistency_result and the original
    document chunks, then calls both LLM judges concurrently.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    list(state.get("errors", []))

    consistency_result = state.get("consistency_result")
    chunks = state.get("document_chunks", [])
    config = state.get("strategy_config", {})
    model_name = config.get("model_name", settings.llm_extraction_model)

    if consistency_result is None or not consistency_result.classes:
        log.warning(
            "quality_judge: no consistency result, skipping",
            extra={"run_id": run_id},
        )
        step_log = StepLog(
            step="quality_judge",
            status="skipped",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error="No consistency result available",
        )
        return {
            "faithfulness_scores": {},
            "validity_scores": {},
            "step_logs": [step_log],
        }

    classes: list[ExtractedClass] = consistency_result.classes

    log.info(
        "quality_judge started",
        extra={
            "run_id": run_id,
            "class_count": len(classes),
            "chunk_count": len(chunks),
        },
    )

    faithfulness_scores, validity_scores = await asyncio.gather(
        judge_faithfulness(classes, chunks, model_name=model_name),
        validate_semantics(classes, model_name=model_name),
    )

    updated_classes: list[ExtractedClass] = []
    for cls in classes:
        updated_classes.append(
            cls.model_copy(
                update={
                    "faithfulness_score": faithfulness_scores.get(cls.uri, 0.5),
                    "semantic_validity_score": validity_scores.get(cls.uri, 0.8),
                }
            )
        )

    updated_result = consistency_result.model_copy(update={"classes": updated_classes})

    duration = time.time() - start
    step_log = StepLog(
        step="quality_judge",
        status="completed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=None,
        metadata={
            "class_count": len(classes),
            "avg_faithfulness": (
                round(sum(faithfulness_scores.values()) / len(faithfulness_scores), 3)
                if faithfulness_scores
                else 0.0
            ),
            "avg_validity": (
                round(sum(validity_scores.values()) / len(validity_scores), 3)
                if validity_scores
                else 0.0
            ),
        },
    )

    log.info(
        "quality_judge completed",
        extra={
            "run_id": run_id,
            "duration_seconds": round(duration, 3),
            "avg_faithfulness": step_log.get("metadata", {}).get("avg_faithfulness"),
            "avg_validity": step_log.get("metadata", {}).get("avg_validity"),
        },
    )

    return {
        "consistency_result": updated_result,
        "faithfulness_scores": faithfulness_scores,
        "validity_scores": validity_scores,
        "step_logs": [step_log],
    }
