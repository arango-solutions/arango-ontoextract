"""001 — Create non-temporal document collections.

Collections: documents, chunks, extraction_runs, curation_decisions,
notifications, organizations, users, aoe_system_meta, ontology_registry.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

NON_TEMPORAL_COLLECTIONS = [
    "documents",
    "chunks",
    "extraction_runs",
    "curation_decisions",
    "notifications",
    "organizations",
    "users",
    "aoe_system_meta",
    "ontology_registry",
]


def up(db: StandardDatabase) -> None:
    for name in NON_TEMPORAL_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            log.info("created collection %s", name)
        else:
            log.debug("collection %s already exists", name)
