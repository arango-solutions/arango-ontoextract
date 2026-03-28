"""LangGraph StateGraph for the ontology extraction pipeline.

Nodes: strategy_selector → extractor → consistency_checker
Conditional edges retry on failure. Checkpointed via MemorySaver.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.extraction.agents.consistency import consistency_checker_node
from app.extraction.agents.extractor import extractor_node
from app.extraction.agents.strategy import strategy_selector_node
from app.extraction.state import ExtractionPipelineState

log = logging.getLogger(__name__)

_EVENT_BUS: dict[str, Any] | None = None


def set_event_bus(bus: dict[str, Any] | None) -> None:
    """Register an event bus for pipeline step notifications (WebSocket)."""
    global _EVENT_BUS
    _EVENT_BUS = bus


def _should_retry_extraction(state: ExtractionPipelineState) -> str:
    """Conditional edge: retry extraction if all passes failed."""
    passes = state.get("extraction_passes", [])
    errors = state.get("errors", [])

    if not passes and errors:
        retry_count = sum(1 for e in errors if "retry" in e.lower())
        if retry_count < 2:
            return "retry"
    return "continue"


def _should_retry_consistency(state: ExtractionPipelineState) -> str:
    """Conditional edge: end if consistency check produced no results."""
    result = state.get("consistency_result")
    if result is None or (hasattr(result, "classes") and len(result.classes) == 0):
        errors = state.get("errors", [])
        if any("No extraction passes" in e for e in errors):
            return "end"
        return "end"
    return "continue"


def build_pipeline() -> StateGraph:
    """Construct the LangGraph StateGraph for extraction.

    Returns the compiled graph with MemorySaver checkpointing.
    """
    graph = StateGraph(ExtractionPipelineState)

    graph.add_node("strategy_selector", strategy_selector_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("consistency_checker", consistency_checker_node)

    graph.set_entry_point("strategy_selector")
    graph.add_edge("strategy_selector", "extractor")

    graph.add_conditional_edges(
        "extractor",
        _should_retry_extraction,
        {
            "retry": "extractor",
            "continue": "consistency_checker",
        },
    )

    graph.add_conditional_edges(
        "consistency_checker",
        _should_retry_consistency,
        {
            "end": END,
            "continue": END,
        },
    )

    return graph


def compile_pipeline(checkpointer: Any | None = None) -> Any:
    """Compile the pipeline with checkpointing.

    Uses MemorySaver by default; accepts custom checkpointer for Redis etc.
    """
    graph = build_pipeline()
    if checkpointer is None:
        checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)
    log.info("extraction pipeline compiled", extra={"checkpointer": type(checkpointer).__name__})
    return compiled


async def run_pipeline(
    *,
    run_id: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    thread_id: str | None = None,
    event_callback: Any | None = None,
) -> ExtractionPipelineState:
    """Execute the extraction pipeline end-to-end.

    Parameters
    ----------
    run_id:
        Unique identifier for this extraction run.
    document_id:
        The document being processed.
    chunks:
        Document chunks to extract from.
    thread_id:
        LangGraph thread for checkpoint resume. Defaults to run_id.
    event_callback:
        Async callable invoked with step events for WebSocket broadcasting.
    """
    compiled = compile_pipeline()

    initial_state: ExtractionPipelineState = {
        "run_id": run_id,
        "document_id": document_id,
        "document_chunks": chunks,
        "extraction_passes": [],
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "initialized",
        "metadata": {},
    }

    config = {"configurable": {"thread_id": thread_id or run_id}}

    log.info(
        "pipeline execution started",
        extra={"run_id": run_id, "document_id": document_id, "chunk_count": len(chunks)},
    )

    final_state: ExtractionPipelineState | None = None
    async for event in compiled.astream(initial_state, config=config):
        for node_name, node_output in event.items():
            log.info(
                "pipeline node completed",
                extra={"run_id": run_id, "node": node_name},
            )
            if event_callback:
                await event_callback(
                    run_id=run_id,
                    event_type="step_completed",
                    step=node_name,
                    data={"current_step": node_name},
                )
            final_state = node_output if isinstance(node_output, dict) else final_state

    snapshot = compiled.get_state(config)
    result_state: ExtractionPipelineState = (  # type: ignore[assignment]
        snapshot.values if snapshot else (final_state or initial_state)
    )

    if event_callback:
        await event_callback(
            run_id=run_id,
            event_type="completed",
            step="pipeline",
            data={
                "consistency_result": result_state.get("consistency_result") is not None,
                "errors": result_state.get("errors", []),
            },
        )

    log.info(
        "pipeline execution completed",
        extra={
            "run_id": run_id,
            "steps": len(result_state.get("step_logs", [])),
            "errors": len(result_state.get("errors", [])),
        },
    )

    return result_state
