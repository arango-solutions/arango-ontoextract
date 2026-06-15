"""Quality metrics API endpoints (PRD §6.13, §3.2).

Thin route handlers that delegate to the quality_metrics service.

The dashboard and per-ontology reports issue dozens of synchronous AQL
round-trips; against a remote (cloud/WAN) ArangoDB that takes seconds. Those
handlers run the service call via ``asyncio.to_thread`` so the event loop
keeps serving other requests while the report computes.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.client import get_db, new_db_connection
from app.services.belief_revision_metrics import revisions_dashboard
from app.services.quality_metrics import (
    compute_dashboard_payload,
    compute_quality_report,
    get_class_scores,
    get_qualitative_evaluation,
    get_quality_history,
)
from app.services.quality_recall import compute_recall

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])


@router.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    """Full dashboard payload: summary + per-ontology scorecards + alerts."""
    try:
        db = get_db()
        return await asyncio.to_thread(
            compute_dashboard_payload,
            db,
            db_factory=new_db_connection,
        )
    except Exception as exc:
        log.exception("Failed to compute dashboard payload")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}")
async def quality_for_ontology(ontology_id: str) -> dict[str, Any]:
    """Return structural and extraction quality scores for an ontology."""
    try:
        db = get_db()
        return await asyncio.to_thread(
            compute_quality_report,
            db,
            ontology_id,
            record_snapshot=True,
        )
    except Exception as exc:
        log.exception("Failed to compute quality for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/history")
async def quality_history_for_ontology(
    ontology_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Return timestamped quality snapshots for trend views."""
    try:
        db = get_db()
        return get_quality_history(db, ontology_id, limit=limit)
    except Exception as exc:
        log.exception("Failed to get quality history for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/evaluation")
async def qualitative_evaluation(ontology_id: str) -> dict[str, Any]:
    """Return the qualitative evaluation (strengths/weaknesses) for an ontology."""
    try:
        db = get_db()
        result = get_qualitative_evaluation(db, ontology_id)
        return result or {"strengths": [], "weaknesses": [], "status": "not_available"}
    except Exception as exc:
        log.exception("Failed to get evaluation for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/revisions")
async def revisions_metrics(
    ontology_id: str,
    recent_limit: int = 20,
) -> dict[str, Any]:
    """Belief-revision metrics tile for an ontology (PRD §7.7a, FR-13.26).

    Read-only aggregation: verdict / action / status distribution, decay
    state, pending curation-inbox count, and a short recent-revisions
    timeline. Degrades to zero-filled defaults when the ontology has no
    recorded revisions yet, so the dashboard tile always renders.
    """
    try:
        db = get_db()
        return dict(revisions_dashboard(ontology_id, recent_limit=recent_limit, db=db))
    except Exception as exc:
        log.exception("Failed to get revision metrics for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}/class-scores")
async def class_scores(ontology_id: str) -> dict[str, Any]:
    """Return per-class faithfulness and semantic validity scores for distribution charts."""
    try:
        db = get_db()
        scores = get_class_scores(db, ontology_id)
        return {"ontology_id": ontology_id, "scores": scores}
    except Exception as exc:
        log.exception("Failed to get class scores for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


class RecallRequest(BaseModel):
    """Request body for ``POST /quality/recall`` (Q.4)."""

    ontology_id: str = Field(..., description="ID of the extracted ontology to score.")
    reference_content: str = Field(
        ...,
        description=(
            "Raw OWL/TTL/RDF content to compare against. Submit the file body "
            "as a string; this avoids the operational complexity of multipart "
            "file uploads through the proxy and keeps MCP tooling parity easy."
        ),
    )
    rdf_format: str = Field(
        "turtle",
        description=(
            "rdflib format hint: ``turtle`` (default), ``xml`` (RDF/XML), ``nt``, ``json-ld``."
        ),
    )
    match_threshold: float = Field(
        0.85,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum normalised label similarity for two concepts to be "
            "considered the same. 1.0 = exact post-normalisation match. "
            "Default 0.85 catches plural/case/punctuation differences "
            "without producing many false positives."
        ),
    )
    include_object_properties: bool = Field(
        True,
        description=(
            "Include OWL ObjectProperty recall in the report. Set to ``false`` "
            "for class-only comparison against reference taxonomies that do "
            "not declare relationships."
        ),
    )


@router.post("/recall")
async def quality_recall(body: RecallRequest) -> dict[str, Any]:
    """Q.4 — compute recall (and precision / F1) of an extracted ontology
    against a user-supplied gold-standard OWL/TTL document.

    See ``app/services/quality_recall.compute_recall`` for the matching
    algorithm and report shape.
    """
    try:
        db = get_db()
        return compute_recall(
            db,
            ontology_id=body.ontology_id,
            reference_content=body.reference_content,
            rdf_format=body.rdf_format,
            match_threshold=body.match_threshold,
            include_object_properties=body.include_object_properties,
        )
    except ValueError as exc:
        # Bad rdf_format / parse failure / out-of-range threshold.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Failed to compute recall for ontology %s", body.ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
