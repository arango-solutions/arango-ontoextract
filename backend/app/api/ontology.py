import json
import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.db import registry_repo
from app.db.client import get_db
from app.models.curation import (
    TemporalDiff,
    TemporalSnapshot,
)
from app.services import export as export_svc
from app.services import ontology_context as ctx_svc
from app.services import temporal as temporal_svc
from app.services.arangordf_bridge import import_from_file
from app.services.schema_extraction import (
    SchemaExtractionConfig,
    extract_schema,
    get_extraction_status,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])


# ---------------------------------------------------------------------------
# Ontology Library endpoints (PRD 7.3)
# ---------------------------------------------------------------------------


@router.get("/library")
async def list_ontology_library(
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
) -> dict:
    """List all ontologies in the registry with cursor-based pagination."""
    try:
        entries, next_cursor = registry_repo.list_registry_entries(
            cursor=cursor, limit=limit
        )
        db = get_db()
        has_col = db.has_collection("ontology_registry")
        total_count = db.collection("ontology_registry").count() if has_col else 0
        return {
            "data": entries,
            "cursor": next_cursor,
            "has_more": next_cursor is not None,
            "total_count": total_count,
        }
    except Exception as exc:
        log.exception("Failed to list ontology library")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/library/{ontology_id}")
async def get_ontology_detail(ontology_id: str) -> dict:
    """Get ontology detail including stats (class count, property count)."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")

    class_count = 0
    property_count = 0
    try:
        db = get_db()
        if db.has_collection("ontology_classes"):
            result = list(
                db.aql.execute(
                    "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
                    "COLLECT WITH COUNT INTO cnt RETURN cnt",
                    bind_vars={"oid": ontology_id},
                )
            )
            class_count = result[0] if result else 0
        if db.has_collection("ontology_properties"):
            result = list(
                db.aql.execute(
                    "FOR p IN ontology_properties FILTER p.ontology_id == @oid "
                    "COLLECT WITH COUNT INTO cnt RETURN cnt",
                    bind_vars={"oid": ontology_id},
                )
            )
            property_count = result[0] if result else 0
    except Exception:
        log.warning("Could not fetch graph stats for ontology %s", ontology_id, exc_info=True)

    return {
        **entry,
        "stats": {
            "class_count": class_count,
            "property_count": property_count,
        },
    }


# ---------------------------------------------------------------------------
# Organization ontology selection (PRD FR-8.4)
# ---------------------------------------------------------------------------


class OrgOntologySelectionRequest(BaseModel):
    """Request body for selecting base ontologies for an organization."""

    ontology_ids: list[str] = Field(
        ..., description="List of ontology registry IDs to use as base ontologies"
    )


@router.put("/orgs/{org_id}/ontologies")
async def set_org_ontologies(org_id: str, body: OrgOntologySelectionRequest) -> dict:
    """Select base ontologies for an organization.

    Tier 2 extraction will use these ontologies as domain context.
    """
    try:
        result = ctx_svc.set_domain_ontology_for_org(
            org_id=org_id,
            ontology_ids=body.ontology_ids,
        )
        return {"org_id": org_id, "selected_ontologies": result.get("selected_ontologies", [])}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Failed to set org ontologies")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orgs/{org_id}/ontologies")
async def get_org_ontologies(org_id: str) -> dict:
    """List selected base ontologies for an organization."""
    ontology_ids = ctx_svc.get_domain_ontology_for_org(org_id=org_id)
    return {"org_id": org_id, "selected_ontologies": ontology_ids}


# ---------------------------------------------------------------------------
# Domain / Local / Staging / Import / Export stubs (other subagents own these)
# ---------------------------------------------------------------------------


@router.get("/domain")
async def get_domain_ontology(offset: int = 0, limit: int = 100) -> dict:
    """Get the full domain ontology graph, paginated."""
    # TODO: implement domain graph query
    return {"classes": [], "edges": [], "offset": offset, "limit": limit}


@router.get("/domain/classes")
async def list_domain_classes(offset: int = 0, limit: int = 100) -> dict:
    """List domain ontology classes."""
    # TODO: implement class listing with filters
    return {"classes": [], "offset": offset, "limit": limit}


@router.get("/local/{org_id}")
async def get_local_ontology(org_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Get an organization's local ontology extension."""
    # TODO: implement local ontology query
    return {"org_id": org_id, "classes": [], "edges": [], "offset": offset, "limit": limit}


