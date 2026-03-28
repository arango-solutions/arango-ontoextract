"""JWT authentication middleware — PRD Section 8.3.

Validates Bearer tokens from the Authorization header, extracts user claims
(user_id, org_id, roles), and provides a dev-mode mock user fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import settings

log = logging.getLogger(__name__)

_AUTH_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_USER_CONTEXT_KEY = "aoe_user"


@dataclass(frozen=True)
class AuthenticatedUser:
    """Decoded user context attached to each request."""

    user_id: str
    org_id: str
    roles: list[str] = field(default_factory=list)
    email: str = ""
    display_name: str = ""


_MOCK_USER = AuthenticatedUser(
    user_id="dev-user-001",
    org_id="dev-org-001",
    roles=["admin"],
    email="dev@aoe.local",
    display_name="Dev Admin",
)

_PUBLIC_PATHS = frozenset({"/health", "/ready", "/docs", "/openapi.json", "/redoc"})


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token.

    Uses HS256 with ``settings.app_secret_key`` for local/dev.
    Production deployments should use RS256 with OIDC JWKS.
    """
    return jwt.decode(
        token,
        settings.app_secret_key,
        algorithms=["HS256"],
        options={"verify_exp": True},
    )


def user_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    """Build an ``AuthenticatedUser`` from JWT claims."""
    return AuthenticatedUser(
        user_id=claims.get("sub", ""),
        org_id=claims.get("org_id", ""),
        roles=claims.get("roles", []),
        email=claims.get("email", ""),
        display_name=claims.get("name", ""),
    )


def get_user_from_request(request: Request) -> AuthenticatedUser | None:
    """Retrieve the authenticated user attached to a request, if any."""
    return getattr(request.state, _USER_CONTEXT_KEY, None)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extracts and validates JWT from Authorization header.

    In development mode (``app_env != 'production'``), requests without a
    token receive a mock admin user so the API is usable without an IdP.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        if request.scope.get("type") == "websocket":
            return await call_next(request)

        auth_header = request.headers.get(_AUTH_HEADER)

        if auth_header and auth_header.startswith(_BEARER_PREFIX):
            token = auth_header[len(_BEARER_PREFIX) :]
            try:
                claims = decode_jwt(token)
                user = user_from_claims(claims)
                request.state.__dict__[_USER_CONTEXT_KEY] = user
            except jwt.ExpiredSignatureError:
                return _error_response(401, "UNAUTHORIZED", "Token has expired")
            except jwt.InvalidTokenError as exc:
                return _error_response(401, "UNAUTHORIZED", f"Invalid token: {exc}")
        elif not settings.is_production:
            request.state.__dict__[_USER_CONTEXT_KEY] = _MOCK_USER
            log.debug("dev mode: using mock user", extra={"user_id": _MOCK_USER.user_id})
        else:
            return _error_response(401, "UNAUTHORIZED", "Missing Authorization header")

        return await call_next(request)


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    import uuid

    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": f"req_{uuid.uuid4().hex[:12]}",
            }
        },
    )
