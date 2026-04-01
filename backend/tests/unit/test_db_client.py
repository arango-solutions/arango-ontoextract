"""Unit tests for app.db.client dynamic settings handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import DeploymentMode


def _make_settings(
    *,
    host: str,
    db: str,
    user: str = "root",
    password: str = "changeme",
):
    return SimpleNamespace(
        effective_arango_host=host,
        arango_db=db,
        arango_user=user,
        arango_password=password,
        arango_verify_ssl=True,
        test_deployment_mode=DeploymentMode.LOCAL_DOCKER,
        is_cluster=False,
        has_gae=False,
        can_create_databases=True,
    )


class TestDbClient:
    def test_reuses_client_when_settings_unchanged(self):
        from app.db import client as db_client

        db_client.close_db()

        settings = _make_settings(host="http://localhost:8530", db="ontology_generator")
        client = MagicMock()
        db = MagicMock()
        client.db.return_value = db

        with (
            patch.object(db_client.app_config, "settings", settings),
            patch.object(db_client, "ArangoClient", return_value=client),
            patch.object(db_client, "_ensure_database_exists"),
        ):
            first = db_client.get_db()
            second = db_client.get_db()

        assert first is db
        assert second is db
        assert client.db.call_count == 1
        client.close.assert_not_called()
        db_client.close_db()

    def test_reconnects_when_settings_change(self):
        from app.db import client as db_client

        db_client.close_db()

        first_settings = _make_settings(
            host="http://localhost:8530",
            db="ontology_generator",
        )
        second_settings = _make_settings(
            host="http://localhost:8530",
            db="aoe_test_db",
        )

        first_client = MagicMock()
        first_db = MagicMock()
        first_client.db.return_value = first_db

        second_client = MagicMock()
        second_db = MagicMock()
        second_client.db.return_value = second_db

        with (
            patch.object(
                db_client.app_config,
                "settings",
                first_settings,
            ),
            patch.object(
                db_client,
                "ArangoClient",
                side_effect=[first_client, second_client],
            ),
            patch.object(db_client, "_ensure_database_exists"),
        ):
            first = db_client.get_db()

            with patch.object(db_client.app_config, "settings", second_settings):
                second = db_client.get_db()

        assert first is first_db
        assert second is second_db
        first_client.close.assert_called_once()
        db_client.close_db()
