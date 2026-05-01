"""Shared WebSocket broadcaster for real-time event distribution.

Provides a reusable event bus with subscriber management, queue-based
delivery, heartbeats, and optional event history replay.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.api.auth import authenticate_websocket

log = logging.getLogger(__name__)

_WS_QUEUE_MAXSIZE = 100
_HEARTBEAT_TIMEOUT = 30.0


class WebSocketBroadcaster:
    """Manages per-key subscriber queues and event broadcasting."""

    def __init__(self, *, keep_history: bool = False) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._history: dict[str, list[dict[str, Any]]] | None = {} if keep_history else None

    def _get_subscribers(self, key: str) -> list[asyncio.Queue[dict[str, Any]]]:
        return self._subscribers.setdefault(key, [])

    async def publish(
        self,
        *,
        key: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        """Publish an event to all subscribers for *key*."""
        event: dict[str, Any] = {
            "event": event_type,
            "data": data or {},
            "timestamp": time.time(),
            **extra,
        }

        if self._history is not None:
            self._history.setdefault(key, []).append(event)

        for queue in self._get_subscribers(key):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning(
                    "WebSocket queue full, dropping event",
                    extra={"key": key, "event": event_type},
                )

    def cleanup(self, key: str) -> None:
        """Remove all subscribers and history for *key*."""
        self._subscribers.pop(key, None)
        if self._history is not None:
            self._history.pop(key, None)

    async def serve(
        self,
        websocket: WebSocket,
        key: str,
        *,
        connected_data: dict[str, Any] | None = None,
        terminal_events: frozenset[str] = frozenset(),
    ) -> None:
        """Authenticate, accept, replay history, and stream events.

        Closes with 4401 if authentication fails.
        """
        user = await authenticate_websocket(websocket)
        if user is None:
            await websocket.close(code=4401, reason="Unauthorized")
            return

        await websocket.accept()
        log.info("WebSocket connected", extra={"key": key, "user_id": user.user_id})

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_WS_QUEUE_MAXSIZE)
        subscribers = self._get_subscribers(key)
        subscribers.append(queue)

        try:
            await websocket.send_json(
                {
                    "event": "connected",
                    "data": connected_data or {},
                    "timestamp": time.time(),
                }
            )

            # Replay missed events
            if self._history is not None:
                for past_event in self._history.get(key, []):
                    await websocket.send_json(past_event)

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_TIMEOUT)
                    await websocket.send_json(event)

                    if event.get("event") in terminal_events:
                        break
                except TimeoutError:
                    await websocket.send_json(
                        {
                            "event": "heartbeat",
                            "data": {},
                            "timestamp": time.time(),
                        }
                    )

        except WebSocketDisconnect:
            log.info("WebSocket disconnected", extra={"key": key})
        except Exception:
            log.exception("WebSocket error", extra={"key": key})
        finally:
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers:
                self.cleanup(key)
