"""Tests for public URL prefix stripping (Container Manager / pilot routes)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.strip_service_prefix import (
    StripServicePrefixMiddleware,
    normalize_service_url_path_prefix,
    stripped_path_if_under_prefix,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("  ", ""),
        ("/_service/uds/db/svc", "/_service/uds/db/svc"),
        ("/_service/uds/db/svc/", "/_service/uds/db/svc"),
        ("_service/x", "/_service/x"),
    ],
)
def test_normalize_service_url_path_prefix(raw: str, expected: str) -> None:
    assert normalize_service_url_path_prefix(raw) == expected


@pytest.mark.parametrize(
    ("path", "prefix", "out"),
    [
        ("/pre", "/pre", "/"),
        ("/pre/", "/pre", "/"),
        ("/pre/health", "/pre", "/health"),
        ("/pre/api/v1/x", "/pre", "/api/v1/x"),
        ("/other", "/pre", None),
        ("/prefixed", "/pre", None),
        ("/health", "/pre", None),
    ],
)
def test_stripped_path_if_under_prefix(
    path: str, prefix: str, out: str | None
) -> None:
    assert stripped_path_if_under_prefix(path, prefix) == out


def test_settings_normalizes_service_url_path_prefix() -> None:
    s = Settings(
        service_url_path_prefix=" /_service/uds/_db/ontoextract/arango-ontoextract/ ",
    )
    assert s.service_url_path_prefix == "/_service/uds/_db/ontoextract/arango-ontoextract"


def test_health_under_prefix_integration() -> None:
    prefix = "/_service/uds/_db/ontoextract/arango-ontoextract"
    inner = FastAPI()

    @inner.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    root = FastAPI()
    root.add_middleware(StripServicePrefixMiddleware, prefix=prefix)
    root.mount("/", inner)

    client = TestClient(root)
    r = client.get(f"{prefix}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
