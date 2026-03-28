"""Notification REST endpoints — PRD Section 8.8.

Paginated listing, mark-as-read, and unread count for the current user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.api.auth import AuthenticatedUser
from app.api.dependencies import get_current_user
from app.api.errors import NotFoundError
from app.models.common import PaginatedResponse
from app.services import notification as notif_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> PaginatedResponse[dict]:
    """Paginated list of notifications for the current user."""
    return notif_svc.list_notifications(user.user_id, limit=limit, cursor=cursor)


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    """Mark a notification as read."""
    updated = notif_svc.mark_as_read(notification_id, user.user_id)
    if updated is None:
        raise NotFoundError(
            f"Notification '{notification_id}' not found",
            details={"notification_id": notification_id},
        )
    return updated


@router.get("/unread-count")
async def get_unread_count(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    """Get the count of unread notifications for the current user."""
    count = notif_svc.get_unread_count(user.user_id)
    return {"unread_count": count}
