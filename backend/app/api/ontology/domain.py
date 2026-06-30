import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.ontology import _shared
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get
from app.services import promotion as promotion_svc

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Domain / Local / Staging / Import / Export stubs (other subagents own these)
# ---------------------------------------------------------------------------


@router.get("/domain")
async def get_domain_ontology(
    offset: int = Query(0, ge=0, description="Number of classes to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max classes to return"),
) -> dict[str, Any]:
    """Get the full domain ontology graph from the composite graph, paginated.

    Returns all current classes across every registered ontology together
    with their ``subclass_of`` and ``has_property`` edges.
    """
    db = _shared.get_db()

    classes: list[dict[str, Any]] = []
    total_classes = 0
    if db.has_collection("ontology_classes"):
        count_result = list(
            _shared.run_aql(
                db,
                "FOR c IN ontology_classes FILTER c.expired == @never "
                "COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={"never": NEVER_EXPIRES},
            )
        )
        total_classes = count_result[0] if count_result else 0

        classes = list(
            _shared.run_aql(
                db,
                "FOR c IN ontology_classes "
                "FILTER c.expired == @never "
                "SORT c.label ASC "
                "LIMIT @offset, @limit "
                "RETURN c",
                bind_vars={"never": NEVER_EXPIRES, "offset": offset, "limit": limit},
            )
        )

    class_ids = {c["_id"] for c in classes}

    edges: list[dict[str, Any]] = []
    for edge_col in (
        "subclass_of",
        "rdfs_domain",
        "rdfs_range_class",
        "has_property",
    ):
        if not db.has_collection(edge_col):
            continue
        result = list(
            _shared.run_aql(
                db,
                f"FOR e IN {edge_col} "
                "FILTER e.expired == @never "
                "AND (e._from IN @ids OR e._to IN @ids) "
                "RETURN MERGE(e, {{edge_type: @et}})",
                bind_vars={
                    "never": NEVER_EXPIRES,
                    "ids": list(class_ids),
                    "et": edge_col,
                },
            )
        )
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
        None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    ),
    ontology_id: str | None = Query(None, description="Filter by ontology ID"),
) -> dict[str, Any]:
    """List domain ontology classes with optional filters.

    Each returned class includes the ``ontology_name`` resolved from the
    ontology registry.
    """
    db = _shared.get_db()

    if not db.has_collection("ontology_classes"):
        return {"classes": [], "offset": offset, "limit": limit, "total": 0, "has_more": False}

    filters: list[str] = ["c.expired == @never"]
    bind_vars: dict[str, Any] = {"never": NEVER_EXPIRES, "offset": offset, "limit": limit}

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

    count_result = list(
        _shared.run_aql(
            db,
            f"FOR c IN ontology_classes FILTER {filter_clause} "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={k: v for k, v in bind_vars.items() if k not in ("offset", "limit")},
        )
    )
    total = count_result[0] if count_result else 0

    classes = list(
        _shared.run_aql(
            db,
            f"FOR c IN ontology_classes "
            f"FILTER {filter_clause} "
            "SORT c.label ASC "
            "LIMIT @offset, @limit "
            "RETURN c",
            bind_vars=bind_vars,
        )
    )

    ontology_ids_in_page = {c.get("ontology_id") for c in classes if c.get("ontology_id")}
    ontology_names: dict[str, str] = {}
    if ontology_ids_in_page and db.has_collection("ontology_registry"):
        name_results = list(
            _shared.run_aql(
                db,
                "FOR o IN ontology_registry "
                "FILTER o._key IN @ids "
                "RETURN {id: o._key, name: o.name}",
                bind_vars={"ids": list(ontology_ids_in_page)},
            )
        )
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
) -> dict[str, Any]:
    """Get an organization's local ontology extension.

    Finds all ontologies registered with the given ``org_id``, then returns
    their current classes and edges — including ``extends_domain`` edges that
    link local classes to domain classes.
    """
    db = _shared.get_db()

    org_ontology_ids: list[str] = []
    if db.has_collection("ontology_registry"):
        org_ontology_ids = list(
            _shared.run_aql(
                db,
                "FOR o IN ontology_registry FILTER o.org_id == @org_id RETURN o._key",
                bind_vars={"org_id": org_id},
            )
        )

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

    classes: list[dict[str, Any]] = []
    total_classes = 0
    if db.has_collection("ontology_classes"):
        count_result = list(
            _shared.run_aql(
                db,
                "FOR c IN ontology_classes "
                "FILTER c.ontology_id IN @oids AND c.expired == @never "
                "COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={"oids": org_ontology_ids, "never": NEVER_EXPIRES},
            )
        )
        total_classes = count_result[0] if count_result else 0

        classes = list(
            _shared.run_aql(
                db,
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
            )
        )

    class_ids = {c["_id"] for c in classes}

    edges: list[dict[str, Any]] = []
    for edge_col in (
        "subclass_of",
        "rdfs_domain",
        "rdfs_range_class",
        "extends_domain",
        "has_property",
        "related_to",
    ):
        if not db.has_collection(edge_col):
            continue
        result = list(
            _shared.run_aql(
                db,
                f"FOR e IN {edge_col} "
                "FILTER e.expired == @never "
                "AND (e._from IN @ids OR e._to IN @ids) "
                "RETURN MERGE(e, {{edge_type: @et}})",
                bind_vars={
                    "never": NEVER_EXPIRES,
                    "ids": list(class_ids),
                    "et": edge_col,
                },
            )
        )
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
async def get_staging(run_id: str) -> dict[str, Any]:
    """Get the staging graph for curation.

    Resolves the ontology_id from the extraction run, then returns all
    current classes, properties, and edges for that ontology.
    """
    db = _shared.get_db()

    ontology_id: str | None = None
    if db.has_collection("extraction_runs") and db.collection("extraction_runs").has(run_id):
        run_doc = doc_get(db.collection("extraction_runs"), run_id)
        ontology_id = (run_doc or {}).get("ontology_id")

    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(
            _shared.run_aql(
                db,
                "FOR o IN ontology_registry "
                "FILTER o.extraction_run_id == @rid "
                "LIMIT 1 RETURN o._key",
                bind_vars={"rid": run_id},
            )
        )
        if matches:
            ontology_id = matches[0]

    if not ontology_id:
        return {"run_id": run_id, "classes": [], "properties": [], "edges": []}

    classes: list[dict[str, Any]] = []
    if db.has_collection("ontology_classes"):
        classes = list(
            _shared.run_aql(
                db,
                "FOR c IN ontology_classes "
                "FILTER c.ontology_id == @oid AND c.expired == @never "
                "SORT c.label ASC RETURN c",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

    properties: list[dict[str, Any]] = []
    for prop_col in (
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_properties",
    ):
        if db.has_collection(prop_col):
            properties.extend(
                _shared.run_aql(
                    db,
                    f"FOR p IN {prop_col} "
                    "FILTER p.ontology_id == @oid AND p.expired == @never "
                    "SORT p.label ASC RETURN p",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                )
            )

    edges: list[dict[str, Any]] = []
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
            result = list(
                _shared.run_aql(
                    db,
                    f"FOR e IN {edge_col} FILTER e.ontology_id == @oid "
                    "AND e.expired == @never "
                    "RETURN MERGE(e, {edge_type: @et})",
                    bind_vars={
                        "oid": ontology_id,
                        "et": edge_col,
                        "never": NEVER_EXPIRES,
                    },
                )
            )
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
        None,
        description="Target ontology ID for promoted entities",
    ),
) -> dict[str, Any]:
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
