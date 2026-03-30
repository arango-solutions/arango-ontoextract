"""LangGraph StateGraph for the ontology extraction pipeline.

Nodes: strategy_selector → extractor → consistency_checker → er_agent → filter
Conditional edges retry on failure. Checkpointed via MemorySaver.
Human-in-the-loop breakpoint after pre-curation filter.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.extraction.agents.consistency import consistency_checker_node
from app.extraction.agents.er_agent import er_agent_node
from app.extraction.agents.extractor import extractor_node
from app.extraction.agents.filter import filter_agent_node
from app.extraction.agents.strategy import strategy_selector_node
from app.extraction.judges.quality_judge_node import quality_judge_node
from app.extraction.state import ExtractionPipelineState

log = logging.getLogger(__name__)

_EVENT_BUS: dict[str, Any] | None = None

_NEXT_STEP: dict[str, str] = {
    "strategy_selector": "extractor",
    "extractor": "consistency_checker",
    "consistency_checker": "quality_judge",
    "quality_judge": "er_agent",
    "er_agent": "filter",
}


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
    """Conditional edge: skip ER + filter if consistency check produced no results."""
    result = state.get("consistency_result")
    if result is None or (hasattr(result, "classes") and len(result.classes) == 0):
        return "end"
    return "continue"


def _should_proceed_to_staging(state: ExtractionPipelineState) -> str:
    """Conditional edge: proceed to staging after pre-curation filter."""
    filter_results = state.get("filter_results", {})
    if filter_results.get("status") == "failed":
        return "end"
    return "continue"


def build_pipeline() -> StateGraph:
    """Construct the LangGraph StateGraph for extraction.

    Full pipeline: Strategy → Extraction → Consistency → ER → Pre-Curation Filter → Staging.
    Includes human-in-the-loop breakpoint after pre-curation filter.
    """
    graph = StateGraph(ExtractionPipelineState)

    graph.add_node("strategy_selector", strategy_selector_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("consistency_checker", consistency_checker_node)
    graph.add_node("quality_judge", quality_judge_node)
    graph.add_node("er_agent", er_agent_node)
    graph.add_node("filter", filter_agent_node)

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
            "continue": "quality_judge",
        },
    )

    graph.add_edge("quality_judge", "er_agent")
    graph.add_edge("er_agent", "filter")

    graph.add_conditional_edges(
        "filter",
        _should_proceed_to_staging,
        {
            "end": END,
            "continue": END,
        },
    )

    return graph


def compile_pipeline(
    checkpointer: Any | None = None,
    *,
    interrupt_after_filter: bool = False,
) -> Any:
    """Compile the pipeline with checkpointing.

    Uses MemorySaver by default; accepts custom checkpointer for Redis etc.

    Parameters
    ----------
    interrupt_after_filter:
        If True, adds a human-in-the-loop breakpoint after the pre-curation
        filter. The pipeline pauses, emits a WebSocket event, and waits for
        curation decisions before proceeding to staging.
    """
    graph = build_pipeline()
    if checkpointer is None:
        checkpointer = MemorySaver()

    interrupt_after = ["filter"] if interrupt_after_filter else None

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after,
    )
    log.info(
        "extraction pipeline compiled",
        extra={
            "checkpointer": type(checkpointer).__name__,
            "interrupt_after_filter": interrupt_after_filter,
        },
    )
    return compiled


async def run_pipeline(
    *,
    run_id: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    thread_id: str | None = None,
    event_callback: Any | None = None,
    domain_context: str = "",
    domain_ontology_ids: list[str] | None = None,
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
    domain_context:
        Serialized domain ontology text for Tier 2 context-aware extraction.
    domain_ontology_ids:
        IDs of domain ontologies used as context for Tier 2 extraction.
    """
    compiled = compile_pipeline(interrupt_after_filter=True)

    initial_state: ExtractionPipelineState = {
        "run_id": run_id,
        "document_id": document_id,
        "document_chunks": chunks,
        "extraction_passes": [],
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "initialized",
        "metadata": {
            "domain_ontology_ids": domain_ontology_ids or [],
        },
        "faithfulness_scores": {},
        "validity_scores": {},
        "er_results": {},
        "filter_results": {},
        "merge_candidates": [],
        "domain_context": domain_context,
    }

    config = {"configurable": {"thread_id": thread_id or run_id}}

    log.info(
        "pipeline execution started",
        extra={"run_id": run_id, "document_id": document_id, "chunk_count": len(chunks)},
    )

    final_state: ExtractionPipelineState | None = None
    last_node: str | None = None
    try:
        if event_callback:
            await event_callback(
                run_id=run_id,
                event_type="step_started",
                step="strategy_selector",
                data={},
            )

        async for event in compiled.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                log.info(
                    "pipeline node completed",
                    extra={"run_id": run_id, "node": node_name},
                )
                last_node = node_name
                if event_callback:
                    await event_callback(
                        run_id=run_id,
                        event_type="step_completed",
                        step=node_name,
                        data={"current_step": node_name},
                    )
                    next_step = _NEXT_STEP.get(node_name)
                    if next_step:
                        await event_callback(
                            run_id=run_id,
                            event_type="step_started",
                            step=next_step,
                            data={},
                        )
                if isinstance(node_output, dict):
                    final_state = node_output
    except Exception as stream_exc:
        log.warning(
            "pipeline stream error, capturing partial state",
            extra={"run_id": run_id, "error": str(stream_exc)},
        )
        if final_state is None:
            final_state = dict(initial_state)
        final_state.setdefault("errors", []).append(str(stream_exc))

        if event_callback:
            await event_callback(
                run_id=run_id,
                event_type="error",
                step=last_node or "pipeline",
                data={"error": str(stream_exc)},
            )
            await event_callback(
                run_id=run_id,
                event_type="completed",
                step="pipeline",
                data={"errors": final_state.get("errors", [])},
            )

        return final_state

    try:
        snapshot = compiled.get_state(config)
    except Exception:
        snapshot = None
    result_state: ExtractionPipelineState = (  # type: ignore[assignment]
        snapshot.values if snapshot else (final_state or initial_state)
    )

    is_interrupted = snapshot and snapshot.next if snapshot else False
    if is_interrupted and event_callback:
        await event_callback(
            run_id=run_id,
            event_type="pipeline_paused",
            step="filter",
            data={
                "message": (
                    "Pipeline paused after pre-curation filter."
                    " Awaiting curation decisions."
                ),
                "filter_results": result_state.get("filter_results", {}),
                "merge_candidates": result_state.get("merge_candidates", []),
            },
        )
    elif event_callback:
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
