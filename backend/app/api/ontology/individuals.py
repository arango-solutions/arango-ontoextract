"""A-box individuals read API (Stream 21 / AB-PR6, PRD §6.18 FR-18.11).

Read surface for the assertion graph so the workspace instance lens can list an
ontology's named individuals (with their rdf:type class + span provenance) and
inspect one. Write/curation + RDF export are separate follow-ups.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.ontology import _shared
from app.db import individuals_repo
from app.services import abox_canonicalize

router = APIRouter()


@router.post("/{ontology_id}/individuals/canonicalize")
async def canonicalize_individuals(
    ontology_id: str,
    min_score: float = Query(0.85, ge=0.0, le=1.0),
    auto_merge: bool = Query(False),
) -> dict[str, Any]:
    """Detect (and optionally auto-merge) duplicate individuals (AB-PR3)."""
    return abox_canonicalize.canonicalize_ontology(
        _shared.get_db(), ontology_id=ontology_id, min_score=min_score, auto_merge=auto_merge
    )


@router.get("/{ontology_id}/individuals")
async def list_individuals(
    ontology_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List the ontology's A-box individuals, each with its type + provenance."""
    rows = individuals_repo.list_individuals_with_types(
        _shared.get_db(), ontology_id, limit=limit, offset=offset
    )
    return {"ontology_id": ontology_id, "data": rows, "count": len(rows)}


@router.get("/individuals/{individual_key}")
async def get_individual(individual_key: str) -> dict[str, Any]:
    """Fetch a single individual (with provenance + history-ready fields)."""
    doc = individuals_repo.get_individual(_shared.get_db(), individual_key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"individual '{individual_key}' not found")
    return doc
