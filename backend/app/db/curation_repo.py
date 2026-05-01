"""Repository for the curation_decisions collection.

All functions accept an explicit ``db`` handle to support testing.
Falls back to ``get_db()`` when ``db`` is ``None``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get, run_aql
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

_COLLECTION = "curation_decisions"


def _ensure_collection(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)


def create_decision(
    db: StandardDatabase | None = None,
    *,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Insert a new curation decision and return the full document."""
    if db is None:
        db = get_db()
    _ensure_collection(db)

    data.setdefault("created_at", time.time())
    result = cast("dict[str, Any]", db.collection(_COLLECTION).insert(data, return_new=True))
    log.info(
        "curation decision created",
        extra={"key": result["_key"], "action": data.get("action")},
    )
    return result["new"]


def get_decision(
    db: StandardDatabase | None = None,
    *,
    key: str,
) -> dict[str, Any] | None:
    """Retrieve a single curation decision by ``_key``."""
    if db is None:
        db = get_db()
    _ensure_collection(db)

    try:
        return doc_get(db.collection(_COLLECTION), key)
    except Exception:
        return None


def list_decisions(
    db: StandardDatabase | None = None,
    *,
    run_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> PaginatedResponse[dict[str, Any]]:
    """List curation decisions with optional filters and cursor pagination."""
    if db is None:
        db = get_db()
    _ensure_collection(db)

    filters: dict[str, Any] = {}
    if run_id is not None:
        filters["run_id"] = run_id
    if status is not None:
        filters["action"] = status

    return paginate(
        db,
        collection=_COLLECTION,
        sort_field="created_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
        filters=filters,
    )


def count_decisions(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    action: str | None = None,
) -> int:
    """Count curation decisions for a run, optionally filtered by action."""
    if db is None:
        db = get_db()
    _ensure_collection(db)

    bind_vars: dict[str, Any] = {"@col": _COLLECTION, "run_id": run_id}
    filter_parts = ["FILTER doc.run_id == @run_id"]

    if action is not None:
        bind_vars["action"] = action
        filter_parts.append("FILTER doc.action == @action")

    filter_block = "\n  ".join(filter_parts)
    query = f"""\
FOR doc IN @@col
  {filter_block}
  COLLECT WITH COUNT INTO cnt
  RETURN cnt"""

    result = list(run_aql(db, query, bind_vars=bind_vars))
    return result[0] if result else 0
