"""Login route discovery (GET vs POST) and minimal HTML fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.minimal_login import render_minimal_login_html


def test_get_api_v1_auth_login_returns_post_instructions() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/auth/login")
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "POST"
    assert data["path"] == "/api/v1/auth/login"
    assert "POST" in data["detail"]


def test_post_api_v1_auth_login_issues_token() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "u@test.dev", "password": "secret"},
    )
    assert response.status_code == 200
    assert "token" in response.json()


def test_render_minimal_login_embeds_prefixed_api_url() -> None:
    html = render_minimal_login_html("/my/prefix")
    assert "/my/prefix/api/v1/auth/login" in html
