"""Admin endpoints — system reset for development/demo (PRD 7.2.1)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from app.db.client import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ONTOLOGY_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "subclass_of",
    "has_property",
    "has_constraint",
    "extracted_from",
    "extends_domain",
    "related_to",
    "imports",
    "extraction_runs",
    "ontology_registry",
    "curation_decisions",
]

ALL_COLLECTIONS = ONTOLOGY_COLLECTIONS + ["documents", "chunks"]


def _require_reset_enabled() -> None:
    if os.environ.get("ALLOW_SYSTEM_RESET", "").lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=403,
            detail="System reset disabled. Set ALLOW_SYSTEM_RESET=true to enable.",
        )


@router.post("/reset")
async def reset_ontology_data() -> dict:
    """Purge extracted ontology data while keeping documents and chunks."""
    _require_reset_enabled()
    db = get_db()
    truncated: list[str] = []
    for name in ONTOLOGY_COLLECTIONS:
        if db.has_collection(name):
            db.collection(name).truncate()
            truncated.append(name)
    log.warning("system reset: truncated %s", truncated)
    return {"reset": True, "collections_truncated": truncated}


@router.post("/reset/full")
async def reset_all_data() -> dict:
    """Full purge including documents and chunks."""
    _require_reset_enabled()
    db = get_db()
    truncated: list[str] = []
    for name in ALL_COLLECTIONS:
        if db.has_collection(name):
            db.collection(name).truncate()
            truncated.append(name)
    log.warning("full system reset: truncated %s", truncated)
    return {"reset": True, "collections_truncated": truncated}
