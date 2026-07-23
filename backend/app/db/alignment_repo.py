"""Persistence for multi-source ontology alignment (Stream 20 / AL-PR1).

Thin data-access layer over the ``alignment_sessions`` and ``correspondences``
collections (migration 028). Keeps AQL/CRUD out of the service so the service
(``app.services.alignment``) stays focused on the matching logic.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from arango.database import StandardDatabase

from app.db.utils import run_aql

SESSIONS = "alignment_sessions"
CORRESPONDENCES = "correspondences"


def create_session(
    db: StandardDatabase,
    *,
    source_ontology_ids: list[str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new alignment session over ``source_ontology_ids``."""
    doc = {
        "_key": uuid.uuid4().hex,
        "source_ontology_ids": source_ontology_ids,
        "params": params or {},
        "status": "candidates_generated",
        "target_master_id": None,
        "created": time.time(),
    }
    db.collection(SESSIONS).insert(doc)
    # ``_id`` is deterministic from the collection + our own ``_key``; deriving
    # it avoids indexing python-arango's sync/async union insert() return type.
    doc["_id"] = f"{SESSIONS}/{doc['_key']}"
    return doc


def get_session(db: StandardDatabase, session_id: str) -> dict[str, Any] | None:
    if not db.has_collection(SESSIONS):
        return None
    doc = db.collection(SESSIONS).get(session_id)
    return doc if isinstance(doc, dict) else None


def save_correspondences(
    db: StandardDatabase, session_id: str, correspondences: list[dict[str, Any]]
) -> int:
    """Bulk-insert candidate correspondences for a session. Returns the count."""
    if not correspondences:
        return 0
    now = time.time()
    docs = [
        {
            "_key": uuid.uuid4().hex,
            "session_id": session_id,
            "created": now,
            **c,
        }
        for c in correspondences
    ]
    db.collection(CORRESPONDENCES).insert_many(docs)
    return len(docs)


def set_session_master(
    db: StandardDatabase, session_id: str, master_id: str
) -> dict[str, Any] | None:
    """Mark a session materialised, recording the target master ontology id."""
    if not db.has_collection(SESSIONS):
        return None
    col = db.collection(SESSIONS)
    if not isinstance(col.get(session_id), dict):
        return None
    col.update({"_key": session_id, "target_master_id": master_id, "status": "materialized"})
    updated = col.get(session_id)
    return updated if isinstance(updated, dict) else None


def list_correspondences(
    db: StandardDatabase,
    session_id: str,
    *,
    status: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List a session's correspondences, highest confidence first."""
    if not db.has_collection(CORRESPONDENCES):
        return []
    filters = ["c.session_id == @sid", "c.confidence >= @minc"]
    bind: dict[str, Any] = {"sid": session_id, "minc": min_confidence}
    if status is not None:
        filters.append("c.status == @status")
        bind["status"] = status
    bind["offset"] = offset
    bind["count"] = limit
    query = f"""
        FOR c IN {CORRESPONDENCES}
          FILTER {" AND ".join(filters)}
          SORT c.confidence DESC
          LIMIT @offset, @count
          RETURN c
    """
    return list(run_aql(db, query, bind_vars=bind))


def set_correspondence_adjudication(
    db: StandardDatabase,
    correspondence_key: str,
    adjudication: dict[str, Any],
    *,
    correspondence_type: str | None = None,
) -> dict[str, Any] | None:
    """Attach an LLM/score adjudication verdict to a correspondence.

    Records the verdict + recommendation under ``adjudication`` and, when the
    verdict refined the correspondence type, updates ``type``. Does not change
    the curation ``status`` — a human still confirms via accept/reject.
    """
    if not db.has_collection(CORRESPONDENCES):
        return None
    col = db.collection(CORRESPONDENCES)
    if not isinstance(col.get(correspondence_key), dict):
        return None
    patch: dict[str, Any] = {"_key": correspondence_key, "adjudication": adjudication}
    if correspondence_type is not None:
        patch["type"] = correspondence_type
    col.update(patch)
    updated = col.get(correspondence_key)
    return updated if isinstance(updated, dict) else None


def set_correspondence_status(
    db: StandardDatabase, correspondence_key: str, status: str
) -> dict[str, Any] | None:
    """Set a correspondence's curation status (candidate/accepted/rejected)."""
    if not db.has_collection(CORRESPONDENCES):
        return None
    col = db.collection(CORRESPONDENCES)
    existing = col.get(correspondence_key)
    if not isinstance(existing, dict):
        return None
    col.update({"_key": correspondence_key, "status": status, "decided_at": time.time()})
    updated = col.get(correspondence_key)
    return updated if isinstance(updated, dict) else None


def find_sessions_for_ontology(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    """Return alignment sessions whose sources include ``ontology_id`` (AL-PR10)."""
    if not db.has_collection(SESSIONS):
        return []
    return list(
        run_aql(
            db,
            f"FOR s IN {SESSIONS} FILTER @oid IN s.source_ontology_ids RETURN s",
            bind_vars={"oid": ontology_id},
        )
    )


def delete_correspondences(db: StandardDatabase, keys: list[str]) -> int:
    """Remove correspondences by ``_key``; returns the number removed (AL-PR10)."""
    if not keys or not db.has_collection(CORRESPONDENCES):
        return 0
    removed = run_aql(
        db,
        f"FOR c IN {CORRESPONDENCES} FILTER c._key IN @keys REMOVE c IN {CORRESPONDENCES} RETURN 1",
        bind_vars={"keys": keys},
    )
    return sum(1 for _ in removed)
