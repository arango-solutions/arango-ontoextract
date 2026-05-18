"""Extraction API endpoints per PRD Section 7.2."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.client import get_db
from app.db.utils import doc_get, run_aql
from app.services import extraction as extraction_service

log = logging.getLogger(__name__)

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

    # `domain_ontology_ids` feeds the Tier 2 LLM context. Historically it
    # absorbed `base_ontology_ids` too, so user-declared bases also showed
    # up in the prompt; keep that for backwards compat AND pass bases
    # through separately so the H.8 post-success hook can record
    # `owl:imports` edges from the new ontology to each base.
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
        base_ontology_ids=body.base_ontology_ids,
    )
    background_tasks.add_task(
        extraction_service.execute_run,
        run_id=run_record["_key"],
        document_ids=doc_ids,
        config_overrides=body.config,
        domain_ontology_ids=ontology_ids or None,
        target_ontology_id=body.target_ontology_id,
        base_ontology_ids=body.base_ontology_ids,
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
            doc = doc_get(docs_col, did)
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
) -> dict[str, Any]:
    """List extraction runs with enriched metadata.

    Stream 12 T8: bulk-enrich the page in two AQL round-trips instead of
    one ``doc_get`` per ``doc_id`` per run + one AQL per run for the
    ontology id. On the demo data (25 runs, 1 doc each) this collapsed
    ~50 sequential round-trips into 2 -- moving the endpoint from ~3s
    p95 down to a single-digit-ms tail.
    """
    db = get_db()
    result = extraction_service.list_runs(
        db,
        cursor=cursor,
        limit=limit,
        status=status,
    )
    payload = result.model_dump()
    runs = payload.get("data", [])
    if not runs:
        return payload

    # Phase 1: collect every doc_id and run_key referenced on the page.
    all_doc_ids: set[str] = set()
    run_keys: list[str] = []
    for run in runs:
        for did in run.get("doc_ids") or []:
            if did:
                all_doc_ids.add(did)
        legacy = run.get("doc_id")
        if legacy:
            all_doc_ids.add(legacy)
        if run.get("_key"):
            run_keys.append(run["_key"])

    # Phase 2: one AQL each for documents and ontology_registry. Both
    # use an `IN @ids` filter so they hit the primary index instead of
    # full-scanning the collection.
    doc_index: dict[str, dict[str, Any]] = {}
    if all_doc_ids and db.has_collection("documents"):
        try:
            for d in run_aql(
                db,
                "FOR d IN documents FILTER d._key IN @ids "
                "RETURN {key: d._key, filename: d.filename, "
                "chunk_count: d.chunk_count}",
                bind_vars={"ids": list(all_doc_ids)},
            ):
                doc_index[d["key"]] = d
        except Exception:
            log.debug("bulk document enrichment failed", exc_info=True)

    ontology_index: dict[str, str] = {}
    if run_keys and db.has_collection("ontology_registry"):
        try:
            for entry in run_aql(
                db,
                "FOR o IN ontology_registry "
                "FILTER o.extraction_run_id IN @rids "
                "RETURN {rid: o.extraction_run_id, oid: o._key}",
                bind_vars={"rids": run_keys},
            ):
                # First writer wins for the rare case where two registry
                # rows point at the same run. Matches the pre-T8
                # behaviour (`LIMIT 1`).
                ontology_index.setdefault(entry["rid"], entry["oid"])
        except Exception:
            log.debug("bulk ontology_id enrichment failed", exc_info=True)

    # Phase 3: stamp each run with the bulk-fetched metadata. Same
    # final shape as the pre-T8 per-run loop -- callers see no diff.
    for run in runs:
        run_doc_ids = run.get("doc_ids") or []
        legacy_id = run.get("doc_id")
        if legacy_id and legacy_id not in run_doc_ids:
            run_doc_ids = [legacy_id, *run_doc_ids]

        names: list[str] = []
        total_chunks = 0
        for did in run_doc_ids:
            d = doc_index.get(did)
            if d:
                names.append(d.get("filename") or did)
                total_chunks += d.get("chunk_count") or 0
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

        # Resolve `ontology_id` from the registry. Earlier versions of
        # this enrichment also re-counted live `ontology_classes` +
        # `ontology_properties` for the target ontology and clobbered
        # `classes_extracted` / `properties_extracted` with
        # whole-ontology totals -- two bugs in one place:
        #
        #   1. Wrong semantic: `*_extracted` should reflect what THIS
        #      run contributed (the Pipeline Monitor's mental model),
        #      not the post-merge size of the target ontology. When 4
        #      docs shared a domain, the override made every run look
        #      like it produced N classes (the running total), not its
        #      actual delta.
        #   2. Wrong collection: `ontology_properties` is the legacy
        #      pre-PGT-split collection and is empty -- live properties
        #      now live in `ontology_object_properties` and
        #      `ontology_datatype_properties`.
        #
        # Per-run stats are populated from `run.stats` above; here we
        # only resolve the *which ontology* link via the bulk index.
        if run.get("_key") in ontology_index:
            run["ontology_id"] = ontology_index[run["_key"]]
        if "ontology_id" not in run and run.get("target_ontology_id"):
            run["ontology_id"] = run["target_ontology_id"]

    return payload


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get extraction run status and stats."""
    db = get_db()
    return extraction_service.get_run(db, run_id=run_id)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, Any]:
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
async def get_run_steps(run_id: str) -> dict[str, Any]:
    """Get per-agent step detail: inputs, outputs, token usage, errors, duration."""
    db = get_db()
    steps = extraction_service.get_run_steps(db, run_id=run_id)
    return {"run_id": run_id, "steps": steps}


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict[str, Any]:
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
async def get_run_cost(run_id: str, refresh: bool = False) -> dict[str, Any]:
    """Get LLM cost breakdown: tokens by model, estimated cost.

    Pass ``?refresh=true`` to bypass the cached quality snapshot
    (Stream 12 T7) and recompute the run's ontology quality metrics.
    Without it, repeat hits return the cached numbers and the
    ``quality_computed_at`` field tells the caller how stale the
    snapshot is.
    """
    db = get_db()
    return extraction_service.get_run_cost(db, run_id=run_id, refresh=refresh)
