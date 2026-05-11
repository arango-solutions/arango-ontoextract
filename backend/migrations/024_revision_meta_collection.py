"""024 — Belief revision audit collection (Stream 11 IBR.1).

Creates ``revision_meta`` -- one document per applied or proposed belief
revision (Phase 2 mechanical verdict or Phase 3 LLM agent action). This
is the audit substrate for PRD §6.16 / FR-16.6.

Design notes
------------

* ``revision_meta`` documents are *immutable* once written; the only
  mutable field is ``status`` (``pending`` / ``applied`` / ``rejected`` /
  ``modified``) which is updated by the curator's accept/reject/modify
  actions. Updating ``status`` is an in-place edit -- no new version is
  created -- because the revision itself is an event record, not a
  belief.
* The ``created`` timestamp is enough for time-ordering; revisions don't
  carry the ``expired`` field used by versioned ontology entities, so we
  use a plain persistent index (not MDI-prefixed).

Indexes
-------

* ``[ontology_id, created]`` -- "show me all revisions for this ontology,
  newest first" (powers ``GET /ontology/{id}/revisions`` and the
  Quality Dashboard time-series tile).
* ``[ontology_id, action, status]`` -- "pending FLAG_FOR_CURATION
  revisions in this ontology" (powers the Revisions Inbox).
* ``[existing_entity_id]`` -- "all revisions touching this class/edge"
  (powers per-class / per-edge revision history endpoints
  ``/ontology/class/{key}/revisions`` and ``/ontology/edge/{key}/revisions``).
* ``[triggering_doc_id]`` -- "what did this document revise?" -- useful
  for Pipeline Monitor run details and for users investigating a
  specific upload.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_COLLECTION = "revision_meta"


_INDEXES = (
    # (name, fields, sparse)
    ("idx_revision_meta_ontology_created", ["ontology_id", "created"], False),
    ("idx_revision_meta_inbox", ["ontology_id", "action", "status"], False),
    ("idx_revision_meta_entity", ["existing_entity_id"], False),
    ("idx_revision_meta_doc", ["triggering_doc_id"], True),
)


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)

    col = db.collection(_COLLECTION)
    existing = {idx.get("name") for idx in col.indexes()}
    for name, fields, sparse in _INDEXES:
        if name in existing:
            continue
        try:
            col.add_persistent_index(fields=fields, name=name, sparse=sparse)
            log.info("created index %s on %s", name, _COLLECTION)
        except IndexCreateError:
            log.warning(
                "could not create index %s on %s",
                name,
                _COLLECTION,
                exc_info=True,
            )
