import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.ontology import _shared
from app.models.curation import (
    TemporalDiff,
    TemporalSnapshot,
)
from app.services import schema_diff as schema_diff_svc
from app.services import temporal as temporal_svc
from app.services.schema_extraction import (
    SchemaExtractionConfig,
    extract_schema,
    get_extraction_status,
    list_named_graphs,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schema extraction endpoints (PRD 6.9 — Week 20)
# ---------------------------------------------------------------------------


@router.post("/schema/extract")
async def trigger_schema_extraction(config: SchemaExtractionConfig) -> dict[str, Any]:
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
async def get_schema_extraction_status(run_id: str) -> dict[str, Any]:
    """Get the status of a schema extraction run."""
    try:
        return get_extraction_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Stream 5 PR 3 sub-B S.5 -- cross-ontology schema diff. GET with two
# query params (no credentials, no body) so this endpoint is safe to
# bookmark / share / curl. The two ontology_ids are public registry
# keys; the diff itself is computed entirely from the local AOE
# database, no upstream Arango is touched.
@router.get("/schema/diff")
async def diff_schema_ontologies(
    a: str = Query(..., description="First ontology_id (the 'before' side)"),
    b: str = Query(..., description="Second ontology_id (the 'after' side)"),
) -> dict[str, Any]:
    """Cross-ontology schema diff (Stream 5 PR 3 sub-B, S.5).

    Compares the current state of two ontologies and returns added /
    removed / changed classes, properties, and constraints. The
    canonical use case is two schema-extraction runs against the same
    target ArangoDB at different points in time, but any two
    ontologies can be diffed.

    Provenance compatibility is surfaced as a warning (not an error):
    when the two ontologies have different ``source_db`` /
    ``source_host`` (or neither was created via schema extraction),
    the diff is still computed and returned, but the
    ``provenance.compatible`` field is ``false`` and
    ``provenance.warning`` carries an explanatory string. The curator
    decides what to do with it.

    Errors mapped:
      - same ontology_id passed for both sides -> 400 (caller mistake)
      - either ontology missing entirely -> 200 with empty added/changed
        and the missing ontology's classes appearing as ``removed``
        (no 404 -- the diff is well-defined when one side is empty,
        and "the user deleted ontology B" is a legitimate diff input).
    """
    try:
        return schema_diff_svc.diff_ontologies(ontology_a=a, ontology_b=b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Stream 5 PR 1 S.6 — named-graph discovery. POST (not GET) because the
# request carries credentials in the body; we never want them in query
# strings (URL logging, browser history, referrer leaks). Same shape as
# SchemaExtractionConfig so the workspace UI's "extract" overlay can
# reuse the connection form and just swap the action button.
@router.post("/schema/graphs")
async def discover_target_graphs(config: SchemaExtractionConfig) -> dict[str, Any]:
    """List named graphs + loose collections on an external ArangoDB.

    Returns the topology the workspace UI's schema-extraction preview
    binds to: per-graph edge definitions, vertex/orphan collections,
    plus loose document/edge collections that are not in any named
    graph. The response is safe to render (no document samples, no
    schemas, just topology).

    Errors mapped:
      - ``ValueError`` -> 400 (bad config)
      - connection / auth failures -> 502 (upstream Arango unreachable)
    """
    try:
        return list_named_graphs(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # We deliberately surface the upstream error message here -- the
        # curator needs to know whether the host was wrong, the password
        # was wrong, or the database does not exist. Sanitisation lives
        # in the global error envelope.
        log.exception("Named-graph discovery failed")
        raise HTTPException(status_code=502, detail=f"Target ArangoDB error: {exc}") from exc


# ---------------------------------------------------------------------------
# Temporal endpoints (PRD 7.3 — Week 10)
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/snapshot", response_model=TemporalSnapshot)
async def get_snapshot(
    ontology_id: str,
    at: float = Query(..., description="Unix timestamp for the point-in-time snapshot"),
) -> dict[str, Any]:
    """Point-in-time graph state — all classes, properties, and edges active at ``at``."""
    return temporal_svc.get_snapshot(ontology_id=ontology_id, timestamp=at)


@router.get("/class/{class_key}/provenance")
async def get_class_provenance(class_key: str) -> dict[str, Any]:
    """Chunks from documents linked to this class via ``extracted_from`` (class → document).

    Provenance is **document-level**: we do not store which substring of a chunk defined the class.
    The query returns all chunks for those documents (same as the workspace list view).
    """
    db = _shared.get_db()
    chunks: list[dict[str, Any]] = []
    if db.has_collection("extracted_from") and db.has_collection("chunks"):
        rows = list(
            _shared.run_aql(
                db,
                "FOR e IN extracted_from "
                "  FILTER e._from == CONCAT('ontology_classes/', @key) "
                "  LET doc_id = PARSE_IDENTIFIER(e._to).key "
                "  FOR c IN chunks "
                "    FILTER c.doc_id == doc_id "
                "    SORT c.chunk_index ASC "
                "    RETURN { _key: c._key, text: c.text, chunk_index: c.chunk_index, "
                "             doc_id: c.doc_id, section_heading: c.section_heading }",
                bind_vars={"key": class_key},
            )
        )
        chunks = rows
    return {"data": chunks, "total_count": len(chunks)}


@router.get("/class/{class_key}/history")
async def get_class_history(class_key: str) -> list[dict[str, Any]]:
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
) -> dict[str, Any]:
    """Temporal diff — added, removed, and changed entities between t1 and t2."""
    if t1 >= t2:
        raise HTTPException(status_code=400, detail="t1 must be less than t2")
    return temporal_svc.get_diff(ontology_id=ontology_id, t1=t1, t2=t2)


@router.get("/{ontology_id}/timeline")
async def get_timeline(ontology_id: str) -> list[dict[str, Any]]:
    """Discrete change events for VCR slider tick marks."""
    return temporal_svc.get_timeline_events(ontology_id=ontology_id)


@router.post("/class/{class_key}/revert")
async def revert_class(
    class_key: str,
    to_version: float = Query(..., description="Timestamp of the version to revert to"),
) -> dict[str, Any]:
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
