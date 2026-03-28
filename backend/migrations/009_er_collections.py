"""009 — Create entity resolution collections.

Collections: similarTo (edge), entity_clusters (document), golden_records (document).
Idempotent — checks before create.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

EDGE_COLLECTIONS = ["similarTo"]
DOCUMENT_COLLECTIONS = ["entity_clusters", "golden_records"]


def up(db: StandardDatabase) -> None:
    for name in EDGE_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            log.info("created edge collection %s", name)
        else:
            log.debug("edge collection %s already exists", name)

    for name in DOCUMENT_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            log.info("created document collection %s", name)
        else:
            log.debug("document collection %s already exists", name)
