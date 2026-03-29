"""005 — MDI-prefixed indexes on temporal fields.

Deployed on all versioned vertex and edge collections to accelerate
point-in-time temporal queries.

The ``mdi-prefixed`` index type uses:
- ``prefixFields``: equality-match fields narrowing the search space first
  (``ontology_id`` — every temporal query is scoped to an ontology)
- ``fields``: multi-dimensional range fields for interval overlap queries
  (``created``, ``expired``)

This enables efficient point-in-time snapshot queries of the form:
  FILTER doc.ontology_id == @oid
    AND doc.created <= @t
    AND (doc.expired == NEVER_EXPIRES OR doc.expired > @t)

python-arango does not expose a dedicated ``add_mdi_prefixed_index`` method,
so we use the raw HTTP API.  If the cluster/version does not support
mdi-prefixed, we fall back to a compound persistent index.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError
from arango.request import Request

log = logging.getLogger(__name__)

VERSIONED_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
]


def _create_mdi_index(db: StandardDatabase, collection_name: str) -> None:
    """Attempt to create an mdi-prefixed index; fall back to persistent."""
    idx_name = f"idx_{collection_name}_mdi_temporal"
    col = db.collection(collection_name)

    for idx in col.indexes():
        if idx.get("name") == idx_name:
            log.debug("index %s already exists on %s", idx_name, collection_name)
            return

    body = {
        "type": "mdi-prefixed",
        "fields": ["created", "expired"],
        "fieldValueTypes": "double",
        "prefixFields": ["ontology_id"],
        "sparse": False,
        "name": idx_name,
    }
    try:
        req = Request(
            method="post",
            endpoint=f"/_api/index?collection={collection_name}",
            data=body,
        )
        resp = db._conn.send_request(req)
        if resp.status_code in (200, 201):
            log.info("created mdi-prefixed index %s on %s", idx_name, collection_name)
            return
        log.warning(
            "mdi-prefixed index creation returned %s on %s — trying fallback",
            resp.status_code, collection_name,
        )
    except Exception as exc:
        log.warning(
            "mdi-prefixed index creation failed on %s: %s — trying fallback",
            collection_name, exc,
        )

    try:
        col.add_persistent_index(
            fields=["ontology_id", "created", "expired"],
            name=idx_name,
        )
        log.info(
            "created persistent (fallback) index %s on %s",
            idx_name,
            collection_name,
        )
    except IndexCreateError:
        log.debug("index %s already exists on %s (via fallback)", idx_name, collection_name)


def up(db: StandardDatabase) -> None:
    for name in VERSIONED_COLLECTIONS:
        if db.has_collection(name):
            _create_mdi_index(db, name)
