"""Entity Resolution API endpoints per PRD Section 7.5."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import er as er_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/er", tags=["entity-resolution"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class ERRunRequest(BaseModel):
    """Trigger an ER pipeline run."""

    ontology_id: str
    config: dict[str, Any] | None = Field(None, description="Optional pipeline config overrides")


class ERExplainRequest(BaseModel):
    """Explain a match between two entities."""

    key1: str
    key2: str


class ERMergeRequest(BaseModel):
    """Execute a merge for a candidate pair."""

    source_key: str
    target_key: str
    strategy: str = "most_complete"


class ERCrossTierRequest(BaseModel):
    """Trigger cross-tier resolution."""

    local_ontology_id: str
    domain_ontology_id: str
    min_score: float = 0.5


class ERConfigUpdate(BaseModel):
    """Update ER pipeline configuration."""

    blocking_strategies: list[str] | None = None
    field_configs: list[dict[str, Any]] | None = None
    topological_weight: float | None = None
    similarity_threshold: float | None = None
    vector_similarity_threshold: float | None = None
    wcc_backend: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run")
async def trigger_er_run(body: ERRunRequest) -> dict[str, Any]:
    """Trigger entity resolution pipeline for an ontology."""
    config = None
    if body.config:
        config = er_svc.ERPipelineConfig.from_dict(body.config)

    result = er_svc.run_er_pipeline(ontology_id=body.ontology_id, config=config)
    return {
        "run_id": result.run_id,
        "status": result.status,
        "candidate_count": result.candidate_count,
        "cluster_count": result.cluster_count,
        "duration_seconds": result.duration_seconds,
        "error": result.error,
    }


@router.get("/runs/{run_id}")
async def get_er_run_status(run_id: str) -> dict[str, Any]:
    """Get ER pipeline run status."""
    result = er_svc.get_run_status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"ER run '{run_id}' not found")
    return {
        "run_id": result.run_id,
        "status": result.status,
        "candidate_count": result.candidate_count,
        "cluster_count": result.cluster_count,
        "duration_seconds": result.duration_seconds,
        "error": result.error,
    }


@router.get("/runs/{run_id}/candidates")
async def list_candidates(
    run_id: str,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_resolved: bool = Query(
        False,
        description="When true, returns pairs that have already been "
        "accepted or rejected. Default false hides resolved decisions.",
    ),
) -> dict[str, Any]:
    """List merge candidate pairs with scores (paginated)."""
    run = er_svc.get_run_status(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"ER run '{run_id}' not found")

    ontology_id = run.config.ontology_id if run.config else None
    if not ontology_id:
        return {"data": [], "total_count": 0}

    candidates = er_svc.get_candidates(
        ontology_id=ontology_id,
        min_score=min_score,
        limit=limit,
        offset=offset,
        include_resolved=include_resolved,
    )
    return {"data": candidates, "total_count": len(candidates)}


# ---------------------------------------------------------------------------
# Stream 2 PR 1 -- per-pair decisions (accept / reject / explain).
#
# Routes are scoped by pair_id (not run_id) because the ``similarTo``
# edge is the source of truth for a candidate and is globally unique by
# _key. Run-id-scoped wrappers can be added later for "this UI session"
# UX, but the underlying decision is on the pair, not the run.
# ---------------------------------------------------------------------------


class ERCandidateAcceptRequest(BaseModel):
    """Optional overrides when accepting a merge candidate."""

    strategy: str = Field(
        "most_complete",
        description="Golden-record selection strategy. Currently "
        "supports 'most_complete' (default) and 'newest'.",
    )


@router.post("/candidates/{pair_id}/accept")
async def accept_candidate(
    pair_id: str,
    body: ERCandidateAcceptRequest | None = None,
) -> dict[str, Any]:
    """Accept a merge candidate by ``pair_id``.

    Looks up the source/target from the underlying ``similarTo`` edge,
    runs the merge, and marks the edge as accepted so the inbox does
    not re-surface it. Idempotent: a second accept returns
    ``status: "already_accepted"`` without re-merging.
    """
    strategy = body.strategy if body else "most_complete"
    try:
        return er_svc.accept_candidate(pair_id=pair_id, strategy=strategy)
    except ValueError as exc:
        # ValueError = pair not found, collection missing, or
        # already-rejected (cannot accept-after-reject) -- all 404 / 409
        # shaped errors that the workspace overlay can render as a
        # toast. We distinguish via the error message so the UI can
        # disambiguate if it wants to.
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/candidates/{pair_id}/reject")
async def reject_candidate(pair_id: str) -> dict[str, Any]:
    """Reject a merge candidate by ``pair_id``.

    Soft-marks the ``similarTo`` edge with ``rejected_at`` so it does
    not re-surface in the inbox. Idempotent. Rejection of an
    already-accepted pair is a 409 (the merge already happened).
    """
    try:
        return er_svc.reject_candidate(pair_id=pair_id)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/candidates/{pair_id}/explain")
async def explain_candidate(pair_id: str) -> dict[str, Any]:
    """Field-by-field similarity breakdown for a candidate ``pair_id``.

    Convenience wrapper -- equivalent to looking up the pair's source
    and target keys, then calling :func:`POST /explain` with them.
    """
    try:
        return er_svc.explain_candidate(pair_id=pair_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/clusters")
async def list_clusters(run_id: str) -> dict[str, Any]:
    """List entity clusters from WCC analysis."""
    run = er_svc.get_run_status(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"ER run '{run_id}' not found")

    ontology_id = run.config.ontology_id if run.config else None
    if not ontology_id:
        return {"data": [], "total_count": 0}

    clusters = er_svc.get_clusters(ontology_id=ontology_id)
    return {"data": clusters, "total_count": len(clusters)}


@router.post("/explain")
async def explain_match(body: ERExplainRequest) -> dict[str, Any]:
    """Return detailed field-by-field similarity breakdown for a pair."""
    return er_svc.explain_match(key1=body.key1, key2=body.key2)


@router.post("/merge")
async def execute_merge(body: ERMergeRequest) -> dict[str, Any]:
    """Execute merge for a candidate pair."""
    try:
        return er_svc.execute_merge(
            source_key=body.source_key,
            target_key=body.target_key,
            strategy=body.strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cross-tier")
async def cross_tier_candidates(body: ERCrossTierRequest) -> dict[str, Any]:
    """Find cross-tier duplicate candidates between local and domain ontologies."""
    candidates = er_svc.get_cross_tier_candidates(
        local_ontology_id=body.local_ontology_id,
        domain_ontology_id=body.domain_ontology_id,
        min_score=body.min_score,
    )
    return {"data": candidates, "total_count": len(candidates)}


@router.get("/config")
async def get_er_config() -> dict[str, Any]:
    """Get current ER pipeline configuration."""
    config = er_svc.get_config()
    return config.to_dict()


@router.put("/config")
async def update_er_config(body: ERConfigUpdate) -> dict[str, Any]:
    """Update ER pipeline configuration."""
    current = er_svc.get_config()
    update_data = current.to_dict()
    body_dict = body.model_dump(exclude_none=True)
    update_data.update(body_dict)

    updated = er_svc.update_config(update_data)
    return updated.to_dict()
