import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.errors import ConflictError
from app.api.ontology import _shared

log = logging.getLogger(__name__)
router = APIRouter()


_IMPORT_FILE = File(..., description="OWL/TTL/RDF-XML/JSON-LD file")


# In-process registry of ontology import jobs.
# Keyed by ontology_id. Each value: {ontology_id, status, filename, started_at,
# finished_at?, result?, error?, error_kind?}.
# NOTE: This is per-worker state. With --reload / multi-worker uvicorn, jobs
# won't be visible across workers. The status endpoint falls back to reading
# the registry entry so completed imports remain discoverable.
_import_jobs: dict[str, dict[str, Any]] = {}

# Strong refs to in-flight import tasks. Kept separate from ``_import_jobs``
# because the job dict is serialized as the response of the status endpoint,
# and ``asyncio.Task`` is not JSON-serializable. Python's event loop only holds
# weak references to tasks, so without an explicit strong ref a long-running
# import can be garbage-collected mid-flight.
_import_tasks: dict[str, asyncio.Task[None]] = {}


async def _run_import_job(
    *,
    ontology_id: str,
    content: bytes,
    filename: str,
    ontology_label: str | None,
    ontology_uri_prefix: str | None,
) -> None:
    """Execute the synchronous import in a worker thread and record the result."""
    job = _import_jobs.get(ontology_id)
    if job is None:
        return
    try:
        result = await asyncio.to_thread(
            _shared.import_from_file,
            file_content=content,
            filename=filename,
            ontology_id=ontology_id,
            ontology_label=ontology_label,
            ontology_uri_prefix=ontology_uri_prefix,
        )
        job["status"] = "completed"
        job["result"] = result
        job["finished_at"] = time.time()
    except ValueError as exc:
        log.warning("Import job %s rejected: %s", ontology_id, exc)
        job["status"] = "failed"
        job["error_kind"] = "validation"
        job["error"] = str(exc)
        job["finished_at"] = time.time()
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("Import job %s failed", ontology_id)
        job["status"] = "failed"
        job["error_kind"] = "internal"
        job["error"] = str(exc)
        job["finished_at"] = time.time()


@router.post("/import", status_code=202)
async def import_ontology_endpoint(
    file: UploadFile = _IMPORT_FILE,
    ontology_id: str = Query(..., description="Unique ID for this ontology"),
    ontology_label: str | None = Query(None, description="Human-readable label"),
    ontology_uri_prefix: str | None = Query(None, description="URI prefix for entity filtering"),
) -> dict[str, Any]:
    """Kick off an asynchronous ontology import.

    Returns 202 Accepted immediately with a ``job_status_url`` the client can
    poll. A real import can take minutes (per-triple Arango writes against a
    remote cluster), which exceeds the HTTP proxy timeout — so we decouple the
    work from the request.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required for format detection")

    existing = _import_jobs.get(ontology_id)
    if existing is not None and existing.get("status") == "running":
        raise HTTPException(
            status_code=409, detail=f"Import already in progress for ontology_id '{ontology_id}'"
        )
    if _shared.registry_repo.get_registry_entry(ontology_id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Ontology '{ontology_id}' already exists in the registry"
        )

    content = await file.read()
    _import_jobs[ontology_id] = {
        "ontology_id": ontology_id,
        "status": "running",
        "filename": file.filename,
        "ontology_label": ontology_label,
        "started_at": time.time(),
    }
    task = asyncio.create_task(
        _run_import_job(
            ontology_id=ontology_id,
            content=content,
            filename=file.filename,
            ontology_label=ontology_label,
            ontology_uri_prefix=ontology_uri_prefix,
        )
    )
    _import_tasks[ontology_id] = task

    def _drop_task_ref(_completed: asyncio.Task[None], oid: str = ontology_id) -> None:
        _import_tasks.pop(oid, None)

    task.add_done_callback(_drop_task_ref)
    return {
        "ontology_id": ontology_id,
        "status": "running",
        "filename": file.filename,
        "job_status_url": f"/api/v1/ontology/import/{ontology_id}/status",
    }


@router.get("/import/{ontology_id}/status")
async def import_status_endpoint(ontology_id: str) -> dict[str, Any]:
    """Return the state of an ongoing or recently finished import job.

    If the job isn't in memory (e.g. process restarted) but the ontology exists
    in the registry, reports ``completed`` so the client can recover.
    """
    job = _import_jobs.get(ontology_id)
    if job is not None:
        return job

    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is not None:
        return {
            "ontology_id": ontology_id,
            "status": "completed",
            "result": {
                "registry_key": entry.get("_key", ontology_id),
                "filename": entry.get("source_filename"),
                "triple_count": entry.get("triple_count"),
            },
        }
    raise HTTPException(
        status_code=404, detail=f"No import job found for ontology_id '{ontology_id}'"
    )


# ---------------------------------------------------------------------------
# Create empty ontology (PRD 6.15 FR-15.7)
# ---------------------------------------------------------------------------


class CreateOntologyRequest(BaseModel):
    """Create a new (empty) ontology in the registry."""

    ontology_id: str | None = Field(
        None, description="Optional custom key; auto-generated if omitted"
    )
    name: str = Field(..., min_length=1, description="Human-readable ontology name")
    description: str = Field(default="", description="Optional description")
    uri_prefix: str | None = Field(
        None, description="URI namespace prefix (e.g. http://example.org/ontology/my-ont#)"
    )
    tier: str = Field(default="local", description="Ontology tier: domain or local")
    imports: list[str] = Field(
        default_factory=list,
        description="Registry keys of ontologies to import into this one",
    )


@router.post("/create", status_code=201)
async def create_ontology(body: CreateOntologyRequest) -> dict[str, Any]:
    """Create an empty ontology, optionally importing other ontologies into it."""
    import uuid

    db = _shared.get_db()
    ont_id = body.ontology_id or f"ont_{uuid.uuid4().hex[:12]}"

    existing = _shared.registry_repo.get_registry_entry(ont_id, db=db)
    if existing is not None:
        raise ConflictError(f"Ontology '{ont_id}' already exists")

    uri = body.uri_prefix or f"http://example.org/ontology/{ont_id}#"
    entry = _shared.registry_repo.create_registry_entry(
        {
            "_key": ont_id,
            "name": body.name,
            "label": body.name,
            "description": body.description,
            "tier": body.tier,
            "source": "manual",
            "uri": uri,
            "class_count": 0,
            "property_count": 0,
        },
        db=db,
    )

    imports_created: list[dict[str, str]] = []
    warnings: list[str] = []
    for target_key in body.imports:
        target = _shared.registry_repo.get_registry_entry(target_key, db=db)
        if target is None:
            warnings.append(f"Import target '{target_key}' not found — skipped")
            continue
        if target_key == ont_id:
            warnings.append("Cannot import self — skipped")
            continue
        if not db.has_collection("imports"):
            warnings.append("'imports' edge collection missing — skipped")
            break
        _shared.ontology_repo.create_edge(
            db=db,
            edge_collection="imports",
            from_id=f"ontology_registry/{ont_id}",
            to_id=f"ontology_registry/{target_key}",
            data={"import_iri": target.get("uri", "")},
        )
        imports_created.append({"target": target_key, "name": target.get("name", target_key)})

    return {
        "ontology_id": entry["_key"],
        "name": entry["name"],
        "imports_created": imports_created,
        "warnings": warnings,
    }
