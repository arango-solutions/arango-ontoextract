import json
import logging
import time
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.api.ontology import _shared
from app.db.temporal_constants import NEVER_EXPIRES

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Ontology imports management (PRD 6.15 FR-15.7-15.12)
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/imports")
async def list_ontology_imports(ontology_id: str) -> dict[str, Any]:
    """List all ontologies imported by this ontology."""
    db = _shared.get_db()
    entry = _shared.registry_repo.get_registry_entry(ontology_id, db=db)
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
        _shared.run_aql(
            db,
            query,
            bind_vars={
                "from_id": f"ontology_registry/{ontology_id}",
                "never": NEVER_EXPIRES,
            },
        )
    )
    return {"imports": results}


@router.get("/{ontology_id}/effective")
async def get_effective_ontology(
    ontology_id: str,
    request: Request,
    include: str = Query(
        "summary",
        description=(
            "Field projection profile. ``summary`` (default) returns the "
            "narrow allow-list the workspace canvas consumes -- see "
            "``app.services.ontology_projections``. ``full`` returns "
            "every field including ``evidence[]`` for detail / export "
            "consumers."
        ),
    ),
    max_depth: int = Query(
        10,
        ge=1,
        le=50,
        description="Maximum number of imports hops to walk (clamped to 1..50).",
    ),
) -> Response:
    """Compute the effective ontology view (Stream 1 H.12 + H.13).

    Returns the target ontology merged with the transitive closure of its
    ``owl:imports`` ancestors. Each class / edge / property is annotated
    with ``source_ontology_id``, ``source_ontology_name``, and
    ``is_imported`` so the workspace canvas (H.15) can render imported
    entities with distinct styling and the import-aware extraction
    prompts (H.17) can tell the LLM which concepts to reuse.

    Conflicts surfaced inline as ``conflicts`` (H.13) cover:

    * ``duplicate_uri`` -- same URI in two or more imported sources
    * ``duplicate_label`` -- same label in two or more sources with
      *different* URIs
    * ``subclass_cycle_via_import`` -- a subclass cycle introduced by
      merging imported axioms (cycles contained within a single source
      are writer bugs, not merge conflicts, and are not reported here)

    ETag / If-None-Match
    --------------------

    The response carries a weak ETag derived from
    ``(ontology_id, include profile, every source's updated_at)`` so
    repeat requests from the same client can short-circuit to ``304``
    once the closure stabilises. The ETag invalidates the moment any
    participating ontology mutates or an ``imports`` edge changes.

    Returns ``404`` if the ontology does not exist.
    """
    db = _shared.get_db()
    try:
        from app.services.ontology_effective import compute_effective_ontology

        payload = compute_effective_ontology(
            db,
            ontology_id=ontology_id,
            include=include,
            max_depth=max_depth,
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    etag = str(payload.get("etag") or "")
    if_none_match = request.headers.get("if-none-match", "").strip()
    # Honour both the weak validator we emit (``W/"abc"``) and the
    # strong-validator variant a paranoid intermediary might rewrite to
    # (``"abc"``). Per RFC 7232 §2.3.2 weak comparison ignores the W/
    # prefix when serving 304s.
    if etag and if_none_match and _etag_matches(if_none_match, etag):
        log.info(
            f"get_effective_ontology 304 ont={ontology_id} include={include} etag={etag}",
            extra={"ontology_id": ontology_id, "include": include, "etag": etag},
        )
        return Response(status_code=304, headers={"ETag": etag})

    log.info(
        f"get_effective_ontology 200 ont={ontology_id} include={include} "
        f"sources={len(payload.get('sources', []))} "
        f"classes={len(payload.get('classes', []))} "
        f"edges={len(payload.get('edges', []))} "
        f"conflicts={len(payload.get('conflicts', []))}",
        extra={
            "ontology_id": ontology_id,
            "include": include,
            "source_count": len(payload.get("sources", [])),
            "class_count": len(payload.get("classes", [])),
            "edge_count": len(payload.get("edges", [])),
            "conflict_count": len(payload.get("conflicts", [])),
            "etag": etag,
        },
    )

    body = json.dumps(payload)
    return Response(
        content=body,
        media_type="application/json",
        headers={"ETag": etag} if etag else {},
    )


def _etag_matches(client_value: str, server_value: str) -> bool:
    """Weak-comparison ETag match per RFC 7232 §2.3.2.

    Strips the ``W/`` weak-validator prefix and any surrounding
    whitespace before comparing the opaque tag. Supports a comma-
    separated list of validators in ``If-None-Match`` (RFC 7232 §3.2).
    """

    def _normalise(tag: str) -> str:
        tag = tag.strip()
        if tag.startswith("W/"):
            tag = tag[2:]
        return tag.strip()

    server_norm = _normalise(server_value)
    return any(_normalise(raw) == server_norm for raw in client_value.split(","))


@router.get("/library/{ontology_id}/deletion-impact")
async def get_ontology_deletion_impact(ontology_id: str) -> dict[str, Any]:
    """Return the cascade-on-delete dependency analysis (Stream 1 H.4).

    Read-only, idempotent. The frontend ``OntologyDeleteDialog`` calls
    this before showing the typed-name confirmation so the user sees:

    * Direct AND transitive dependents via ``imports`` (with depth)
    * Cross-ontology ``extends_domain`` edge counts
    * Per-collection counts of entities/edges that the cascade will
      soft-expire
    * Number of extraction runs whose ``target_ontology_id`` /
      ``domain_ontology_ids`` reference this ontology
    * Quality history snapshots, released versions, and pending
      belief revisions associated with the ontology

    Returns ``404`` if the ontology does not exist. The ``DELETE``
    endpoint's dry-run path also returns this payload (under
    ``deletion_impact``) so callers may use either route.
    """
    db = _shared.get_db()
    try:
        from app.services.ontology_dependency import analyze_deletion_impact

        return analyze_deletion_impact(db, ontology_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


@router.get("/{ontology_id}/imported-by")
async def list_ontology_dependents(ontology_id: str) -> dict[str, Any]:
    """List all ontologies that import this ontology."""
    db = _shared.get_db()
    entry = _shared.registry_repo.get_registry_entry(ontology_id, db=db)
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
        _shared.run_aql(
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
async def add_ontology_import(ontology_id: str, body: AddImportRequest) -> dict[str, Any]:
    """Add an import edge from one ontology to another."""
    db = _shared.get_db()
    entry = _shared.registry_repo.get_registry_entry(ontology_id, db=db)
    if entry is None:
        raise NotFoundError(f"Ontology '{ontology_id}' not found")

    target = _shared.registry_repo.get_registry_entry(body.target_ontology_id, db=db)
    if target is None:
        raise NotFoundError(f"Target ontology '{body.target_ontology_id}' not found")

    if body.target_ontology_id == ontology_id:
        raise ValidationError("Cannot import self")

    if not db.has_collection("imports"):
        raise HTTPException(status_code=500, detail="'imports' edge collection not available")

    from_id = f"ontology_registry/{ontology_id}"
    to_id = f"ontology_registry/{body.target_ontology_id}"

    existing = list(
        _shared.run_aql(
            db,
            "FOR e IN imports "
            "FILTER e._from == @f AND e._to == @t AND e.expired == @never "
            "RETURN e._key",
            bind_vars={"f": from_id, "t": to_id, "never": NEVER_EXPIRES},
        )
    )
    if existing:
        raise ConflictError(f"'{ontology_id}' already imports '{body.target_ontology_id}'")

    # Circular dependency check: would target importing us create a cycle?
    cycle_check = list(
        _shared.run_aql(
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
        raise ValidationError("Adding this import would create a circular dependency")

    edge = _shared.ontology_repo.create_edge(
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
async def remove_ontology_import(ontology_id: str, target_ontology_id: str) -> dict[str, Any]:
    """Remove an import edge (soft-delete via temporal expiry)."""
    db = _shared.get_db()

    if not db.has_collection("imports"):
        raise NotFoundError("imports edge collection not available")

    from_id = f"ontology_registry/{ontology_id}"
    to_id = f"ontology_registry/{target_ontology_id}"

    edges = list(
        _shared.run_aql(
            db,
            "FOR e IN imports "
            "FILTER e._from == @f AND e._to == @t AND e.expired == @never "
            "RETURN e",
            bind_vars={"f": from_id, "t": to_id, "never": NEVER_EXPIRES},
        )
    )
    if not edges:
        raise NotFoundError(f"No active import from '{ontology_id}' to '{target_ontology_id}'")

    now = time.time()
    for edge in edges:
        db.collection("imports").update(
            {"_key": edge["_key"], "expired": now, "ttlExpireAt": now + 90 * 86400}
        )

    return {"removed": len(edges), "from": ontology_id, "to": target_ontology_id}


@router.get("/catalog")
async def list_standard_ontology_catalog() -> dict[str, Any]:
    """Return the bundled standard ontology catalog (Stream 1 H.5).

    The catalog is the curated list of well-known ontologies the user
    can one-click-import. Each entry includes display metadata
    (``name``, ``description``, ``uri``, ``tier``, ``tags``,
    ``class_count``, ``property_count``) plus a ``source`` hint
    indicating whether import will read a bundled file or fetch a
    remote URL (the frontend uses this to render an offline-capable
    badge).
    """
    from app.services.standard_ontology_catalog import load_catalog

    entries = load_catalog()
    return {"ontologies": entries, "count": len(entries)}


class CatalogImportRequest(BaseModel):
    ontology_id: str | None = Field(
        default=None,
        description=(
            "Optional override for the new registry _key. Defaults to the catalog entry id."
        ),
    )


@router.post("/catalog/{catalog_id}/import", status_code=201)
async def import_from_catalog(
    catalog_id: str,
    body: CatalogImportRequest | None = None,
) -> dict[str, Any]:
    """Import a standard ontology by catalog id (Stream 1 H.5).

    Synchronous. Returns the import stats (triple count, registry key,
    imports edges created) on success, ``404`` for unknown catalog
    ids, ``409`` if an ontology with the chosen id already exists,
    and ``500`` for fetch / parse failures (which carry the upstream
    error message for debugging).

    Bundled entries import instantly; URL entries depend on network
    reachability and may take several seconds.
    """
    from app.services.standard_ontology_catalog import import_catalog_entry

    db = _shared.get_db()
    requested_id = body.ontology_id if body else None

    try:
        return import_catalog_entry(
            catalog_id,
            db=db,
            ontology_id=requested_id,
        )
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ConflictError:
        raise
    except ValueError as exc:
        # Bubbles up from import_from_file (e.g. unparseable Turtle).
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Catalog packaging bug -- bubbles up clearly to the operator.
        log.exception("catalog import failed for %s", catalog_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/imports-graph")
async def get_imports_graph(
    root: str | None = Query(
        None,
        description=(
            "Optional registry _key to anchor the traversal on. "
            "Omit for the full registry-wide imports DAG."
        ),
    ),
    direction: str = Query(
        "both",
        description=(
            "When `root` is set: 'outbound' (ancestors), 'inbound' (descendants), "
            "or 'both' (default, union). Ignored when `root` is omitted."
        ),
    ),
    max_depth: int = Query(
        10,
        ge=1,
        le=50,
        description="Maximum traversal depth (clamped to 1..50). Imports DAGs are shallow.",
    ),
) -> dict[str, Any]:
    """Return the live ``owl:imports`` dependency DAG (Stream 1 H.3).

    Two modes:

    * Without ``root``: every live import edge plus every registry row
      that participates as either endpoint. Powers the workspace
      ``ImportsDependencyOverlay`` global view (H.7).
    * With ``root``: the sub-DAG reachable from that ontology in the
      requested ``direction``. Powers per-ontology dependency previews
      (H.6 catalog browser, H.7 "show my imports tree").

    Returns ``404`` if ``root`` is given but the ontology does not
    exist; ``400`` if ``direction`` is unrecognised.
    """
    from app.services.ontology_imports_graph import (
        Direction,
        build_imports_dag,
    )

    if direction not in ("outbound", "inbound", "both"):
        raise ValidationError(
            f"direction must be one of 'outbound', 'inbound', 'both' -- got {direction!r}"
        )

    db = _shared.get_db()
    try:
        return build_imports_dag(
            db,
            root=root,
            direction=cast(Direction, direction),
            max_depth=max_depth,
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
