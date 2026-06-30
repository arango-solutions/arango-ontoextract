import binascii
import logging
import time
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query

from app.api.errors import NotFoundError
from app.api.ontology import _shared
from app.db.temporal_constants import NEVER_EXPIRES
from app.services import temporal as temporal_svc
from app.services.edge_confidence import (
    compute_edge_confidence,
    enrich_rdfs_range_class_edges,
)
from app.services.ontology_projections import (
    CLASS_SUMMARY_RETURN,
    INCLUDE_SUMMARY,
    LIVE_EDGE_COLLECTIONS,
    LIVE_PROP_COLLECTIONS,
    normalize_include,
    summarize_class,
    summarize_edge,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Ontology classes and edges (used by library ClassHierarchy component)
# Must come AFTER all static routes to avoid catching /domain/classes etc.
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/classes")
async def list_ontology_classes(
    ontology_id: str,
    include: str = Query(
        "full",
        description=(
            "Field projection profile. ``full`` (default, legacy shape) returns "
            "every field including ``evidence[]``. ``summary`` returns the "
            "narrow allow-list the workspace canvas + asset explorer consume "
            "(see ``app.services.ontology_projections.CLASS_SUMMARY_FIELDS``); "
            "this is ~3x smaller on the WTW Ontology and is the recommended "
            "profile for canvas/list views. Detail panels should use "
            "``GET /{ontology_id}/classes/{class_key}`` for full-fidelity data."
        ),
    ),
    limit: int | None = Query(
        None,
        ge=1,
        le=500,
        description=(
            "Opt-in keyset pagination (Stream 12 T10). When omitted the "
            "endpoint returns the full class list in one response (legacy, "
            "back-compatible shape ``{data: [...]}``). When set, the response "
            "is a single page of at most ``limit`` classes plus a "
            "``next_cursor`` to fetch the following page (``null`` on the last "
            "page). Pages are ordered by ``(label, _key)`` so they are stable "
            "across requests even when labels collide."
        ),
    ),
    cursor: str | None = Query(
        None,
        description=(
            "Opaque cursor from a previous response's ``next_cursor``. Only "
            "honoured when ``limit`` is also set. An invalid / corrupt cursor "
            "returns ``400``."
        ),
    ),
) -> dict[str, Any]:
    """List classes belonging to an ontology.

    Two modes:

    * **Full (default, no ``limit``)** -- returns every live class sorted by
      label. The ``?include=summary`` profile projects fields **inside AQL**
      rather than in Python, so the dropped bytes never leave Arango. On the
      WTW Ontology this turns the payload from 943 KB into ~280 KB (mostly by
      dropping ``evidence[]`` arrays the canvas does not render). This shape
      is unchanged for every existing caller.

    * **Paginated (``limit`` set)** -- keyset pagination via
      :func:`app.db.pagination.paginate` over ``(label, _key)``, so a
      5K+ class ontology can be pulled a bounded page at a time instead of in
      one unbounded response. The page is projected to the summary allow-list
      in Python when ``include=summary``; the per-page size makes the
      post-projection cost negligible versus the AQL-side projection used by
      the full path. Response adds ``next_cursor`` / ``has_more`` /
      ``total_count``.

    Why ``/classes`` and not the canvas: the workspace canvas loads through
    ``GET /{id}/effective`` (target + transitive imports, with ETag/304),
    not this endpoint. ``/classes`` backs the library ``ClassHierarchy`` and
    the asset-explorer previews; those are the consumers pagination protects
    from unbounded payloads on very large ontologies.
    """
    db = _shared.get_db()
    if not db.has_collection("ontology_classes"):
        if limit is not None:
            return {"data": [], "next_cursor": None, "has_more": False, "total_count": 0}
        return {"data": []}
    profile = normalize_include(include)

    if limit is not None:
        return _list_classes_paginated(
            db,
            ontology_id=ontology_id,
            profile=profile,
            limit=limit,
            cursor=cursor,
        )

    return_clause = CLASS_SUMMARY_RETURN if profile == INCLUDE_SUMMARY else "RETURN c"
    t0 = time.perf_counter()
    classes = list(
        _shared.run_aql(
            db,
            "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
            "AND c.expired == @never "
            "SORT c.label ASC " + return_clause,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    ms_aql = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        f"list_ontology_classes timing ont={ontology_id} "
        f"classes={len(classes)} include={profile} aql={ms_aql}ms",
        extra={
            "ontology_id": ontology_id,
            "class_count": len(classes),
            "include": profile,
            "ms_aql": ms_aql,
        },
    )
    return {"data": classes}


def _list_classes_paginated(
    db: Any,
    *,
    ontology_id: str,
    profile: str,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """Keyset-paginated branch of :func:`list_ontology_classes` (Stream 12 T10).

    Delegates to the shared :func:`app.db.pagination.paginate` helper so the
    cursor encoding, ``(sort_field, _key)`` tiebreak, ``has_more`` look-ahead,
    and ``total_count`` all match every other paginated endpoint. A corrupt
    cursor surfaces as ``400`` rather than a 500 so clients can distinguish a
    bad request from a server fault.
    """
    t0 = time.perf_counter()
    try:
        page = _shared.paginate(
            db,
            collection="ontology_classes",
            sort_field="label",
            sort_order="asc",
            limit=limit,
            cursor=cursor,
            filters={"ontology_id": ontology_id, "expired": NEVER_EXPIRES},
        )
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc

    data = page.data
    if profile == INCLUDE_SUMMARY:
        data = [summarize_class(c) for c in data]

    ms_aql = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        f"list_ontology_classes paginated ont={ontology_id} "
        f"page={len(data)} total={page.total_count} include={profile} "
        f"has_more={page.has_more} aql={ms_aql}ms",
        extra={
            "ontology_id": ontology_id,
            "page_count": len(data),
            "total_count": page.total_count,
            "include": profile,
            "has_more": page.has_more,
            "ms_aql": ms_aql,
        },
    )
    return {
        "data": data,
        "next_cursor": page.cursor,
        "has_more": page.has_more,
        "total_count": page.total_count,
    }


@router.get("/{ontology_id}/classes/{class_key}")
async def get_class_detail(ontology_id: str, class_key: str) -> dict[str, Any]:
    """Get class detail with properties resolved via rdfs_domain traversal (ADR-006).

    Returns the class document plus ``attributes`` (datatype properties) and
    ``relationships`` (object properties with resolved range class).  Falls
    back to legacy ``has_property`` edges when no PGT-aligned data exists.
    """
    db = _shared.get_db()

    cls = _shared.ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise NotFoundError(f"Class '{class_key}' not found in ontology '{ontology_id}'")

    class_id = cls["_id"]

    attributes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []

    # NOTE on dedup pattern (applies to all three queries below):
    # The previous shape was a Cartesian-style ``FOR e IN <edge> FOR p IN
    # <prop>`` join, which emits one row per matching edge. When a property
    # has more than one live edge to the same class (e.g. the writer
    # re-asserted ``rdfs_domain`` on re-extraction without expiring the
    # prior edge), the property document was returned twice -- causing
    # React duplicate-key warnings in ``FloatingDetailPanel``. We now
    # pre-collect property IDs via ``RETURN DISTINCT``, then look each
    # property up exactly once. Cleaner shape, cheaper plan, and the
    # contract of "one property document per logical property" matches
    # what every consumer expects.

    if db.has_collection("rdfs_domain") and db.has_collection("ontology_datatype_properties"):
        attributes = list(
            _shared.run_aql(
                db,
                "LET prop_ids = ("
                "  FOR e IN rdfs_domain "
                "  FILTER e._to == @cid AND e.expired == @never "
                "  RETURN DISTINCT e._from"
                ") "
                "FOR p IN ontology_datatype_properties "
                "FILTER p._id IN prop_ids AND p.expired == @never "
                "RETURN p",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

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
        relationships = list(
            _shared.run_aql(
                db,
                "LET prop_ids = ("
                "  FOR e IN rdfs_domain "
                "  FILTER e._to == @cid AND e.expired == @never "
                "  RETURN DISTINCT e._from"
                ") "
                "FOR p IN ontology_object_properties "
                f"FILTER p._id IN prop_ids AND p.expired == @never "
                f"{range_sub}",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

    legacy_properties: list[dict[str, Any]] = []
    if (
        not attributes
        and not relationships
        and db.has_collection("has_property")
        and db.has_collection("ontology_properties")
    ):
        legacy_properties = list(
            _shared.run_aql(
                db,
                "LET prop_ids = ("
                "  FOR e IN has_property "
                "  FILTER e._from == @cid AND e.expired == @never "
                "  RETURN DISTINCT e._to"
                ") "
                "FOR prop IN ontology_properties "
                "FILTER prop._id IN prop_ids AND prop.expired == @never "
                "RETURN prop",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

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
) -> dict[str, Any]:
    """List properties for an ontology, optionally filtered by comma-separated keys."""
    db = _shared.get_db()
    props: list[dict[str, Any]] = []
    key_list = [k.strip() for k in keys.split(",") if k.strip()] if keys else None

    for prop_col in (
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_properties",
    ):
        if not db.has_collection(prop_col):
            continue
        if key_list:
            props.extend(
                _shared.run_aql(
                    db,
                    f"FOR p IN {prop_col} "
                    "FILTER p.ontology_id == @oid AND p._key IN @keys "
                    "AND p.expired == @never "
                    "SORT p.label ASC RETURN p",
                    bind_vars={
                        "oid": ontology_id,
                        "keys": key_list,
                        "never": NEVER_EXPIRES,
                    },
                )
            )
        else:
            props.extend(
                _shared.run_aql(
                    db,
                    f"FOR p IN {prop_col} "
                    "FILTER p.ontology_id == @oid "
                    "AND p.expired == @never "
                    "SORT p.label ASC RETURN p",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                )
            )
    return {"data": props}


_EDGE_HISTORY_COLLECTIONS = (
    "subclass_of",
    "rdfs_domain",
    "rdfs_range_class",
    "equivalent_class",
    "has_property",
    "related_to",
    "extends_domain",
    "imports",
    "extracted_from",
)


@router.get("/{ontology_id}/edges")
async def list_ontology_edges(
    ontology_id: str,
    include: str = Query(
        "full",
        description=(
            "Field projection profile. ``full`` (default, legacy shape) returns "
            "every field including ``evidence[]``. ``summary`` returns the "
            "narrow allow-list the workspace canvas consumes (see "
            "``app.services.ontology_projections.EDGE_SUMMARY_FIELDS``); this "
            "is ~1.3x smaller on the WTW Ontology and is the recommended "
            "profile for canvas views. Detail panels should fetch the full "
            "edge via ``GET /{ontology_id}/edges/{edge_key}``."
        ),
    ),
) -> dict[str, Any]:
    """List all edges for an ontology (PGT-aligned + legacy fallback).

    Each edge is annotated with a top-level ``confidence`` derived from
    ``evidence[].evidence_confidence`` (mean) when an explicit field is not
    already present -- see ``app.services.edge_confidence``. This is what the
    workspace canvas's confidence lens (PRD §5.3, FR-7.8.6) reads to paint
    edge color, stroke width, and the appended ``%`` label.

    For ``rdfs_range_class`` edges, ``label``/``description``/``confidence``/
    ``evidence`` are first lifted from the owning ``ontology_object_properties``
    vertex via :func:`enrich_rdfs_range_class_edges`. Without this join, the
    canvas falls back to the structural label ``owl:ObjectProperty`` and shows
    no confidence percentage, even though the real relationship name (e.g.
    "generates Risk Profile") and a 0.9 confidence with grounded evidence
    live one hop away on the property document.

    Projection ordering note
    ------------------------

    The ``?include=summary`` projection happens **after** enrichment and
    confidence computation, not as an AQL projection. The workspace
    canvas needs the lifted ``label`` / merged ``confidence`` on
    ``rdfs_range_class`` edges, and those fields are produced in Python.
    Doing AQL-level projection first would either lose the merge or
    require the projection to also include ``evidence`` so
    ``compute_edge_confidence`` could still derive a value -- defeating
    the size win. Projecting after the merge is correct and cheap:
    ``summarize_edge`` is a 12-field dict comprehension per row.
    """
    db = _shared.get_db()
    # Stage-level timing so the dev log surfaces where the WTW load
    # cost actually goes after T2. Without this we were guessing
    # between (a) network RTT to remote Arango, (b) AQL execution on
    # a large dataset, (c) Python enrichment on 1000+ edges, (d) JSON
    # serialization of the response. Each stage is logged separately
    # plus a TOTAL line so a single click reveals the breakdown.
    t0 = time.perf_counter()
    edges, properties_by_id = _fetch_live_edges_and_properties(db, ontology_id)
    t_fetch = time.perf_counter() - t0

    t1 = time.perf_counter()
    enrich_rdfs_range_class_edges(edges, properties_by_id)
    t_enrich = time.perf_counter() - t1

    t2 = time.perf_counter()
    for edge in edges:
        conf = compute_edge_confidence(edge)
        if conf is not None and edge.get("confidence") in (None, ""):
            edge["confidence"] = conf
    t_conf = time.perf_counter() - t2

    t3 = time.perf_counter()
    profile = normalize_include(include)
    if profile == INCLUDE_SUMMARY:
        edges = [summarize_edge(e) for e in edges]
    t_proj = time.perf_counter() - t3

    ms_fetch = round(t_fetch * 1000, 1)
    ms_enrich = round(t_enrich * 1000, 1)
    ms_conf = round(t_conf * 1000, 1)
    ms_proj = round(t_proj * 1000, 1)
    ms_total = round((t_fetch + t_enrich + t_conf + t_proj) * 1000, 1)
    # Bake values into the message string -- the dev log formatter only
    # shows the message, not ``extra``, so structured fields would be
    # invisible. Keep ``extra`` too for production JSON loggers.
    log.info(
        f"list_ontology_edges timing ont={ontology_id} edges={len(edges)} "
        f"props={len(properties_by_id)} include={profile} "
        f"fetch={ms_fetch}ms enrich={ms_enrich}ms conf={ms_conf}ms "
        f"project={ms_proj}ms TOTAL={ms_total}ms",
        extra={
            "ontology_id": ontology_id,
            "edge_count": len(edges),
            "prop_count": len(properties_by_id),
            "include": profile,
            "ms_fetch_aql": ms_fetch,
            "ms_enrich_rdfs": ms_enrich,
            "ms_compute_conf": ms_conf,
            "ms_project": ms_proj,
            "ms_total_handler": ms_total,
        },
    )

    return {"data": edges}


@router.get("/{ontology_id}/edges/{edge_key}")
async def get_edge_detail(
    ontology_id: str,
    edge_key: str,
    include: str = Query(
        "full",
        description=(
            "Field projection profile. Defaults to ``full`` since detail "
            "panels render evidence and the full description; the canvas "
            "uses ``GET /{ontology_id}/edges`` (the list endpoint) with "
            "``?include=summary``."
        ),
    ),
) -> dict[str, Any]:
    """Get a single live ontology edge by key.

    Replaces the N+1 anti-pattern where the workspace ``FloatingDetailPanel``
    used to fetch the entire ``GET /edges`` list (1219 edges / 555 KB / 3.3 s
    on the WTW Ontology) just to ``.find()`` one edge by key. This endpoint
    does at most one indexed primary lookup per edge collection (``.get``
    by ``_key``), so the same operation now costs 1-2 WAN round-trips and
    a few KB.

    Enrichment parity with the list endpoint
    ----------------------------------------

    For ``rdfs_range_class`` edges the canvas + detail panel expect the
    relationship label, description, confidence, and evidence to be
    *lifted* from the owning ``ontology_object_properties`` document --
    without that, the panel would display ``owl:ObjectProperty`` and no
    confidence. We replicate the list endpoint's :func:`enrich_rdfs_range_
    class_edges` step here, but only fetch the ONE property document
    referenced by ``edge._from`` (one extra primary lookup) instead of
    pulling the entire property collection.

    Confidence is then derived from ``evidence[]`` the same way the list
    endpoint does (see :func:`compute_edge_confidence`), so the wire
    contract for a single-edge fetch matches what the same edge would
    look like inside the list response.
    """
    db = _shared.get_db()
    found = _find_edge_collection_for_key(db, edge_key)
    if found is None:
        raise NotFoundError(f"Edge '{edge_key}' not found")
    edge_col, doc = found
    if doc.get("ontology_id") != ontology_id:
        raise NotFoundError(f"Edge '{edge_key}' does not belong to ontology '{ontology_id}'")
    if doc.get("expired") != NEVER_EXPIRES:
        # Older, expired versions are reachable via /edge/{edge_key}/history,
        # not via this point-in-time live-edge endpoint.
        raise NotFoundError(f"Edge '{edge_key}' is no longer live")

    edge = dict(doc)
    edge["edge_type"] = edge_col

    # Single-property enrichment for rdfs_range_class. ``_from`` is the
    # full ``collection/key`` reference to the owning property document
    # (object-property or, in legacy data, datatype-property). One
    # primary-key lookup is enough -- no need to scan the whole
    # collection like the list endpoint does.
    if edge_col == "rdfs_range_class":
        from_id = edge.get("_from")
        if isinstance(from_id, str) and "/" in from_id:
            prop_col_name, prop_key = from_id.split("/", 1)
            if db.has_collection(prop_col_name):
                try:
                    prop_doc = cast(
                        "dict[str, Any] | None",
                        db.collection(prop_col_name).get(prop_key),
                    )
                except Exception:
                    prop_doc = None
                if prop_doc is not None:
                    enrich_rdfs_range_class_edges([edge], {from_id: prop_doc})

    conf = compute_edge_confidence(edge)
    if conf is not None and edge.get("confidence") in (None, ""):
        edge["confidence"] = conf

    if normalize_include(include) == INCLUDE_SUMMARY:
        edge = summarize_edge(edge)

    return edge


@router.get("/{ontology_id}/properties/{prop_key}")
async def get_property_detail(ontology_id: str, prop_key: str) -> dict[str, Any]:
    """Get a single live ontology property (object or datatype) by key.

    Replaces the N+1 anti-pattern where the workspace ``FloatingDetailPanel``
    used to fetch the entire ``GET /properties`` list to ``.find()`` one
    property. We do at most one indexed primary lookup per property
    collection.

    Properties live in two collections in PGT-aligned ontologies
    (``ontology_object_properties`` for relationships, ``ontology_datatype_
    properties`` for attributes), with a legacy ``ontology_properties``
    collection still present in some older ontologies. We probe in that
    order; the first match within the requested ontology wins.

    Note: there is no ``?include=`` parameter here -- a single property
    document is small (label + description + URI + range + confidence)
    and detail panels always need the full shape. The bandwidth win is
    "fetch one row instead of all rows", not "shrink the row".
    """
    db = _shared.get_db()
    for col_name in (
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_properties",
    ):
        if not db.has_collection(col_name):
            continue
        try:
            doc = cast(
                "dict[str, Any] | None",
                db.collection(col_name).get(prop_key),
            )
        except Exception:
            doc = None
        if doc is None:
            continue
        if doc.get("ontology_id") != ontology_id:
            # The same _key could in principle exist in another ontology;
            # keep probing rather than returning the wrong document.
            continue
        if doc.get("expired") != NEVER_EXPIRES:
            # Skip expired versions -- versioned history is exposed
            # elsewhere (property repo helpers), not via this live
            # point-in-time endpoint.
            continue
        # Annotate which collection owns this property so the detail
        # panel can branch on object vs datatype without a second
        # round-trip.
        return dict(doc, property_collection=col_name)
    raise NotFoundError(f"Property '{prop_key}' not found in ontology '{ontology_id}'")


def _live_properties_by_id(db: Any, ontology_id: str) -> dict[str, dict[str, Any]]:
    """Return ``{_id: property_doc}`` for live object/datatype properties.

    Used by :func:`list_ontology_edges` to enrich ``rdfs_range_class`` edges
    without a per-edge round-trip. Both property collections are keyed by
    ``_id`` (full ``collection/key`` form) since that is what the
    ``rdfs_range_class._from`` field stores.

    Note: ``list_ontology_edges`` no longer calls this directly -- it uses
    :func:`_fetch_live_edges_and_properties` which folds the edge-collection
    fan-out and the property-collection fan-out into a single AQL.  This
    function is retained for callers that only need the property map (e.g.
    future single-edge enrichment fast paths) and for backwards compatibility
    with downstream code/tests.
    """
    out: dict[str, dict[str, Any]] = {}
    for col_name in ("ontology_object_properties", "ontology_datatype_properties"):
        if not db.has_collection(col_name):
            continue
        rows = _shared.run_aql(
            db,
            f"FOR p IN {col_name} FILTER p.ontology_id == @oid AND p.expired == @never RETURN p",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
        for row in rows:
            pid = row.get("_id")
            if isinstance(pid, str):
                out[pid] = row
    return out


# Allowlist of every edge collection ``list_ontology_edges`` is willing to
# read. The values are interpolated into the generated AQL string (one
# ``FOR`` subquery per name), so they MUST stay a fixed set of trusted
# identifiers -- never accept user input here.
#
# Promoted to ``app.services.ontology_projections.LIVE_EDGE_COLLECTIONS`` /
# ``LIVE_PROP_COLLECTIONS`` so the multi-ontology effective-graph service
# (Stream 1 H.12) shares the same source of truth without reaching into
# this module's private constants. These aliases keep the file-local
# references stable; updating the allow-list in one place updates both.
_LIVE_EDGE_COLLECTIONS: tuple[str, ...] = LIVE_EDGE_COLLECTIONS
_LIVE_PROP_COLLECTIONS: tuple[str, ...] = LIVE_PROP_COLLECTIONS

# Cache the generated AQL keyed by ``(edge_cols, prop_cols)``.  The set
# of existing collections is effectively static during a process's
# lifetime (created at ontology bootstrap, never dropped at runtime), so
# we will hit one or two distinct cache keys for the lifetime of the
# server.  Avoids re-stringifying the query on every request.
_LIVE_EDGES_AND_PROPS_QUERY_CACHE: dict[tuple[tuple[str, ...], tuple[str, ...]], str] = {}


def _build_live_edges_and_props_query(
    edge_collections: tuple[str, ...],
    prop_collections: tuple[str, ...],
) -> str:
    """Build the single-shot AQL that returns ``{edges, props}``.

    AQL parses (and validates) every collection reference at submission
    time, so we can only emit subqueries for collections that actually
    exist.  The two ``FLATTEN`` calls handle the 0/1/N-collection cases
    uniformly: each subquery yields an array, and ``FLATTEN(..., 1)``
    concatenates them.
    """
    cache_key = (edge_collections, prop_collections)
    cached = _LIVE_EDGES_AND_PROPS_QUERY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    edge_subqueries = ",\n        ".join(
        f"(FOR e IN {col} "
        "FILTER e.ontology_id == @oid AND e.expired == @never "
        f'RETURN MERGE(e, {{edge_type: "{col}"}}))'
        for col in edge_collections
    )
    prop_subqueries = ",\n        ".join(
        f"(FOR p IN {col} FILTER p.ontology_id == @oid AND p.expired == @never RETURN p)"
        for col in prop_collections
    )

    edges_expr = f"FLATTEN([\n        {edge_subqueries}\n    ], 1)" if edge_collections else "[]"
    props_expr = f"FLATTEN([\n        {prop_subqueries}\n    ], 1)" if prop_collections else "[]"

    query = (
        f"LET edges = {edges_expr}\n"
        f"LET props = {props_expr}\n"
        "RETURN { edges: edges, props: props }"
    )
    _LIVE_EDGES_AND_PROPS_QUERY_CACHE[cache_key] = query
    return query


def _fetch_live_edges_and_properties(
    db: Any, ontology_id: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Fetch live edges + property map for an ontology in 2 round-trips.

    Replaces the previous fan-out which issued one ``has_collection`` HTTP
    call plus one AQL per edge collection (6) plus the same pair per
    property collection (2), totalling ~8-14 sequential round-trips against
    the database.  On a remote ArangoDB with ~50-100 ms RTT that
    translated to ~8-9 s of pure latency on the WTW Ontology, before any
    JSON or rendering work, which the user perceived as "the canvas is
    just stuck after I click an ontology".

    The new shape:

    1. Single ``db.collections()`` HTTP call to discover which of the
       allowlisted edge / property collections actually exist (older
       ontologies and mid-migration databases may be missing some).
    2. Single AQL query with two ``FLATTEN`` subqueries returning
       ``{edges, props}`` in one cursor.

    Returns
    -------
    ``(edges, properties_by_id)`` -- ``edges`` is a list of edge docs
    each annotated with an ``edge_type`` field naming the source
    collection, mirroring the legacy per-collection ``MERGE`` step so
    downstream enrichment / projection code is unchanged. ``properties_by_id``
    is a mapping from property ``_id`` (full ``collection/key``) to
    property doc, the exact shape ``enrich_rdfs_range_class_edges``
    consumes.
    """
    t_collections = time.perf_counter()
    existing = {col["name"] for col in db.collections()}
    edge_cols = tuple(c for c in _LIVE_EDGE_COLLECTIONS if c in existing)
    prop_cols = tuple(c for c in _LIVE_PROP_COLLECTIONS if c in existing)
    ms_collections = round((time.perf_counter() - t_collections) * 1000, 1)

    if not edge_cols and not prop_cols:
        log.info(
            f"fetch_live_edges_and_properties: no collections exist "
            f"ont={ontology_id} db.collections()={ms_collections}ms",
            extra={"ontology_id": ontology_id, "ms_collections": ms_collections},
        )
        return [], {}

    query = _build_live_edges_and_props_query(edge_cols, prop_cols)
    t_aql = time.perf_counter()
    rows = list(
        _shared.run_aql(
            db,
            query,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    ms_aql = round((time.perf_counter() - t_aql) * 1000, 1)
    log.info(
        f"fetch_live_edges_and_properties timing ont={ontology_id} "
        f"db.collections()={ms_collections}ms aql={ms_aql}ms "
        f"edge_cols={len(edge_cols)} prop_cols={len(prop_cols)}",
        extra={
            "ontology_id": ontology_id,
            "ms_collections": ms_collections,
            "ms_aql": ms_aql,
            "edge_cols": list(edge_cols),
            "prop_cols": list(prop_cols),
        },
    )
    if not rows:
        return [], {}

    payload = rows[0] or {}
    edges_raw = payload.get("edges") or []
    props_raw = payload.get("props") or []

    edges: list[dict[str, Any]] = [e for e in edges_raw if isinstance(e, dict)]
    properties_by_id: dict[str, dict[str, Any]] = {}
    for p in props_raw:
        if not isinstance(p, dict):
            continue
        pid = p.get("_id")
        if isinstance(pid, str):
            properties_by_id[pid] = p

    return edges, properties_by_id


def _find_edge_collection_for_key(db: Any, edge_key: str) -> tuple[str, dict[str, Any]] | None:
    """Locate which edge collection owns ``edge_key`` and return ``(collection, doc)``.

    Edges live in one of several collections (``subclass_of``, ``rdfs_domain``,
    …); we discover the owner by checking each in order. This mirrors the
    lookup pattern in ``_shared.ontology_repo._EDGE_COLLECTIONS_FOR_LOOKUP``.
    """
    for col_name in _EDGE_HISTORY_COLLECTIONS:
        if not db.has_collection(col_name):
            continue
        try:
            doc = cast(
                "dict[str, Any] | None",
                db.collection(col_name).get(edge_key),
            )
        except Exception:
            doc = None
        if doc is not None:
            return col_name, doc
    return None


@router.get("/edge/{edge_key}/history")
async def get_edge_history(edge_key: str) -> list[dict[str, Any]]:
    """All versions of an edge sorted by ``created`` DESC.

    Mirrors ``GET /class/{class_key}/history`` for first-class edge support
    (PRD FR-7.8.6: "Selecting a node/edge opens a floating panel with
    metadata, properties, provenance, history, and quality scores").

    Edges are grouped by their endpoint pair ``(_from, _to, ontology_id)``
    rather than by URI — see ``temporal_svc.get_edge_history`` for the
    grouping rationale and the cross-vertex-version caveat.
    """
    db = _shared.get_db()
    located = _find_edge_collection_for_key(db, edge_key)
    if located is None:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_key}' not found")
    collection, _doc = located

    history = temporal_svc.get_edge_history(
        db,
        collection=collection,
        key=edge_key,
    )
    if not history:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_key}' not found")
    for ver in history:
        conf = compute_edge_confidence(ver)
        if conf is not None and "confidence" not in ver:
            ver["confidence"] = conf
    return history


@router.get("/edge/{edge_key}/provenance")
async def get_edge_provenance(edge_key: str) -> dict[str, Any]:
    """Source chunks supporting an edge, derived from ``evidence[].source_chunk_ids``.

    Unlike the class-level provenance (which links to whole documents via
    ``extracted_from``), edge provenance is **chunk-level**: every relationship
    extracted under FR-2.14 records the exact ``source_chunk_ids`` and a
    verbatim ``evidence_text`` snippet. We surface those chunks plus the
    inline ``evidence_text`` so the workspace panel can show why this
    relationship was inferred.

    Returned shape mirrors ``/class/{class_key}/provenance`` (``{data, total_count}``)
    so the frontend ``AssetInfoPanel`` can render edge provenance with the
    same code path that already renders class provenance via the ``_provenance``
    field - see ``frontend/src/app/workspace/page.tsx`` lines 1247-1273.
    """
    db = _shared.get_db()
    located = _find_edge_collection_for_key(db, edge_key)
    if located is None:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_key}' not found")
    _collection, doc = located

    chunk_ids: list[str] = []
    inline_evidence: list[dict[str, Any]] = []
    evidence = doc.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            ids = item.get("source_chunk_ids")
            if isinstance(ids, list):
                for cid in ids:
                    if isinstance(cid, str) and cid not in chunk_ids:
                        chunk_ids.append(cid)
            inline_evidence.append(
                {
                    "evidence_text": item.get("evidence_text"),
                    "evidence_confidence": item.get("evidence_confidence"),
                    "extraction_rationale": item.get("extraction_rationale"),
                    "source_chunk_ids": item.get("source_chunk_ids"),
                    "source_spans": item.get("source_spans"),
                }
            )

    chunks: list[dict[str, Any]] = []
    if chunk_ids and db.has_collection("chunks"):
        chunks = list(
            _shared.run_aql(
                db,
                "FOR c IN chunks "
                "  FILTER c._key IN @ids "
                "  SORT c.chunk_index ASC "
                "  RETURN { _key: c._key, text: c.text, chunk_index: c.chunk_index, "
                "           doc_id: c.doc_id, section_heading: c.section_heading }",
                bind_vars={"ids": chunk_ids},
            )
        )

    return {
        "data": chunks,
        "total_count": len(chunks),
        "evidence": inline_evidence,
    }
