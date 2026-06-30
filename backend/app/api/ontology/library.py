import logging
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import get_user_from_request
from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.api.ontology import _shared
from app.db import (
    documents_repo,
    releases_repo,
)
from app.db.temporal_constants import NEVER_EXPIRES
from app.models.ontology import (
    UpdateConstraintRequest,
)
from app.services import ontology_context as ctx_svc

log = logging.getLogger(__name__)
router = APIRouter()


_LIBRARY_EDGE_COLLECTIONS = (
    "subclass_of",
    "rdfs_domain",
    "rdfs_range_class",
    "has_property",
    "related_to",
)


def _batch_edge_counts_for_ontology_ids(
    db: Any, ontology_ids: list[str], *, existing: set[str] | None = None
) -> dict[str, int]:
    """Edge counts per ontology in a SINGLE AQL round-trip across all collections.

    python-arango's ``has_collection`` issues a full ``GET /_api/collection``
    every call, and the old shape did one ``has_collection`` + one AQL *per* edge
    collection — up to 10 round-trips. On a remote (cloud, WAN) ArangoDB that
    dominates the ``/library`` latency. We instead snapshot the collection set
    once (``existing``, ideally passed by the caller) and union per-collection
    grouped counts in one query: each subquery does an efficient server-side
    ``COLLECT … WITH COUNT``, then we sum the partials by ontology_id.
    """
    if not ontology_ids:
        return {}
    counts: dict[str, int] = {oid: 0 for oid in ontology_ids}
    unique_ids = sorted(set(ontology_ids))

    if existing is None:
        existing = {c["name"] for c in (db.collections() or []) if isinstance(c, dict)}
    edge_cols = tuple(c for c in _LIBRARY_EDGE_COLLECTIONS if c in existing)
    if not edge_cols:
        return counts

    subqueries = ",\n            ".join(
        f"(FOR e IN {col} FILTER e.ontology_id IN @oids AND e.expired == @never "
        "COLLECT oid = e.ontology_id WITH COUNT INTO cnt RETURN {oid: oid, cnt: cnt})"
        for col in edge_cols
    )
    query = (
        f"LET partials = FLATTEN([\n            {subqueries}\n        ], 1)\n"
        "FOR p IN partials\n"
        "  COLLECT oid = p.oid AGGREGATE total = SUM(p.cnt)\n"
        "  RETURN { oid: oid, cnt: total }"
    )
    try:
        rows = list(
            _shared.run_aql(db, query, bind_vars={"oids": unique_ids, "never": NEVER_EXPIRES})
        )
    except Exception:
        log.debug("batch edge count failed", exc_info=True)
        return counts
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
) -> dict[str, Any]:
    """List all ontologies in the registry with cursor-based pagination."""
    try:
        entries, next_cursor = _shared.registry_repo.list_registry_entries(
            cursor=cursor, limit=limit
        )
        db = _shared.get_db()
        # Snapshot collection names once (each has_collection/collections call is
        # a full WAN round-trip on a remote ArangoDB). Reused for the registry
        # existence check and the batched edge-count query below.
        existing = {
            c["name"] for c in cast("list[dict[str, Any]]", db.collections() or []) if "name" in c
        }
        has_col = "ontology_registry" in existing
        total_count = db.collection("ontology_registry").count() if has_col else 0

        if tag:
            entries = [e for e in entries if tag in (e.get("tags") or [])]

        oids = [str(e.get("_key", "")) for e in entries if e.get("_key")]
        batch_counts = _batch_edge_counts_for_ontology_ids(db, oids, existing=existing)

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
async def update_ontology_metadata(ontology_id: str, body: UpdateOntologyRequest) -> dict[str, Any]:
    """Update ontology registry metadata (J.3).

    Validates status transitions:
    - draft  -> active | deprecated
    - active -> deprecated
    - deprecated -> (none)
    """
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    updates: dict[str, Any] = {}
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
        updated = _shared.registry_repo.update_registry_entry(ontology_id, updates)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


class CreateOntologyReleaseRequest(BaseModel):
    """Body for recording a versioned ontology release."""

    version: str = Field(
        ..., min_length=1, max_length=120, description="Release version label, e.g. 1.0.0"
    )
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
) -> dict[str, Any]:
    """Record a new ontology release and update registry release metadata."""
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
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
) -> dict[str, Any]:
    """List release records for an ontology, newest first."""
    if _shared.registry_repo.get_registry_entry(ontology_id) is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")
    rows = releases_repo.list_releases_for_ontology(ontology_id, limit=limit)
    return {"data": rows}


