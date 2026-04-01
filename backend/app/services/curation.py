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
from app.db.ontology_repo import _ONTOLOGY_EDGE_COLLECTIONS
from app.db.utils import run_aql
from app.services.temporal import (
    NEVER_EXPIRES,
    expire_entity,
    re_create_edges,
    update_entity,
)

log = logging.getLogger(__name__)

_ENTITY_COLLECTION_MAP = {
    "class": "ontology_classes",
    "property": "ontology_properties",
}


def _collection_for(entity_type: str) -> str:
    col = _ENTITY_COLLECTION_MAP.get(entity_type)
    if col is None:
        raise ValueError(f"Unsupported entity_type: {entity_type}")
    return col


def record_decision(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    entity_key: str,
    entity_type: str,
    action: str,
    curator_id: str,
    notes: str | None = None,
    edited_data: dict[str, Any] | None = None,
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

    decision_doc = {
        "run_id": run_id,
        "entity_key": entity_key,
        "entity_type": entity_type,
        "action": action,
        "curator_id": curator_id,
        "notes": notes,
        "edited_data": edited_data,
        "created_at": time.time(),
    }
    saved = curation_repo.create_decision(db, data=decision_doc)

    if entity_type == "edge":
        log.info(
            "curation decision recorded for edge (no temporal side-effect)",
            extra={"decision_key": saved["_key"], "action": action},
        )
        return saved

    collection = _collection_for(entity_type)

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

    if collection in ("ontology_classes", "ontology_properties"):
        try:
            expire_class_cascade(db, key=key)
        except ValueError:
            expire_entity(db, collection=collection, key=key)
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
                edited_data=item.get("edited_data"),
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
        run_aql(db,
            query,
            bind_vars={"@col": collection, "key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None
