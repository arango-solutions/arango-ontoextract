"""Organization & User REST endpoints — PRD Section 7.6.

All 8 endpoints for organization CRUD and user management within orgs.
Routes delegate to ``db.orgs_repo`` and enforce RBAC via dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.auth import AuthenticatedUser
from app.api.dependencies import get_current_user, get_or_404, require_role
from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.db import orgs_repo
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])

VALID_ROLES = {"admin", "ontology_engineer", "domain_expert", "viewer"}


# ---------- Request models ----------


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=256)
    settings: dict[str, Any] | None = None


class UpdateOrgRequest(BaseModel):
    display_name: str | None = None
    settings: dict[str, Any] | None = None


class AddUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    email: str = Field(default="")
    display_name: str = Field(default="")


class UpdateRoleRequest(BaseModel):
    role: str = Field(..., min_length=1)


# ---------- Organization endpoints ----------


@router.post("")
async def create_organization(
    body: CreateOrgRequest,
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Create a new organization."""
    org = orgs_repo.create_organization(
        name=body.name,
        display_name=body.display_name,
        settings=body.settings,
    )
    return org


@router.get("")
async def list_organizations(
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> PaginatedResponse[dict[str, Any]]:
    """List all organizations (admin only)."""
    return orgs_repo.list_organizations(
        limit=limit,
        cursor=cursor,
        sort_field=sort,
        sort_order=order,
    )


@router.get("/{org_id}")
async def get_organization(
    org_id: str,
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get organization details and settings."""
    return get_or_404(orgs_repo.get_organization(org_id), "Organization", org_id)


@router.put("/{org_id}")
async def update_organization(
    org_id: str,
    body: UpdateOrgRequest,
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Update organization settings."""
    org = get_or_404(orgs_repo.get_organization(org_id), "Organization", org_id)

    updates: dict[str, Any] = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.settings is not None:
        updates["settings"] = body.settings

    if not updates:
        return org

    updated = orgs_repo.update_organization(org_id, updates=updates)
    return updated or org


# ---------- User endpoints ----------


@router.post("/{org_id}/users")
async def add_user_to_org(
    org_id: str,
    body: AddUserRequest,
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Add a user to an organization with a role."""
    get_or_404(orgs_repo.get_organization(org_id), "Organization", org_id)

    if body.role not in VALID_ROLES:
        raise ValidationError(
            f"Invalid role: {body.role}",
            details={"valid_roles": sorted(VALID_ROLES)},
        )

    existing = orgs_repo.get_org_user(org_id, body.user_id)
    if existing:
        raise ConflictError(
            f"User '{body.user_id}' already belongs to organization '{org_id}'",
            details={"user_id": body.user_id, "org_id": org_id},
        )

    user = orgs_repo.add_user_to_org(
        user_id=body.user_id,
        org_id=org_id,
        role=body.role,
        email=body.email,
        display_name=body.display_name,
    )
    return user


@router.get("/{org_id}/users")
async def list_org_users(
    org_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> PaginatedResponse[dict[str, Any]]:
    """List users in an organization."""
    get_or_404(orgs_repo.get_organization(org_id), "Organization", org_id)
    return orgs_repo.list_org_users(org_id, limit=limit, cursor=cursor)


@router.put("/{org_id}/users/{user_id}/role")
async def update_user_role(
    org_id: str,
    user_id: str,
    body: UpdateRoleRequest,
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Update a user's role within an organization."""
    if body.role not in VALID_ROLES:
        raise ValidationError(
            f"Invalid role: {body.role}",
            details={"valid_roles": sorted(VALID_ROLES)},
        )

    updated = orgs_repo.update_user_role(org_id, user_id, body.role)
    if updated is None:
        raise NotFoundError(
            f"User '{user_id}' not found in organization '{org_id}'",
            details={"user_id": user_id, "org_id": org_id},
        )
    return updated


@router.delete("/{org_id}/users/{user_id}")
async def remove_user_from_org(
    org_id: str,
    user_id: str,
    _user: AuthenticatedUser = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Remove a user from an organization."""
    removed = orgs_repo.remove_user_from_org(org_id, user_id)
    if not removed:
        raise NotFoundError(
            f"User '{user_id}' not found in organization '{org_id}'",
            details={"user_id": user_id, "org_id": org_id},
        )
    return {"user_id": user_id, "org_id": org_id, "status": "removed"}
