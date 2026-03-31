"""Extraction API endpoints per PRD Section 7.2."""

from __future__ import annotations

import logging
import sys
from typing import Any

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services import extraction as extraction_service

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize

router = APIRouter(prefix="/api/v1/extraction", tags=["extraction"])


class StartRunRequest(BaseModel):
    document_id: str | None = Field(
        default=None,
        description="ID of a single document to extract from (backward compat)",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="IDs of documents to extract from (multi-doc mode)",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional config overrides (num_passes, consistency_threshold, etc.)",
    )
    target_ontology_id: str | None = Field(
        default=None,
        description="Existing ontology to merge results into (incremental extraction)",
    )
    base_ontology_ids: list[str] | None = Field(
        default=None,
        description="Multiple base ontologies for Tier 2 context-aware extraction",
    )


class StartRunResponse(BaseModel):
    run_id: str
    doc_id: str | None = None
    doc_ids: list[str] = []
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
    """Trigger ontology extraction on one or more documents.

    Creates the run record immediately and dispatches the pipeline
    as a background task so the HTTP response returns without waiting
    for the full extraction to complete.
    """
    doc_ids = _resolve_doc_ids(body)
    db = get_db()

    ontology_ids: list[str] = []
    if body.target_ontology_id:
        ontology_ids.append(body.target_ontology_id)
    if body.base_ontology_ids:
        ontology_ids.extend(oid for oid in body.base_ontology_ids if oid not in ontology_ids)

    run_record = extraction_service.create_run_record(
        db,
        document_ids=doc_ids,
        config_overrides=body.config,
        domain_ontology_ids=ontology_ids or None,
        target_ontology_id=body.target_ontology_id,
    )
    background_tasks.add_task(
        extraction_service.execute_run,
        run_id=run_record["_key"],
        document_ids=doc_ids,
        config_overrides=body.config,
        domain_ontology_ids=ontology_ids or None,
        target_ontology_id=body.target_ontology_id,
    )
    return StartRunResponse(
        run_id=run_record["_key"],
        doc_id=doc_ids[0] if len(doc_ids) == 1 else None,
        doc_ids=doc_ids,
        status=run_record["status"],
    )


def _resolve_doc_ids(body: StartRunRequest) -> list[str]:
    """Normalize document_id / document_ids into a single list.

    Also validates that every referenced document exists and has finished
    ingestion (status ``ready``).  Raises 422 if any document is missing
    or not yet ready.
    """
    ids: list[str] = []
    if body.document_ids:
        ids.extend(body.document_ids)
    if body.document_id and body.document_id not in ids:
        ids.insert(0, body.document_id)
    if not ids:
        raise HTTPException(
            status_code=422,
            detail="At least one of document_id or document_ids is required",
        )

    db = get_db()
    if db.has_collection("documents"):
        docs_col = db.collection("documents")
        for did in ids:
            doc = docs_col.get(did)
            if doc is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Document '{did}' not found",
                )
            status = doc.get("status", "")
            if status != "ready":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Document '{did}' is not ready for extraction "
                        f"(current status: {status}). Wait for ingestion to complete."
                    ),
                )

    return ids


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
        run_doc_ids = run.get("doc_ids") or []
        legacy_id = run.get("doc_id")
        if legacy_id and legacy_id not in run_doc_ids:
            run_doc_ids = [legacy_id] + run_doc_ids
        if run_doc_ids and db.has_collection("documents"):
            names: list[str] = []
            total_chunks = 0
            for did in run_doc_ids:
                try:
                    doc = db.collection("documents").get(did)
                    if doc:
                        names.append(doc.get("filename", did))
                        total_chunks += doc.get("chunk_count", 0)
                except Exception:
                    pass
            if names:
                run["document_name"] = ", ".join(names)
                run["chunk_count"] = total_chunks
        run.setdefault("document_name", legacy_id or "Unknown")
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
