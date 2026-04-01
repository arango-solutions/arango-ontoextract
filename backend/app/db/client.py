import logging
from typing import Any, cast

from arango import ArangoClient
from arango.database import StandardDatabase

import app.config as app_config

log = logging.getLogger(__name__)

_client: ArangoClient | None = None
_db: StandardDatabase | None = None
_config_signature: tuple[Any, ...] | None = None


def _settings_signature() -> tuple[Any, ...]:
    settings = app_config.settings
    return (
        settings.effective_arango_host,
        settings.arango_db,
        settings.arango_user,
        settings.arango_password,
        settings.arango_verify_ssl,
        settings.test_deployment_mode,
    )


def _get_settings():
    global _config_signature
    settings = app_config.settings
    signature = _settings_signature()
    if _config_signature != signature:
        close_db()
        _config_signature = signature
    return settings


def get_arango_client() -> ArangoClient:
    global _client
    settings = _get_settings()
    if _client is None:
        host = settings.effective_arango_host
        kwargs: dict[str, Any] = {"hosts": host}

        if settings.is_cluster and not settings.arango_verify_ssl:
            kwargs["verify_override"] = False

        log.info(
            "connecting to ArangoDB",
            extra={
                "host": host,
                "mode": settings.test_deployment_mode.value,
                "is_cluster": settings.is_cluster,
                "has_gae": settings.has_gae,
            },
        )
        _client = ArangoClient(**kwargs)
    return _client


def _ensure_database_exists(client: ArangoClient) -> None:
    """Connect to _system and create the target database if it doesn't exist.

    Skipped on managed platforms where _system access may be restricted.
    """
    settings = _get_settings()
    if not settings.can_create_databases:
        log.info(
            "skipping auto-create database on managed platform — "
            "database must be pre-provisioned",
            extra={"db": settings.arango_db, "mode": settings.test_deployment_mode.value},
        )
        return

    sys_db = client.db(
        "_system",
        username=settings.arango_user,
        password=settings.arango_password,
    )
    if settings.arango_db not in cast(list[str], sys_db.databases()):
        log.info("creating database", extra={"db": settings.arango_db})
        sys_db.create_database(settings.arango_db)


def get_db() -> StandardDatabase:
    global _db
    settings = _get_settings()
    if _db is None:
        client = get_arango_client()
        _ensure_database_exists(client)
        _db = client.db(
            settings.arango_db,
            username=settings.arango_user,
            password=settings.arango_password,
        )
    return _db


def close_db() -> None:
    global _client, _db, _config_signature
    if _client is not None:
        _client.close()
    _client = None
    _db = None
    _config_signature = None
