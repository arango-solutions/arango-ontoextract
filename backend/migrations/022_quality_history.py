"""022 — Quality history snapshots.

Creates ``quality_history`` for timestamped ontology quality snapshots used by
trend views and offline quality review.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_COLLECTION = "quality_history"


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)

    col = db.collection(_COLLECTION)
    idx_name = "idx_quality_history_ontology_timestamp"
    for idx in col.indexes():
        if idx.get("name") == idx_name:
            return
    try:
        col.add_persistent_index(
            fields=["ontology_id", "timestamp"],
            name=idx_name,
        )
    except IndexCreateError:
        log.warning("could not create index %s", idx_name, exc_info=True)
