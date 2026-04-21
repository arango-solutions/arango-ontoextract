import asyncio
import json
import logging
import re
import sys
import time
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.api.auth import get_user_from_request
from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.db import documents_repo, ontology_repo, registry_repo, releases_repo
from app.db.client import get_db
from app.db.utils import doc_get, run_aql
from app.models.curation import (
    TemporalDiff,
    TemporalSnapshot,
)
from app.models.ontology import (
    CreateClassRequest,
    CreateEdgeRequest,
    CreatePropertyRequest,
    UpdateClassRequest,
    UpdateEdgeRequest,
    UpdatePropertyRequest,
)
from app.services import export as export_svc
from app.services import ontology_context as ctx_svc
from app.services import promotion as promotion_svc
from app.services import temporal as temporal_svc
from app.services.arangordf_bridge import import_from_file
from app.services.schema_extraction import (
    SchemaExtractionConfig,
    extract_schema,
    get_extraction_status,
)

NEVER_EXPIRES: int = sys.maxsize

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])

_LIBRARY_EDGE_COLLECTIONS = (
    "subclass_of",
    "rdfs_domain",
    "rdfs_range_class",
    "has_property",
    "related_to",
)


def _batch_edge_counts_for_ontology_ids(db: Any, ontology_ids: list[str]) -> dict[str, int]:
    """One AQL per edge collection, grouped by ontology_id (avoids N×5 round-trips).

    The previous per-entry loop blocked the asyncio event loop and stalled other
    API routes (e.g. GET /documents) on the same worker.
    """
    if not ontology_ids:
        return {}
    counts: dict[str, int] = {oid: 0 for oid in ontology_ids}
    unique_ids = sorted(set(ontology_ids))
    never = NEVER_EXPIRES
    for edge_col in _LIBRARY_EDGE_COLLECTIONS:
        if not db.has_collection(edge_col):
            continue
        try:
            rows = list(
                run_aql(
                    db,
                    f"FOR e IN {edge_col} "
                    "FILTER e.ontology_id IN @oids AND e.expired == @never "
                    "COLLECT oid = e.ontology_id WITH COUNT INTO cnt "
                    "RETURN {{ oid: oid, cnt: cnt }}",
                    bind_vars={"oids": unique_ids, "never": never},
                )
            )
        except Exception:
            log.debug("batch edge count failed for %s", edge_col, exc_info=True)
            continue
        for row in rows:
            oid = row.get("oid")
            if oid in counts:
                counts[oid] += int(row.get("cnt") or 0)
    return counts


# ---------------------------------------------------------------------------
# Ontology Library endpoints (PRD 7.3)
# ---------------------------------------------------------------------------


@router.get("/library")
async def list_ontology_library(
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    tag: str | None = Query(None, description="Filter by tag"),
) -> dict:
    """List all ontologies in the registry with cursor-based pagination."""
    try:
        entries, next_cursor = registry_repo.list_registry_entries(
            cursor=cursor, limit=limit
        )
        db = get_db()
        has_col = db.has_collection("ontology_registry")
        total_count = db.collection("ontology_registry").count() if has_col else 0

        if tag:
            entries = [e for e in entries if tag in (e.get("tags") or [])]

        oids = [str(e.get("_key", "")) for e in entries if e.get("_key")]
        batch_counts = _batch_edge_counts_for_ontology_ids(db, oids)

        for entry in entries:
            entry.setdefault("tags", [])
            oid = entry.get("_key", "")
            entry.setdefault("edge_count", 0)
            entry.setdefault("updated_at", entry.get("created_at"))
            entry.setdefault("last_updated", entry.get("updated_at") or entry.get("created_at"))
            if oid:
                entry["edge_count"] = batch_counts.get(oid, 0)
            # File imports historically stored only ``label``; UI and APIs expect ``name``.
            raw_name = entry.get("name")
            if raw_name is None or (isinstance(raw_name, str) and not raw_name.strip()):
                fallback = entry.get("label") or oid or "Ontology"
                entry["name"] = str(fallback).strip() or "Ontology"
            if entry.get("tier") not in ("domain", "local"):
                entry["tier"] = "local"

        return {
            "data": entries,
            "cursor": next_cursor,
            "has_more": next_cursor is not None,
            "total_count": total_count,
        }
    except Exception as exc:
        log.exception("Failed to list ontology library")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


class UpdateOntologyRequest(BaseModel):
    """Request body for updating ontology metadata (J.3)."""

    name: str | None = Field(None, description="Updated name")
    description: str | None = Field(None, description="Updated description")
    tags: list[str] | None = Field(None, description="Tag labels")
    tier: str | None = Field(None, description="domain or local")
    status: str | None = Field(None, description="draft, active, or deprecated")


_VALID_STATUSES = {"draft", "active", "deprecated"}
_VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "deprecated"},
    "active": {"deprecated"},
    "deprecated": set(),
}


@router.put("/library/{ontology_id}")
async def update_ontology_metadata(
    ontology_id: str, body: UpdateOntologyRequest
) -> dict:
    """Update ontology registry metadata (J.3).

    Validates status transitions:
    - draft  -> active | deprecated
    - active -> deprecated
    - deprecated -> (none)
    """
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    updates: dict = {}
    if body.name is not None:
        stripped = body.name.strip()
        if not stripped:
            raise ValidationError("Name cannot be empty or whitespace")
        updates["name"] = stripped
        updates["label"] = stripped
    if body.description is not None:
        updates["description"] = body.description
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.tier is not None:
        if body.tier not in ("domain", "local"):
            raise ValidationError(
                f"Invalid tier '{body.tier}'",
                details={"allowed": ["domain", "local"]},
            )
        updates["tier"] = body.tier
    if body.status is not None:
        if body.status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid status '{body.status}'",
                details={"allowed": sorted(_VALID_STATUSES)},
            )
        current_status = entry.get("status", "draft")
        allowed = _VALID_STATUS_TRANSITIONS.get(current_status, set())
        if body.status != current_status and body.status not in allowed:
            raise ValidationError(
                f"Cannot transition from '{current_status}' to '{body.status}'",
                details={"current": current_status, "allowed": sorted(allowed)},
            )
        updates["status"] = body.status

    if not updates:
        raise ValidationError("No fields to update")

    try:
        updated = registry_repo.update_registry_entry(ontology_id, updates)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


class CreateOntologyReleaseRequest(BaseModel):
    """Body for recording a versioned ontology release."""

    version: str = Field(..., min_length=1, max_length=120, description="Release version label, e.g. 1.0.0")
    description: str = Field(
        "",
        max_length=4000,
        description="Short description of this release",
    )
    release_notes: str = Field(
        "",
        max_length=50000,
        description="Detailed release notes or changelog",
    )


