"""Ontology repository — CRUD for ontology_classes, ontology_properties, and edges.

All write operations go through temporal versioning.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES, create_version, expire_entity, update_entity

log = logging.getLogger(__name__)

_ONTOLOGY_EDGE_COLLECTIONS = [
    "subclass_of",
    "has_property",
    "equivalent_class",
    "extends_domain",
    "related_to",
]


def create_class(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    data: dict[str, Any],
    created_by: str = "system",
) -> dict[str, Any]:
    """Create a new ontology class with temporal versioning."""
    if db is None:
        db = get_db()

    doc = {
        **data,
        "ontology_id": ontology_id,
        "version": 1,
    }

    return create_version(
        db,
        collection="ontology_classes",
        data=doc,
        created_by=created_by,
        change_type="initial",
        change_summary=f"Created class {data.get('label', data.get('uri', 'unknown'))}",
    )


def get_class(
    db: StandardDatabase | None = None,
    *,
    key: str,
) -> dict[str, Any] | None:
    """Get the current version of an ontology class by ``_key``."""
    if db is None:
        db = get_db()

    query = """\
FOR cls IN ontology_classes
  FILTER cls._key == @key
  FILTER cls.expired == @never
  LIMIT 1
  RETURN cls"""

    results = list(
        run_aql(
            db,
            query,
            bind_vars={"key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


def list_classes(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """List ontology classes for a given ontology, optionally including expired."""
    if db is None:
        db = get_db()

    if include_expired:
        query = """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  SORT cls.created DESC
  RETURN cls"""
    else:
        query = """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  SORT cls.label ASC
  RETURN cls"""

    bind_vars: dict[str, Any] = {"oid": ontology_id}
    if not include_expired:
        bind_vars["never"] = NEVER_EXPIRES

    return list(run_aql(db, query, bind_vars=bind_vars))


def update_class(
    db: StandardDatabase | None = None,
    *,
    key: str,
    data: dict[str, Any],
    created_by: str = "system",
    change_summary: str = "",
) -> dict[str, Any]:
    """Update an ontology class — expire old, create new version, re-create edges."""
    if db is None:
        db = get_db()

    return update_entity(
        db,
        collection="ontology_classes",
        key=key,
        new_data=data,
        created_by=created_by,
        change_type="edit",
        change_summary=change_summary or f"Updated class {key}",
        edge_collections=_ONTOLOGY_EDGE_COLLECTIONS,
    )


def create_property(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    data: dict[str, Any],
    created_by: str = "system",
) -> dict[str, Any]:
    """Create a new ontology property with temporal versioning."""
    if db is None:
        db = get_db()

    doc = {
        **data,
        "ontology_id": ontology_id,
        "version": 1,
    }

    return create_version(
        db,
        collection="ontology_properties",
        data=doc,
        created_by=created_by,
        change_type="initial",
        change_summary=f"Created property {data.get('label', data.get('uri', 'unknown'))}",
    )


def get_property(
    db: StandardDatabase | None = None,
    *,
    key: str,
) -> dict[str, Any] | None:
    """Get the current version of an ontology property by ``_key``."""
    if db is None:
        db = get_db()

    query = """\
FOR prop IN ontology_properties
  FILTER prop._key == @key
  FILTER prop.expired == @never
  LIMIT 1
  RETURN prop"""

    results = list(
        run_aql(
            db,
            query,
            bind_vars={"key": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


def list_properties(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """List current ontology properties for a given ontology."""
    if db is None:
        db = get_db()

    query = """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  SORT prop.label ASC
  RETURN prop"""

    return list(
        run_aql(
            db,
            query,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def update_property(
    db: StandardDatabase | None = None,
    *,
    key: str,
    data: dict[str, Any],
    created_by: str = "system",
    change_summary: str = "",
) -> dict[str, Any]:
    """Update an ontology property — expire old, create new version, re-create edges."""
    if db is None:
        db = get_db()

    return update_entity(
        db,
        collection="ontology_properties",
        key=key,
        new_data=data,
        created_by=created_by,
        change_type="edit",
        change_summary=change_summary or f"Updated property {key}",
        edge_collections=_ONTOLOGY_EDGE_COLLECTIONS,
    )


def expire_class_cascade(
    db: StandardDatabase | None = None,
    *,
    key: str,
) -> dict[str, Any]:
    """Expire a class and all connected edges (temporal soft delete).

    Finds every active edge in each ontology edge collection where ``_from``
    or ``_to`` matches the class's ``_id`` and expires them as well.
    """
    if db is None:
        db = get_db()

    cls = get_class(db, key=key)
    if cls is None:
        raise ValueError(f"No current version for ontology_classes/{key}")

    class_id = cls["_id"]

    expire_entity(db, collection="ontology_classes", key=key)

    for edge_col in _ONTOLOGY_EDGE_COLLECTIONS:
        if not db.has_collection(edge_col):
            continue
        edge_keys = list(
            run_aql(
                db,
                "FOR e IN @@col "
                "FILTER (e._from == @id OR e._to == @id) "
                "AND e.expired == @never "
                "RETURN e._key",
                bind_vars={"@col": edge_col, "id": class_id, "never": NEVER_EXPIRES},
            )
        )
        for edge_key in edge_keys:
            expire_entity(db, collection=edge_col, key=edge_key)

    log.info("class cascade-expired", extra={"key": key, "class_id": class_id})
    return cls


def create_edge(
    db: StandardDatabase | None = None,
    *,
    edge_collection: str,
    from_id: str,
    to_id: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a temporal edge between two ontology entities."""
    if db is None:
        db = get_db()

    import time

    now = time.time()
    edge_doc = {
        **(data or {}),
        "_from": from_id,
        "_to": to_id,
        "created": now,
        "expired": NEVER_EXPIRES,
        "ttlExpireAt": None,
    }

    result = cast(
        "dict[str, Any]",
        db.collection(edge_collection).insert(edge_doc, return_new=True),
    )
    log.info(
        "ontology edge created",
        extra={
            "edge_collection": edge_collection,
            "from": from_id,
            "to": to_id,
        },
    )
    return result["new"]
