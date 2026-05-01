"""Repository layer for ``organizations`` and ``users`` collections.

All AQL is encapsulated here — no raw queries in routes or services.
org_id filtering is mandatory on all tenant-scoped queries.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get, run_aql
from app.db.utils import now_iso as _now_iso
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

ORGANIZATIONS_COLLECTION = "organizations"
USERS_COLLECTION = "users"


# ---------- Organizations ----------


def create_organization(
    *,
    name: str,
    display_name: str = "",
    settings: dict | None = None,
    db: StandardDatabase | None = None,
) -> dict:
    """Insert a new organization. Returns the full stored document."""
    db = db or get_db()
    col = db.collection(ORGANIZATIONS_COLLECTION)
    doc = {
        "name": name,
        "display_name": display_name or name,
        "settings": settings or {},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    result = cast("dict[str, Any]", col.insert(doc, return_new=True))
    return result["new"]


def get_organization(org_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Return a single organization by ``_key``, or ``None``."""
    db = db or get_db()
    col = db.collection(ORGANIZATIONS_COLLECTION)
    try:
        return doc_get(col, org_id)
    except Exception:
        return None


def list_organizations(
    *,
    limit: int = 25,
    cursor: str | None = None,
    sort_field: str = "created_at",
    sort_order: str = "desc",
    db: StandardDatabase | None = None,
) -> PaginatedResponse[dict]:
    """Paginated listing of all organizations."""
    db = db or get_db()
    return paginate(
        db,
        collection=ORGANIZATIONS_COLLECTION,
        sort_field=sort_field,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
    )


def update_organization(
    org_id: str,
    *,
    updates: dict[str, Any],
    db: StandardDatabase | None = None,
) -> dict | None:
    """Update an organization. Returns the updated document."""
    db = db or get_db()
    col = db.collection(ORGANIZATIONS_COLLECTION)
    updates["updated_at"] = _now_iso()
    result = cast("dict[str, Any]", col.update({"_key": org_id, **updates}, return_new=True))
    return result["new"]


# ---------- Users ----------


def add_user_to_org(
    *,
    user_id: str,
    org_id: str,
    role: str,
    email: str = "",
    display_name: str = "",
    db: StandardDatabase | None = None,
) -> dict:
    """Add a user to an organization with a role."""
    db = db or get_db()
    col = db.collection(USERS_COLLECTION)
    doc = {
        "user_id": user_id,
        "org_id": org_id,
        "role": role,
        "email": email,
        "display_name": display_name,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    result = cast("dict[str, Any]", col.insert(doc, return_new=True))
    return result["new"]


def list_org_users(
    org_id: str,
    *,
    limit: int = 25,
    cursor: str | None = None,
    db: StandardDatabase | None = None,
) -> PaginatedResponse[dict]:
    """Paginated listing of users in an organization."""
    db = db or get_db()
    return paginate(
        db,
        collection=USERS_COLLECTION,
        sort_field="created_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
        filters={"org_id": org_id},
    )


def get_org_user(org_id: str, user_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Find a user record by org_id and user_id."""
    db = db or get_db()
    query = """\
FOR u IN @@col
  FILTER u.org_id == @org_id
  FILTER u.user_id == @user_id
  LIMIT 1
  RETURN u"""
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"@col": USERS_COLLECTION, "org_id": org_id, "user_id": user_id},
        )
    )
    return rows[0] if rows else None


def update_user_role(
    org_id: str,
    user_id: str,
    role: str,
    *,
    db: StandardDatabase | None = None,
) -> dict | None:
    """Update a user's role within an organization."""
    db = db or get_db()
    user = get_org_user(org_id, user_id, db=db)
    if user is None:
        return None
    col = db.collection(USERS_COLLECTION)
    result = cast(
        "dict[str, Any]",
        col.update(
            {"_key": user["_key"], "role": role, "updated_at": _now_iso()},
            return_new=True,
        ),
    )
    return result["new"]


def remove_user_from_org(
    org_id: str,
    user_id: str,
    *,
    db: StandardDatabase | None = None,
) -> bool:
    """Remove a user from an organization. Returns True if deleted."""
    db = db or get_db()
    user = get_org_user(org_id, user_id, db=db)
    if user is None:
        return False
    col = db.collection(USERS_COLLECTION)
    col.delete(user["_key"])
    return True


def find_user_by_email(
    email: str, org_id: str, *, db: StandardDatabase | None = None
) -> dict | None:
    """Find a user by email within an organization."""
    db = db or get_db()
    query = """\
FOR u IN @@col
  FILTER u.org_id == @org_id
  FILTER u.email == @email
  LIMIT 1
  RETURN u"""
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"@col": USERS_COLLECTION, "org_id": org_id, "email": email},
        )
    )
    return rows[0] if rows else None
