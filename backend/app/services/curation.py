"""Curation service — decision recording, batch operations, and entity merging.

Every decision creates a ``curation_decisions`` audit record and, when the
decision implies a data change (approve/reject/edit), a new temporal version
of the affected entity.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from arango.database import StandardDatabase

from app.db import curation_repo
from app.db.client import get_db
from app.db.ontology_repo import _ONTOLOGY_EDGE_COLLECTIONS, _resolve_property_collection
from app.db.utils import run_aql
from app.services.temporal import (
    NEVER_EXPIRES,
    expire_entity,
    re_create_edges,
    update_entity,
)

log = logging.getLogger(__name__)


def _collection_for(
    entity_type: str,
    *,
    db: StandardDatabase | None = None,
    entity_key: str | None = None,
) -> str:
    """Resolve Arango collection for curation entity_type.

    ``property`` resolves via ``_resolve_property_collection`` when ``db`` and
    ``entity_key`` are provided (PGT split collections).
    """
    if entity_type == "class":
        return "ontology_classes"
    if entity_type == "property":
        if db is not None and entity_key:
            return _resolve_property_collection(db, entity_key)
        return "ontology_properties"
    if entity_type == "object_property":
        return "ontology_object_properties"
    if entity_type == "datatype_property":
        return "ontology_datatype_properties"
    raise ValueError(f"Unsupported entity_type: {entity_type}")


def record_decision(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    entity_key: str,
    entity_type: str,
    action: str,
    curator_id: str,
    notes: str | None = None,
    issue_reasons: list[str] | None = None,
    edited_data: dict[str, Any] | None = None,
    decision_latency_ms: int | None = None,
) -> dict[str, Any]:
    """Record a single curation decision and apply the temporal side-effect.

    - **approve**: sets entity status to ``approved``
    - **reject**: expires the entity (sets ``expired=now``)
    - **edit**: creates a new version with ``edited_data``
    - **merge**: no temporal side-effect here (handled by ``merge_entities``)

    Returns the persisted decision document.
    """
    if db is None:
        db = get_db()

    collection: str | None = None
    current_entity: dict[str, Any] | None = None
    if entity_type != "edge":
        collection = _collection_for(
            entity_type,
            db=db,
            entity_key=entity_key,
        )
        if action == "edit":
            current_entity = _get_current_by_key(db, collection=collection, key=entity_key)

    decision_doc = {
        "run_id": run_id,
        "entity_key": entity_key,
        "entity_type": entity_type,
        "action": action,
        "curator_id": curator_id,
        "notes": notes,
        "issue_reasons": issue_reasons or [],
        "edited_data": edited_data,
        "edit_diff": (
            _build_edit_diff(current_entity, edited_data or {}) if action == "edit" else None
        ),
        "created_at": time.time(),
        # Q.5 — None when the client did not supply a measurement (e.g. CLI,
        # MCP, batch import). Querying for throughput filters these out.
        "decision_latency_ms": decision_latency_ms,
    }
    saved = curation_repo.create_decision(db, data=decision_doc)

    if entity_type == "edge":
        log.info(
            "curation decision recorded for edge (no temporal side-effect)",
            extra={"decision_key": saved["_key"], "action": action},
        )
        return saved

    if collection is None:
        raise ValueError(f"Unsupported entity_type: {entity_type}")

    if action == "approve":
        _apply_approve(db, collection=collection, key=entity_key, curator_id=curator_id)
    elif action == "reject":
        _apply_reject(db, collection=collection, key=entity_key)
    elif action == "edit":
        _apply_edit(
            db,
            collection=collection,
            key=entity_key,
            edited_data=edited_data or {},
            curator_id=curator_id,
        )

    log.info(
        "curation decision recorded",
        extra={"decision_key": saved["_key"], "action": action, "entity_key": entity_key},
    )
    return saved


def _apply_approve(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
    curator_id: str,
) -> None:
    """Set entity status to 'approved' via temporal update."""
    update_entity(
        db,
        collection=collection,
        key=key,
        new_data={"status": "approved"},
        created_by=curator_id,
        change_type="approve",
        change_summary="Approved by curator",
        edge_collections=_ONTOLOGY_EDGE_COLLECTIONS,
    )


def _apply_reject(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
) -> None:
    """Expire the entity and all connected edges (temporal soft-delete with cascade).

    Per PRD §5.3 FR-5.2: expiring a vertex must also expire edges to/from it.
    """
    from app.db.ontology_repo import expire_class_cascade

    if collection == "ontology_classes":
        expire_class_cascade(db, key=key)
    else:
        expire_entity(db, collection=collection, key=key)


def _apply_edit(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
    edited_data: dict[str, Any],
    curator_id: str,
) -> None:
    """Create a new version with the edited data."""
    update_entity(
        db,
        collection=collection,
        key=key,
        new_data=edited_data,
        created_by=curator_id,
        change_type="edit",
        change_summary="Edited by curator",
        edge_collections=_ONTOLOGY_EDGE_COLLECTIONS,
    )


def batch_decide(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process a batch of curation decisions.

    Returns a summary with counts and individual results / errors.
    """
    if db is None:
        db = get_db()

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for item in decisions:
        try:
            saved = record_decision(
                db,
                run_id=run_id,
                entity_key=item["entity_key"],
                entity_type=item["entity_type"],
                action=item["action"],
                curator_id=item["curator_id"],
                notes=item.get("notes"),
                issue_reasons=item.get("issue_reasons"),
                edited_data=item.get("edited_data"),
                decision_latency_ms=item.get("decision_latency_ms"),
            )
            results.append(saved)
        except Exception as exc:
            log.warning(
                "batch decision failed",
                extra={"entity_key": item.get("entity_key"), "error": str(exc)},
                exc_info=True,
            )
            errors.append({"entity_key": item.get("entity_key"), "error": str(exc)})

    return {
        "processed": len(decisions),
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def merge_entities(
    db: StandardDatabase | None = None,
    *,
    source_keys: list[str],
    target_key: str,
    merged_data: dict[str, Any],
    curator_id: str,
    collection: str = "ontology_classes",
    notes: str | None = None,
) -> dict[str, Any]:
    """Merge multiple source entities into a target entity.

    1. Expire all source entities.
    2. Re-point source edges to the target.
    3. Create a new version of the target with ``merged_data``.

    Returns merge report.
    """
    if db is None:
        db = get_db()

    edges_recreated = 0
    expired_sources: list[str] = []

    target_current = _get_current_by_key(db, collection=collection, key=target_key)
    if target_current is None:
        raise ValueError(f"Target entity {collection}/{target_key} not found or expired")
    target_id = target_current["_id"]

    for src_key in source_keys:
        src_doc = _get_current_by_key(db, collection=collection, key=src_key)
        if src_doc is None:
            log.warning("source entity %s/%s not found, skipping", collection, src_key)
            continue

        src_id = src_doc["_id"]
        expire_entity(db, collection=collection, key=src_key)
        expired_sources.append(src_key)

        for edge_col in _ONTOLOGY_EDGE_COLLECTIONS:
            edges_recreated += re_create_edges(
                db,
                edge_collection=edge_col,
                old_id=src_id,
                new_id=target_id,
            )

    new_version = update_entity(
        db,
        collection=collection,
        key=target_key,
        new_data={**merged_data, "status": "approved"},
        created_by=curator_id,
        change_type="merge",
        change_summary=f"Merged from {', '.join(expired_sources)}",
        edge_collections=_ONTOLOGY_EDGE_COLLECTIONS,
    )

    curation_repo.create_decision(
        db,
        data={
            "run_id": "merge",
            "entity_key": target_key,
            "entity_type": "class",
            "action": "merge",
            "curator_id": curator_id,
            "notes": notes or f"Merged {len(expired_sources)} entities",
            "created_at": time.time(),
        },
    )

    log.info(
        "entities merged",
        extra={
            "target_key": target_key,
            "expired_sources": expired_sources,
            "edges_recreated": edges_recreated,
        },
    )

    return {
        "target_key": target_key,
        "merged_version": new_version,
        "expired_sources": expired_sources,
        "edges_recreated": edges_recreated,
    }


def get_decisions(
    db: StandardDatabase | None = None,
    *,
    run_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """List curation decisions with pagination."""
    if db is None:
        db = get_db()

    page = curation_repo.list_decisions(
        db,
        run_id=run_id,
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return page.model_dump()


def get_decision(
    db: StandardDatabase | None = None,
    *,
    decision_id: str,
) -> dict[str, Any] | None:
    """Get a single decision by key."""
    if db is None:
        db = get_db()
    return curation_repo.get_decision(db, key=decision_id)


def compute_curation_throughput(
    db: StandardDatabase | None = None,
    *,
    run_id: str | None = None,
    ontology_id: str | None = None,
    window_seconds: int = 3600,
) -> dict[str, Any]:
    """Compute curator throughput as concepts-reviewed-per-hour (Q.5).

    Two strategies, in order of preference:

    1. **Active time** — sum the client-supplied ``decision_latency_ms``
       across decisions in the window. This is the "real" curation time
       because the client only ticks the timer between consecutive
       decisions; idle / break time is not counted.
    2. **Wall-clock fallback** — if no latencies were recorded (e.g. all
       decisions came from MCP / batch import), divide the decision
       count by the wall-clock span between first and last decision.

    Always returns a stable shape so the frontend can render even when
    there is no data:

        {
          "decisions_in_window": int,
          "decisions_per_hour": float | None,
          "active_time_seconds": float | None,
          "wall_clock_seconds": float | None,
          "first_decision_at": float | None,
          "last_decision_at": float | None,
          "source": "active_time" | "wall_clock" | "none",
          "window_seconds": int,
          "run_id": str | None,
          "ontology_id": str | None,
        }
    """
    if db is None:
        db = get_db()

    if not db.has_collection("curation_decisions"):
        return _throughput_empty(window_seconds, run_id, ontology_id)

    cutoff = time.time() - window_seconds

    # Filter clauses are composed conditionally so the AQL stays simple
    # for the common case (no run_id / ontology_id) and the optional
    # ontology_id case still uses the (cheap) ``decisions WHERE run IN
    # runs OF ontology`` join via ``extraction_runs.ontology_id``.
    filters = ["d.created_at >= @cutoff"]
    bind_vars: dict[str, Any] = {"cutoff": cutoff}
    if run_id:
        filters.append("d.run_id == @run_id")
        bind_vars["run_id"] = run_id
    if ontology_id:
        filters.append(
            "d.run_id IN ("
            "  FOR r IN extraction_runs "
            "  FILTER HAS(r, 'ontology_id') AND r.ontology_id == @oid "
            "  RETURN r._key"
            ")"
        )
        bind_vars["oid"] = ontology_id

    query = (
        "FOR d IN curation_decisions "
        f"FILTER {' AND '.join(filters)} "
        "COLLECT AGGREGATE "
        "  count = COUNT(d), "
        "  active_ms_sum = SUM(d.decision_latency_ms), "
        "  measured_count = SUM(d.decision_latency_ms != null ? 1 : 0), "
        "  first_ts = MIN(d.created_at), "
        "  last_ts = MAX(d.created_at) "
        "RETURN { count, active_ms_sum, measured_count, first_ts, last_ts }"
    )
    rows = list(run_aql(db, query, bind_vars=bind_vars))
    row = rows[0] if rows else {}
    count = int(row.get("count") or 0)
    if count == 0:
        return _throughput_empty(window_seconds, run_id, ontology_id)

    measured_count = int(row.get("measured_count") or 0)
    active_ms_sum = row.get("active_ms_sum")
    first_ts = row.get("first_ts")
    last_ts = row.get("last_ts")
    wall_clock_seconds = (last_ts - first_ts) if (first_ts and last_ts) else None

    decisions_per_hour: float | None = None
    active_time_seconds: float | None = None
    source = "none"

    if measured_count > 0 and active_ms_sum and active_ms_sum > 0:
        # Scale the measured-only active time up to the full count so a
        # mix of measured + unmeasured decisions still produces a sane
        # rate (rather than under-counting when a few rows happen to
        # have null latencies).
        active_time_seconds = (active_ms_sum / 1000.0) * (count / measured_count)
        if active_time_seconds > 0:
            decisions_per_hour = count / (active_time_seconds / 3600.0)
            source = "active_time"

    if decisions_per_hour is None and wall_clock_seconds and wall_clock_seconds > 0:
        decisions_per_hour = count / (wall_clock_seconds / 3600.0)
        source = "wall_clock"

    return {
        "decisions_in_window": count,
        "decisions_per_hour": decisions_per_hour,
        "active_time_seconds": active_time_seconds,
        "wall_clock_seconds": wall_clock_seconds,
        "first_decision_at": first_ts,
        "last_decision_at": last_ts,
        "source": source,
        "window_seconds": window_seconds,
        "run_id": run_id,
        "ontology_id": ontology_id,
    }


def _throughput_empty(
    window_seconds: int,
    run_id: str | None,
    ontology_id: str | None,
) -> dict[str, Any]:
    return {
        "decisions_in_window": 0,
        "decisions_per_hour": None,
        "active_time_seconds": None,
        "wall_clock_seconds": None,
        "first_decision_at": None,
        "last_decision_at": None,
        "source": "none",
        "window_seconds": window_seconds,
        "run_id": run_id,
        "ontology_id": ontology_id,
    }


def _get_current_by_key(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
) -> dict[str, Any] | None:
    """Get the current (non-expired) version of an entity by _key."""
    query = """\
FOR doc IN @@col
  FILTER doc._key == @key
  FILTER doc.expired == @never
  LIMIT 1
  RETURN doc"""

    results = list(
        run_aql(
            db,
            query,
            bind_vars={"@col": collection, "key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


def _build_edit_diff(
    current_entity: dict[str, Any] | None,
    edited_data: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact before/after diff for curator edits."""
    changed_fields = sorted(edited_data.keys())
    before = {
        field: current_entity.get(field) if current_entity is not None else None
        for field in changed_fields
    }
    after = {field: edited_data.get(field) for field in changed_fields}
    return {
        "changed_fields": changed_fields,
        "before": before,
        "after": after,
    }