@router.post("/library/{ontology_id}/releases")
async def create_ontology_release(
    ontology_id: str,
    body: CreateOntologyReleaseRequest,
    request: Request,
) -> dict:
    """Record a new ontology release and update registry release metadata."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")
    if entry.get("status") == "deprecated":
        raise ValidationError("Cannot release a deprecated ontology")

    user = get_user_from_request(request)
    released_by = user.user_id if user else None

    version = body.version.strip()
    if not version:
        raise ValidationError("Release version is required")

    try:
        rec = releases_repo.create_release(
            ontology_id,
            version=version,
            description=body.description.strip(),
            release_notes=body.release_notes.strip(),
            released_by=released_by,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise ConflictError(msg) from exc
        raise ValidationError(msg) from exc

    return {"release": rec}


@router.get("/library/{ontology_id}/releases")
async def list_ontology_releases(
    ontology_id: str,
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """List release records for an ontology, newest first."""
    if registry_repo.get_registry_entry(ontology_id) is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")
    rows = releases_repo.list_releases_for_ontology(ontology_id, limit=limit)
    return {"data": rows}


@router.delete("/library/{ontology_id}")
async def delete_ontology(
    ontology_id: str,
    confirm: bool = Query(False, description="Set to true to actually delete"),
) -> dict:
    """Deprecate an ontology with cascade analysis (PRD FR-8.13).

    Uses temporal soft-delete: sets ``expired = now`` on all classes,
    properties, and edges so the VCR timeline can still show historical
    state.  The registry entry is marked ``deprecated`` (not removed).
    Per-ontology named graph is removed (it references the same shared
    collections, and expired entities are filtered out by queries).

    Without ``?confirm=true``, returns dependent ontologies (dry-run).
    """
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    if entry.get("status") == "deprecated":
        raise ValidationError(f"Ontology '{ontology_id}' is already deprecated")

    db = get_db()
    now = __import__("time").time()

    dependents: list[dict] = []
    if db.has_collection("imports"):
        dep_edges = list(
            run_aql(db,
                "FOR e IN imports "
                "FILTER e._to == @target AND e.expired == @never "
                "RETURN DISTINCT e._from",
                bind_vars={
                    "target": f"ontology_registry/{ontology_id}",
                    "never": NEVER_EXPIRES,
                },
            )
        )
        if dep_edges and db.has_collection("ontology_registry"):
            dep_keys = [d.split("/")[-1] for d in dep_edges if "/" in d]
            if dep_keys:
                dependents = list(
                    run_aql(db,
                        "FOR o IN ontology_registry FILTER o._key IN @keys "
                        "RETURN {_key: o._key, name: o.name, status: o.status}",
                        bind_vars={"keys": dep_keys},
                    )
                )

    if not confirm:
        return {
            "ontology_id": ontology_id,
            "status": "pending_confirmation",
            "dependent_ontologies": dependents,
            "message": "Pass ?confirm=true to proceed with deprecation.",
        }

    expired_counts: dict[str, int] = {}

    for col_name in (
        "ontology_classes", "ontology_properties",
        "ontology_object_properties", "ontology_datatype_properties",
        "ontology_constraints",
    ):
        if db.has_collection(col_name):
            result = list(
                run_aql(db,
                    f"FOR doc IN {col_name} "
                    "FILTER doc.ontology_id == @oid AND doc.expired == @never "
                    f"UPDATE doc WITH {{ expired: @now }} IN {col_name} "
                    "RETURN NEW._key",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES, "now": now},
                )
            )
            expired_counts[col_name] = len(result)

    for edge_col in (
        "subclass_of", "has_property", "has_constraint", "related_to",
        "equivalent_class", "extracted_from", "extends_domain",
        "has_chunk", "produced_by",
        "rdfs_domain", "rdfs_range_class",
    ):
        if db.has_collection(edge_col):
            result = list(
                run_aql(db,
                    f"FOR e IN {edge_col} "
                    "FILTER e.ontology_id == @oid AND e.expired == @never "
                    f"UPDATE e WITH {{ expired: @now }} IN {edge_col} "
                    "RETURN NEW._key",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES, "now": now},
                )
            )
            expired_counts[edge_col] = len(result)

    if db.has_collection("imports"):
        target_id = f"ontology_registry/{ontology_id}"
        cross_expired = list(
            run_aql(db,
                "FOR e IN imports "
                "FILTER (e._from == @target OR e._to == @target) AND e.expired == @never "
                "UPDATE e WITH { expired: @now } IN imports "
                "RETURN NEW._key",
                bind_vars={"target": target_id, "never": NEVER_EXPIRES, "now": now},
            )
        )
        expired_counts["imports_cross"] = len(cross_expired)

    if db.has_collection("extends_domain"):
        class_ids = []
        if db.has_collection("ontology_classes"):
            class_ids = list(
                run_aql(db,
                    "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
                    "RETURN c._id",
                    bind_vars={"oid": ontology_id},
                )
            )
        if class_ids:
            cross_extends = list(
                run_aql(db,
                    "FOR e IN extends_domain "
                    "FILTER e._to IN @targets AND e.expired == @never "
                    "UPDATE e WITH { expired: @now } IN extends_domain "
                    "RETURN NEW._key",
                    bind_vars={"targets": class_ids, "never": NEVER_EXPIRES, "now": now},
                )
            )
            expired_counts["extends_domain_cross"] = len(cross_extends)

    from app.services.ontology_graphs import delete_ontology_graph

    graph_deleted = delete_ontology_graph(ontology_id, db=db)

    registry_repo.deprecate_registry_entry(ontology_id)

    return {
        "ontology_id": ontology_id,
        "status": "deprecated",
        "expired_at": now,
        "expired_counts": expired_counts,
        "graph_deleted": graph_deleted,
        "dependent_ontologies": dependents,
    }


@router.get("/library/{ontology_id}")
async def get_ontology_detail(ontology_id: str) -> dict:
    """Get ontology detail including stats (class count, property count)."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    class_count = 0
    property_count = 0
    try:
        db = get_db()
        if db.has_collection("ontology_classes"):
            result = list(
                run_aql(db,
                    "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
                    "AND c.expired == @never "
                    "COLLECT WITH COUNT INTO cnt RETURN cnt",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                )
            )
            class_count = result[0] if result else 0
        for prop_col in (
            "ontology_datatype_properties",
            "ontology_object_properties",
            "ontology_properties",
        ):
            if db.has_collection(prop_col):
                result = list(
                    run_aql(db,
                        f"FOR p IN {prop_col} FILTER p.ontology_id == @oid "
                        "AND p.expired == @never "
                        "COLLECT WITH COUNT INTO cnt RETURN cnt",
                        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                    )
                )
                property_count += result[0] if result else 0
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
# Add document to existing ontology (G.3)
# ---------------------------------------------------------------------------

_ADD_DOC_FILE = File(..., description="PDF, DOCX, or Markdown file")


