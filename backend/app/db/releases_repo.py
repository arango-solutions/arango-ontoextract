"""Repository for ontology release records (``ontology_releases``)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from arango.database import StandardDatabase

from app.db import registry_repo
from app.db.client import get_db
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_COLLECTION = "ontology_releases"


def _ensure_collection(db: StandardDatabase | None = None) -> StandardDatabase:
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)
    return db


def release_exists(
    ontology_id: str,
    version: str,
    *,
    db: StandardDatabase | None = None,
) -> bool:
    """Return True if a release with this ontology id and version exists."""
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return False
    rows = list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.ontology_id == @oid AND r.version == @ver "
            "LIMIT 1 RETURN 1",
            bind_vars={"oid": ontology_id, "ver": version},
        )
    )
    return bool(rows)


def list_releases_for_ontology(
    ontology_id: str,
    *,
    limit: int = 50,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """Return releases newest first (empty if collection missing)."""
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return []
    return list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.ontology_id == @oid "
            "SORT r.released_at DESC "
            "LIMIT @lim "
            "RETURN r",
            bind_vars={"oid": ontology_id, "lim": limit},
        )
    )


def create_release(
    ontology_id: str,
    *,
    version: str,
    description: str,
    release_notes: str,
    released_by: str | None = None,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Insert a release row and update registry denormalized release fields.

    Raises:
        ValueError: duplicate version for this ontology.
    """
    db = _ensure_collection(db)
    ver = version.strip()
    if not ver:
        raise ValueError("version cannot be empty")

    if release_exists(ontology_id, ver, db=db):
        raise ValueError(f"Release version '{ver}' already exists for this ontology")

    now = datetime.now(UTC).isoformat()
    doc: dict[str, Any] = {
        "_key": uuid.uuid4().hex,
        "ontology_id": ontology_id,
        "version": ver,
        "description": (description or "").strip(),
        "release_notes": (release_notes or "").strip(),
        "released_at": now,
        "released_by": released_by,
    }
    col = db.collection(_COLLECTION)
    result = cast("dict[str, Any]", col.insert(doc, return_new=True))
    new_doc = result["new"]

    registry_repo.update_registry_entry(
        ontology_id,
        {
            "current_release_version": ver,
            "current_release_description": doc["description"],
            "current_release_at": now,
            "release_state": "released",
        },
        db=db,
    )
    return new_doc
