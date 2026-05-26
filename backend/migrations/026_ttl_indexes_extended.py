"""026 — Sparse TTL indexes on ``ttlExpireAt`` for collections added after migration 006.

Migration 006 created TTL indexes on the original set of versioned
collections. Several collections were added later:

* ``ontology_object_properties`` / ``ontology_datatype_properties``
  -- the PGT property split per ADR-006.
* ``rdfs_domain`` / ``rdfs_range_class`` -- temporal edge collections
  added when the rule engine + ArangoRDF bridge started persisting
  RDF schema relations.

Without TTL indexes on these collections, expired versions stay in
the database forever even when ``ttlExpireAt`` is set -- Arango only
GCs rows under a sparse TTL index. This migration closes the gap.

Idempotency: same belt-and-braces approach as 006 -- check
``col.indexes()`` for ``idx_<name>_ttl``, only ``add_ttl_index`` when
missing, and catch ``IndexCreateError`` to absorb the race between
two migration runners (or a re-run after a partial apply). A missing
collection (eg on a database that never ingested object/datatype
properties) is logged and skipped rather than raised -- the migration
runner already retries failed migrations and we'd rather degrade
gracefully than block the upgrade path on optional collections.

Why a new migration rather than editing 006: migration 006 already
ran in production. ``MigrationRunner`` keys completion by file name
in ``schema_migrations``; rewriting 006 in place would NOT re-execute
on those databases, so the new collections would stay un-indexed.
The fix has to ship as a separate, sequenced file.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

# Collections added after migration 006. Keep ordered by category for
# the operator reading the log line on a slow database.
EXTENDED_VERSIONED_COLLECTIONS = [
    # PGT property split (ADR-006)
    "ontology_object_properties",
    "ontology_datatype_properties",
    # Temporal edge collections added later
    "rdfs_domain",
    "rdfs_range_class",
]


def up(db: StandardDatabase) -> None:
    for name in EXTENDED_VERSIONED_COLLECTIONS:
        if not db.has_collection(name):
            log.warning(
                "TTL index target collection missing; skipping",
                extra={"collection": name},
            )
            continue

        idx_name = f"idx_{name}_ttl"
        col = db.collection(name)

        # cast narrows the union returned by python-arango's
        # ``indexes()`` (which can also be AsyncJob / BatchJob /
        # None in async-batch modes we never use here). Same pattern
        # used in higher-traffic migrations under app/db/.
        existing_indexes = cast("list[dict[str, Any]]", col.indexes())
        for idx in existing_indexes:
            if idx.get("name") == idx_name:
                log.debug("TTL index %s already exists on %s", idx_name, name)
                break
        else:
            try:
                col.add_ttl_index(
                    fields=["ttlExpireAt"],
                    expiry_time=0,
                    name=idx_name,
                    in_background=True,
                )
                log.info("created TTL index %s on %s", idx_name, name)
            except IndexCreateError:
                # Race with another concurrent migration runner. Safe
                # to swallow because the only thing we'd do on retry is
                # the same idempotent add_ttl_index call.
                log.debug("TTL index %s already exists on %s (race)", idx_name, name)
