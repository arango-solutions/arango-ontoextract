"""Persistence for ontology requirements / competency-question specs.

Stream 22 / CQ-PR1 (PRD §6.19). One ``ontology_requirements`` document per target
ontology, keyed by the ontology's registry ``_key`` (natural upsert). Keeps the
CRUD out of the API layer; the coverage service (CQ-PR4/5) reads specs via
:func:`get_requirements` + :func:`iter_competency_questions`.
"""

from __future__ import annotations

import time
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db

COLLECTION = "ontology_requirements"


def get_requirements(db: StandardDatabase | None, ontology_id: str) -> dict[str, Any] | None:
    """Return the requirements spec for an ontology, or ``None``."""
    if db is None:
        db = get_db()
    if not db.has_collection(COLLECTION):
        return None
    doc = db.collection(COLLECTION).get(ontology_id)
    return doc if isinstance(doc, dict) else None


def upsert_requirements(
    db: StandardDatabase | None, ontology_id: str, spec: dict[str, Any]
) -> dict[str, Any]:
    """Create or replace the requirements spec for an ontology."""
    if db is None:
        db = get_db()
    doc = {
        **spec,
        "_key": ontology_id,
        "ontology_id": ontology_id,
        "updated_at": time.time(),
    }
    col = db.collection(COLLECTION)
    if col.has(ontology_id):
        col.replace(doc)
    else:
        col.insert(doc)
    return doc


def delete_requirements(db: StandardDatabase | None, ontology_id: str) -> bool:
    """Delete the requirements spec. Returns True if one was removed."""
    if db is None:
        db = get_db()
    if not db.has_collection(COLLECTION):
        return False
    col = db.collection(COLLECTION)
    if not col.has(ontology_id):
        return False
    col.delete(ontology_id)
    return True


def iter_competency_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a spec's competency questions across all use cases.

    Each returned CQ is annotated with its owning ``use_case`` name so coverage
    reports (CQ-PR5) can group by use case.
    """
    out: list[dict[str, Any]] = []
    for uc in spec.get("use_cases") or []:
        if not isinstance(uc, dict):
            continue
        uc_name = uc.get("name")
        for cq in uc.get("competency_questions") or []:
            if isinstance(cq, dict):
                out.append({**cq, "use_case": uc_name})
    return out
