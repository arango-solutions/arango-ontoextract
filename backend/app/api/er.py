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
async def trigger_er_run(body: ERRunRequest) -> dict:
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
async def get_er_run_status(run_id: str) -> dict:
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
) -> dict:
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
    )
    return {"data": candidates, "total_count": len(candidates)}


@router.get("/runs/{run_id}/clusters")
async def list_clusters(run_id: str) -> dict:
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
async def explain_match(body: ERExplainRequest) -> dict:
    """Return detailed field-by-field similarity breakdown for a pair."""
    return er_svc.explain_match(key1=body.key1, key2=body.key2)


@router.post("/merge")
async def execute_merge(body: ERMergeRequest) -> dict:
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
async def cross_tier_candidates(body: ERCrossTierRequest) -> dict:
    """Find cross-tier duplicate candidates between local and domain ontologies."""
    candidates = er_svc.get_cross_tier_candidates(
        local_ontology_id=body.local_ontology_id,
        domain_ontology_id=body.domain_ontology_id,
        min_score=body.min_score,
    )
    return {"data": candidates, "total_count": len(candidates)}


@router.get("/config")
async def get_er_config() -> dict:
    """Get current ER pipeline configuration."""
    config = er_svc.get_config()
    return config.to_dict()


@router.put("/config")
async def update_er_config(body: ERConfigUpdate) -> dict:
    """Update ER pipeline configuration."""
    current = er_svc.get_config()
    update_data = current.to_dict()
    body_dict = body.model_dump(exclude_none=True)
    update_data.update(body_dict)

    updated = er_svc.update_config(update_data)
    return updated.to_dict()
