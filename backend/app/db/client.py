import logging

from arango import ArangoClient
from arango.database import StandardDatabase

from app.config import settings

log = logging.getLogger(__name__)

_client: ArangoClient | None = None
_db: StandardDatabase | None = None


def get_arango_client() -> ArangoClient:
    global _client
    if _client is None:
        host = settings.effective_arango_host
        kwargs: dict = {"hosts": host}

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
    if settings.arango_db not in sys_db.databases():
        log.info("creating database", extra={"db": settings.arango_db})
        sys_db.create_database(settings.arango_db)


def get_db() -> StandardDatabase:
    global _db
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
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