@router.post("/library/{ontology_id}/add-document")
async def add_document_to_ontology(
    ontology_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = _ADD_DOC_FILE,
) -> dict:
    """Upload a document and trigger incremental extraction into an existing ontology."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    content = await file.read()

    mime = file.content_type or ""
    allowed = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/markdown",
    }
    if mime not in allowed:
        if file.filename and file.filename.endswith(".md"):
            mime = "text/markdown"
        else:
            raise ValidationError(
                f"Unsupported file type: {mime}",
                details={"allowed": sorted(allowed)},
            )

    from app.services.ingestion import compute_file_hash

    file_hash = compute_file_hash(content)
    existing = documents_repo.find_document_by_hash(file_hash)
    if existing:
        raise ConflictError(
            "Duplicate document — a file with identical content already exists",
            details={"existing_doc_id": existing["_key"], "file_hash": file_hash},
        )

    doc = documents_repo.create_document(
        filename=file.filename or "untitled",
        mime_type=mime,
        file_hash=file_hash,
    )

    from app.services import extraction as extraction_service
    from app.tasks import process_document

    async def _process_then_extract(doc_id: str, raw: bytes, mt: str, oid: str) -> None:
        await process_document(doc_id, raw, mt)
        db = get_db()
        doc_record = documents_repo.get_document(doc_id, db=db)
        if doc_record and doc_record.get("status") in ("ready", "processed"):
            await extraction_service.start_run(
                db, document_id=doc_id, target_ontology_id=oid,
            )

    background_tasks.add_task(_process_then_extract, doc["_key"], content, mime, ontology_id)

    return {
        "doc_id": doc["_key"],
        "filename": doc["filename"],
        "ontology_id": ontology_id,
        "status": "processing",
    }


# ---------------------------------------------------------------------------
# Document-ontology relationship endpoints (G.6)
# ---------------------------------------------------------------------------


@router.get("/library/{ontology_id}/documents")
async def list_ontology_documents(ontology_id: str) -> dict:
    """List source documents linked to an ontology via ``extracted_from`` edges."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    db = get_db()
    documents: list[dict] = []
    if db.has_collection("extracted_from") and db.has_collection("documents"):
        documents = list(run_aql(db,
            "FOR e IN extracted_from "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "LET doc_key = PARSE_IDENTIFIER(e._to).key "
            "FOR d IN documents "
            "FILTER d._key == doc_key "
            "COLLECT doc = d INTO group "
            "RETURN MERGE(doc, {edge_count: LENGTH(group)})",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))

    return {"ontology_id": ontology_id, "documents": documents}


# ---------------------------------------------------------------------------
# Library full-text search (J.6)
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_ontology_library(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results per source type"),
    offset: int = Query(0, ge=0, description="Result offset for pagination"),
) -> dict:
    """Full-text search across ontology registry, classes, and properties (J.6).

    Uses the ``ontology_search_view`` ArangoSearch view with BM25 ranking.
    Returns results grouped by source type with snippets and ontology context.
    """
    db = get_db()

    existing_views = {v["name"] for v in cast("list[dict[str, Any]]", db.views())}
    if "ontology_search_view" not in existing_views:
        return {
            "query": q,
            "results": {"registry": [], "classes": [], "properties": []},
            "counts": {"registry": 0, "classes": 0, "properties": 0},
        }

    registry_results: list[dict] = []
    if db.has_collection("ontology_registry"):
        registry_results = list(
            run_aql(db,
                "FOR doc IN ontology_search_view "
                "SEARCH ANALYZER("
                "  BOOST(PHRASE(doc.name, @q), 3) OR "
                "  BOOST(LIKE(doc.name, CONCAT('%', @q, '%')), 2) OR "
                "  PHRASE(doc.description, @q)"
                ", 'text_en') "
                "FILTER IS_SAME_COLLECTION('ontology_registry', doc) "
                "SORT BM25(doc) DESC "
                "LIMIT @offset, @limit "
                "RETURN {"
                "  _key: doc._key, name: doc.name, "
                "  description: doc.description, "
                "  tier: doc.tier, status: doc.status, "
                "  tags: doc.tags, "
                "  score: BM25(doc), source: 'registry'"
                "}",
                bind_vars={"q": q, "offset": offset, "limit": limit},
            )
        )

    class_results: list[dict] = []
    if db.has_collection("ontology_classes"):
        class_results = list(
            run_aql(db,
                "FOR doc IN ontology_search_view "
                "SEARCH ANALYZER("
                "  BOOST(PHRASE(doc.label, @q), 3) OR "
                "  BOOST(LIKE(doc.label, CONCAT('%', @q, '%')), 2) OR "
                "  PHRASE(doc.description, @q)"
                ", 'text_en') "
                "FILTER IS_SAME_COLLECTION('ontology_classes', doc) "
                "FILTER doc.expired == @never "
                "SORT BM25(doc) DESC "
                "LIMIT @offset, @limit "
                "LET ont = (FOR o IN ontology_registry "
                "FILTER o._key == doc.ontology_id LIMIT 1 RETURN o)[0] "
                "RETURN {"
                "  _key: doc._key, label: doc.label, "
                "  description: doc.description, "
                "  ontology_id: doc.ontology_id, "
                "  ontology_name: ont.name, "
                "  confidence: doc.confidence, "
                "  score: BM25(doc), source: 'class'"
                "}",
                bind_vars={"q": q, "offset": offset, "limit": limit, "never": NEVER_EXPIRES},
            )
        )

    property_results: list[dict] = []
    if db.has_collection("ontology_properties"):
        property_results = list(
            run_aql(db,
                "FOR doc IN ontology_search_view "
                "SEARCH ANALYZER("
                "  BOOST(PHRASE(doc.label, @q), 3) OR "
                "  LIKE(doc.label, CONCAT('%', @q, '%'))"
                ", 'text_en') "
                "FILTER IS_SAME_COLLECTION('ontology_properties', doc) "
                "FILTER doc.expired == @never "
                "SORT BM25(doc) DESC "
                "LIMIT @offset, @limit "
                "LET ont = (FOR o IN ontology_registry "
                "FILTER o._key == doc.ontology_id LIMIT 1 RETURN o)[0] "
                "RETURN {"
                "  _key: doc._key, label: doc.label, "
                "  description: doc.description, "
                "  ontology_id: doc.ontology_id, "
                "  ontology_name: ont.name, "
                "  domain_class: doc.domain_class, "
                "  score: BM25(doc), source: 'property'"
                "}",
                bind_vars={"q": q, "offset": offset, "limit": limit, "never": NEVER_EXPIRES},
            )
        )

    return {
        "query": q,
        "results": {
            "registry": registry_results,
            "classes": class_results,
            "properties": property_results,
        },
        "counts": {
            "registry": len(registry_results),
            "classes": len(class_results),
            "properties": len(property_results),
        },
        "offset": offset,
        "limit": limit,
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
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/orgs/{org_id}/ontologies")
async def get_org_ontologies(org_id: str) -> dict:
    """List selected base ontologies for an organization."""
    ontology_ids = ctx_svc.get_domain_ontology_for_org(org_id=org_id)
    return {"org_id": org_id, "selected_ontologies": ontology_ids}


# ---------------------------------------------------------------------------
# Per-ontology graphs
# ---------------------------------------------------------------------------


@router.get("/graphs")
async def list_ontology_graphs() -> dict:
    """List all per-ontology named graphs plus the composite graph."""
    from app.services.ontology_graphs import list_ontology_graphs as _list_graphs
    per_ontology = _list_graphs()
    system_graphs = [
        {
            "graph_name": "domain_ontology",
            "description": "Shared domain ontology (all classes across all ontologies)",
        },
        {"graph_name": "aoe_process", "description": "Extraction pipeline lineage"},
    ]
    return {"system_graphs": system_graphs, "ontology_graphs": per_ontology}


# ---------------------------------------------------------------------------
# Domain / Local / Staging / Import / Export stubs (other subagents own these)
# ---------------------------------------------------------------------------


@router.get("/domain")
async def get_domain_ontology(
    offset: int = Query(0, ge=0, description="Number of classes to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max classes to return"),
) -> dict:
    """Get the full domain ontology graph from the composite graph, paginated.

    Returns all current classes across every registered ontology together
    with their ``subclass_of`` and ``has_property`` edges.
    """
    db = get_db()

    classes: list[dict] = []
    total_classes = 0
    if db.has_collection("ontology_classes"):
        count_result = list(run_aql(db,
            "FOR c IN ontology_classes FILTER c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"never": NEVER_EXPIRES},
        ))
        total_classes = count_result[0] if count_result else 0

        classes = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.expired == @never "
            "SORT c.label ASC "
            "LIMIT @offset, @limit "
            "RETURN c",
            bind_vars={"never": NEVER_EXPIRES, "offset": offset, "limit": limit},
        ))

    class_ids = {c["_id"] for c in classes}

    edges: list[dict] = []
    for edge_col in (
        "subclass_of", "rdfs_domain", "rdfs_range_class",
        "has_property",
    ):
        if not db.has_collection(edge_col):
            continue
        result = list(run_aql(db,
            f"FOR e IN {edge_col} "
            "FILTER e.expired == @never "
            "AND (e._from IN @ids OR e._to IN @ids) "
            "RETURN MERGE(e, {{edge_type: @et}})",
            bind_vars={
                "never": NEVER_EXPIRES,
                "ids": list(class_ids),
                "et": edge_col,
            },
        ))
        edges.extend(result)

    return {
        "classes": classes,
        "edges": edges,
        "offset": offset,
        "limit": limit,
        "total_classes": total_classes,
        "has_more": offset + limit < total_classes,
    }


