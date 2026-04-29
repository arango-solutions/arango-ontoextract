"""Quality metrics API endpoints (PRD §6.13, §3.2).

Thin route handlers that delegate to the quality_metrics service.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.db.client import get_db
from app.services.quality_metrics import (
    compute_dashboard_payload,
    compute_quality_report,
    get_class_scores,
    get_qualitative_evaluation,
    get_quality_history,
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
        return compute_quality_report(db, ontology_id, record_snapshot=True)
    except Exception as exc:
        log.exception("Failed to compute quality for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/history")
async def quality_history_for_ontology(
    ontology_id: str,
    limit: int = 50,
) -> dict:
    """Return timestamped quality snapshots for trend views."""
    try:
        db = get_db()
        return get_quality_history(db, ontology_id, limit=limit)
    except Exception as exc:
        log.exception("Failed to get quality history for ontology %s", ontology_id)
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
