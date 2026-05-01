"""Tests for the shared WebSocket broadcaster (ws_broadcast.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.ws_broadcast import WebSocketBroadcaster


@pytest.fixture
def broadcaster():
    return WebSocketBroadcaster(keep_history=True)


@pytest.fixture
def broadcaster_no_history():
    return WebSocketBroadcaster(keep_history=False)


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self, broadcaster: WebSocketBroadcaster):
        queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        broadcaster._subscribers["run1"] = [queue]

        await broadcaster.publish(key="run1", event_type="step_completed", data={"x": 1})

        event = queue.get_nowait()
        assert event["event"] == "step_completed"
        assert event["data"] == {"x": 1}
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_publish_stores_history(self, broadcaster: WebSocketBroadcaster):
        broadcaster._subscribers["run1"] = []
        await broadcaster.publish(key="run1", event_type="test_event")

        assert len(broadcaster._history["run1"]) == 1
        assert broadcaster._history["run1"][0]["event"] == "test_event"

    @pytest.mark.asyncio
    async def test_publish_no_history_when_disabled(
        self,
        broadcaster_no_history: WebSocketBroadcaster,
    ):
        broadcaster_no_history._subscribers["run1"] = []
        await broadcaster_no_history.publish(key="run1", event_type="test_event")

        assert broadcaster_no_history._history is None

    @pytest.mark.asyncio
    async def test_publish_drops_event_on_full_queue(self, broadcaster: WebSocketBroadcaster):
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        queue.put_nowait({"event": "filler"})
        broadcaster._subscribers["run1"] = [queue]

        # Should not raise — just drops the event
        await broadcaster.publish(key="run1", event_type="dropped")

        # Queue still has original event
        assert queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_publish_extra_fields_included(self, broadcaster: WebSocketBroadcaster):
        queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        broadcaster._subscribers["run1"] = [queue]

        await broadcaster.publish(
            key="run1",
            event_type="step_started",
            step="extractor",
            run_id="run1",
        )

        event = queue.get_nowait()
        assert event["step"] == "extractor"
        assert event["run_id"] == "run1"


class TestCleanup:
    def test_cleanup_removes_subscribers_and_history(self, broadcaster: WebSocketBroadcaster):
        broadcaster._subscribers["run1"] = [asyncio.Queue()]
        broadcaster._history["run1"] = [{"event": "old"}]

        broadcaster.cleanup("run1")

        assert "run1" not in broadcaster._subscribers
        assert "run1" not in broadcaster._history

    def test_cleanup_noop_for_unknown_key(self, broadcaster: WebSocketBroadcaster):
        broadcaster.cleanup("nonexistent")  # Should not raise


class TestServe:
    @pytest.mark.asyncio
    async def test_serve_rejects_unauthenticated(self, broadcaster: WebSocketBroadcaster):
        ws = AsyncMock()
        ws.query_params = {}

        with patch("app.api.ws_broadcast.authenticate_websocket", return_value=None):
            await broadcaster.serve(ws, "run1")

        ws.close.assert_called_once_with(code=4401, reason="Unauthorized")
        ws.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_serve_accepts_authenticated(self, broadcaster: WebSocketBroadcaster):
        ws = AsyncMock()
        ws.query_params = {"token": "valid"}
        ws.send_json = AsyncMock()

        mock_user = MagicMock()
        mock_user.user_id = "user1"

        from fastapi import WebSocketDisconnect

        # Simulate immediate disconnect after connected event
        call_count = 0

        async def side_effect(msg):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise WebSocketDisconnect()

        ws.send_json.side_effect = side_effect

        with patch("app.api.ws_broadcast.authenticate_websocket", return_value=mock_user):
            await broadcaster.serve(ws, "run1", connected_data={"run_id": "run1"})

        ws.accept.assert_called_once()
        # First call is the connected event
        first_call = ws.send_json.call_args_list[0]
        assert first_call[0][0]["event"] == "connected"