@router.get("/domain/classes")
async def list_domain_classes(
    offset: int = Query(0, ge=0, description="Number of classes to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max classes to return"),
    label: str | None = Query(None, description="Partial match on class label (case-insensitive)"),
    tier: str | None = Query(None, description="Filter by tier: domain or local"),
    confidence: float | None = Query(
        None, ge=0.0, le=1.0, description="Minimum confidence threshold",
    ),
    ontology_id: str | None = Query(None, description="Filter by ontology ID"),
) -> dict:
    """List domain ontology classes with optional filters.

    Each returned class includes the ``ontology_name`` resolved from the
    ontology registry.
    """
    db = get_db()

    if not db.has_collection("ontology_classes"):
        return {"classes": [], "offset": offset, "limit": limit, "total": 0, "has_more": False}

    filters: list[str] = ["c.expired == @never"]
    bind_vars: dict = {"never": NEVER_EXPIRES, "offset": offset, "limit": limit}

    if label:
        filters.append("CONTAINS(LOWER(c.label), LOWER(@label))")
        bind_vars["label"] = label
    if tier:
        filters.append("c.tier == @tier")
        bind_vars["tier"] = tier
    if confidence is not None:
        filters.append("c.confidence >= @confidence")
        bind_vars["confidence"] = confidence
    if ontology_id:
        filters.append("c.ontology_id == @ontology_id")
        bind_vars["ontology_id"] = ontology_id

    filter_clause = " AND ".join(filters)

    count_result = list(run_aql(db,
        f"FOR c IN ontology_classes FILTER {filter_clause} "
        "COLLECT WITH COUNT INTO cnt RETURN cnt",
        bind_vars={k: v for k, v in bind_vars.items() if k not in ("offset", "limit")},
    ))
    total = count_result[0] if count_result else 0

    classes = list(run_aql(db,
        f"FOR c IN ontology_classes "
        f"FILTER {filter_clause} "
        "SORT c.label ASC "
        "LIMIT @offset, @limit "
        "RETURN c",
        bind_vars=bind_vars,
    ))

    ontology_ids_in_page = {c.get("ontology_id") for c in classes if c.get("ontology_id")}
    ontology_names: dict[str, str] = {}
    if ontology_ids_in_page and db.has_collection("ontology_registry"):
        name_results = list(run_aql(db,
            "FOR o IN ontology_registry "
            "FILTER o._key IN @ids "
            "RETURN {id: o._key, name: o.name}",
            bind_vars={"ids": list(ontology_ids_in_page)},
        ))
        ontology_names = {r["id"]: r["name"] for r in name_results}

    for cls in classes:
        cls["ontology_name"] = ontology_names.get(cls.get("ontology_id", ""), "")

    return {
        "classes": classes,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/local/{org_id}")
async def get_local_ontology(
    org_id: str,
    offset: int = Query(0, ge=0, description="Number of classes to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max classes to return"),
) -> dict:
    """Get an organization's local ontology extension.

    Finds all ontologies registered with the given ``org_id``, then returns
    their current classes and edges — including ``extends_domain`` edges that
    link local classes to domain classes.
    """
    db = get_db()

    org_ontology_ids: list[str] = []
    if db.has_collection("ontology_registry"):
        org_ontology_ids = list(run_aql(db,
            "FOR o IN ontology_registry "
            "FILTER o.org_id == @org_id "
            "RETURN o._key",
            bind_vars={"org_id": org_id},
        ))

    if not org_ontology_ids:
        return {
            "org_id": org_id,
            "classes": [],
            "edges": [],
            "offset": offset,
            "limit": limit,
            "total_classes": 0,
            "has_more": False,
            "message": f"No ontology data found for organization '{org_id}'. "
                       "Upload documents and run extraction to create a local ontology.",
        }

    classes: list[dict] = []
    total_classes = 0
    if db.has_collection("ontology_classes"):
        count_result = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id IN @oids AND c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oids": org_ontology_ids, "never": NEVER_EXPIRES},
        ))
        total_classes = count_result[0] if count_result else 0

        classes = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id IN @oids AND c.expired == @never "
            "SORT c.label ASC "
            "LIMIT @offset, @limit "
            "RETURN c",
            bind_vars={
                "oids": org_ontology_ids,
                "never": NEVER_EXPIRES,
                "offset": offset,
                "limit": limit,
            },
        ))

    class_ids = {c["_id"] for c in classes}

    edges: list[dict] = []
    for edge_col in (
        "subclass_of", "rdfs_domain", "rdfs_range_class",
        "extends_domain", "has_property", "related_to",
    ):
        if not db.has_collection(edge_col):
            continue
        result = list(run_aql(db,
            f"FOR e IN {edge_col} "
            "FILTER e.expired == @never "
            "AND (e._from IN @ids OR e._to IN @ids) "
            "RETURN MERGE(e, {{edge_type: @et}})",
            bind_vars={
                "never": NEVER_EXPIRES,
                "ids": list(class_ids),
                "et": edge_col,
            },
        ))
        edges.extend(result)

    return {
        "org_id": org_id,
        "classes": classes,
        "edges": edges,
        "offset": offset,
        "limit": limit,
        "total_classes": total_classes,
        "has_more": offset + limit < total_classes,
        "ontology_ids": org_ontology_ids,
    }


