"""Core edge-interval time travel operations per PRD Section 5.3.

Every versioned vertex and edge carries ``created`` / ``expired`` timestamps.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def _now() -> float:
    return time.time()


def create_version(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    data: dict[str, Any],
    created_by: str = "system",
    change_type: str = "initial",
    change_summary: str = "",
) -> dict[str, Any]:
    """Insert a new versioned document with ``created=now``, ``expired=NEVER_EXPIRES``.

    Returns the inserted document including ``_key``, ``_id``.
    """
    if db is None:
        db = get_db()

    now = _now()
    doc = {
        **data,
        "created": now,
        "expired": NEVER_EXPIRES,
        "created_by": created_by,
        "change_type": change_type,
        "change_summary": change_summary,
        "version": data.get("version", 1),
        "ttlExpireAt": None,
    }

    result = db.collection(collection).insert(doc, return_new=True)
    log.info(
        "temporal version created",
        extra={"collection": collection, "key": result["_key"]},
    )
    return result["new"]


def expire_entity(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str,
    ttl_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Set ``expired=now`` on the current version of an entity.

    Returns the expired document, or None if not found / already expired.
    """
    if db is None:
        db = get_db()

    now = _now()
    update_data: dict[str, Any] = {"expired": now}
    if ttl_seconds is not None:
        update_data["ttlExpireAt"] = now + ttl_seconds

    try:
        result = db.collection(collection).update(
            {"_key": key, **update_data},
            return_new=True,
        )
        log.info(
            "temporal entity expired",
            extra={"collection": collection, "key": key},
        )
        return result["new"]
    except Exception:
        log.warning(
            "failed to expire entity",
            extra={"collection": collection, "key": key},
            exc_info=True,
        )
        return None


def update_entity(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str,
    new_data: dict[str, Any],
    created_by: str = "system",
    change_type: str = "edit",
    change_summary: str = "",
    edge_collections: list[str] | None = None,
) -> dict[str, Any]:
    """Expire the old version and create a new one, re-creating connected edges.

    Steps:
    1. Read current version to get old ``_id`` and ``version``
    2. Expire old version
    3. Create new version with incremented version number
    4. Re-create edges pointing to/from old document
    """
    if db is None:
        db = get_db()

    old_doc = get_current(db, collection=collection, key=key)
    if old_doc is None:
        raise ValueError(f"No current version found for {collection}/{key}")

    old_id = old_doc["_id"]
    old_version = old_doc.get("version", 1)

    expire_entity(db, collection=collection, key=key)

    merged = {**old_doc, **new_data}
    for meta_field in ("_key", "_id", "_rev", "created", "expired", "ttlExpireAt"):
        merged.pop(meta_field, None)
    merged["version"] = old_version + 1

    new_doc = create_version(
        db,
        collection=collection,
        data=merged,
        created_by=created_by,
        change_type=change_type,
        change_summary=change_summary,
    )

    if edge_collections:
        new_id = new_doc["_id"]
        for edge_col in edge_collections:
            re_create_edges(
                db,
                edge_collection=edge_col,
                old_id=old_id,
                new_id=new_id,
            )

    return new_doc


def re_create_edges(
    db: StandardDatabase | None = None,
    *,
    edge_collection: str,
    old_id: str,
    new_id: str,
) -> int:
    """Expire old edges and create new edges with the same data but updated endpoints.

    Handles both outbound (``_from == old_id``) and inbound (``_to == old_id``) edges.
    Returns count of re-created edges.
    """
    if db is None:
        db = get_db()

    if not db.has_collection(edge_collection):
        return 0

    now = _now()
    count = 0

    outbound_query = """\
FOR e IN @@col
  FILTER e._from == @old_id AND e.expired == @never
  RETURN e"""
    outbound_edges = list(
        db.aql.execute(
            outbound_query,
            bind_vars={"@col": edge_collection, "old_id": old_id, "never": NEVER_EXPIRES},
        )
    )
    for edge in outbound_edges:
        db.collection(edge_collection).update(
            {"_key": edge["_key"], "expired": now, "ttlExpireAt": now + 7776000}
        )
        new_edge = {
            k: v
            for k, v in edge.items()
            if not k.startswith("_") and k not in ("created", "expired", "ttlExpireAt")
        }
        new_edge["_from"] = new_id
        new_edge["_to"] = edge["_to"]
        new_edge["created"] = now
        new_edge["expired"] = NEVER_EXPIRES
        new_edge["ttlExpireAt"] = None
        db.collection(edge_collection).insert(new_edge)
        count += 1

    inbound_query = """\
FOR e IN @@col
  FILTER e._to == @old_id AND e.expired == @never
  RETURN e"""
    inbound_edges = list(
        db.aql.execute(
            inbound_query,
            bind_vars={"@col": edge_collection, "old_id": old_id, "never": NEVER_EXPIRES},
        )
    )
    for edge in inbound_edges:
        db.collection(edge_collection).update(
            {"_key": edge["_key"], "expired": now, "ttlExpireAt": now + 7776000}
        )
        new_edge = {
            k: v
            for k, v in edge.items()
            if not k.startswith("_") and k not in ("created", "expired", "ttlExpireAt")
        }
        new_edge["_from"] = edge["_from"]
        new_edge["_to"] = new_id
        new_edge["created"] = now
        new_edge["expired"] = NEVER_EXPIRES
        new_edge["ttlExpireAt"] = None
        db.collection(edge_collection).insert(new_edge)
        count += 1

    log.info(
        "edges re-created",
        extra={
            "edge_collection": edge_collection,
            "old_id": old_id,
            "new_id": new_id,
            "count": count,
        },
    )
    return count


def get_at_timestamp(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str | None = None,
    timestamp: float | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve entities active at a specific timestamp.

    If ``key`` is provided, returns at most one result for that key's URI.
    If ``filters`` is provided, applies additional equality filters.
    """
    if db is None:
        db = get_db()
    if timestamp is None:
        timestamp = _now()

    bind_vars: dict[str, Any] = {
        "@col": collection,
        "ts": timestamp,
    }
    filter_parts = [
        "FILTER doc.created <= @ts",
        "FILTER doc.expired > @ts",
    ]

    if key is not None:
        bind_vars["uri_key"] = key
        filter_parts.append("FILTER doc.uri == @uri_key")

    if filters:
        for i, (field, value) in enumerate(filters.items()):
            var = f"flt_{i}"
            filter_parts.append(f"FILTER doc.`{field}` == @{var}")
            bind_vars[var] = value

    filter_block = "\n  ".join(filter_parts)
    query = f"""\
FOR doc IN @@col
  {filter_block}
  RETURN doc"""

    return list(db.aql.execute(query, bind_vars=bind_vars))


def get_current(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str,
) -> dict[str, Any] | None:
    """Retrieve the current (non-expired) version of an entity by ``_key``."""
    if db is None:
        db = get_db()

    query = """\
FOR doc IN @@col
  FILTER doc._key == @key
  FILTER doc.expired == @never
  LIMIT 1
  RETURN doc"""

    results = list(
        db.aql.execute(
            query,
            bind_vars={"@col": collection, "key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None
