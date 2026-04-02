"""Quality metrics API endpoints (PRD §6.13, §3.2).

Thin route handlers that delegate to the quality_metrics service.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.db.client import get_db
from app.services.quality_metrics import (
    compute_dashboard_payload,
    compute_extraction_quality,
    compute_ontology_quality,
    get_class_scores,
    get_qualitative_evaluation,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])


@router.get("/dashboard")
async def dashboard() -> dict:
    """Full dashboard payload: summary + per-ontology scorecards + alerts."""
    try:
        db = get_db()
        return compute_dashboard_payload(db)
    except Exception as exc:
        log.exception("Failed to compute dashboard payload")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}")
async def quality_for_ontology(ontology_id: str) -> dict:
    """Return structural and extraction quality scores for an ontology."""
    try:
        db = get_db()
        ontology_quality = compute_ontology_quality(db, ontology_id)
        extraction_quality = compute_extraction_quality(db, ontology_id)
        return {
            **ontology_quality,
            **extraction_quality,
        }
    except Exception as exc:
        log.exception("Failed to compute quality for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/evaluation")
async def qualitative_evaluation(ontology_id: str) -> dict:
    """Return the qualitative evaluation (strengths/weaknesses) for an ontology."""
    try:
        db = get_db()
        result = get_qualitative_evaluation(db, ontology_id)
        return result or {"strengths": [], "weaknesses": [], "status": "not_available"}
    except Exception as exc:
        log.exception("Failed to get evaluation for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/class-scores")
async def class_scores(ontology_id: str) -> dict:
    """Return per-class faithfulness and semantic validity scores for distribution charts."""
    try:
        db = get_db()
        scores = get_class_scores(db, ontology_id)
        return {"ontology_id": ontology_id, "scores": scores}
    except Exception as exc:
        log.exception("Failed to get class scores for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