@router.get("/staging/{run_id}")
async def get_staging(run_id: str) -> dict:
    """Get the staging graph for curation.

    Resolves the ontology_id from the extraction run, then returns all
    current classes, properties, and edges for that ontology.
    """
    db = get_db()

    ontology_id: str | None = None
    if db.has_collection("extraction_runs") and db.collection("extraction_runs").has(run_id):
        run_doc = doc_get(db.collection("extraction_runs"), run_id)
        ontology_id = (run_doc or {}).get("ontology_id")

    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(run_aql(db,
            "FOR o IN ontology_registry "
            "FILTER o.extraction_run_id == @rid "
            "LIMIT 1 RETURN o._key",
            bind_vars={"rid": run_id},
        ))
        if matches:
            ontology_id = matches[0]

    if not ontology_id:
        return {"run_id": run_id, "classes": [], "properties": [], "edges": []}

    classes: list[dict] = []
    if db.has_collection("ontology_classes"):
        classes = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "SORT c.label ASC RETURN c",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))

    properties: list[dict] = []
    for prop_col in (
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_properties",
    ):
        if db.has_collection(prop_col):
            properties.extend(run_aql(db,
                f"FOR p IN {prop_col} "
                "FILTER p.ontology_id == @oid AND p.expired == @never "
                "SORT p.label ASC RETURN p",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            ))

    edges: list[dict] = []
    for edge_col in (
        "subclass_of",
        "rdfs_domain",
        "rdfs_range_class",
        "equivalent_class",
        "extracted_from",
        "has_property",
        "related_to",
    ):
        if db.has_collection(edge_col):
            result = list(run_aql(db,
                f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                "AND e.expired == @never "
                "RETURN MERGE(e, {edge_type: @et})",
                bind_vars={
                    "oid": ontology_id, "et": edge_col,
                    "never": NEVER_EXPIRES,
                },
            ))
            edges.extend(result)

    return {
        "run_id": run_id,
        "ontology_id": ontology_id,
        "classes": classes,
        "properties": properties,
        "edges": edges,
    }


