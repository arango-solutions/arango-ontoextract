"""030 — Ontology requirements / competency-question specs (Stream 22 / CQ-PR1).

Creates ``ontology_requirements``: one document per target ontology (``_key`` ==
the ontology's registry ``_key``) holding an ORSD-style requirements spec —
purpose, scope, intended uses, and use cases with their competency questions
(PRD §6.19 / FR-19.1). One-spec-per-ontology, so ``_key`` keying gives natural
upsert semantics; no extra index needed.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

_COLLECTION = "ontology_requirements"


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)
