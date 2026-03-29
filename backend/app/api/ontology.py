import json
import logging
import re
import sys
import time

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.db import ontology_repo, registry_repo
from app.db.client import get_db
from app.models.curation import (
    TemporalDiff,
    TemporalSnapshot,
)
from app.models.ontology import (
    CreateClassRequest,
    CreateEdgeRequest,
    CreatePropertyRequest,
    UpdateClassRequest,
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

        for entry in entries:
            oid = entry.get("_key", "")
            entry.setdefault("edge_count", 0)
            entry.setdefault("updated_at", entry.get("created_at"))
            entry.setdefault("last_updated", entry.get("updated_at") or entry.get("created_at"))
            try:
                edge_count = 0
                for edge_col in ("subclass_of", "has_property", "related_to"):
                    if db.has_collection(edge_col):
                        result = list(db.aql.execute(
                            f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                            "AND e.expired == @never "
                            "COLLECT WITH COUNT INTO cnt RETURN cnt",
                            bind_vars={"oid": oid, "never": NEVER_EXPIRES},
                        ))
                        edge_count += result[0] if result else 0
                entry["edge_count"] = edge_count
            except Exception:
                pass

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
# Per-ontology graphs
# ---------------------------------------------------------------------------


@router.get("/graphs")
async def list_ontology_graphs() -> dict:
    """List all per-ontology named graphs plus the composite graph."""
    from app.services.ontology_graphs import list_ontology_graphs as _list_graphs
    per_ontology = _list_graphs()
    system_graphs = [
        {"graph_name": "domain_ontology", "description": "Shared domain ontology (all classes across all ontologies)"},
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
        count_result = list(db.aql.execute(
            "FOR c IN ontology_classes FILTER c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"never": NEVER_EXPIRES},
        ))
        total_classes = count_result[0] if count_result else 0

        classes = list(db.aql.execute(
            "FOR c IN ontology_classes "
            "FILTER c.expired == @never "
            "SORT c.label ASC "
            "LIMIT @offset, @limit "
            "RETURN c",
            bind_vars={"never": NEVER_EXPIRES, "offset": offset, "limit": limit},
        ))

    class_ids = {c["_id"] for c in classes}

    edges: list[dict] = []
    for edge_col in ("subclass_of", "has_property"):
        if not db.has_collection(edge_col):
            continue
        result = list(db.aql.execute(
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
    confidence: float | None = Query(None, ge=0.0, le=1.0, description="Minimum confidence threshold"),
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

    count_result = list(db.aql.execute(
        f"FOR c IN ontology_classes FILTER {filter_clause} "
        "COLLECT WITH COUNT INTO cnt RETURN cnt",
        bind_vars={k: v for k, v in bind_vars.items() if k not in ("offset", "limit")},
    ))
    total = count_result[0] if count_result else 0

    classes = list(db.aql.execute(
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
        name_results = list(db.aql.execute(
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
        org_ontology_ids = list(db.aql.execute(
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
        count_result = list(db.aql.execute(
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id IN @oids AND c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oids": org_ontology_ids, "never": NEVER_EXPIRES},
        ))
        total_classes = count_result[0] if count_result else 0

        classes = list(db.aql.execute(
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
    for edge_col in ("subclass_of", "has_property", "related_to", "extends_domain"):
        if not db.has_collection(edge_col):
            continue
        result = list(db.aql.execute(
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
        run_doc = db.collection("extraction_runs").get(run_id)
        ontology_id = (run_doc or {}).get("ontology_id")

    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(db.aql.execute(
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
        classes = list(db.aql.execute(
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "SORT c.label ASC RETURN c",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))

    properties: list[dict] = []
    if db.has_collection("ontology_properties"):
        properties = list(db.aql.execute(
            "FOR p IN ontology_properties "
            "FILTER p.ontology_id == @oid AND p.expired == @never "
            "SORT p.label ASC RETURN p",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))

    edges: list[dict] = []
    for edge_col in ("subclass_of", "has_property", "related_to", "equivalent_class", "extracted_from"):
        if db.has_collection(edge_col):
            result = list(db.aql.execute(
                f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                "AND e.expired == @never "
                "RETURN MERGE(e, {type: @et})",
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
async def promote_staging(run_id: str, ontology_id: str | None = Query(None, description="Target ontology ID for promoted entities")) -> dict:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
    classes = list(db.aql.execute(
        "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
        "AND c.expired == @never "
        "SORT c.label ASC RETURN c",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return {"data": classes}


@router.get("/{ontology_id}/properties")
async def list_ontology_properties(
    ontology_id: str,
    keys: str | None = None,
) -> dict:
    """List properties for an ontology, optionally filtered by comma-separated keys."""
    db = get_db()
    if not db.has_collection("ontology_properties"):
        return {"data": []}
    if keys:
        key_list = [k.strip() for k in keys.split(",") if k.strip()]
        props = list(db.aql.execute(
            "FOR p IN ontology_properties "
            "FILTER p.ontology_id == @oid AND p._key IN @keys "
            "AND p.expired == @never "
            "SORT p.label ASC RETURN p",
            bind_vars={
                "oid": ontology_id, "keys": key_list,
                "never": NEVER_EXPIRES,
            },
        ))
    else:
        props = list(db.aql.execute(
            "FOR p IN ontology_properties "
            "FILTER p.ontology_id == @oid "
            "AND p.expired == @never "
            "SORT p.label ASC RETURN p",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
    return {"data": props}


@router.get("/{ontology_id}/edges")
async def list_ontology_edges(ontology_id: str) -> dict:
    """List all edges (subclass_of, has_property, related_to) for an ontology."""
    db = get_db()
    edges: list[dict] = []
    for edge_col in ("subclass_of", "has_property", "related_to", "equivalent_class"):
        if db.has_collection(edge_col):
            query = (
                f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                "AND e.expired == @never "
                "RETURN MERGE(e, {edge_type: @et})"
            )
            result = list(db.aql.execute(
                query,
                bind_vars={
                    "oid": ontology_id, "et": edge_col,
                    "never": NEVER_EXPIRES,
                },
            ))
            edges.extend(result)
    return {"data": edges}


# ---------------------------------------------------------------------------
# CRUD endpoints for ontology classes, properties, and edges (K.3–K.6b)
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
        db.aql.execute(
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
    """Create a new ontology property with a ``has_property`` edge (K.4)."""
    db = get_db()
    _ensure_collection(db, "ontology_classes")
    _ensure_collection(db, "ontology_properties")
    _ensure_collection(db, "has_property", edge=True)

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
        "domain_class": body.domain_class_key,
        "range": body.range,
        "property_type": body.property_type,
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
    }

    try:
        prop_doc = ontology_repo.create_property(
            db, ontology_id=ontology_id, data=data, created_by="manual"
        )
    except Exception as exc:
        if "unique constraint" in str(exc).lower() or "1210" in str(exc):
            data["_key"] = f"{prop_key}_{int(time.time()) % 100000}"
            prop_doc = ontology_repo.create_property(
                db, ontology_id=ontology_id, data=data, created_by="manual"
            )
        else:
            log.exception("Failed to create property")
            raise

    ontology_repo.create_edge(
        db,
        edge_collection="has_property",
        from_id=domain_cls["_id"],
        to_id=prop_doc["_id"],
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
        db.aql.execute(
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
