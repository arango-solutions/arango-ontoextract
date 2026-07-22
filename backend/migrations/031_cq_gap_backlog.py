"""031 — Competency-question coverage-gap backlog (Stream 22 / CQ-PR6).

Creates ``cq_gap_backlog``: one document per (ontology, competency question) that
coverage validation found *not answerable*, so unanswerable CQs become concrete,
trackable work items instead of a transient report line (PRD §6.19 / FR-19.6).

``_key`` is a deterministic hash of ``ontology_id`` + the CQ text, so re-running
coverage upserts the same item (no duplicates) and can flip it ``open`` ->
``resolved`` when the gap closes. A secondary index on
(``ontology_id``, ``status``) backs the dashboard's open-gap list.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

_COLLECTION = "cq_gap_backlog"


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)
    col = db.collection(_COLLECTION)
    col.add_persistent_index(
        fields=["ontology_id", "status"],
        name="idx_cq_gap_ontology_status",
        sparse=False,
    )
    log.info("ensured index idx_cq_gap_ontology_status on %s", _COLLECTION)
