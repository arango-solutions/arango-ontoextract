"""WebSocket endpoint for curation collaboration per PRD Section 7.8.

Events: decision_made, entity_merged, staging_promoted.
Broadcasts curation decision events to all connected curators on the same session.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()

_session_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}


def _get_subscribers(session_id: str) -> list[asyncio.Queue[dict[str, Any]]]:
    return _session_subscribers.setdefault(session_id, [])


async def publish_curation_event(
    *,
    session_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    user_id: str = "",
) -> None:
    """Publish a curation event to all WebSocket subscribers for a session.

    Called by the curation service when decisions are recorded.
    """
    event = {
        "event": event_type,
        "data": data or {},
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": time.time(),
    }

    subscribers = _get_subscribers(session_id)
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning(
                "Curation WebSocket queue full, dropping event",
                extra={"session_id": session_id, "event": event_type},
            )


def cleanup_session(session_id: str) -> None:
    """Remove all subscribers for a closed session."""
    _session_subscribers.pop(session_id, None)


@router.websocket("/ws/curation/{session_id}")
async def ws_curation(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time curation collaboration.

    Curators on the same session receive events as decisions are made.
    """
    await websocket.accept()
    log.info("Curation WebSocket connected", extra={"session_id": session_id})

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    subscribers = _get_subscribers(session_id)
    subscribers.append(queue)

    try:
        await websocket.send_json({
            "event": "connected",
            "data": {"session_id": session_id},
            "timestamp": time.time(),
        })

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except TimeoutError:
                await websocket.send_json({
                    "event": "heartbeat",
                    "data": {},
                    "timestamp": time.time(),
                })

    except WebSocketDisconnect:
        log.info("Curation WebSocket disconnected", extra={"session_id": session_id})
    except Exception:
        log.exception("Curation WebSocket error", extra={"session_id": session_id})
    finally:
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            cleanup_session(session_id)
