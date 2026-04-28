"""JWT authentication middleware and login endpoint — PRD Section 8.3.

Validates Bearer tokens from the Authorization header, extracts user claims
(user_id, org_id, roles), and provides a dev-mode mock user fallback.

Also exposes ``POST /api/v1/auth/login`` — a scaffold login endpoint that
issues HS256 JWTs.  Real IdP integration will replace this later.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import APIRouter, Request, WebSocket
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

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

# Under ``/api/`` only these accept HTTP requests without ``Authorization`` (production).
_PUBLIC_API_PATHS_WITHOUT_AUTH = frozenset({
    "/api/v1/auth/login",
    "/api/v1/metrics",
})


def _is_public_http_path(path: str) -> bool:
    """Paths that skip JWT middleware.

    - Next static export (HTML, ``/_next/*``, ``/favicon.*``, ``/health``, …) never sends Bearer on first load.
    - REST APIs under ``/api/`` require JWT unless listed in ``_PUBLIC_API_PATHS_WITHOUT_AUTH``.
    """
    if path.startswith("/_next/"):
        return True
    if not path.startswith("/api/"):
        return True
    return path in _PUBLIC_API_PATHS_WITHOUT_AUTH


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


async def authenticate_websocket(websocket: WebSocket) -> AuthenticatedUser | None:
    """Authenticate a WebSocket connection via query param ``token``.

    Returns the authenticated user on success, or ``None`` if the token is
    missing/invalid.  In dev mode, falls back to the mock admin user.
    """
    token = websocket.query_params.get("token")
    if token:
        try:
            claims = decode_jwt(token)
            return user_from_claims(claims)
        except jwt.ExpiredSignatureError:
            log.warning("WebSocket auth: expired token")
            return None
        except jwt.InvalidTokenError as exc:
            log.warning("WebSocket auth: invalid token", extra={"error": str(exc)})
            return None

    if not settings.is_production:
        log.debug("WebSocket dev mode: using mock user")
        return _MOCK_USER

    return None


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extracts and validates JWT from Authorization header.

    In development mode (``app_env != 'production'``), requests without a
    token receive a mock admin user so the API is usable without an IdP.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if _is_public_http_path(request.url.path):
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
            log.warning(
                "dev mode: authentication bypassed — set APP_ENV=production to enforce auth",
                extra={"user_id": _MOCK_USER.user_id},
            )
        else:
            return _error_response(401, "UNAUTHORIZED", "Missing Authorization header")

        return await call_next(request)


def _error_response(status: int, code: str, message: str) -> JSONResponse:
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


# ---------------------------------------------------------------------------
# Login endpoint (scaffold — will be replaced by real IdP integration)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Issue a JWT for valid credentials.

    This is a scaffold endpoint: any non-empty email/password pair is accepted.
    Production deployments will delegate to an external IdP.
    """
    if not body.email.strip() or not body.password.strip():
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Email and password are required",
                    "details": {},
                    "request_id": f"req_{uuid.uuid4().hex[:12]}",
                }
            },
        )

    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": f"user_{uuid.uuid4().hex[:8]}",
        "org_id": "org_default",
        "roles": ["editor"],
        "email": body.email.strip(),
        "name": body.email.split("@")[0],
        "iat": now,
        "exp": now + datetime.timedelta(hours=24),
    }
    token = jwt.encode(claims, settings.app_secret_key, algorithm="HS256")
    return LoginResponse(token=token)
