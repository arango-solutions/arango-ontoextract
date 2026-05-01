"""Unit tests for WebSocket event publishing in the extraction pipeline.

Verifies that run_pipeline emits step_started, step_completed, error, and
completed events via the event_callback, and that execute_run defaults to
publish_event when no callback is supplied.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extraction.pipeline import _NEXT_STEPS, run_pipeline


async def _empty_stream() -> AsyncIterator[dict[str, Any]]:
    return
    yield  # makes this an async generator


class TestPipelineStepEvents:
    """Verify event_callback is called with correct event types and ordering."""

    @pytest.mark.asyncio
    async def test_emits_step_started_before_stream(self):
        """step_started for strategy_selector fires before the stream loop."""
        callback = AsyncMock()

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: _empty_stream()
        mock_compiled.get_state.return_value = None

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        first_call = callback.call_args_list[0]
        assert first_call.kwargs["event_type"] == "step_started"
        assert first_call.kwargs["step"] == "strategy_selector"

    @pytest.mark.asyncio
    async def test_emits_step_completed_and_next_started(self):
        """After a node completes, step_completed fires, then step_started for the next node."""
        callback = AsyncMock()

        async def fake_stream():
            yield {"strategy_selector": {}}
            yield {"extractor": {}}

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: fake_stream()
        mock_compiled.get_state.return_value = None

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        event_types = [c.kwargs["event_type"] for c in callback.call_args_list]
        event_steps = [c.kwargs["step"] for c in callback.call_args_list]

        assert (event_types[0], event_steps[0]) == ("step_started", "strategy_selector")
        assert (event_types[1], event_steps[1]) == ("step_completed", "strategy_selector")
        assert (event_types[2], event_steps[2]) == ("step_started", "extractor")
        assert (event_types[3], event_steps[3]) == ("step_completed", "extractor")
        assert (event_types[4], event_steps[4]) == ("step_started", "consistency_checker")

    @pytest.mark.asyncio
    async def test_last_node_does_not_emit_next_started(self):
        """The filter node (last in pipeline) should not emit a step_started for a next node."""
        callback = AsyncMock()

        async def fake_stream():
            yield {"filter": {}}

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: fake_stream()
        mock_compiled.get_state.return_value = None

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        step_started_steps = [
            c.kwargs["step"]
            for c in callback.call_args_list
            if c.kwargs["event_type"] == "step_started"
        ]
        assert "filter" not in _NEXT_STEPS
        for step in step_started_steps:
            assert step != "__end__"

    @pytest.mark.asyncio
    async def test_emits_completed_on_success(self):
        """A successful pipeline run emits a completed event at the end."""
        callback = AsyncMock()

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: _empty_stream()
        mock_compiled.get_state.return_value = None

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        last_call = callback.call_args_list[-1]
        assert last_call.kwargs["event_type"] == "completed"
        assert last_call.kwargs["step"] == "pipeline"


class TestPipelineErrorEvents:
    """Verify error event emission when the stream raises."""

    @pytest.mark.asyncio
    async def test_emits_error_and_completed_on_stream_failure(self):
        """When astream raises, both error and completed events fire."""
        callback = AsyncMock()

        async def failing_stream():
            yield {"strategy_selector": {}}
            raise RuntimeError("LLM provider timeout")

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: failing_stream()

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            result = await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        event_types = [c.kwargs["event_type"] for c in callback.call_args_list]
        assert "error" in event_types
        assert event_types[-1] == "completed"

        error_call = next(c for c in callback.call_args_list if c.kwargs["event_type"] == "error")
        assert "LLM provider timeout" in error_call.kwargs["data"]["error"]
        assert error_call.kwargs["step"] == "strategy_selector"

        assert "LLM provider timeout" in result.get("errors", [])[0]

    @pytest.mark.asyncio
    async def test_error_step_defaults_to_pipeline_when_no_node(self):
        """If no node has completed before the error, step defaults to 'pipeline'."""
        callback = AsyncMock()

        async def immediate_fail():
            raise ValueError("bad config")
            yield  # makes this an async generator

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: immediate_fail()

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        error_call = next(c for c in callback.call_args_list if c.kwargs["event_type"] == "error")
        assert error_call.kwargs["step"] == "pipeline"

    @pytest.mark.asyncio
    async def test_no_error_when_callback_is_none(self):
        """Pipeline handles event_callback=None gracefully (no AttributeError)."""

        async def failing_stream():
            raise RuntimeError("boom")
            yield  # makes this an async generator

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: failing_stream()

        with patch("app.extraction.pipeline.compile_pipeline", return_value=mock_compiled):
            result = await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=None,
            )

        assert "boom" in result.get("errors", [])[0]


class TestExecuteRunDefaultCallback:
    """Verify execute_run wires publish_event as default callback."""

    @pytest.mark.asyncio
    async def test_defaults_to_publish_event(self):
        """When event_callback is None, execute_run uses ws publish_event."""
        captured_callback: list[Any] = []

        async def spy_run_pipeline(**kwargs):
            captured_callback.append(kwargs.get("event_callback"))
            return {
                "errors": [],
                "consistency_result": None,
                "token_usage": {},
                "step_logs": [],
            }

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "_key": "r1",
            "doc_id": "d1",
            "status": "running",
            "stats": {"token_usage": {}, "errors": [], "step_logs": []},
        }
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_col

        with (
            patch("app.services.extraction.get_db", return_value=mock_db),
            patch("app.services.extraction.run_pipeline", spy_run_pipeline),
            patch("app.services.extraction._load_document_chunks", return_value=[]),
        ):
            from app.services.extraction import execute_run

            await execute_run(run_id="r1", document_id="d1")

        assert len(captured_callback) == 1
        from app.api.ws_extraction import publish_event

        assert captured_callback[0] is publish_event

    @pytest.mark.asyncio
    async def test_uses_custom_callback_when_provided(self):
        """When a custom event_callback is passed, it is used instead of publish_event."""
        custom_cb = AsyncMock()
        captured_callback: list[Any] = []

        async def spy_run_pipeline(**kwargs):
            captured_callback.append(kwargs.get("event_callback"))
            return {
                "errors": [],
                "consistency_result": None,
                "token_usage": {},
                "step_logs": [],
            }

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "_key": "r1",
            "doc_id": "d1",
            "status": "running",
            "stats": {"token_usage": {}, "errors": [], "step_logs": []},
        }
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_col

        with (
            patch("app.services.extraction.get_db", return_value=mock_db),
            patch("app.services.extraction.run_pipeline", spy_run_pipeline),
            patch("app.services.extraction._load_document_chunks", return_value=[]),
        ):
            from app.services.extraction import execute_run

            await execute_run(run_id="r1", document_id="d1", event_callback=custom_cb)

        assert captured_callback[0] is custom_cb


class TestPublishEventBroadcast:
    """Verify ws_extraction.publish_event broadcasts to subscribers."""

    @pytest.mark.asyncio
    async def test_publishes_to_subscribed_queues(self):
        from app.api.ws_extraction import _broadcaster, publish_event

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10)
        _broadcaster._subscribers.setdefault("run_x", []).append(queue)

        try:
            await publish_event(
                run_id="run_x",
                event_type="step_completed",
                step="extractor",
                data={"key": "value"},
            )

            event = queue.get_nowait()
            assert event["event"] == "step_completed"
            assert event["step"] == "extractor"
            assert event["data"] == {"key": "value"}
            assert event["run_id"] == "run_x"
            assert "timestamp" in event
        finally:
            _broadcaster._subscribers.pop("run_x", None)

    @pytest.mark.asyncio
    async def test_no_error_when_no_subscribers(self):
        """publish_event handles zero subscribers gracefully."""
        from app.api.ws_extraction import publish_event

        await publish_event(
            run_id="no_such_run",
            event_type="step_completed",
            step="extractor",
            data={},
        )

    @pytest.mark.asyncio
    async def test_drops_event_on_full_queue(self):
        """When a subscriber queue is full, the event is dropped without raising."""
        from app.api.ws_extraction import _broadcaster, publish_event

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        queue.put_nowait({"dummy": True})
        _broadcaster._subscribers.setdefault("run_full", []).append(queue)

        try:
            await publish_event(
                run_id="run_full",
                event_type="step_completed",
                step="extractor",
                data={},
            )
            assert queue.qsize() == 1
        finally:
            _broadcaster._subscribers.pop("run_full", None)