@router.delete("/library/{ontology_id}")
async def delete_ontology(
    ontology_id: str,
    confirm: bool = Query(False, description="Set to true to actually delete"),
    hard_delete: bool = Query(
        False,
        description="When true, also remove the ontology_registry entry after expiring contents",
    ),
) -> dict[str, Any]:
    """Delete or deprecate an ontology with cascade analysis (PRD FR-8.13).

    Uses temporal soft-delete: sets ``expired = now`` on all classes,
    properties, and edges so the VCR timeline can still show historical
    state.  By default the registry entry is marked ``deprecated``. With
    ``hard_delete=true`` the registry entry is removed after the contents
    are expired, which is useful for cleaning up test/duplicate ontologies.
    Per-ontology named graph is removed (it references the same shared
    collections, and expired entities are filtered out by queries).

    Without ``?confirm=true``, returns dependent ontologies (dry-run).
    """
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    if entry.get("status") == "deprecated" and not hard_delete:
        raise ValidationError(f"Ontology '{ontology_id}' is already deprecated")

    db = _shared.get_db()
    now = __import__("time").time()

    # Dry-run: surface the same deletion-impact payload the dedicated GET
    # endpoint returns so the frontend can render a single dialog from
    # either route. ``dependent_ontologies`` is retained for backward
    # compatibility with older clients that only consume direct dependents.
    from app.services.ontology_dependency import analyze_deletion_impact

    try:
        impact = analyze_deletion_impact(db, ontology_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    dependents = impact["direct_dependents"]

    if not confirm:
        return {
            "ontology_id": ontology_id,
            "status": "pending_confirmation",
            "dependent_ontologies": dependents,
            "deletion_impact": impact,
            "message": "Pass ?confirm=true to proceed with deprecation.",
        }

    expired_counts: dict[str, int] = {}

    for col_name in (
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_constraints",
    ):
        if db.has_collection(col_name):
            result = list(
                _shared.run_aql(
                    db,
                    f"FOR doc IN {col_name} "
                    "FILTER doc.ontology_id == @oid AND doc.expired == @never "
                    f"UPDATE doc WITH {{ expired: @now }} IN {col_name} "
                    "RETURN NEW._key",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES, "now": now},
                )
            )
            expired_counts[col_name] = len(result)

    for edge_col in (
        "subclass_of",
        "has_property",
        "has_constraint",
        "related_to",
        "equivalent_class",
        "extracted_from",
        "extends_domain",
        "has_chunk",
        "produced_by",
        "rdfs_domain",
        "rdfs_range_class",
    ):
        if db.has_collection(edge_col):
            result = list(
                _shared.run_aql(
                    db,
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
            _shared.run_aql(
                db,
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
                _shared.run_aql(
                    db,
                    "FOR c IN ontology_classes FILTER c.ontology_id == @oid RETURN c._id",
                    bind_vars={"oid": ontology_id},
                )
            )
        if class_ids:
            cross_extends = list(
                _shared.run_aql(
                    db,
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

    if hard_delete:
        registry_deleted = _shared.registry_repo.delete_registry_entry(ontology_id)
        status = "deleted"
    else:
        _shared.registry_repo.deprecate_registry_entry(ontology_id)
        registry_deleted = False
        status = "deprecated"

    return {
        "ontology_id": ontology_id,
        "status": status,
        "expired_at": now,
        "expired_counts": expired_counts,
        "graph_deleted": graph_deleted,
        "registry_deleted": registry_deleted,
        "dependent_ontologies": dependents,
    }


@router.get("/library/{ontology_id}")
async def get_ontology_detail(ontology_id: str) -> dict[str, Any]:
    """Get ontology detail including stats (class count, property count)."""
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    class_count = 0
    property_count = 0
    try:
        db = _shared.get_db()
        if db.has_collection("ontology_classes"):
            result = list(
                _shared.run_aql(
                    db,
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
                    _shared.run_aql(
                        db,
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
) -> dict[str, Any]:
    """Upload a document and trigger incremental extraction into an existing ontology."""
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
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
        db = _shared.get_db()
        doc_record = documents_repo.get_document(doc_id, db=db)
        if doc_record and doc_record.get("status") in ("ready", "processed"):
            await extraction_service.start_run(
                db,
                document_id=doc_id,
                target_ontology_id=oid,
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
async def list_ontology_documents(ontology_id: str) -> dict[str, Any]:
    """List source documents linked to an ontology via ``extracted_from`` edges."""
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    db = _shared.get_db()
    documents: list[dict[str, Any]] = []
    if db.has_collection("extracted_from") and db.has_collection("documents"):
        documents = list(
            _shared.run_aql(
                db,
                "FOR e IN extracted_from "
                "FILTER e.ontology_id == @oid AND e.expired == @never "
                "LET doc_key = PARSE_IDENTIFIER(e._to).key "
                "FOR d IN documents "
                "FILTER d._key == doc_key "
                "COLLECT doc = d INTO group "
                "RETURN MERGE(doc, {edge_count: LENGTH(group)})",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

    return {"ontology_id": ontology_id, "documents": documents}


@router.get("/library/{ontology_id}/constraints")
async def list_ontology_constraints(
    ontology_id: str,
    constraint_type: str | None = Query(
        default=None,
        description=(
            "Optional exact-match filter on constraint_type, e.g. 'owl:Restriction' "
            "or 'sh:NodeShape'. Omit to return all kinds."
        ),
    ),
    include_unresolved: bool = Query(
        default=True,
        description=(
            "When false, drop constraints whose property_id is null. Default "
            "true so curators can fix unresolved property URIs in the UI."
        ),
    ),
    class_id: str | None = Query(
        default=None,
        description=(
            "Optional exact-match filter on the full on_class document id "
            "(e.g. 'ontology_classes/Customer'). Used by the workspace "
            "FloatingDetailPanel to fetch constraints for one class per "
            "click without pulling the whole ontology's constraints."
        ),
    ),
) -> dict[str, Any]:
    """List live OWL restrictions and SHACL shapes for an ontology (Stream 3 PR 1-PR 3).

    Reads from the ``ontology_constraints`` collection populated by
    extraction materialization (PR 1), OWL import (PR 2), and SHACL
    import (PR 3). Each row is one restriction in the OWL-native shape
    (a class with both min and max cardinality returns two rows; group
    on the client side if you want a single bound).

    Joins ``on_class`` to ``ontology_classes`` for ``class_label`` so the
    workspace UI can render constraints without a second round-trip.
    Property labels are joined opportunistically -- left null when the
    constraint references an unresolved property URI.
    """
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise NotFoundError(
            f"Ontology '{ontology_id}' not found",
            details={"ontology_id": ontology_id},
        )

    db = _shared.get_db()
    constraints = _shared.constraints_repo.list_constraints_for_ontology(
        db,
        ontology_id=ontology_id,
        constraint_type=constraint_type,
        include_unresolved=include_unresolved,
        on_class=class_id,
    )

    if not constraints:
        return {
            "ontology_id": ontology_id,
            "constraints": [],
            "total": 0,
        }

    # One AQL per unique class id / property id to attach labels.
    # Volumes are typically small (constraints per ontology rarely
    # exceed a few hundred); per-id round-trip would be wasteful so
    # we DOCUMENT() in a single query keyed by the ids in this batch.
    class_ids = sorted({c["on_class"] for c in constraints if c.get("on_class")})
    property_ids = sorted({c["property_id"] for c in constraints if c.get("property_id")})

    class_labels: dict[str, str] = {}
    if class_ids:
        rows = list(
            _shared.run_aql(
                db,
                "FOR id IN @ids LET d = DOCUMENT(id) "
                "FILTER d != null AND d.expired == @never "
                "RETURN {id: d._id, label: d.label}",
                bind_vars={"ids": class_ids, "never": NEVER_EXPIRES},
            )
        )
        for row in rows:
            class_labels[row["id"]] = row.get("label") or ""

    property_labels: dict[str, str] = {}
    if property_ids:
        rows = list(
            _shared.run_aql(
                db,
                "FOR id IN @ids LET d = DOCUMENT(id) "
                "FILTER d != null AND d.expired == @never "
                "RETURN {id: d._id, label: d.label}",
                bind_vars={"ids": property_ids, "never": NEVER_EXPIRES},
            )
        )
        for row in rows:
            property_labels[row["id"]] = row.get("label") or ""

    enriched: list[dict[str, Any]] = []
    for c in constraints:
        enriched.append(
            {
                **c,
                "class_label": class_labels.get(c.get("on_class", ""), ""),
                "property_label": property_labels.get(c.get("property_id") or "", ""),
            }
        )

    # Stable sort: by class label, then property URI, then restriction
    # type. The two AQL passes above are unordered.
    enriched.sort(
        key=lambda c: (
            c.get("class_label", ""),
            c.get("property_uri", ""),
            c.get("restriction_type", ""),
        )
    )

    return {
        "ontology_id": ontology_id,
        "constraints": enriched,
        "total": len(enriched),
    }


# ---------------------------------------------------------------------------
# Constraint curation mutations (Stream 3 I.7)
# ---------------------------------------------------------------------------


def _resolve_live_constraint(ontology_id: str, constraint_key: str) -> dict[str, Any]:
    """Fetch a live constraint and assert it belongs to ``ontology_id``.

    Raises ``NotFoundError`` if the constraint doesn't exist (or was already
    rejected/superseded), and ``ValidationError`` if it belongs to another
    ontology — the same guard pattern the class/edge mutation endpoints use.
    """
    db = _shared.get_db()
    constraint = _shared.constraints_repo.get_constraint(db, key=constraint_key)
    if constraint is None:
        raise NotFoundError(
            f"Constraint '{constraint_key}' not found",
            details={"ontology_id": ontology_id, "constraint_key": constraint_key},
        )
    if constraint.get("ontology_id") != ontology_id:
        raise ValidationError("Constraint belongs to a different ontology")
    return constraint


@router.post("/{ontology_id}/constraints/{constraint_key}/approve")
async def approve_constraint_endpoint(
    ontology_id: str,
    constraint_key: str,
) -> dict[str, Any]:
    """Approve a constraint — set ``status='approved'`` (Stream 3 I.7).

    Non-destructive: the constraint stays live and continues to be enforced
    by the rule engine. Uses temporal versioning so the approval is an
    auditable new version, consistent with edge/class status changes.
    """
    _resolve_live_constraint(ontology_id, constraint_key)
    db = _shared.get_db()
    try:
        return _shared.constraints_repo.update_constraint(
            db,
            key=constraint_key,
            data={"status": "approved"},
            created_by="workspace",
            change_summary=f"Constraint {constraint_key} approved",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


@router.post("/{ontology_id}/constraints/{constraint_key}/reject")
async def reject_constraint_endpoint(
    ontology_id: str,
    constraint_key: str,
) -> dict[str, Any]:
    """Reject a constraint — soft-delete it (Stream 3 I.7).

    Expires the constraint so it drops out of the constraints list, the rule
    engine, and exports (all filter on ``expired == NEVER_EXPIRES``). The
    version is retained in temporal history, so a reject is auditable and
    recoverable rather than a hard delete.
    """
    _resolve_live_constraint(ontology_id, constraint_key)
    db = _shared.get_db()
    expired = _shared.constraints_repo.expire_constraint(db, key=constraint_key)
    if expired is None:
        raise NotFoundError(f"Constraint '{constraint_key}' not found")
    return {"status": "rejected", "constraint_key": constraint_key, "ontology_id": ontology_id}


@router.put("/{ontology_id}/constraints/{constraint_key}")
async def update_constraint_endpoint(
    ontology_id: str,
    constraint_key: str,
    body: UpdateConstraintRequest,
) -> dict[str, Any]:
    """Edit a constraint's value or description (Stream 3 I.7).

    Expires the old version and creates a new one carrying the edited fields.
    Editing resets ``status`` to ``'pending'`` — a curator-changed bound
    should be re-reviewed rather than inherit the prior approval.
    """
    _resolve_live_constraint(ontology_id, constraint_key)

    update_data: dict[str, Any] = {
        k: v
        for k, v in {
            "restriction_value": body.restriction_value,
            "description": body.description,
        }.items()
        if v is not None
    }
    if not update_data:
        raise ValidationError("No fields to update")
    update_data["status"] = "pending"

    db = _shared.get_db()
    try:
        return _shared.constraints_repo.update_constraint(
            db,
            key=constraint_key,
            data=update_data,
            created_by="workspace",
            change_summary=f"Edited constraint {constraint_key}: {', '.join(update_data.keys())}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Library full-text search (J.6)
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_ontology_library(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results per source type"),
    offset: int = Query(0, ge=0, description="Result offset for pagination"),
) -> dict[str, Any]:
    """Full-text search across ontology registry, classes, and properties (J.6).

    Uses the ``ontology_search_view`` ArangoSearch view with BM25 ranking.
    Returns results grouped by source type with snippets and ontology context.
    """
    db = _shared.get_db()

    existing_views = {v["name"] for v in cast("list[dict[str, Any]]", db.views())}
    if "ontology_search_view" not in existing_views:
        return {
            "query": q,
            "results": {"registry": [], "classes": [], "properties": []},
            "counts": {"registry": 0, "classes": 0, "properties": 0},
        }

    registry_results: list[dict[str, Any]] = []
    if db.has_collection("ontology_registry"):
        registry_results = list(
            _shared.run_aql(
                db,
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

    class_results: list[dict[str, Any]] = []
    if db.has_collection("ontology_classes"):
        class_results = list(
            _shared.run_aql(
                db,
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

    property_results: list[dict[str, Any]] = []
    if db.has_collection("ontology_properties"):
        property_results = list(
            _shared.run_aql(
                db,
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
async def set_org_ontologies(org_id: str, body: OrgOntologySelectionRequest) -> dict[str, Any]:
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
async def get_org_ontologies(org_id: str) -> dict[str, Any]:
    """List selected base ontologies for an organization."""
    ontology_ids = ctx_svc.get_domain_ontology_for_org(org_id=org_id)
    return {"org_id": org_id, "selected_ontologies": ontology_ids}


# ---------------------------------------------------------------------------
# Per-ontology graphs
# ---------------------------------------------------------------------------


@router.get("/graphs")
async def list_ontology_graphs() -> dict[str, Any]:
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
