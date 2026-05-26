"""Unit tests for temporal versioning service — all DB operations mocked."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from app.services.temporal import NEVER_EXPIRES, create_version, expire_entity, get_current


class TestNeverExpires:
    def test_sentinel_value(self):
        assert sys.maxsize == NEVER_EXPIRES
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
            create_version(
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
            expire_entity(
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

    def test_default_ttl_expires_history_after_90_days(self):
        """Stream 7 PR 1 -- E.3 bugfix coverage.

        Prior to PR 1, ``expire_entity`` only stamped ``ttlExpireAt``
        when callers explicitly passed ``ttl_seconds``. ``update_entity``
        (and every higher-level path that went through it) never did,
        which meant superseded vertex versions accumulated forever
        even though the TTL index from migration 006 was sitting
        ready to GC them. Pin the new default behaviour so the bug
        cannot regress.
        """
        mock_col = MagicMock()
        mock_col.update.return_value = {"new": {"_key": "k", "expired": 1700001000.0}}
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700001000.0):
            expire_entity(mock_db, collection="ontology_classes", key="k")

        update_args = mock_col.update.call_args[0][0]
        # 90 days = 7_776_000 s (the PRD default). The ttlExpireAt MUST
        # be set even though the caller did not pass ttl_seconds.
        assert update_args["ttlExpireAt"] == 1700001000.0 + 7_776_000

    def test_explicit_ttl_seconds_override_default(self):
        mock_col = MagicMock()
        mock_col.update.return_value = {"new": {"_key": "k", "expired": 1700001000.0}}
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700001000.0):
            expire_entity(
                mock_db,
                collection="ontology_classes",
                key="k",
                ttl_seconds=3600,
            )

        update_args = mock_col.update.call_args[0][0]
        assert update_args["ttlExpireAt"] == 1700001000.0 + 3600

    def test_ttl_seconds_zero_opts_out_of_stamp(self):
        """A forensic-capture mode: pass ttl_seconds=0 to keep history
        forever. ttlExpireAt must NOT be written -- a value of 0 would
        set it to ``now + 0`` and the TTL index would GC the row
        immediately, which is the opposite of what the caller asked for.
        """
        mock_col = MagicMock()
        mock_col.update.return_value = {"new": {"_key": "k", "expired": 1700001000.0}}
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700001000.0):
            expire_entity(
                mock_db,
                collection="ontology_classes",
                key="k",
                ttl_seconds=0,
            )

        update_args = mock_col.update.call_args[0][0]
        assert "ttlExpireAt" not in update_args
        assert update_args["expired"] == 1700001000.0

    def test_negative_ttl_seconds_also_opts_out(self):
        """Defensive: a negative ttl_seconds would set ttlExpireAt in
        the past and trip immediate GC. We treat it as opt-out rather
        than data-loss surprise.
        """
        mock_col = MagicMock()
        mock_col.update.return_value = {"new": {"_key": "k", "expired": 1700001000.0}}
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with patch("app.services.temporal._now", return_value=1700001000.0):
            expire_entity(
                mock_db,
                collection="ontology_classes",
                key="k",
                ttl_seconds=-1,
            )

        update_args = mock_col.update.call_args[0][0]
        assert "ttlExpireAt" not in update_args

    def test_retention_setting_drives_default(self):
        """Operator-facing knob: ``settings.temporal_retention_seconds``
        controls the default. We patch the helper that reads it so we
        can pin the wiring without touching the actual pydantic
        Settings (which would force us to think about env-var loading
        in a unit test).
        """
        mock_col = MagicMock()
        mock_col.update.return_value = {"new": {"_key": "k", "expired": 1700001000.0}}
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        with (
            patch("app.services.temporal._now", return_value=1700001000.0),
            patch(
                "app.services.temporal._default_ttl_seconds",
                return_value=2_592_000,  # 30 days
            ),
        ):
            expire_entity(mock_db, collection="ontology_classes", key="k")

        update_args = mock_col.update.call_args[0][0]
        assert update_args["ttlExpireAt"] == 1700001000.0 + 2_592_000


class TestGetCurrent:
    def test_returns_current_version(self):
        mock_aql = MagicMock()
        mock_aql.execute.return_value = iter(
            [{"_key": "abc", "label": "Foo", "expired": NEVER_EXPIRES}]
        )
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
