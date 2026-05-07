"""Admin endpoints — system operations and review artifacts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.client import get_db
from app.services.feedback_learning import build_feedback_learning_examples

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ONTOLOGY_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
    "ontology_constraints",
    "subclass_of",
    "has_property",
    "has_constraint",
    "extracted_from",
    "extends_domain",
    "related_to",
    "rdfs_domain",
    "rdfs_range_class",
    "imports",
    "has_chunk",
    "produced_by",
    "extraction_runs",
    "ontology_registry",
    "ontology_releases",
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
    """Allow ``/admin/reset*`` only when the operator opts in via Settings.

    Reads ``settings.allow_system_reset`` (env: ``ALLOW_SYSTEM_RESET``) so the
    knob lives in one place — see ``app.config.Settings`` and
    ``backend/app/AGENTS.md`` ("Configuration comes from app/config.py via the
    settings singleton — never read env vars directly").
    """
    if not settings.allow_system_reset:
        raise HTTPException(
            status_code=403,
            detail="System reset disabled. Set ALLOW_SYSTEM_RESET=true in .env to enable.",
        )


@router.post("/reset")
async def reset_ontology_data() -> dict[str, Any]:
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
async def reset_all_data() -> dict[str, Any]:
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


@router.get("/feedback-learning")
async def feedback_learning_artifacts(
    ontology_id: str | None = Query(
        default=None,
        description="Optional ontology ID used to scope curation feedback.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of curation decisions to convert into artifacts.",
    ),
) -> dict[str, Any]:
    """Return gated HITL learning artifacts for offline review/export."""
    try:
        db = get_db()
        return build_feedback_learning_examples(
            db,
            ontology_id=ontology_id,
            limit=limit,
        )
    except Exception as exc:
        log.exception("failed to build feedback-learning artifacts")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
