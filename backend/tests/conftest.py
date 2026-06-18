"""Shared pytest fixtures for the AOE backend test suite."""

from __future__ import annotations

import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from arango import ArangoClient
from arango.database import StandardDatabase
from fastapi.testclient import TestClient

ARANGO_TEST_HOST = os.getenv("ARANGO_TEST_HOST", "http://localhost:8530")
ARANGO_TEST_USER = os.getenv("ARANGO_TEST_USER", "root")
ARANGO_TEST_PASSWORD = os.getenv("ARANGO_TEST_PASSWORD", "")
REDIS_TEST_URL = os.getenv("REDIS_TEST_URL", "redis://localhost:6380/0")


@pytest.fixture(scope="session")
def arango_client() -> ArangoClient:
    """Session-scoped ArangoClient for integration tests."""
    client = ArangoClient(hosts=ARANGO_TEST_HOST)
    yield client  # type: ignore[misc]
    client.close()


@pytest.fixture(scope="session")
def test_db(arango_client: ArangoClient) -> StandardDatabase:
    """Create a unique test database; drop it after the session.

    The database name includes a random suffix to allow parallel CI runs.
    Connects to _system to create/drop the DB, then yields a handle to
    the test database itself.
    """
    db_name = f"aoe_test_{uuid4().hex[:8]}"

    connect_kwargs: dict = {"username": ARANGO_TEST_USER}
    if ARANGO_TEST_PASSWORD:
        connect_kwargs["password"] = ARANGO_TEST_PASSWORD

    sys_db = arango_client.db("_system", **connect_kwargs)
    sys_db.create_database(db_name)

    db = arango_client.db(db_name, **connect_kwargs)
    yield db  # type: ignore[misc]

    sys_db.delete_database(db_name, ignore_missing=True)


@pytest.fixture()
def mock_settings(test_db: StandardDatabase):
    """Patch ``app.config.settings`` with test-appropriate overrides.

    Overrides the ArangoDB connection to point at the ephemeral test DB
    and switches Redis to the test instance.
    """
    overrides = {
        "test_deployment_mode": "local_docker",
        "arango_host": ARANGO_TEST_HOST,
        "arango_db": test_db.name,
        "arango_user": ARANGO_TEST_USER,
        "arango_password": ARANGO_TEST_PASSWORD,
        "arango_no_auth": not ARANGO_TEST_PASSWORD,
        "redis_url": REDIS_TEST_URL,
        "app_env": "testing",
    }
    with patch.dict(os.environ, {k.upper(): str(v) for k, v in overrides.items()}):
        from app.config import Settings

        test_settings = Settings(**overrides)  # type: ignore[arg-type]
        with patch("app.config.settings", test_settings):
            yield test_settings


@pytest.fixture()
def test_client(mock_settings) -> TestClient:
    """FastAPI ``TestClient`` wired to test settings.

    ``mock_settings`` is depended upon so that the app sees the patched
    configuration when it boots.
    """
    from app.main import app

    return TestClient(app)
