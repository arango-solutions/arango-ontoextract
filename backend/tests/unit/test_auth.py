"""Unit tests for JWT authentication, role checking, and mock user — PRD Section 8.3."""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest

from app.api.auth import (
    _MOCK_USER,
    AuthenticatedUser,
    decode_jwt,
    user_from_claims,
)
from app.api.dependencies import get_current_user, require_role

_TEST_SECRET = "test-secret-key"


def _make_token(
    claims: dict,
    secret: str = _TEST_SECRET,
    algorithm: str = "HS256",
) -> str:
    return jwt.encode(claims, secret, algorithm=algorithm)


class TestDecodeJwt:
    """Tests for ``decode_jwt``."""

    @patch("app.api.auth.settings")
    def test_decode_valid_token(self, mock_settings):
        mock_settings.app_secret_key = _TEST_SECRET
        claims = {
            "sub": "user-123",
            "org_id": "org-456",
            "roles": ["admin"],
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(claims)
        decoded = decode_jwt(token)
        assert decoded["sub"] == "user-123"
        assert decoded["org_id"] == "org-456"
        assert decoded["roles"] == ["admin"]

    @patch("app.api.auth.settings")
    def test_decode_expired_token_raises(self, mock_settings):
        mock_settings.app_secret_key = _TEST_SECRET
        claims = {
            "sub": "user-123",
            "exp": int(time.time()) - 100,
        }
        token = _make_token(claims)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_jwt(token)

    @patch("app.api.auth.settings")
    def test_decode_invalid_token_raises(self, mock_settings):
        mock_settings.app_secret_key = _TEST_SECRET
        with pytest.raises(jwt.InvalidTokenError):
            decode_jwt("not-a-valid-token")

    @patch("app.api.auth.settings")
    def test_decode_wrong_secret_raises(self, mock_settings):
        mock_settings.app_secret_key = _TEST_SECRET
        claims = {"sub": "user-123", "exp": int(time.time()) + 3600}
        token = _make_token(claims, secret="wrong-secret")
        with pytest.raises(jwt.InvalidSignatureError):
            decode_jwt(token)


class TestUserFromClaims:
    """Tests for ``user_from_claims``."""

    def test_full_claims(self):
        claims = {
            "sub": "user-abc",
            "org_id": "org-xyz",
            "roles": ["admin", "ontology_engineer"],
            "email": "test@example.com",
            "name": "Test User",
        }
        user = user_from_claims(claims)
        assert user.user_id == "user-abc"
        assert user.org_id == "org-xyz"
        assert user.roles == ["admin", "ontology_engineer"]
        assert user.email == "test@example.com"
        assert user.display_name == "Test User"

    def test_minimal_claims(self):
        claims = {"sub": "user-min"}
        user = user_from_claims(claims)
        assert user.user_id == "user-min"
        assert user.org_id == ""
        assert user.roles == []
        assert user.email == ""

    def test_empty_claims(self):
        user = user_from_claims({})
        assert user.user_id == ""


class TestMockUser:
    """Tests for the dev-mode mock user."""

    def test_mock_user_has_admin_role(self):
        assert "admin" in _MOCK_USER.roles

    def test_mock_user_has_org_id(self):
        assert _MOCK_USER.org_id != ""

    def test_mock_user_has_user_id(self):
        assert _MOCK_USER.user_id != ""


class TestGetCurrentUser:
    """Tests for ``get_current_user`` dependency."""

    def test_returns_user_when_present(self):
        user = AuthenticatedUser(
            user_id="u1", org_id="o1", roles=["viewer"]
        )

        class FakeRequest:
            class State:
                aoe_user = user

            state = State()

        result = get_current_user(FakeRequest())  # type: ignore[arg-type]
        assert result.user_id == "u1"

    def test_raises_when_no_user(self):
        class FakeRequest:
            class State:
                pass

            state = State()

        from app.api.errors import UnauthorizedError

        with pytest.raises(UnauthorizedError):
            get_current_user(FakeRequest())  # type: ignore[arg-type]


class TestRequireRole:
    """Tests for ``require_role`` dependency factory."""

    def test_allows_matching_role(self):
        guard = require_role("admin")
        user = AuthenticatedUser(
            user_id="u1", org_id="o1", roles=["admin"]
        )
        result = guard(user)
        assert result.user_id == "u1"

    def test_allows_one_of_multiple_roles(self):
        guard = require_role("admin", "ontology_engineer")
        user = AuthenticatedUser(
            user_id="u1", org_id="o1", roles=["ontology_engineer"]
        )
        result = guard(user)
        assert result.user_id == "u1"

    def test_denies_wrong_role(self):
        guard = require_role("admin")
        user = AuthenticatedUser(
            user_id="u1", org_id="o1", roles=["viewer"]
        )
        from app.api.errors import ForbiddenError

        with pytest.raises(ForbiddenError):
            guard(user)

    def test_denies_no_roles(self):
        guard = require_role("admin")
        user = AuthenticatedUser(user_id="u1", org_id="o1", roles=[])
        from app.api.errors import ForbiddenError

        with pytest.raises(ForbiddenError):
            guard(user)
