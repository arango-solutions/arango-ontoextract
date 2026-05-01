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
    "rdfs_domain",
    "rdfs_range_class",
    "imports",
]

_EDGE_COLLECTIONS_FOR_LOOKUP = list(_ONTOLOGY_EDGE_COLLECTIONS)


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
    collection: str = "ontology_properties",
) -> dict[str, Any]:
    """Create a new ontology property with temporal versioning.

    ``collection`` defaults to ``"ontology_properties"`` for backward compat.
    Callers should pass ``"ontology_object_properties"`` or
    ``"ontology_datatype_properties"`` for PGT-aligned storage.
    """
    if db is None:
        db = get_db()

    doc = {
        **data,
        "ontology_id": ontology_id,
        "version": 1,
    }

    return create_version(
        db,
        collection=collection,
        data=doc,
        created_by=created_by,
        change_type="initial",
        change_summary=f"Created property {data.get('label', data.get('uri', 'unknown'))}",
    )


_PROPERTY_COLLECTIONS = [
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
]


def get_property(
    db: StandardDatabase | None = None,
    *,
    key: str,
) -> dict[str, Any] | None:
    """Get the current version of an ontology property by ``_key``.

    Searches ``ontology_properties`` (legacy), ``ontology_object_properties``,
    and ``ontology_datatype_properties`` in that order.
    """
    if db is None:
        db = get_db()

    for col_name in _PROPERTY_COLLECTIONS:
        if not db.has_collection(col_name):
            continue
        results = list(
            run_aql(
                db,
                f"FOR prop IN {col_name} "
                "FILTER prop._key == @key AND prop.expired == @never "
                "LIMIT 1 RETURN prop",
                bind_vars={"key": key, "never": NEVER_EXPIRES},
            )
        )
        if results:
            return results[0]
    return None


def list_properties(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """List current ontology properties for a given ontology.

    Unions across legacy ``ontology_properties``, ``ontology_object_properties``,
    and ``ontology_datatype_properties``.
    """
    if db is None:
        db = get_db()

    all_props: list[dict[str, Any]] = []
    for col_name in _PROPERTY_COLLECTIONS:
        if not db.has_collection(col_name):
            continue
        all_props.extend(
            run_aql(
                db,
                f"FOR prop IN {col_name} "
                "FILTER prop.ontology_id == @oid AND prop.expired == @never "
                "SORT prop.label ASC RETURN prop",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

    all_props.sort(key=lambda p: (p.get("label") or "").lower())
    return all_props


def _resolve_property_collection(db: StandardDatabase, key: str) -> str:
    """Determine which property collection holds the current version of ``key``."""
    for col_name in _PROPERTY_COLLECTIONS:
        if not db.has_collection(col_name):
            continue
        hits = list(
            run_aql(
                db,
                f"FOR p IN {col_name} FILTER p._key == @key AND p.expired == @never "
                "LIMIT 1 RETURN 1",
                bind_vars={"key": key, "never": NEVER_EXPIRES},
            )
        )
        if hits:
            return col_name
    return "ontology_properties"


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

    collection = _resolve_property_collection(db, key)

    return update_entity(
        db,
        collection=collection,
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


def resolve_ontology_edge(
    db: StandardDatabase | None = None,
    *,
    edge_key: str,
) -> tuple[str, dict[str, Any]] | None:
    """Return ``(collection_name, doc)`` for the current version of an edge by ``_key``."""
    if db is None:
        db = get_db()

    for col_name in _EDGE_COLLECTIONS_FOR_LOOKUP:
        if not db.has_collection(col_name):
            continue
        try:
            # ``Collection.get`` is typed as ``T | AsyncJob[T] | BatchJob[T]``
            # in python-arango because the same handle is reused for batch /
            # async execution; on a ``StandardDatabase`` only the ``dict``
            # branch is ever produced.
            doc = cast(
                "dict[str, Any] | None",
                db.collection(col_name).get(edge_key),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if doc and doc.get("expired") == NEVER_EXPIRES:
            return col_name, doc
    return None


def update_edge(
    db: StandardDatabase | None = None,
    *,
    edge_key: str,
    data: dict[str, Any],
    created_by: str = "workspace",
    change_summary: str = "",
) -> dict[str, Any]:
    """Update an ontology edge (temporal version bump)."""
    if db is None:
        db = get_db()

    resolved = resolve_ontology_edge(db, edge_key=edge_key)
    if resolved is None:
        raise ValueError(f"No current edge found with _key={edge_key!r}")

    collection_name, _doc = resolved

    return update_entity(
        db,
        collection=collection_name,
        key=edge_key,
        new_data=data,
        created_by=created_by,
        change_type="edit",
        change_summary=change_summary or f"Updated edge {edge_key}",
        edge_collections=None,
    )
