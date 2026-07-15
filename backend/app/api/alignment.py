"""Multi-source ontology alignment API (Stream 20, PRD §6.17 / FR-17.12).

Session lifecycle + candidate review surface. Materialisation of the reconciled
master (AL-PR4) and MCP tools (AL-PR6) build on these routes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import alignment as alignment_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alignment", tags=["alignment"])


class CreateSessionRequest(BaseModel):
    """Start an alignment session over ≥2 source ontologies."""

    source_ontology_ids: list[str] = Field(..., min_length=2)
    min_score: float = Field(0.5, ge=0.0, le=1.0)
    weights: dict[str, float] | None = None


class CorrespondenceStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(candidate|accepted|rejected)$")


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create a session, generate candidate correspondences, and persist them."""
    try:
        return alignment_svc.create_alignment_session(
            source_ontology_ids=body.source_ontology_ids,
            min_score=body.min_score,
            weights=body.weights,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = alignment_svc.get_alignment_session(None, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"alignment session '{session_id}' not found")
    return session


@router.post("/sessions/{session_id}/adjudicate")
async def adjudicate_session(session_id: str) -> dict[str, Any]:
    """Run selective LLM adjudication over the session's candidates (AL-PR3).

    High-confidence pairs auto-accept; the borderline middle gets an LLM verdict.
    """
    if alignment_svc.get_alignment_session(None, session_id) is None:
        raise HTTPException(status_code=404, detail=f"alignment session '{session_id}' not found")
    return await alignment_svc.adjudicate_session(session_id=session_id)


@router.get("/sessions/{session_id}/candidates")
async def list_candidates(
    session_id: str,
    status: str | None = Query(None, pattern="^(candidate|accepted|rejected)$"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    candidates = alignment_svc.list_session_candidates(
        None,
        session_id,
        status=status,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return {"session_id": session_id, "candidates": candidates, "count": len(candidates)}


@router.post("/candidates/{correspondence_key}/{decision}")
async def decide_candidate(correspondence_key: str, decision: str) -> dict[str, Any]:
    """Accept or reject a candidate correspondence (bounded human confirmation)."""
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'accept' or 'reject'")
    status = "accepted" if decision == "accept" else "rejected"
    updated = alignment_svc.set_candidate_status(None, correspondence_key, status)
    if updated is None:
        raise HTTPException(
            status_code=404, detail=f"correspondence '{correspondence_key}' not found"
        )
    return updated
