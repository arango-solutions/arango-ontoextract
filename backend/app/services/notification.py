"""Notification service — PRD Section 8.8.

Writes notifications to the ``notifications`` collection and publishes
events to Redis Pub/Sub for real-time delivery.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from arango.database import StandardDatabase

from app.config import settings
from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get, run_aql
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

NOTIFICATIONS_COLLECTION = "notifications"
_REDIS_CHANNEL = "aoe:notifications"


class NotificationType(StrEnum):
    EXTRACTION_COMPLETE = "extraction_complete"
    CURATION_NEEDED = "curation_needed"
    MERGE_SUGGESTED = "merge_suggested"
    PROMOTION_DONE = "promotion_done"
    ERROR = "error"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_redis():
    """Lazy Redis connection for pub/sub. Returns None if unavailable."""
    try:
        import redis as redis_lib  # type: ignore[import-untyped]

        return redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        log.warning("Redis unavailable for notification pub/sub")
        return None


def create_notification(
    *,
    user_id: str,
    org_id: str,
    notification_type: NotificationType | str,
    title: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    db: StandardDatabase | None = None,
) -> dict:
    """Create and persist a notification, then publish to Redis Pub/Sub."""
    db = db or get_db()
    col = db.collection(NOTIFICATIONS_COLLECTION)

    doc = {
        "user_id": user_id,
        "org_id": org_id,
        "type": str(notification_type),
        "title": title,
        "message": message,
        "metadata": metadata or {},
        "read": False,
        "created_at": _now_iso(),
    }

    result = cast("dict[str, Any]", col.insert(doc, return_new=True))
    notification = result["new"]

    _publish_to_redis(notification)

    return notification


def _publish_to_redis(notification: dict) -> None:
    """Best-effort publish to Redis Pub/Sub."""
    r = _get_redis()
    if r is None:
        return
    try:
        payload = {
            "_key": notification["_key"],
            "user_id": notification["user_id"],
            "org_id": notification["org_id"],
            "type": notification["type"],
            "title": notification["title"],
            "created_at": notification["created_at"],
        }
        r.publish(_REDIS_CHANNEL, json.dumps(payload))
    except Exception:
        log.warning("Failed to publish notification to Redis", exc_info=True)
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            r.close()


def list_notifications(
    user_id: str,
    *,
    limit: int = 25,
    cursor: str | None = None,
    db: StandardDatabase | None = None,
) -> PaginatedResponse[dict]:
    """Paginated notifications for a user, newest first."""
    db = db or get_db()
    return paginate(
        db,
        collection=NOTIFICATIONS_COLLECTION,
        sort_field="created_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
        filters={"user_id": user_id},
    )


def mark_as_read(
    notification_id: str,
    user_id: str,
    *,
    db: StandardDatabase | None = None,
) -> dict | None:
    """Mark a notification as read. Returns updated doc or None."""
    db = db or get_db()
    col = db.collection(NOTIFICATIONS_COLLECTION)
    try:
        doc = doc_get(col, notification_id)
    except Exception:
        return None

    if doc is None or doc.get("user_id") != user_id:
        return None

    result = cast(
        "dict[str, Any]",
        col.update(
            {"_key": notification_id, "read": True, "read_at": _now_iso()},
            return_new=True,
        ),
    )
    return result["new"]


def get_unread_count(
    user_id: str,
    *,
    db: StandardDatabase | None = None,
) -> int:
    """Count unread notifications for a user."""
    db = db or get_db()
    query = """\
FOR n IN @@col
  FILTER n.user_id == @user_id
  FILTER n.read != true
  COLLECT WITH COUNT INTO c
  RETURN c"""
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"@col": NOTIFICATIONS_COLLECTION, "user_id": user_id},
        )
    )
    return int(rows[0]) if rows else 0
