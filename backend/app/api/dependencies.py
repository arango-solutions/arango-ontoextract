"""FastAPI dependencies for authentication and RBAC — PRD Section 8.3.

Provides injectable dependencies for route handlers:
- ``get_current_user``: extracts the authenticated user from the request
- ``require_role``: RBAC guard that checks the user has a required role
- ``get_org_id``: extracts the org_id from the current user context
"""

from __future__ import annotations

from fastapi import Depends, Request

from app.api.auth import AuthenticatedUser, get_user_from_request
from app.api.errors import ForbiddenError, UnauthorizedError

ROLES = ("admin", "ontology_engineer", "domain_expert", "viewer")


def get_current_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency — returns the authenticated user or raises 401."""
    user = get_user_from_request(request)
    if user is None:
        raise UnauthorizedError("Authentication required")
    return user


def get_org_id(user: AuthenticatedUser = Depends(get_current_user)) -> str:
    """FastAPI dependency — returns the org_id from the current user."""
    if not user.org_id:
        raise ForbiddenError("User is not associated with an organization")
    return user.org_id


def require_role(*allowed_roles: str):
    """Return a dependency that enforces role-based access.

    Usage::

        @router.post("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(): ...

    Or as a function parameter::

        @router.get("/data")
        async def get_data(
            user: AuthenticatedUser = Depends(require_role("admin", "ontology_engineer")),
        ):
            ...
    """

    def _guard(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not any(role in allowed_roles for role in user.roles):
            raise ForbiddenError(
                f"Requires one of roles: {', '.join(allowed_roles)}",
                details={"required_roles": list(allowed_roles), "user_roles": user.roles},
            )
        return user

    return _guard
