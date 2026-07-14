"""028 — Multi-source ontology alignment collections (Stream 20 / AL-PR1).

Creates the two document collections behind the alignment API (PRD §6.17):

* ``alignment_sessions`` -- one document per alignment run over N≥2 source
  ontologies. Holds the source id set, parameters, status, and (once
  materialised, AL-PR4) the target master ontology id. Event-style record;
  ``status`` is edited in place, no temporal versioning.
* ``correspondences`` -- one document per candidate correspondence between an
  entity in source A and an entity in source B, with per-signal scores, a
  provisional type, and a curation ``status`` (candidate / accepted / rejected).

Indexes power the two hot reads: "candidates for this session, by status" and
"candidates for this session, highest confidence first" (the DualLoop review
overlay, AL-PR5), plus "sessions touching this source ontology".
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_SESSIONS = "alignment_sessions"
_CORRESPONDENCES = "correspondences"

_SESSION_INDEXES = (
    # (name, fields, sparse)
    ("idx_alignment_sessions_created", ["created"], False),
)
_CORRESPONDENCE_INDEXES = (
    ("idx_correspondences_session_status", ["session_id", "status"], False),
    ("idx_correspondences_session_conf", ["session_id", "confidence"], False),
)


def _ensure(
    db: StandardDatabase,
    name: str,
    indexes: tuple[tuple[str, list[str], bool], ...],
) -> None:
    if not db.has_collection(name):
        db.create_collection(name)
        log.info("created collection %s", name)
    col = db.collection(name)
    existing = {idx.get("name") for idx in col.indexes()}
    for idx_name, fields, sparse in indexes:
        if idx_name in existing:
            continue
        try:
            col.add_persistent_index(fields=fields, name=idx_name, sparse=sparse)
            log.info("created index %s on %s", idx_name, name)
        except IndexCreateError:
            log.warning("could not create index %s on %s", idx_name, name, exc_info=True)


def up(db: StandardDatabase) -> None:
    _ensure(db, _SESSIONS, _SESSION_INDEXES)
    _ensure(db, _CORRESPONDENCES, _CORRESPONDENCE_INDEXES)
