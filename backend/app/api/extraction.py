"""Extraction API endpoints per PRD Section 7.2."""

from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services import extraction as extraction_service

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize

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
async def start_extraction(
    body: StartRunRequest,
    background_tasks: BackgroundTasks,
) -> StartRunResponse:
    """Trigger ontology extraction on a document.

    Creates the run record immediately and dispatches the pipeline
    as a background task so the HTTP response returns without waiting
    for the full extraction to complete.
    """
    db = get_db()
    run_record = extraction_service.create_run_record(
        db,
        document_id=body.document_id,
        config_overrides=body.config,
    )
    background_tasks.add_task(
        extraction_service.execute_run,
        run_id=run_record["_key"],
        document_id=body.document_id,
        config_overrides=body.config,
    )
    return StartRunResponse(
        run_id=run_record["_key"],
        doc_id=run_record["doc_id"],
        status=run_record["status"],
    )


@router.get("/runs")
async def list_runs(
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    status: str | None = Query(None, description="Filter by status"),
) -> dict:
    """List extraction runs with enriched metadata."""
    db = get_db()
    result = extraction_service.list_runs(
        db, cursor=cursor, limit=limit, status=status,
    )
    payload = result.model_dump()

    for run in payload.get("data", []):
        doc_id = run.get("doc_id")
        if doc_id and db.has_collection("documents"):
            try:
                doc = db.collection("documents").get(doc_id)
                if doc:
                    run["document_name"] = doc.get("filename", doc_id)
                    run["chunk_count"] = doc.get("chunk_count", 0)
            except Exception:
                pass
        run.setdefault("document_name", doc_id or "Unknown")
        run.setdefault("chunk_count", 0)

        stats = run.get("stats", {})
        run["classes_extracted"] = stats.get("classes_extracted", 0)
        run["properties_extracted"] = stats.get("properties_extracted", 0)
        run["error_count"] = len(stats.get("errors", []))

        started = run.get("started_at", 0)
        completed = run.get("completed_at", 0)
        if started and completed:
            run["duration_ms"] = int((completed - started) * 1000)
        else:
            run.setdefault("duration_ms", 0)

        if db.has_collection("ontology_classes") and run.get("_key"):
            try:
                oid_result = list(db.aql.execute(
                    "FOR o IN ontology_registry "
                    "FILTER o.extraction_run_id == @rid LIMIT 1 RETURN o._key",
                    bind_vars={"rid": run["_key"]},
                ))
                oid = oid_result[0] if oid_result else None
                if oid:
                    cls_count = list(db.aql.execute(
                        "FOR c IN ontology_classes "
                        "FILTER c.ontology_id == @oid AND c.expired == @never "
                        "COLLECT WITH COUNT INTO cnt RETURN cnt",
                        bind_vars={"oid": oid, "never": NEVER_EXPIRES},
                    ))
                    run["classes_extracted"] = cls_count[0] if cls_count else 0
                    prop_count = list(db.aql.execute(
                        "FOR p IN ontology_properties "
                        "FILTER p.ontology_id == @oid AND p.expired == @never "
                        "COLLECT WITH COUNT INTO cnt RETURN cnt",
                        bind_vars={"oid": oid, "never": NEVER_EXPIRES},
                    ))
                    run["properties_extracted"] = prop_count[0] if prop_count else 0
            except Exception:
                pass

    return payload


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get extraction run status and stats."""
    db = get_db()
    return extraction_service.get_run(db, run_id=run_id)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    """Delete an extraction run and its results document."""
    db = get_db()
    if not db.has_collection("extraction_runs"):
        raise HTTPException(status_code=404, detail="No extraction runs collection")
    col = db.collection("extraction_runs")
    if not col.has(run_id):
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    col.delete(run_id)
    results_key = f"results_{run_id}"
    if col.has(results_key):
        col.delete(results_key)
    log.info("deleted extraction run %s", run_id)
    return {"deleted": True, "run_id": run_id}


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
