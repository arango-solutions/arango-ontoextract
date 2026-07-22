"""Competency-question coverage-gap backlog repository (Stream 22 / CQ-PR6).

Persists unanswerable competency questions as trackable work items so the
coverage loop closes: a gap opens when a CQ is not answerable and flips to
``resolved`` once coverage can answer it (PRD §6.19 / FR-19.6). Idempotent by a
deterministic key over (ontology_id, cq_text) so re-running coverage never
duplicates a gap.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql

COLLECTION = "cq_gap_backlog"

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"


def gap_key(ontology_id: str, cq_text: str) -> str:
    """Deterministic ``_key`` for a gap so re-runs upsert the same document."""
    digest = hashlib.sha1(f"{ontology_id}\x00{cq_text}".encode()).hexdigest()
    return digest[:32]


def upsert_gap(
    db: StandardDatabase | None,
    *,
    ontology_id: str,
    cq_text: str,
    use_case: str | None,
    priority: str | None,
    gap_kind: str,
    now: float | None = None,
) -> bool:
    """Open (or re-open) a gap item. Returns ``True`` if newly created/re-opened.

    ``gap_kind`` is the coverage status that made this a gap
    (``unanswerable`` / ``unformalized`` / ``error``).
    """
    if db is None:
        db = get_db()
    ts = time.time() if now is None else now
    col = db.collection(COLLECTION)
    key = gap_key(ontology_id, cq_text)
    existing = col.get(key)
    if isinstance(existing, dict):
        was_resolved = existing.get("status") == STATUS_RESOLVED
        col.update(
            {
                "_key": key,
                "status": STATUS_OPEN,
                "gap_kind": gap_kind,
                "priority": priority,
                "use_case": use_case,
                "updated": ts,
                "resolved_at": None,
            }
        )
        return was_resolved
    col.insert(
        {
            "_key": key,
            "ontology_id": ontology_id,
            "cq_text": cq_text,
            "use_case": use_case,
            "priority": priority,
            "gap_kind": gap_kind,
            "status": STATUS_OPEN,
            "created": ts,
            "updated": ts,
            "resolved_at": None,
        }
    )
    return True


def resolve_gaps_not_in(
    db: StandardDatabase | None,
    ontology_id: str,
    active_keys: set[str],
    *,
    now: float | None = None,
) -> int:
    """Resolve open gaps whose key is not in ``active_keys`` (the CQ now answers).

    Returns the number of gaps flipped ``open`` -> ``resolved``.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(COLLECTION):
        return 0
    ts = time.time() if now is None else now
    rows = run_aql(
        db,
        f"""
        FOR g IN {COLLECTION}
          FILTER g.ontology_id == @oid AND g.status == @open
            AND g._key NOT IN @active
          UPDATE g WITH {{status: @resolved, resolved_at: @ts, updated: @ts}} IN {COLLECTION}
          RETURN 1
        """,
        bind_vars={
            "oid": ontology_id,
            "open": STATUS_OPEN,
            "resolved": STATUS_RESOLVED,
            "active": list(active_keys),
            "ts": ts,
        },
    )
    return sum(1 for _ in rows)


def list_gaps(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    status: str | None = STATUS_OPEN,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List backlog gaps for an ontology (default: only open ones)."""
    if db is None:
        db = get_db()
    if not db.has_collection(COLLECTION):
        return []
    status_filter = "AND g.status == @status" if status else ""
    bind: dict[str, Any] = {"oid": ontology_id, "limit": limit}
    if status:
        bind["status"] = status
    rows = run_aql(
        db,
        f"""
        FOR g IN {COLLECTION}
          FILTER g.ontology_id == @oid {status_filter}
          SORT g.created DESC
          LIMIT @limit
          RETURN g
        """,
        bind_vars=bind,
    )
    return list(rows)
