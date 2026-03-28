"""ExtractionRunService — orchestrates extraction pipeline lifecycle.

Creates extraction_runs records, dispatches LangGraph pipeline, updates status,
and tracks token usage and cost.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from arango.database import StandardDatabase

from app.api.errors import NotFoundError
from app.config import settings
from app.db.client import get_db
from app.db.pagination import paginate
from app.extraction.pipeline import run_pipeline
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

_COST_PER_1K_TOKENS: dict[str, float] = {
    "claude-sonnet-4-20250514": 0.003,
    "claude-3-5-sonnet-20241022": 0.003,
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
}


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _get_collection(db: StandardDatabase, name: str):
    if not db.has_collection(name):
        db.create_collection(name)
    return db.collection(name)


async def start_run(
    db: StandardDatabase | None = None,
    *,
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Create an extraction run record and dispatch the LangGraph pipeline.

    Returns the run record with status.
    """
    if db is None:
        db = get_db()

    run_id = _generate_run_id()
    now = time.time()

    chunks = _load_document_chunks(db, document_id)

    run_record = {
        "_key": run_id,
        "doc_id": document_id,
        "model": settings.llm_extraction_model,
        "prompt_version": "tier1_standard",
        "started_at": now,
        "completed_at": None,
        "status": "running",
        "stats": {
            "passes": settings.extraction_passes,
            "consistency_threshold": settings.extraction_consistency_threshold,
            "token_usage": {},
            "errors": [],
            "step_logs": [],
        },
    }

    if config_overrides:
        run_record["stats"].update(config_overrides)

    col = _get_collection(db, "extraction_runs")
    col.insert(run_record)

    log.info(
        "extraction run created",
        extra={"run_id": run_id, "doc_id": document_id, "chunk_count": len(chunks)},
    )

    try:
        final_state = await run_pipeline(
            run_id=run_id,
            document_id=document_id,
            chunks=chunks,
            event_callback=event_callback,
        )

        completed_at = time.time()
        status = "completed"
        if final_state.get("errors"):
            status = "completed_with_errors"
        if final_state.get("consistency_result") is None:
            status = "failed"

        update_data: dict[str, Any] = {
            "completed_at": completed_at,
            "status": status,
            "stats": {
                **run_record["stats"],
                "token_usage": final_state.get("token_usage", {}),
                "errors": final_state.get("errors", []),
                "step_logs": [
                    _serialize_step_log(sl) for sl in final_state.get("step_logs", [])
                ],
                "classes_extracted": (
                    len(final_state["consistency_result"].classes)
                    if final_state.get("consistency_result")
                    else 0
                ),
            },
        }
        col.update({"_key": run_id, **update_data})

        if final_state.get("consistency_result"):
            _store_results(db, run_id=run_id, result=final_state["consistency_result"])

    except Exception as exc:
        log.exception("extraction pipeline failed", extra={"run_id": run_id})
        col.update({
            "_key": run_id,
            "status": "failed",
            "completed_at": time.time(),
            "stats": {
                **run_record["stats"],
                "errors": [str(exc)],
            },
        })
        raise

    updated = col.get(run_id)
    return updated


def get_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction run details."""
    if db is None:
        db = get_db()

    col = _get_collection(db, "extraction_runs")
    run = col.get(run_id)
    if run is None:
        raise NotFoundError(f"Extraction run '{run_id}' not found")
    return run


def list_runs(
    db: StandardDatabase | None = None,
    *,
    cursor: str | None = None,
    limit: int = 25,
    status: str | None = None,
) -> PaginatedResponse[dict]:
    """List extraction runs with cursor-based pagination."""
    if db is None:
        db = get_db()

    _get_collection(db, "extraction_runs")

    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status

    return paginate(
        db,
        collection="extraction_runs",
        sort_field="started_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
        filters=filters if filters else None,
    )


def get_run_steps(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Get per-agent step logs for a run."""
    run = get_run(db, run_id=run_id)
    return run.get("stats", {}).get("step_logs", [])


def get_run_results(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction results (stored classes and properties) for a run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    results_key = f"results_{run_id}"

    col = _get_collection(db, "extraction_runs")
    results_doc = col.get(results_key)

    if results_doc and "extraction_result" in results_doc:
        return results_doc["extraction_result"]

    return {
        "classes": [],
        "properties": [],
        "run_id": run_id,
        "status": run.get("status", "unknown"),
    }


async def retry_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Retry a failed extraction run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    if run["status"] not in ("failed", "completed_with_errors"):
        raise ValueError(f"Can only retry failed runs, current status: {run['status']}")

    return await start_run(
        db,
        document_id=run["doc_id"],
        event_callback=event_callback,
    )


def get_run_cost(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get token usage and estimated cost for a run."""
    run = get_run(db, run_id=run_id)
    stats = run.get("stats", {})
    token_usage = stats.get("token_usage", {})
    model = run.get("model", settings.llm_extraction_model)

    total_tokens = token_usage.get("total_tokens", 0)
    cost_per_1k = _COST_PER_1K_TOKENS.get(model, 0.003)
    estimated_cost = (total_tokens / 1000) * cost_per_1k

    return {
        "run_id": run_id,
        "model": model,
        "token_usage": token_usage,
        "estimated_cost_usd": round(estimated_cost, 6),
        "cost_per_1k_tokens": cost_per_1k,
    }


def _load_document_chunks(
    db: StandardDatabase,
    document_id: str,
) -> list[dict[str, Any]]:
    """Load chunks for a document from the database."""
    if not db.has_collection("chunks"):
        return []

    query = """\
FOR chunk IN chunks
  FILTER chunk.doc_id == @doc_id
  SORT chunk.chunk_index ASC
  RETURN chunk"""

    return list(db.aql.execute(query, bind_vars={"doc_id": document_id}))


def _store_results(
    db: StandardDatabase,
    *,
    run_id: str,
    result: Any,
) -> None:
    """Persist extraction results alongside the run record."""
    col = _get_collection(db, "extraction_runs")
    results_key = f"results_{run_id}"

    result_data = result.model_dump() if hasattr(result, "model_dump") else result
    doc = {
        "_key": results_key,
        "run_id": run_id,
        "extraction_result": result_data,
        "stored_at": time.time(),
    }

    try:
        col.insert(doc)
    except Exception:
        col.update({"_key": results_key, **doc})


def _serialize_step_log(step_log: dict[str, Any] | Any) -> dict[str, Any]:
    """Serialize a step log entry for storage."""
    if isinstance(step_log, dict):
        return step_log
    if hasattr(step_log, "model_dump"):
        return step_log.model_dump()
    return dict(step_log)