@router.get("/staging/{run_id}")
async def get_staging(run_id: str) -> dict:
    """Get the staging graph for curation."""
    # TODO: implement staging graph query
    return {"run_id": run_id, "classes": [], "edges": []}


@router.post("/staging/{run_id}/promote")
async def promote_staging(run_id: str) -> dict:
    """Promote approved staging entities to production."""
    # TODO: implement promotion logic
    return {"run_id": run_id, "promoted": 0}


@router.get("/{ontology_id}/export")
async def export_ontology_endpoint(
    ontology_id: str,
    format: str = Query("turtle", description="Export format: turtle, jsonld, csv"),
) -> Response:
    """Export an ontology in OWL Turtle, JSON-LD, or CSV format."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")

    try:
        if format == "jsonld":
            data = export_svc.export_jsonld(ontology_id)
            return Response(
                content=json.dumps(data, indent=2),
                media_type="application/ld+json",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.jsonld"'},
            )
        elif format == "csv":
            csv_content = export_svc.export_csv(ontology_id)
            return PlainTextResponse(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.csv"'},
            )
        else:
            ttl_content = export_svc.export_ontology(ontology_id, fmt="turtle")
            return PlainTextResponse(
                content=ttl_content,
                media_type="text/turtle",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.ttl"'},
            )
    except Exception as exc:
        log.exception("Export failed for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_IMPORT_FILE = File(..., description="OWL/TTL/RDF-XML/JSON-LD file")


@router.post("/import")
async def import_ontology_endpoint(
    file: UploadFile = _IMPORT_FILE,
    ontology_id: str = Query(..., description="Unique ID for this ontology"),
    ontology_label: str | None = Query(None, description="Human-readable label"),
    ontology_uri_prefix: str | None = Query(None, description="URI prefix for entity filtering"),
) -> dict:
    """Import an ontology file (OWL/TTL/RDF-XML/JSON-LD) into the platform."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required for format detection")

    try:
        content = await file.read()
        result = import_from_file(
            file_content=content,
            filename=file.filename,
            ontology_id=ontology_id,
            ontology_label=ontology_label,
            ontology_uri_prefix=ontology_uri_prefix,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Import failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Schema extraction endpoints (PRD 6.9 — Week 20)
# ---------------------------------------------------------------------------


@router.post("/schema/extract")
async def trigger_schema_extraction(config: SchemaExtractionConfig) -> dict:
    """Trigger schema extraction from an external ArangoDB database."""
    try:
        result = extract_schema(config)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Schema extraction failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/schema/extract/{run_id}")
async def get_schema_extraction_status(run_id: str) -> dict:
    """Get the status of a schema extraction run."""
    try:
        return get_extraction_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Temporal endpoints (PRD 7.3 — Week 10)
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/snapshot", response_model=TemporalSnapshot)
async def get_snapshot(
    ontology_id: str,
    at: float = Query(..., description="Unix timestamp for the point-in-time snapshot"),
) -> dict:
    """Point-in-time graph state — all classes, properties, and edges active at ``at``."""
    return temporal_svc.get_snapshot(ontology_id=ontology_id, timestamp=at)


@router.get("/class/{class_key}/history")
async def get_class_history(class_key: str) -> list[dict]:
    """All versions of a class sorted by created DESC."""
    history = temporal_svc.get_entity_history(
        collection="ontology_classes",
        key=class_key,
    )
    if not history:
        raise HTTPException(status_code=404, detail=f"Class '{class_key}' not found")
    return history


@router.get("/{ontology_id}/diff", response_model=TemporalDiff)
async def get_diff(
    ontology_id: str,
    t1: float = Query(..., description="Start timestamp"),
    t2: float = Query(..., description="End timestamp"),
) -> dict:
    """Temporal diff — added, removed, and changed entities between t1 and t2."""
    if t1 >= t2:
        raise HTTPException(status_code=400, detail="t1 must be less than t2")
    return temporal_svc.get_diff(ontology_id=ontology_id, t1=t1, t2=t2)


@router.get("/{ontology_id}/timeline")
async def get_timeline(ontology_id: str) -> list[dict]:
    """Discrete change events for VCR slider tick marks."""
    return temporal_svc.get_timeline_events(ontology_id=ontology_id)


@router.post("/class/{class_key}/revert")
async def revert_class(
    class_key: str,
    to_version: float = Query(
        ..., description="Timestamp of the version to revert to"
    ),
) -> dict:
    """Revert a class to a historical version. Creates a new current version."""
    try:
        result = temporal_svc.revert_to_version(
            collection="ontology_classes",
            key=class_key,
            version_created_ts=to_version,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
