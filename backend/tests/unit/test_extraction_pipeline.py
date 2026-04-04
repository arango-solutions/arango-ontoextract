"""Unit tests for extraction pipeline compilation, conditional edges, and run_pipeline.

Complements test_pipeline_events.py which covers WebSocket event emission.
These tests focus on pipeline structure, conditional edge logic, and compile options.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.extraction.pipeline import (
    _NEXT_STEPS,
    _should_proceed_to_staging,
    _should_retry_consistency,
    _should_retry_extraction,
    build_pipeline,
    compile_pipeline,
    set_event_bus,
)

# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------


class TestShouldRetryExtraction:
    def test_continue_when_passes_exist(self):
        state = {"extraction_passes": [MagicMock()], "errors": []}
        assert _should_retry_extraction(state) == "continue"

    def test_continue_when_no_errors(self):
        state = {"extraction_passes": [], "errors": []}
        assert _should_retry_extraction(state) == "continue"

    def test_retry_when_no_passes_and_errors_with_retry(self):
        state = {"extraction_passes": [], "errors": ["retry needed"]}
        assert _should_retry_extraction(state) == "retry"

    def test_continue_after_two_retries(self):
        state = {
            "extraction_passes": [],
            "errors": ["retry 1", "retry 2"],
        }
        assert _should_retry_extraction(state) == "continue"

    def test_retry_on_first_retry_error(self):
        state = {"extraction_passes": [], "errors": ["first retry attempt"]}
        assert _should_retry_extraction(state) == "retry"


class TestShouldRetryConsistency:
    def test_end_when_no_result(self):
        state = {"consistency_result": None}
        assert _should_retry_consistency(state) == "end"

    def test_end_when_empty_classes(self):
        mock_result = MagicMock()
        mock_result.classes = []
        state = {"consistency_result": mock_result}
        assert _should_retry_consistency(state) == "end"

    def test_continue_when_classes_exist(self):
        mock_result = MagicMock()
        mock_result.classes = [MagicMock()]
        state = {"consistency_result": mock_result}
        assert _should_retry_consistency(state) == "continue"


class TestShouldProceedToStaging:
    def test_end_when_filter_failed(self):
        state = {"filter_results": {"status": "failed"}}
        assert _should_proceed_to_staging(state) == "end"

    def test_continue_when_filter_succeeded(self):
        state = {"filter_results": {"status": "completed"}}
        assert _should_proceed_to_staging(state) == "continue"

    def test_continue_when_no_filter_results(self):
        state = {"filter_results": {}}
        assert _should_proceed_to_staging(state) == "continue"


# ---------------------------------------------------------------------------
# Pipeline build and compile
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    def test_returns_state_graph(self):
        graph = build_pipeline()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        graph = build_pipeline()
        node_names = set(graph.nodes.keys())
        expected = {
            "strategy_selector", "extractor", "consistency_checker",
            "quality_judge", "er_agent", "filter",
        }
        assert expected.issubset(node_names)


class TestCompilePipeline:
    def test_compiles_with_default_checkpointer(self):
        compiled = compile_pipeline()
        assert compiled is not None

    def test_compiles_with_custom_checkpointer(self):
        compiled = compile_pipeline(MemorySaver())
        assert compiled is not None

    def test_compiles_with_interrupt_after_filter(self):
        compiled = compile_pipeline(interrupt_after_filter=True)
        assert compiled is not None


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class TestSetEventBus:
    def test_sets_and_clears_event_bus(self):
        bus = {"key": "value"}
        set_event_bus(bus)
        from app.extraction.pipeline import _EVENT_BUS
        assert _EVENT_BUS is bus

        set_event_bus(None)
        from app.extraction import pipeline
        assert pipeline._EVENT_BUS is None


# ---------------------------------------------------------------------------
# NEXT_STEPS mapping
# ---------------------------------------------------------------------------


class TestNextStepsMapping:
    def test_has_expected_transitions(self):
        assert _NEXT_STEPS["strategy_selector"] == ["extractor"]
        assert _NEXT_STEPS["extractor"] == ["consistency_checker"]
        assert _NEXT_STEPS["consistency_checker"] == ["quality_judge", "er_agent"]
        assert _NEXT_STEPS["quality_judge"] == ["filter"]
        assert _NEXT_STEPS["er_agent"] == ["filter"]

    def test_filter_not_in_next_steps(self):
        assert "filter" not in _NEXT_STEPS


# ---------------------------------------------------------------------------
# run_pipeline: interrupted (paused) state
# ---------------------------------------------------------------------------


class TestRunPipelinePaused:
    @pytest.mark.asyncio
    async def test_emits_pipeline_paused_on_interrupt(self):
        callback = AsyncMock()

        async def fake_stream():
            yield {"filter": {"filter_results": {"status": "ok"}}}

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "filter_results": {"status": "ok"},
            "merge_candidates": [{"a": 1}],
            "errors": [],
            "step_logs": [],
        }
        mock_snapshot.next = ["staging"]  # truthy means interrupted

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: fake_stream()
        mock_compiled.get_state.return_value = mock_snapshot

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            from app.extraction.pipeline import run_pipeline
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        event_types = [c.kwargs["event_type"] for c in callback.call_args_list]
        assert "pipeline_paused" in event_types
