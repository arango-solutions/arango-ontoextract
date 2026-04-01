"""Repository for the ontology_registry collection.

All functions are typed and use get_db() for database access.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

_COLLECTION = "ontology_registry"


def _ensure_collection(db: StandardDatabase | None = None) -> StandardDatabase:
    """Create the ontology_registry collection if it doesn't exist."""
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)
    return db


def create_registry_entry(
    entry: dict[str, Any],
    *,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Insert a new ontology into the registry.

    Automatically sets ``created_at`` and ``status`` if not provided.
    Returns the created document (including ``_key``, ``_id``, ``_rev``).
    """
    db = _ensure_collection(db)
    now = datetime.now(UTC).isoformat()
    entry.setdefault("status", "active")
    entry.setdefault("created_at", now)
    entry.setdefault("updated_at", now)
    result = cast("dict[str, Any]", db.collection(_COLLECTION).insert(entry, return_new=True))
    return result["new"]


def get_registry_entry(
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
) -> dict[str, Any] | None:
    """Retrieve a single ontology registry entry by ``_key``.

    Returns ``None`` if the entry does not exist.
    """
    db = _ensure_collection(db)
    col = db.collection(_COLLECTION)
    try:
        doc = doc_get(col, ontology_id)
        return doc
    except Exception:
        return None


def list_registry_entries(
    cursor: str | None = None,
    limit: int = 25,
    *,
    db: StandardDatabase | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """List ontology registry entries with cursor-based pagination.

    Returns a tuple of (entries, next_cursor).
    """
    db = _ensure_collection(db)
    result: PaginatedResponse[dict[str, Any]] = paginate(
        db,
        collection=_COLLECTION,
        sort_field="created_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
    )
    return result.data, result.cursor


def update_registry_entry(
    ontology_id: str,
    updates: dict[str, Any],
    *,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Merge-update an ontology registry entry.

    Returns the updated document.
    Raises ``ValueError`` if the entry does not exist.
    """
    db = _ensure_collection(db)
    col = db.collection(_COLLECTION)
    existing = doc_get(col, ontology_id)
    if existing is None:
        raise ValueError(f"Ontology registry entry '{ontology_id}' not found")
    updates["updated_at"] = datetime.now(UTC).isoformat()
    result = cast("dict[str, Any]", col.update({**updates, "_key": ontology_id}, return_new=True))
    return result["new"]


def deprecate_registry_entry(
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Set an ontology registry entry's status to ``deprecated``.

    Returns the updated document.
    """
    return update_registry_entry(ontology_id, {"status": "deprecated"}, db=db)


def delete_registry_entry(
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
) -> bool:
    """Hard-delete an ontology registry entry.

    Returns True if the entry was deleted, False if it didn't exist.
    """
    db = _ensure_collection(db)
    col = db.collection(_COLLECTION)
    existing = doc_get(col, ontology_id)
    if existing is None:
        return False
    col.delete(ontology_id)
    return True
