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
    "has_chunk",
    "produced_by",
    "extraction_runs",
    "ontology_registry",
    "curation_decisions",
    "quality_history",
]

ALL_COLLECTIONS = [*ONTOLOGY_COLLECTIONS, "documents", "chunks"]


def _remove_ontology_graphs(db) -> list[str]:
    """Remove all per-ontology named graphs (ontology_*)."""
    removed: list[str] = []
    try:
        for g in db.graphs():
            name = g["name"] if isinstance(g, dict) else g
            if isinstance(name, str) and name.startswith("ontology_"):
                db.delete_graph(name, drop_collections=False)
                removed.append(name)
    except Exception:
        log.warning("failed to list/remove ontology graphs", exc_info=True)
    return removed


def _require_reset_enabled() -> None:
    env_value = os.getenv("ALLOW_SYSTEM_RESET")
    if env_value is None:
        enabled = False
    else:
        enabled = env_value.strip().lower() in {"1", "true", "yes", "on"}

    if not enabled:
        raise HTTPException(
            status_code=403,
            detail="System reset disabled. Set ALLOW_SYSTEM_RESET=true in .env to enable.",
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
    graphs_removed = _remove_ontology_graphs(db)
    log.warning("system reset: truncated %s, removed graphs %s", truncated, graphs_removed)
    return {"reset": True, "collections_truncated": truncated, "graphs_removed": graphs_removed}


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
    graphs_removed = _remove_ontology_graphs(db)
    log.warning("full system reset: truncated %s, removed graphs %s", truncated, graphs_removed)
    return {"reset": True, "collections_truncated": truncated, "graphs_removed": graphs_removed}
