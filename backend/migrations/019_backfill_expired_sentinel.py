"""019 — Backfill temporal ``expired`` sentinel values.

Older writes may have ``expired: null``, a missing ``expired`` field, or ``0``
instead of ``NEVER_EXPIRES`` (``sys.maxsize``). Point-in-time and current-state
queries that compare to the sentinel then return incorrect results.

Idempotent: only updates documents where ``expired`` is null, absent, or 0.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# Vertex and edge collections that use edge-interval temporal semantics.
COLLECTIONS_WITH_EXPIRED: tuple[str, ...] = (
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "ontology_object_properties",
    "ontology_datatype_properties",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
    "rdfs_domain",
    "rdfs_range_class",
    "has_chunk",
    "produced_by",
)


def _backfill_collection(db: StandardDatabase, name: str) -> int:
    if not db.has_collection(name):
        return 0
    result = list(
        run_aql(
            db,
            """
            RETURN LENGTH(
              FOR doc IN @@col
                FILTER doc.expired == null
                    OR doc.expired == 0
                    OR !HAS(doc, "expired")
                UPDATE doc WITH { expired: @never } IN @@col
                RETURN 1
            )
            """,
            bind_vars={"@col": name, "never": NEVER_EXPIRES},
        ),
    )
    updated = int(result[0]) if result else 0
    if updated:
        log.info("backfilled expired sentinel on %s (%d documents)", name, updated)
    return updated


def up(db: StandardDatabase) -> None:
    total = 0
    for name in COLLECTIONS_WITH_EXPIRED:
        total += _backfill_collection(db, name)
    if total:
        log.info("019_backfill_expired_sentinel: updated %d documents total", total)
    else:
        log.debug("019_backfill_expired_sentinel: nothing to backfill")
