"""Promotion service — move approved staging entities to production graph.

The staging graph (``staging_{run_id}``) contains entities tagged with
``ontology_id = extraction_{run_id}``. Promotion copies approved entities
to the production ``domain_ontology`` graph, tagging them with the target
``ontology_id``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES, create_version

log = logging.getLogger(__name__)

_VERTEX_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
]
_EDGE_COLLECTIONS = [
    "subclass_of",
    "has_property",
    "equivalent_class",
    "extends_domain",
    "related_to",
    "rdfs_domain",
    "rdfs_range_class",
    "extracted_from",
    "imports",
]

_promotion_cache: dict[str, dict[str, Any]] = {}


def promote_staging(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    ontology_id: str | None = None,
) -> dict[str, Any]:
    """Promote all approved entities from staging to production.

    For each approved entity in the staging graph:
    1. Create a new temporal version in the production collections tagged
       with the target ``ontology_id``.
    2. Re-create edges between promoted entities.

    Returns a promotion report with counts.
    """
    if db is None:
        db = get_db()

    staging_ontology_id = f"extraction_{run_id}"
    target_ontology_id = ontology_id or staging_ontology_id

    promoted_count = 0
    skipped_count = 0
    error_count = 0
    errors: list[dict[str, Any]] = []
    key_map: dict[str, str] = {}

    for col_name in _VERTEX_COLLECTIONS:
        if not db.has_collection(col_name):
            continue

        staging_entities = _get_approved_staging_entities(
            db, collection=col_name, staging_ontology_id=staging_ontology_id
        )

        for entity in staging_entities:
            try:
                old_id = entity["_id"]
                prod_doc = _promote_entity(
                    db,
                    collection=col_name,
                    entity=entity,
                    target_ontology_id=target_ontology_id,
                )
                key_map[old_id] = prod_doc["_id"]
                promoted_count += 1
            except Exception as exc:
                log.warning(
                    "failed to promote entity",
                    extra={"entity_key": entity.get("_key"), "error": str(exc)},
                    exc_info=True,
                )
                errors.append({"entity_key": entity.get("_key"), "error": str(exc)})
                error_count += 1

        skipped_entities = _get_non_approved_staging_entities(
            db, collection=col_name, staging_ontology_id=staging_ontology_id
        )
        skipped_count += len(skipped_entities)

    promoted_edges = _promote_edges(db, key_map=key_map)

    now = time.time()
    report = {
        "run_id": run_id,
        "ontology_id": target_ontology_id,
        "promoted_count": promoted_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "edges_promoted": promoted_edges,
        "promoted_at": now,
        "errors": errors,
        "status": "completed",
    }

    _promotion_cache[run_id] = report

    log.info(
        "staging promotion complete",
        extra={
            "run_id": run_id,
            "promoted": promoted_count,
            "skipped": skipped_count,
            "errors": error_count,
        },
    )

    return report


def get_promotion_status(run_id: str) -> dict[str, Any] | None:
    """Retrieve the cached promotion status for a run."""
    return _promotion_cache.get(run_id)


def _get_approved_staging_entities(
    db: StandardDatabase,
    *,
    collection: str,
    staging_ontology_id: str,
) -> list[dict[str, Any]]:
    """Get entities from the staging graph that have status='approved'."""
    query = """\
FOR doc IN @@col
  FILTER doc.ontology_id == @oid
  FILTER doc.expired == @never
  FILTER doc.status == "approved"
  RETURN doc"""

    return list(
        run_aql(db,
            query,
            bind_vars={
                "@col": collection,
                "oid": staging_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )


def _get_non_approved_staging_entities(
    db: StandardDatabase,
    *,
    collection: str,
    staging_ontology_id: str,
) -> list[dict[str, Any]]:
    """Get entities from the staging graph that are NOT approved."""
    query = """\
FOR doc IN @@col
  FILTER doc.ontology_id == @oid
  FILTER doc.expired == @never
  FILTER doc.status != "approved"
  RETURN doc"""

    return list(
        run_aql(db,
            query,
            bind_vars={
                "@col": collection,
                "oid": staging_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )


def _promote_entity(
    db: StandardDatabase,
    *,
    collection: str,
    entity: dict[str, Any],
    target_ontology_id: str,
) -> dict[str, Any]:
    """Create a new temporal version in production for a staging entity."""
    prod_data = {
        k: v
        for k, v in entity.items()
        if not k.startswith("_") and k not in ("created", "expired", "version", "ttlExpireAt")
    }
    prod_data["ontology_id"] = target_ontology_id
    prod_data["status"] = "approved"

    return create_version(
        db,
        collection=collection,
        data=prod_data,
        created_by="promotion_service",
        change_type="promote",
        change_summary=f"Promoted from staging to production (ontology: {target_ontology_id})",
    )


def _promote_edges(
    db: StandardDatabase,
    *,
    key_map: dict[str, str],
) -> int:
    """Re-create edges between promoted entities in production.

    Only promotes edges where both endpoints were promoted (exist in key_map).
    """
    if not key_map:
        return 0

    count = 0

    for edge_col in _EDGE_COLLECTIONS:
        if not db.has_collection(edge_col):
            continue

        query = """\
FOR e IN @@col
  FILTER e.expired == @never
  RETURN e"""

        edges = list(
            run_aql(db,
                query,
                bind_vars={"@col": edge_col, "never": NEVER_EXPIRES},
            )
        )

        for edge in edges:
            from_id = edge.get("_from", "")
            to_id = edge.get("_to", "")
            new_from = key_map.get(from_id)
            new_to = key_map.get(to_id)

            if new_from is None and new_to is None:
                continue

            resolved_from = new_from or from_id
            resolved_to = new_to or to_id

            edge_data = {
                k: v
                for k, v in edge.items()
                if not k.startswith("_")
                and k not in ("created", "expired", "ttlExpireAt")
            }
            edge_data["_from"] = resolved_from
            edge_data["_to"] = resolved_to
            edge_data["created"] = time.time()
            edge_data["expired"] = NEVER_EXPIRES
            edge_data["ttlExpireAt"] = None

            db.collection(edge_col).insert(edge_data)
            count += 1

    return count
