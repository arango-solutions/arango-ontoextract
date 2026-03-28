"""Unit tests for notification service — PRD Section 8.8."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.notification import (
    NotificationType,
    create_notification,
    get_unread_count,
    mark_as_read,
)


@pytest.fixture()
def mock_db():
    """Provide a mock ArangoDB database."""
    db = MagicMock()
    col = MagicMock()
    db.collection.return_value = col
    return db


@pytest.fixture()
def mock_col(mock_db):
    return mock_db.collection.return_value


class TestCreateNotification:
    """Tests for ``create_notification``."""

    @patch("app.services.notification._publish_to_redis")
    def test_creates_notification(self, mock_publish, mock_db, mock_col):
        mock_col.insert.return_value = {
            "new": {
                "_key": "notif-1",
                "user_id": "user-1",
                "org_id": "org-1",
                "type": "extraction_complete",
                "title": "Extraction Done",
                "message": "Your extraction is complete",
                "metadata": {},
                "read": False,
                "created_at": "2026-03-27T12:00:00+00:00",
            }
        }

        result = create_notification(
            user_id="user-1",
            org_id="org-1",
            notification_type=NotificationType.EXTRACTION_COMPLETE,
            title="Extraction Done",
            message="Your extraction is complete",
            db=mock_db,
        )

        assert result["_key"] == "notif-1"
        assert result["type"] == "extraction_complete"
        assert result["read"] is False

        mock_col.insert.assert_called_once()
        inserted = mock_col.insert.call_args[0][0]
        assert inserted["user_id"] == "user-1"
        assert inserted["org_id"] == "org-1"
        assert inserted["type"] == "extraction_complete"

        mock_publish.assert_called_once()

    @patch("app.services.notification._publish_to_redis")
    def test_creates_notification_with_metadata(self, mock_publish, mock_db, mock_col):
        meta = {"run_id": "run-123", "entity_count": 42}
        mock_col.insert.return_value = {
            "new": {
                "_key": "notif-2",
                "user_id": "user-1",
                "org_id": "org-1",
                "type": "merge_suggested",
                "title": "Merge Candidates",
                "message": "42 merge candidates found",
                "metadata": meta,
                "read": False,
                "created_at": "2026-03-27T12:00:00+00:00",
            }
        }

        result = create_notification(
            user_id="user-1",
            org_id="org-1",
            notification_type=NotificationType.MERGE_SUGGESTED,
            title="Merge Candidates",
            message="42 merge candidates found",
            metadata=meta,
            db=mock_db,
        )

        assert result["metadata"]["run_id"] == "run-123"


class TestMarkAsRead:
    """Tests for ``mark_as_read``."""

    def test_marks_read(self, mock_db, mock_col):
        mock_col.get.return_value = {
            "_key": "notif-1",
            "user_id": "user-1",
            "read": False,
        }
        mock_col.update.return_value = {
            "new": {"_key": "notif-1", "user_id": "user-1", "read": True}
        }

        result = mark_as_read("notif-1", "user-1", db=mock_db)
        assert result is not None
        assert result["read"] is True
        mock_col.update.assert_called_once()

    def test_returns_none_for_missing(self, mock_db, mock_col):
        mock_col.get.return_value = None
        result = mark_as_read("notif-missing", "user-1", db=mock_db)
        assert result is None

    def test_returns_none_for_wrong_user(self, mock_db, mock_col):
        mock_col.get.return_value = {
            "_key": "notif-1",
            "user_id": "other-user",
            "read": False,
        }
        result = mark_as_read("notif-1", "user-1", db=mock_db)
        assert result is None
        mock_col.update.assert_not_called()


class TestGetUnreadCount:
    """Tests for ``get_unread_count``."""

    def test_returns_count(self, mock_db):
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter([5]))
        mock_db.aql.execute.return_value = mock_cursor

        count = get_unread_count("user-1", db=mock_db)
        assert count == 5

    def test_returns_zero_when_empty(self, mock_db):
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter([0]))
        mock_db.aql.execute.return_value = mock_cursor

        count = get_unread_count("user-1", db=mock_db)
        assert count == 0


class TestNotificationType:
    """Tests for notification type enum values."""

    def test_all_types_exist(self):
        assert NotificationType.EXTRACTION_COMPLETE == "extraction_complete"
        assert NotificationType.CURATION_NEEDED == "curation_needed"
        assert NotificationType.MERGE_SUGGESTED == "merge_suggested"
        assert NotificationType.PROMOTION_DONE == "promotion_done"
        assert NotificationType.ERROR == "error"

    def test_string_conversion(self):
        assert str(NotificationType.EXTRACTION_COMPLETE) == "extraction_complete"
