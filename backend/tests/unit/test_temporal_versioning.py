"""Unit tests for temporal versioning service — all DB operations mocked."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.temporal import NEVER_EXPIRES, create_version, expire_entity, get_current


class TestNeverExpires:
    def test_sentinel_value(self):
        assert NEVER_EXPIRES == sys.maxsize
        assert NEVER_EXPIRES == 9223372036854775807


class TestCreateVersion:
    def test_creates_document_with_temporal_fields(self):
        mock_col = MagicMock()
        mock_col.insert.return_value = {
            "_key": "abc123",
            "new": {
                "_key": "abc123",
                "_id": "ontology_classes/abc123",
                "uri": "http://ex.org#Foo",
                "label": "Foo",
                "created": 1700000000.0,
                "expired": NEVER_EXPIRES,
                "version": 1,
                "created_by": "tester",
                "change_type": "initial",
                "change_summary": "Created Foo",
                "ttlExpireAt": None,
            },
        }
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700000000.0):
            result = create_version(
                mock_db,
                collection="ontology_classes",
                data={"uri": "http://ex.org#Foo", "label": "Foo"},
                created_by="tester",
            )

        mock_col.insert.assert_called_once()
        insert_args = mock_col.insert.call_args
        doc = insert_args[0][0]
        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] == 1700000000.0
        assert doc["created_by"] == "tester"
        assert doc["ttlExpireAt"] is None


class TestExpireEntity:
    def test_sets_expired_timestamp(self):
        mock_col = MagicMock()
        mock_col.update.return_value = {
            "new": {
                "_key": "abc123",
                "expired": 1700001000.0,
            }
        }
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700001000.0):
            result = expire_entity(
                mock_db,
                collection="ontology_classes",
                key="abc123",
            )

        mock_col.update.assert_called_once()
        update_args = mock_col.update.call_args[0][0]
        assert update_args["expired"] == 1700001000.0

    def test_returns_none_on_failure(self):
        mock_col = MagicMock()
        mock_col.update.side_effect = Exception("not found")
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        result = expire_entity(
            mock_db,
            collection="ontology_classes",
            key="missing",
        )
        assert result is None


class TestGetCurrent:
    def test_returns_current_version(self):
        mock_aql = MagicMock()
        mock_aql.execute.return_value = iter([
            {"_key": "abc", "label": "Foo", "expired": NEVER_EXPIRES}
        ])
        mock_db = MagicMock()
        mock_db.aql = mock_aql

        result = get_current(
            mock_db,
            collection="ontology_classes",
            key="abc",
        )

        assert result is not None
        assert result["_key"] == "abc"

    def test_returns_none_when_not_found(self):
        mock_aql = MagicMock()
        mock_aql.execute.return_value = iter([])
        mock_db = MagicMock()
        mock_db.aql = mock_aql

        result = get_current(
            mock_db,
            collection="ontology_classes",
            key="missing",
        )
        assert result is None