@router.post("/staging/{run_id}/promote")
async def promote_staging(
    run_id: str,
    ontology_id: str | None = Query(
        None, description="Target ontology ID for promoted entities",
    ),
) -> dict:
    """Promote approved staging entities to the production graph.

    Delegates to the promotion service (same logic as ``POST /curation/promote/{run_id}``).
    """
    try:
        report = promotion_svc.promote_staging(
            run_id=run_id,
            ontology_id=ontology_id,
        )
        return report
    except Exception as exc:
        log.exception("Staging promotion failed for run %s", run_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Ontology classes and edges (used by library ClassHierarchy component)
# Must come AFTER all static routes to avoid catching /domain/classes etc.
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/classes")
async def list_ontology_classes(ontology_id: str) -> dict:
    """List all classes belonging to an ontology."""
    db = get_db()
    if not db.has_collection("ontology_classes"):
        return {"data": []}
    classes = list(run_aql(db,
        "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
        "AND c.expired == @never "
        "SORT c.label ASC RETURN c",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return {"data": classes}


@router.get("/{ontology_id}/classes/{class_key}")
async def get_class_detail(ontology_id: str, class_key: str) -> dict:
    """Get class detail with properties resolved via rdfs_domain traversal (ADR-006).

    Returns the class document plus ``attributes`` (datatype properties) and
    ``relationships`` (object properties with resolved range class).  Falls
    back to legacy ``has_property`` edges when no PGT-aligned data exists.
    """
    db = get_db()

    cls = ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise NotFoundError(
            f"Class '{class_key}' not found in ontology '{ontology_id}'"
        )

    class_id = cls["_id"]

    attributes: list[dict] = []
    relationships: list[dict] = []

    if db.has_collection("rdfs_domain") and db.has_collection("ontology_datatype_properties"):
        attributes = list(run_aql(db,
            "FOR e IN rdfs_domain "
            "FILTER e._to == @cid AND e.expired == @never "
            "FOR p IN ontology_datatype_properties "
            "FILTER p._id == e._from AND p.expired == @never "
            "RETURN p",
            bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
        ))

    if db.has_collection("rdfs_domain") and db.has_collection("ontology_object_properties"):
        range_sub = "RETURN p"
        if db.has_collection("rdfs_range_class"):
            range_sub = (
                "LET target = FIRST("
                "  FOR re IN rdfs_range_class "
                "  FILTER re._from == p._id AND re.expired == @never "
                "  LET t = DOCUMENT(re._to) "
                "  RETURN {_key: t._key, label: t.label, _id: t._id}"
                ") "
                "RETURN MERGE(p, {target_class: target})"
            )
        relationships = list(run_aql(db,
            "FOR e IN rdfs_domain "
            "FILTER e._to == @cid AND e.expired == @never "
            "FOR p IN ontology_object_properties "
            f"FILTER p._id == e._from AND p.expired == @never "
            f"{range_sub}",
            bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
        ))

    legacy_properties: list[dict] = []
    if not attributes and not relationships:
        if db.has_collection("has_property") and db.has_collection("ontology_properties"):
            legacy_properties = list(run_aql(db,
                "FOR e IN has_property "
                "FILTER e._from == @cid AND e.expired == @never "
                "LET prop = DOCUMENT(e._to) "
                "FILTER prop != null AND prop.expired == @never "
                "RETURN prop",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            ))

    return {
        **cls,
        "attributes": attributes,
        "relationships": relationships,
        "legacy_properties": legacy_properties,
    }


@router.get("/{ontology_id}/properties")
async def list_ontology_properties(
    ontology_id: str,
    keys: str | None = None,
) -> dict:
    """List properties for an ontology, optionally filtered by comma-separated keys."""
    db = get_db()
    props: list[dict] = []
    key_list = [k.strip() for k in keys.split(",") if k.strip()] if keys else None

    for prop_col in (
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_properties",
    ):
        if not db.has_collection(prop_col):
            continue
        if key_list:
            props.extend(run_aql(db,
                f"FOR p IN {prop_col} "
                "FILTER p.ontology_id == @oid AND p._key IN @keys "
                "AND p.expired == @never "
                "SORT p.label ASC RETURN p",
                bind_vars={
                    "oid": ontology_id, "keys": key_list,
                    "never": NEVER_EXPIRES,
                },
            ))
        else:
            props.extend(run_aql(db,
                f"FOR p IN {prop_col} "
                "FILTER p.ontology_id == @oid "
                "AND p.expired == @never "
                "SORT p.label ASC RETURN p",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            ))
    return {"data": props}


@router.get("/{ontology_id}/edges")
async def list_ontology_edges(ontology_id: str) -> dict:
    """List all edges for an ontology (PGT-aligned + legacy fallback)."""
    db = get_db()
    edges: list[dict] = []
    for edge_col in (
        "subclass_of",
        "rdfs_domain",
        "rdfs_range_class",
        "equivalent_class",
        "has_property",
        "related_to",
    ):
        if db.has_collection(edge_col):
            query = (
                f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                "AND e.expired == @never "
                "RETURN MERGE(e, {edge_type: @et})"
            )
            result = list(run_aql(db,
                query,
                bind_vars={
                    "oid": ontology_id, "et": edge_col,
                    "never": NEVER_EXPIRES,
                },
            ))
            edges.extend(result)
    return {"data": edges}


# ---------------------------------------------------------------------------
# CRUD endpoints for ontology classes, properties, and edges (K.3-K.6b)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert text to an ArangoDB-safe key slug."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")


def _key_from_uri(uri: str) -> str:
    """Extract a document key from the URI fragment (after ``#`` or last ``/``)."""
    fragment = uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]
    return _slugify(fragment)


def _ensure_collection(db, name: str, *, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge)


@router.post("/{ontology_id}/classes", status_code=201)
async def create_class(ontology_id: str, body: CreateClassRequest) -> dict:
    """Create a new ontology class (K.3)."""
    db = get_db()
    _ensure_collection(db, "ontology_classes")

    slug = _slugify(body.label)
    uri = body.uri or f"http://example.org/ontology/{ontology_id}#{slug}"
    key = _key_from_uri(uri)

    existing = list(
        run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.uri == @uri AND c.expired == @never "
            "LIMIT 1 RETURN c._key",
            bind_vars={"oid": ontology_id, "uri": uri, "never": NEVER_EXPIRES},
        )
    )
    if existing:
        raise ConflictError(f"Class with URI '{uri}' already exists")

    data: dict = {
        "_key": key,
        "uri": uri,
        "label": body.label,
        "description": body.description or "",
        "rdf_type": body.rdf_type,
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
    }

    try:
        cls_doc = ontology_repo.create_class(
            db, ontology_id=ontology_id, data=data, created_by="manual"
        )
    except Exception as exc:
        if "unique constraint" in str(exc).lower() or "1210" in str(exc):
            data["_key"] = f"{key}_{int(time.time()) % 100000}"
            cls_doc = ontology_repo.create_class(
                db, ontology_id=ontology_id, data=data, created_by="manual"
            )
        else:
            log.exception("Failed to create class")
            raise

    if body.parent_class_key:
        parent = ontology_repo.get_class(db, key=body.parent_class_key)
        if parent is None:
            raise NotFoundError(f"Parent class '{body.parent_class_key}' not found")
        if parent.get("ontology_id") != ontology_id:
            raise ValidationError("Parent class belongs to a different ontology")
        _ensure_collection(db, "subclass_of", edge=True)
        ontology_repo.create_edge(
            db,
            edge_collection="subclass_of",
            from_id=cls_doc["_id"],
            to_id=parent["_id"],
            data={
                "ontology_id": ontology_id,
                "label": f"{body.label} subClassOf {parent.get('label', '')}",
            },
        )

    return cls_doc


@router.post("/{ontology_id}/properties", status_code=201)
async def create_property(ontology_id: str, body: CreatePropertyRequest) -> dict:
    """Create a new ontology property with PGT-aligned edges (K.4 / ADR-006)."""
    db = get_db()
    _ensure_collection(db, "ontology_classes")

    is_object = body.property_type == "object"
    target_col = "ontology_object_properties" if is_object else "ontology_datatype_properties"
    _ensure_collection(db, target_col)
    _ensure_collection(db, "rdfs_domain", edge=True)
    if is_object:
        _ensure_collection(db, "rdfs_range_class", edge=True)

    domain_cls = ontology_repo.get_class(db, key=body.domain_class_key)
    if domain_cls is None:
        raise NotFoundError(f"Domain class '{body.domain_class_key}' not found")
    if domain_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Domain class belongs to a different ontology")

    slug = _slugify(body.label)
    prop_key = f"{body.domain_class_key}_{slug}"
    uri = body.uri or f"http://example.org/ontology/{ontology_id}#{prop_key}"

    data: dict = {
        "_key": prop_key,
        "uri": uri,
        "label": body.label,
        "description": body.description or "",
        "range": body.range,
        "property_type": body.property_type,
        "rdf_type": "owl:ObjectProperty" if is_object else "owl:DatatypeProperty",
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
    }
    if not is_object:
        data["range_datatype"] = body.range

    try:
        prop_doc = ontology_repo.create_property(
            db, ontology_id=ontology_id, data=data, created_by="manual",
            collection=target_col,
        )
    except Exception as exc:
        if "unique constraint" in str(exc).lower() or "1210" in str(exc):
            data["_key"] = f"{prop_key}_{int(time.time()) % 100000}"
            prop_doc = ontology_repo.create_property(
                db, ontology_id=ontology_id, data=data, created_by="manual",
                collection=target_col,
            )
        else:
            log.exception("Failed to create property")
            raise

    ontology_repo.create_edge(
        db,
        edge_collection="rdfs_domain",
        from_id=prop_doc["_id"],
        to_id=domain_cls["_id"],
        data={"ontology_id": ontology_id},
    )

    if is_object and body.range:
        range_cls = ontology_repo.get_class(db, key=body.range)
        if range_cls:
            ontology_repo.create_edge(
                db,
                edge_collection="rdfs_range_class",
                from_id=prop_doc["_id"],
                to_id=range_cls["_id"],
                data={"ontology_id": ontology_id},
            )

    return prop_doc


@router.post("/{ontology_id}/edges", status_code=201)
async def create_or_update_edge(ontology_id: str, body: CreateEdgeRequest) -> dict:
    """Create an edge between two classes, or update if one already exists (K.5)."""
    db = get_db()
    _ensure_collection(db, "ontology_classes")

    from_cls = ontology_repo.get_class(db, key=body.from_key)
    if from_cls is None:
        raise NotFoundError(f"Source class '{body.from_key}' not found")
    if from_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Source class belongs to a different ontology")

    to_cls = ontology_repo.get_class(db, key=body.to_key)
    if to_cls is None:
        raise NotFoundError(f"Target class '{body.to_key}' not found")
    if to_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Target class belongs to a different ontology")

    _ensure_collection(db, body.edge_type, edge=True)

    existing_edges = list(
        run_aql(db,
            "FOR e IN @@col "
            "FILTER e._from == @from_id AND e._to == @to_id "
            "AND e.expired == @never RETURN e",
            bind_vars={
                "@col": body.edge_type,
                "from_id": from_cls["_id"],
                "to_id": to_cls["_id"],
                "never": NEVER_EXPIRES,
            },
        )
    )
    for old_edge in existing_edges:
        temporal_svc.expire_entity(
            db, collection=body.edge_type, key=old_edge["_key"]
        )

    edge_data: dict = {"ontology_id": ontology_id}
    if body.label:
        edge_data["label"] = body.label

    edge_doc = ontology_repo.create_edge(
        db,
        edge_collection=body.edge_type,
        from_id=from_cls["_id"],
        to_id=to_cls["_id"],
        data=edge_data,
    )

    return edge_doc


@router.put("/{ontology_id}/edges/{edge_key}")
async def update_edge_endpoint(
    ontology_id: str,
    edge_key: str,
    body: UpdateEdgeRequest,
) -> dict:
    """Update curation status (or other fields) on a versioned ontology edge."""
    db = get_db()
    resolved = ontology_repo.resolve_ontology_edge(db, edge_key=edge_key)
    if resolved is None:
        raise NotFoundError(f"Edge '{edge_key}' not found")
    _col, doc = resolved
    if doc.get("ontology_id") != ontology_id:
        raise ValidationError("Edge belongs to a different ontology")

    try:
        return ontology_repo.update_edge(
            db,
            edge_key=edge_key,
            data={"status": body.status},
            created_by="workspace",
            change_summary=f"Edge {edge_key} status → {body.status}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


@router.put("/{ontology_id}/classes/{class_key}")
async def update_class_endpoint(
    ontology_id: str, class_key: str, body: UpdateClassRequest
) -> dict:
    """Update an ontology class — expire old version, create new (K.6)."""
    db = get_db()

    cls = ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise ValidationError("Class belongs to a different ontology")

    update_data = {
        k: v
        for k, v in {
            "label": body.label,
            "description": body.description,
            "uri": body.uri,
            "status": body.status,
        }.items()
        if v is not None
    }
    if not update_data:
        raise ValidationError("No fields to update")

    try:
        updated = ontology_repo.update_class(
            db,
            key=class_key,
            data=update_data,
            created_by="manual",
            change_summary=f"Updated class {class_key}: {', '.join(update_data.keys())}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


@router.put("/{ontology_id}/properties/{prop_key}")
async def update_property_endpoint(
    ontology_id: str, prop_key: str, body: UpdatePropertyRequest
) -> dict:
    """Update an ontology property — expire old version, create new (K.6)."""
    db = get_db()

    prop = ontology_repo.get_property(db, key=prop_key)
    if prop is None:
        raise NotFoundError(f"Property '{prop_key}' not found")
    if prop.get("ontology_id") != ontology_id:
        raise ValidationError("Property belongs to a different ontology")

    update_data = {
        k: v
        for k, v in {
            "label": body.label,
            "description": body.description,
            "uri": body.uri,
            "range": body.range,
        }.items()
        if v is not None
    }
    if not update_data:
        raise ValidationError("No fields to update")

    try:
        updated = ontology_repo.update_property(
            db,
            key=prop_key,
            data=update_data,
            created_by="manual",
            change_summary=f"Updated property {prop_key}: {', '.join(update_data.keys())}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


@router.delete("/{ontology_id}/classes/{class_key}")
async def delete_class_endpoint(ontology_id: str, class_key: str) -> dict:
    """Soft-delete a class and all connected edges (K.6b)."""
    db = get_db()

    cls = ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise ValidationError("Class belongs to a different ontology")

    try:
        expired_cls = ontology_repo.expire_class_cascade(db, key=class_key)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return {"deleted": True, "class_key": class_key, "expired_class": expired_cls}


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


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
        raise HTTPException(status_code=500, detail="Internal server error") from exc


_IMPORT_FILE = File(..., description="OWL/TTL/RDF-XML/JSON-LD file")


# In-process registry of ontology import jobs.
# Keyed by ontology_id. Each value: {ontology_id, status, filename, started_at,
# finished_at?, result?, error?, error_kind?}.
# NOTE: This is per-worker state. With --reload / multi-worker uvicorn, jobs
# won't be visible across workers. The status endpoint falls back to reading
# the registry entry so completed imports remain discoverable.
_import_jobs: dict[str, dict[str, Any]] = {}


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
            import_from_file,
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
) -> dict:
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
    if registry_repo.get_registry_entry(ontology_id) is not None:
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
    asyncio.create_task(
        _run_import_job(
            ontology_id=ontology_id,
            content=content,
            filename=file.filename,
            ontology_label=ontology_label,
            ontology_uri_prefix=ontology_uri_prefix,
        )
    )
    return {
        "ontology_id": ontology_id,
        "status": "running",
        "filename": file.filename,
        "job_status_url": f"/api/v1/ontology/import/{ontology_id}/status",
    }


@router.get("/import/{ontology_id}/status")
async def import_status_endpoint(ontology_id: str) -> dict:
    """Return the state of an ongoing or recently finished import job.

    If the job isn't in memory (e.g. process restarted) but the ontology exists
    in the registry, reports ``completed`` so the client can recover.
    """
    job = _import_jobs.get(ontology_id)
    if job is not None:
        return job

    entry = registry_repo.get_registry_entry(ontology_id)
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
async def create_ontology(body: CreateOntologyRequest) -> dict:
    """Create an empty ontology, optionally importing other ontologies into it."""
    import uuid

    db = get_db()
    ont_id = body.ontology_id or f"ont_{uuid.uuid4().hex[:12]}"

    existing = registry_repo.get_registry_entry(ont_id, db=db)
    if existing is not None:
        raise ConflictError(f"Ontology '{ont_id}' already exists")

    uri = body.uri_prefix or f"http://example.org/ontology/{ont_id}#"
    entry = registry_repo.create_registry_entry(
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
        target = registry_repo.get_registry_entry(target_key, db=db)
        if target is None:
            warnings.append(f"Import target '{target_key}' not found — skipped")
            continue
        if target_key == ont_id:
            warnings.append("Cannot import self — skipped")
            continue
        if not db.has_collection("imports"):
            warnings.append("'imports' edge collection missing — skipped")
            break
        ontology_repo.create_edge(
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


# ---------------------------------------------------------------------------
# Ontology imports management (PRD 6.15 FR-15.7–15.12)
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/imports")
async def list_ontology_imports(ontology_id: str) -> dict:
    """List all ontologies imported by this ontology."""
    db = get_db()
    entry = registry_repo.get_registry_entry(ontology_id, db=db)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    if not db.has_collection("imports"):
        return {"imports": []}

    query = """
        FOR e IN imports
          FILTER e._from == @from_id
          FILTER e.expired == @never
          LET target = DOCUMENT(e._to)
          RETURN {
            edge_key: e._key,
            target_id: PARSE_IDENTIFIER(e._to).key,
            target_name: target.name || target.label || PARSE_IDENTIFIER(e._to).key,
            target_uri: target.uri,
            import_iri: e.import_iri,
            created: e.created
          }
    """
    results = list(
        run_aql(
            db,
            query,
            bind_vars={
                "from_id": f"ontology_registry/{ontology_id}",
                "never": NEVER_EXPIRES,
            },
        )
    )
    return {"imports": results}


@router.get("/{ontology_id}/imported-by")
async def list_ontology_dependents(ontology_id: str) -> dict:
    """List all ontologies that import this ontology."""
    db = get_db()
    entry = registry_repo.get_registry_entry(ontology_id, db=db)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    if not db.has_collection("imports"):
        return {"imported_by": []}

    query = """
        FOR e IN imports
          FILTER e._to == @to_id
          FILTER e.expired == @never
          LET source = DOCUMENT(e._from)
          RETURN {
            edge_key: e._key,
            source_id: PARSE_IDENTIFIER(e._from).key,
            source_name: source.name || source.label || PARSE_IDENTIFIER(e._from).key,
            created: e.created
          }
    """
    results = list(
        run_aql(
            db,
            query,
            bind_vars={
                "to_id": f"ontology_registry/{ontology_id}",
                "never": NEVER_EXPIRES,
            },
        )
    )
    return {"imported_by": results}


class AddImportRequest(BaseModel):
    target_ontology_id: str = Field(..., description="Registry key of the ontology to import")


@router.post("/{ontology_id}/imports", status_code=201)
async def add_ontology_import(ontology_id: str, body: AddImportRequest) -> dict:
    """Add an import edge from one ontology to another."""
    db = get_db()
    entry = registry_repo.get_registry_entry(ontology_id, db=db)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    target = registry_repo.get_registry_entry(body.target_ontology_id, db=db)
    if target is None:
        raise NotFoundError(f"Target ontology '{body.target_ontology_id}' not found")

    if body.target_ontology_id == ontology_id:
        raise ValidationError("Cannot import self")

    if not db.has_collection("imports"):
        raise HTTPException(status_code=500, detail="'imports' edge collection not available")

    from_id = f"ontology_registry/{ontology_id}"
    to_id = f"ontology_registry/{body.target_ontology_id}"

    existing = list(
        run_aql(
            db,
            "FOR e IN imports FILTER e._from == @f AND e._to == @t AND e.expired == @never RETURN e._key",
            bind_vars={"f": from_id, "t": to_id, "never": NEVER_EXPIRES},
        )
    )
    if existing:
        raise ConflictError(
            f"'{ontology_id}' already imports '{body.target_ontology_id}'"
        )

    # Circular dependency check: would target importing us create a cycle?
    cycle_check = list(
        run_aql(
            db,
            """
            FOR v IN 1..10 OUTBOUND @target_id imports
              FILTER v._key == @source_key
              LIMIT 1
              RETURN true
            """,
            bind_vars={
                "target_id": to_id,
                "source_key": ontology_id,
            },
        )
    )
    if cycle_check:
        raise ValidationError(
            f"Adding this import would create a circular dependency"
        )

    edge = ontology_repo.create_edge(
        db=db,
        edge_collection="imports",
        from_id=from_id,
        to_id=to_id,
        data={"import_iri": target.get("uri", "")},
    )

    return {
        "edge_key": edge["_key"],
        "from": ontology_id,
        "to": body.target_ontology_id,
        "target_name": target.get("name", body.target_ontology_id),
    }


@router.delete("/{ontology_id}/imports/{target_ontology_id}")
async def remove_ontology_import(ontology_id: str, target_ontology_id: str) -> dict:
    """Remove an import edge (soft-delete via temporal expiry)."""
    db = get_db()

    if not db.has_collection("imports"):
        raise NotFoundError("imports edge collection not available")

    from_id = f"ontology_registry/{ontology_id}"
    to_id = f"ontology_registry/{target_ontology_id}"

    edges = list(
        run_aql(
            db,
            "FOR e IN imports FILTER e._from == @f AND e._to == @t AND e.expired == @never RETURN e",
            bind_vars={"f": from_id, "t": to_id, "never": NEVER_EXPIRES},
        )
    )
    if not edges:
        raise NotFoundError(
            f"No active import from '{ontology_id}' to '{target_ontology_id}'"
        )

    now = time.time()
    for edge in edges:
        db.collection("imports").update(
            {"_key": edge["_key"], "expired": now, "ttlExpireAt": now + 90 * 86400}
        )

    return {"removed": len(edges), "from": ontology_id, "to": target_ontology_id}


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
        raise HTTPException(status_code=500, detail="Internal server error") from exc


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


@router.get("/class/{class_key}/provenance")
async def get_class_provenance(class_key: str) -> dict:
    """Chunks from documents linked to this class via ``extracted_from`` (class → document).

    Provenance is **document-level**: we do not store which substring of a chunk defined the class.
    The query returns all chunks for those documents (same as the workspace list view).
    """
    db = get_db()
    chunks: list[dict] = []
    if db.has_collection("extracted_from") and db.has_collection("chunks"):
        rows = list(run_aql(db,
            "FOR e IN extracted_from "
            "  FILTER e._from == CONCAT('ontology_classes/', @key) "
            "  LET doc_id = PARSE_IDENTIFIER(e._to).key "
            "  FOR c IN chunks "
            "    FILTER c.doc_id == doc_id "
            "    SORT c.chunk_index ASC "
            "    RETURN { _key: c._key, text: c.text, chunk_index: c.chunk_index, "
            "             doc_id: c.doc_id, section_heading: c.section_heading }",
            bind_vars={"key": class_key},
        ))
        chunks = rows
    return {"data": chunks, "total_count": len(chunks)}


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
