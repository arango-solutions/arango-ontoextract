"""Extraction API endpoints per PRD Section 7.2."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services import extraction as extraction_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/extraction", tags=["extraction"])


class StartRunRequest(BaseModel):
    document_id: str = Field(description="ID of the document to extract from")
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional config overrides (num_passes, consistency_threshold, etc.)",
    )


class StartRunResponse(BaseModel):
    run_id: str
    doc_id: str
    status: str


class RetryResponse(BaseModel):
    run_id: str
    new_run_id: str
    status: str


@router.post("/run")
async def start_extraction(body: StartRunRequest) -> StartRunResponse:
    """Trigger ontology extraction on a document."""
    db = get_db()
    run = await extraction_service.start_run(
        db,
        document_id=body.document_id,
        config_overrides=body.config,
    )
    return StartRunResponse(
        run_id=run["_key"],
        doc_id=run["doc_id"],
        status=run["status"],
    )


@router.get("/runs")
async def list_runs(
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    status: str | None = Query(None, description="Filter by status"),
) -> dict:
    """List extraction runs with cursor-based pagination."""
    db = get_db()
    result = extraction_service.list_runs(
        db,
        cursor=cursor,
        limit=limit,
        status=status,
    )
    return result.model_dump()


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get extraction run status and stats."""
    db = get_db()
    return extraction_service.get_run(db, run_id=run_id)


@router.get("/runs/{run_id}/steps")
async def get_run_steps(run_id: str) -> dict:
    """Get per-agent step detail: inputs, outputs, token usage, errors, duration."""
    db = get_db()
    steps = extraction_service.get_run_steps(db, run_id=run_id)
    return {"run_id": run_id, "steps": steps}


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict:
    """Get extracted entities from a run."""
    db = get_db()
    return extraction_service.get_run_results(db, run_id=run_id)


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str) -> RetryResponse:
    """Retry a failed extraction run."""
    db = get_db()
    new_run = await extraction_service.retry_run(db, run_id=run_id)
    return RetryResponse(
        run_id=run_id,
        new_run_id=new_run["_key"],
        status=new_run["status"],
    )


@router.get("/runs/{run_id}/cost")
async def get_run_cost(run_id: str) -> dict:
    """Get LLM cost breakdown: tokens by model, estimated cost."""
    db = get_db()
    return extraction_service.get_run_cost(db, run_id=run_id)
