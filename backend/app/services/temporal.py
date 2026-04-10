"""Core edge-interval time travel operations per PRD Section 5.3.

Every versioned vertex and edge carries ``created`` / ``expired`` timestamps.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize

# ---------------------------------------------------------------------------
# Materialized snapshot cache (Week 23 — PRD R16)
# ---------------------------------------------------------------------------
# In-process cache keyed by (ontology_id, precise_timestamp).
# TTL: 5 minutes.  Invalidated on any write to the ontology.

_SNAPSHOT_CACHE_TTL = 300  # seconds
_snapshot_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _snapshot_cache_key(ontology_id: str, timestamp: float) -> str:
    """Deterministic cache key: ontology + precise timestamp."""
    raw = f"{ontology_id}:{timestamp:.6f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _snapshot_cache_get(key: str) -> dict[str, Any] | None:
    entry = _snapshot_cache.get(key)
    if entry is None:
        return None
    stored_at, data = entry
    if time.time() - stored_at > _SNAPSHOT_CACHE_TTL:
        _snapshot_cache.pop(key, None)
        return None
    return data


def _snapshot_cache_put(key: str, data: dict[str, Any]) -> None:
    _snapshot_cache[key] = (time.time(), data)


def invalidate_snapshot_cache(ontology_id: str) -> int:
    """Remove all cached snapshots for an ontology.  Called on any write."""
    to_remove = [
        k for k, (_, v) in _snapshot_cache.items()
        if v.get("ontology_id") == ontology_id
    ]
    for k in to_remove:
        _snapshot_cache.pop(k, None)
    removed = len(to_remove)
    if removed:
        log.info(
        "snapshot_cache_invalidated",
        extra={"ontology_id": ontology_id, "evicted": removed},
    )
    return removed


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

    result = cast("dict[str, Any]", db.collection(collection).insert(doc, return_new=True))
    log.info(
        "temporal version created",
        extra={"collection": collection, "key": result["_key"]},
    )
    ontology_id = data.get("ontology_id")
    if ontology_id:
        invalidate_snapshot_cache(ontology_id)
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
        result = cast("dict[str, Any]", db.collection(collection).update(
            {"_key": key, **update_data},
            return_new=True,
        ))
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
        run_aql(db,
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
        run_aql(db,
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

    return list(run_aql(db,query, bind_vars=bind_vars))


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
        run_aql(db,
            query,
            bind_vars={"@col": collection, "key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Temporal query functions (Week 10)
# ---------------------------------------------------------------------------

# PGT-aligned: include split property collections (ADR-006). Legacy
# ``ontology_properties`` remains for databases not yet migrated.
_ONTOLOGY_VERTEX_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
]

_PROPERTY_VERTEX_COLLECTIONS = [
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
]

# Edges included in point-in-time snapshot and diff. Aligns with
# ``ontology_repo._ONTOLOGY_EDGE_COLLECTIONS`` plus provenance.
_ONTOLOGY_TEMPORAL_EDGE_COLLECTIONS = [
    "subclass_of",
    "has_property",
    "equivalent_class",
    "extends_domain",
    "related_to",
    "rdfs_domain",
    "rdfs_range_class",
    "imports",
    "extracted_from",
]

# Backward-compatible aliases (used by get_diff, get_timeline_events, revert)
_VERTEX_COLLECTIONS = _ONTOLOGY_VERTEX_COLLECTIONS
_EDGE_COLLECTIONS = _ONTOLOGY_TEMPORAL_EDGE_COLLECTIONS


def get_snapshot(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    timestamp: float,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Return the full graph state at ``timestamp`` for an ontology.

    Checks the materialized snapshot cache first (keyed by ontology_id +
    timestamp rounded to the minute, TTL 5 min).  On miss, queries
    ontology classes, all property vertex collections (legacy + PGT split),
    and ontology edge collections filtering by ``created <= ts < expired``.
    """
    cache_key = _snapshot_cache_key(ontology_id, timestamp)

    if not bypass_cache:
        cached = _snapshot_cache_get(cache_key)
        if cached is not None:
            log.debug("snapshot_cache_hit", extra={"ontology_id": ontology_id})
            return cached

    if db is None:
        db = get_db()

    classes: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    vertex_query = """\
FOR doc IN @@col
  FILTER doc.ontology_id == @oid
  FILTER doc.created <= @ts
  FILTER doc.expired > @ts
  RETURN doc"""

    if db.has_collection("ontology_classes"):
        classes = list(
            run_aql(db,
                vertex_query,
                bind_vars={"@col": "ontology_classes", "oid": ontology_id, "ts": timestamp},
            )
        )

    for prop_col in _PROPERTY_VERTEX_COLLECTIONS:
        if not db.has_collection(prop_col):
            continue
        properties.extend(
            list(
                run_aql(
                    db,
                    vertex_query,
                    bind_vars={
                        "@col": prop_col,
                        "oid": ontology_id,
                        "ts": timestamp,
                    },
                )
            )
        )

    active_ids = {doc["_id"] for doc in classes + properties}

    edge_query = """\
FOR e IN @@col
  FILTER e.created <= @ts
  FILTER e.expired > @ts
  RETURN e"""

    for edge_col in _ONTOLOGY_TEMPORAL_EDGE_COLLECTIONS:
        if not db.has_collection(edge_col):
            continue
        col_edges = list(
            run_aql(db,edge_query, bind_vars={"@col": edge_col, "ts": timestamp})
        )
        for e in col_edges:
            if e.get("_from") in active_ids or e.get("_to") in active_ids:
                edges.append(e)

    result = {
        "ontology_id": ontology_id,
        "timestamp": timestamp,
        "classes": classes,
        "properties": properties,
        "edges": edges,
    }

    _snapshot_cache_put(cache_key, result)
    return result


