"""Tests for ``app.static_export_app.NextStaticExportApp``.

Verifies the ``<path>.html`` fallback that Next ``output: 'export'`` requires
when served by a generic static server (FastAPI / Starlette ``StaticFiles``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_export_app import NextStaticExportApp, _is_extensionless_clean_url


def _populate_export(out: Path) -> None:
    """Mirror the layout produced by ``next build`` with ``output: 'export'``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text("<!DOCTYPE html><title>home</title>", encoding="utf-8")
    (out / "library.html").write_text("<!DOCTYPE html><title>library</title>", encoding="utf-8")
    (out / "workspace.html").write_text("<!DOCTYPE html><title>workspace</title>", encoding="utf-8")
    (out / "404.html").write_text("<!DOCTYPE html><title>not-found</title>", encoding="utf-8")
    nested = out / "ontology"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "edit.html").write_text(
        "<!DOCTYPE html><title>ontology-edit</title>", encoding="utf-8"
    )
    asset_dir = out / "_next" / "static"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "foo.js").write_text("console.log('foo');", encoding="utf-8")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    out = tmp_path / "out"
    _populate_export(out)
    app = FastAPI()
    app.mount("/", NextStaticExportApp(directory=str(out), html=True), name="static")
    return TestClient(app)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("library", True),
        ("ontology/edit", True),
        ("workspace", True),
        ("", False),
        ("library/", False),
        ("library.html", False),
        ("_next/static/foo.js", False),
        ("ontology/", False),
    ],
)
def test_is_extensionless_clean_url(path: str, expected: bool) -> None:
    assert _is_extensionless_clean_url(path) is expected


def test_root_serves_index(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "home" in r.text


def test_clean_url_falls_back_to_html(client: TestClient) -> None:
    r = client.get("/library")
    assert r.status_code == 200
    assert "library" in r.text


def test_nested_clean_url_falls_back_to_html(client: TestClient) -> None:
    r = client.get("/ontology/edit")
    assert r.status_code == 200
    assert "ontology-edit" in r.text


def test_direct_html_request_still_works(client: TestClient) -> None:
    r = client.get("/library.html")
    assert r.status_code == 200
    assert "library" in r.text


def test_static_asset_not_affected_by_fallback(client: TestClient) -> None:
    r = client.get("/_next/static/foo.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_unknown_route_serves_next_404(client: TestClient) -> None:
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert "not-found" in r.text


def test_unknown_nested_route_serves_next_404(client: TestClient) -> None:
    r = client.get("/ontology/missing")
    assert r.status_code == 404
    assert "not-found" in r.text


def test_html_disabled_skips_fallback(tmp_path: Path) -> None:
    """When ``html=False`` the subclass must not invent ``.html`` lookups."""
    out = tmp_path / "out"
    _populate_export(out)
    app = FastAPI()
    app.mount("/", NextStaticExportApp(directory=str(out), html=False), name="static")
    client = TestClient(app)

    r = client.get("/library")
    assert r.status_code == 404