def get_entity_history(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str,
) -> list[dict[str, Any]]:
    """Return all versions of an entity sharing the same ``uri``, sorted by ``created`` DESC.

    Looks up the entity's ``uri`` from the given ``_key``, then finds all
    documents with that URI across versions.
    """
    if db is None:
        db = get_db()

    if not db.has_collection(collection):
        return []

    uri_query = """\
FOR doc IN @@col
  FILTER doc._key == @key
  LIMIT 1
  RETURN doc.uri"""

    uri_results = list(
        run_aql(db,uri_query, bind_vars={"@col": collection, "key": key})
    )
    if not uri_results or uri_results[0] is None:
        return []

    uri = uri_results[0]

    history_query = """\
FOR doc IN @@col
  FILTER doc.uri == @uri
  SORT doc.created DESC
  RETURN doc"""

    return list(
        run_aql(db,history_query, bind_vars={"@col": collection, "uri": uri})
    )


def get_diff(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    t1: float,
    t2: float,
) -> dict[str, Any]:
    """Compare two timestamps and return added/removed/changed entities.

    - **added**: entities active at t2 but not at t1 (by URI)
    - **removed**: entities active at t1 but not at t2 (by URI)
    - **changed**: entities active at both but with different data
    """
    if db is None:
        db = get_db()

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    snapshot_query = """\
FOR doc IN @@col
  FILTER doc.ontology_id == @oid
  FILTER doc.created <= @ts
  FILTER doc.expired > @ts
  RETURN doc"""

    for col_name in _VERTEX_COLLECTIONS:
        if not db.has_collection(col_name):
            continue

        at_t1 = list(
            run_aql(db,
                snapshot_query,
                bind_vars={"@col": col_name, "oid": ontology_id, "ts": t1},
            )
        )
        at_t2 = list(
            run_aql(db,
                snapshot_query,
                bind_vars={"@col": col_name, "oid": ontology_id, "ts": t2},
            )
        )

        t1_by_uri = {doc["uri"]: doc for doc in at_t1 if "uri" in doc}
        t2_by_uri = {doc["uri"]: doc for doc in at_t2 if "uri" in doc}

        for uri, doc in t2_by_uri.items():
            if uri not in t1_by_uri:
                added.append(doc)
            else:
                old_doc = t1_by_uri[uri]
                if _has_data_changed(old_doc, doc):
                    changed.append(
                        {"before": old_doc, "after": doc, "collection": col_name}
                    )

        for uri, doc in t1_by_uri.items():
            if uri not in t2_by_uri:
                removed.append(doc)

    return {
        "ontology_id": ontology_id,
        "t1": t1,
        "t2": t2,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _has_data_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Compare two versioned documents ignoring metadata fields."""
    skip = {"_key", "_id", "_rev", "created", "expired", "version", "ttlExpireAt"}
    for k in set(old.keys()) | set(new.keys()):
        if k in skip:
            continue
        if old.get(k) != new.get(k):
            return True
    return False


def get_timeline_events(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """Aggregate created/expired timestamps into discrete timeline events.

    Returns a chronologically sorted list of events suitable for VCR slider
    tick marks.
    """
    if db is None:
        db = get_db()

    events: list[dict[str, Any]] = []

    event_query = """\
FOR doc IN @@col
  FILTER doc.ontology_id == @oid
  SORT doc.created ASC
  RETURN {
    timestamp: doc.created,
    event_type: doc.source_type == "manual" ? "created_manual"
      : doc.expired != @never ? "expired"
      : "created",
    entity_key: doc._key,
    entity_label: doc.label || doc._key,
    ontology_id: doc.ontology_id,
    uri: doc.uri,
    collection: @col_name,
    extraction_run_id: doc.extraction_run_id
  }"""

    for col_name in _VERTEX_COLLECTIONS:
        if not db.has_collection(col_name):
            continue
        col_events = list(
            run_aql(db,
                event_query,
                bind_vars={
                    "@col": col_name,
                    "oid": ontology_id,
                    "col_name": col_name,
                    "never": NEVER_EXPIRES,
                },
            )
        )
        events.extend(col_events)

    events.sort(key=lambda e: e.get("timestamp", 0))
    return events


def revert_to_version(
    db: StandardDatabase | None = None,
    *,
    collection: str,
    key: str,
    version_created_ts: float,
    edge_collections: list[str] | None = None,
) -> dict[str, Any]:
    """Revert an entity to the state it had at ``version_created_ts``.

    Finds the historical version whose ``created`` matches the given timestamp,
    then creates a new current version with that historical data.
    Does **not** delete intermediate history.
    """
    if db is None:
        db = get_db()

    historical_query = """\
FOR doc IN @@col
  FILTER doc._key == @key
  FILTER doc.created == @ts
  LIMIT 1
  RETURN doc"""

    results = list(
        run_aql(db,
            historical_query,
            bind_vars={"@col": collection, "key": key, "ts": version_created_ts},
        )
    )

    if not results:
        history = get_entity_history(db, collection=collection, key=key)
        for doc in history:
            if abs(doc["created"] - version_created_ts) < 0.001:
                results = [doc]
                break

    if not results:
        raise ValueError(
            f"No version found for {collection}/{key} at timestamp {version_created_ts}"
        )

    historical = results[0]

    revert_data = {
        k: v
        for k, v in historical.items()
        if not k.startswith("_") and k not in ("created", "expired", "version", "ttlExpireAt")
    }

    return update_entity(
        db,
        collection=collection,
        key=_find_current_key(db, collection=collection, uri=historical.get("uri", "")),
        new_data=revert_data,
        created_by="system",
        change_type="revert",
        change_summary=f"Reverted to version from {version_created_ts}",
        edge_collections=edge_collections or _EDGE_COLLECTIONS,
    )


def _find_current_key(
    db: StandardDatabase,
    *,
    collection: str,
    uri: str,
) -> str:
    """Find the ``_key`` of the current (non-expired) version by URI."""
    query = """\
FOR doc IN @@col
  FILTER doc.uri == @uri
  FILTER doc.expired == @never
  LIMIT 1
  RETURN doc._key"""

    results = list(
        run_aql(db,
            query,
            bind_vars={"@col": collection, "uri": uri, "never": NEVER_EXPIRES},
        )
    )
    if not results:
        raise ValueError(f"No current version found for uri={uri} in {collection}")
    return results[0]
