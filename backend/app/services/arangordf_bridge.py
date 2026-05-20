"""ArangoRDF bridge — wraps arango_rdf for PGT import with post-processing.

Handles OWL/TTL import into ArangoDB, post-import ontology_id tagging,
per-ontology named graph creation, and file/URL-based import with format
detection.
"""

from __future__ import annotations

import logging
import time
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from arango.database import StandardDatabase
from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
from rdflib import Graph as RDFGraph

from app.db.client import get_db
from app.db.ontology_repo import create_class, create_edge, create_property
from app.db.registry_repo import create_registry_entry
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)

_URI_MAP_COLLECTION = "aoe_uri_map"

# ---------------------------------------------------------------------------
# Stream 3 PR 2 -- OWL restriction import (PRD §6.14 FR-14.2)
# ---------------------------------------------------------------------------

# Map OWL restriction predicates to the PR 1 ``RestrictionType`` enum values
# (see ``app.models.ontology.RestrictionType``). Keeping this map flat means
# the rdflib walker can identify a restriction's kind by a single membership
# lookup, and PR 1's existing materialization-shape contract is reused
# verbatim by the import path.
_OWL_CARDINALITY_PREDICATES: dict[URIRef, str] = {
    OWL.minCardinality: "minCardinality",
    OWL.maxCardinality: "maxCardinality",
    OWL.cardinality: "cardinality",
}
_OWL_VALUE_RESTRICTION_PREDICATES: dict[URIRef, str] = {
    OWL.allValuesFrom: "allValuesFrom",
    OWL.someValuesFrom: "someValuesFrom",
    OWL.hasValue: "hasValue",
}
# Qualified-cardinality variants are recognised so we can warn-and-skip
# them explicitly. They require an ``owl:onClass`` / ``owl:onDataRange``
# companion which expands the PR 1 wire shape; deferred to a follow-up.
_OWL_QUALIFIED_CARDINALITY_PREDICATES: set[URIRef] = {
    OWL.minQualifiedCardinality,
    OWL.maxQualifiedCardinality,
    OWL.qualifiedCardinality,
}

# Edges by which OWL restrictions attach to a class. ``rdfs:subClassOf``
# is by far the most common (the textbook anonymous-superclass pattern);
# ``owl:equivalentClass`` is also legal when the class is *defined* by
# a restriction (e.g. ``Adult equivalentClass [Person and (age >= 18)]``).
_OWL_RESTRICTION_ATTACHMENT_PREDICATES: tuple[URIRef, ...] = (
    RDFS.subClassOf,
    OWL.equivalentClass,
)

# Marker stamped on every constraint document produced by this importer
# so downstream consumers (queries, dashboards, the future SHACL importer
# in PR 3) can distinguish "extracted from documents" rows (PR 1, marked
# by ``extraction_run_id``) from "imported from an OWL file" rows.
_IMPORT_SOURCE_OWL_RESTRICTION = "owl_restriction"


def _ensure_arango_rdf() -> type[Any]:
    """Import arango_rdf lazily to avoid hard dependency at module load."""
    try:
        from arango_rdf import ArangoRDF as _ArangoRDFCls

        return cast(type[Any], _ArangoRDFCls)
    except ImportError as exc:
        raise ImportError(
            "arango_rdf is required for OWL import. Install it with: pip install arango-rdf"
        ) from exc


def import_owl_to_graph(
    db: StandardDatabase | None = None,
    *,
    ttl_content: str,
    graph_name: str,
    ontology_id: str,
    ontology_uri_prefix: str | None = None,
) -> dict[str, Any]:
    """Import OWL/TTL content into ArangoDB via PGT transformation.

    Steps:
    1. Parse TTL into rdflib graph
    2. Import via ArangoRDF PGT
    3. Tag all created documents with ``ontology_id``
    4. Create per-ontology named graph if not exists

    Returns dict with import stats.
    """
    if db is None:
        db = get_db()

    rdf_graph = RDFGraph()
    rdf_graph.parse(data=ttl_content, format="turtle")

    triple_count = len(rdf_graph)
    log.info(
        "importing OWL via PGT",
        extra={
            "graph_name": graph_name,
            "ontology_id": ontology_id,
            "triple_count": triple_count,
        },
    )

    try:
        arango_rdf_cls = _ensure_arango_rdf()
    except ImportError:
        log.warning("arango_rdf unavailable; using rdflib fallback importer")
        _import_with_rdflib_fallback(
            db,
            rdf_graph=rdf_graph,
            ontology_id=ontology_id,
        )
    else:
        adb_rdf = arango_rdf_cls(db)

        adb_rdf.init_rdf_collections(
            bnode_collection=f"{graph_name}_bnodes",
        )

        adb_rdf.rdf_to_arangodb_by_pgt(
            name=graph_name,
            rdf_graph=rdf_graph,
            overwrite=False,
        )

    _tag_documents_with_ontology_id(
        db,
        ontology_id=ontology_id,
        ontology_uri_prefix=ontology_uri_prefix,
        graph_name=graph_name,
    )

    # Stream 3 PR 2 -- materialise OWL restrictions in the same shape
    # PR 1's extraction-time materializer uses. Runs AFTER tagging so
    # the class/property resolution AQL sees correctly-tagged rows
    # (the resolver filters on ``ontology_id``).
    restrictions_imported = _import_owl_restrictions(
        db,
        rdf_graph=rdf_graph,
        ontology_id=ontology_id,
    )

    _ensure_named_graph(db, graph_name=graph_name)

    stats = {
        "graph_name": graph_name,
        "ontology_id": ontology_id,
        "triple_count": triple_count,
        "imported": True,
        "restrictions_imported": restrictions_imported,
    }

    log.info("OWL import completed", extra=stats)
    return stats


def _find_registry_key_for_import_iri(
    db: StandardDatabase,
    imported_iri: str,
) -> str | None:
    """Resolve an ``owl:imports`` target IRI to an ``ontology_registry`` ``_key``."""
    if not db.has_collection("ontology_registry"):
        return None
    rows = list(
        run_aql(
            db,
            """
            FOR o IN ontology_registry
              FILTER o.uri != null AND o.uri != ""
              FILTER o.status == null OR o.status != "deprecated"
              LET u = o.uri
              FILTER u == @iri OR STARTS_WITH(@iri, u) OR STARTS_WITH(u, @iri)
              SORT LENGTH(u) DESC
              LIMIT 1
              RETURN o._key
            """,
            bind_vars={"iri": imported_iri},
        )
    )
    if not rows:
        return None
    key = rows[0]
    return str(key) if key is not None else None


def sync_owl_imports_edges(
    db: StandardDatabase,
    rdf_graph: RDFGraph,
    importer_registry_key: str,
) -> dict[str, Any]:
    """Wire ``owl:imports`` IRIs to ``imports`` edges between registry documents.

    Edges run ``ontology_registry/{importer}`` → ``ontology_registry/{imported}`` when the
    imported IRI matches another registry document's ``uri`` (exact or prefix). Targets not
    in the library are logged as warnings (PGT.7 / PRD imports graph).
    """
    if not db.has_collection("imports"):
        return {"created": 0, "skipped": 0, "warnings": []}

    from_id = f"ontology_registry/{importer_registry_key}"
    imported_iris: set[str] = set()
    for _subj, obj in rdf_graph.subject_objects(OWL.imports):
        o_str = str(obj)
        if o_str:
            imported_iris.add(o_str)

    warnings: list[str] = []
    created = 0
    skipped = 0

    for iri in sorted(imported_iris):
        target_key = _find_registry_key_for_import_iri(db, iri)
        if target_key is None:
            warnings.append(f"No registry entry for owl:imports target {iri!r}")
            continue
        if target_key == importer_registry_key:
            skipped += 1
            continue
        to_id = f"ontology_registry/{target_key}"
        dup = list(
            run_aql(
                db,
                """
                FOR e IN imports
                  FILTER e._from == @fr AND e._to == @to AND e.expired == @never
                  LIMIT 1
                  RETURN 1
                """,
                bind_vars={
                    "fr": from_id,
                    "to": to_id,
                    "never": NEVER_EXPIRES,
                },
            )
        )
        if dup:
            skipped += 1
            continue
        create_edge(
            db,
            edge_collection="imports",
            from_id=from_id,
            to_id=to_id,
            data={"import_iri": iri},
        )
        created += 1

    if warnings:
        log.warning(
            "owl:imports targets missing from ontology_registry",
            extra={"importer": importer_registry_key, "warnings": warnings},
        )

    return {
        "created": created,
        "skipped": skipped,
        "warnings": warnings,
    }


def _extract_owl_restrictions(
    rdf_graph: RDFGraph,
) -> list[dict[str, Any]]:
    """Walk ``rdf_graph`` for OWL restrictions attached to class definitions.

    Restrictions in OWL/Turtle are anonymous nodes typed ``owl:Restriction``
    that ride on a class via ``rdfs:subClassOf`` or ``owl:equivalentClass``::

        :Account a owl:Class ;
            rdfs:subClassOf [
                a owl:Restriction ;
                owl:onProperty :holder ;
                owl:minCardinality 1
            ] .

    Each call returns a list of dicts -- one per (class, restriction)
    pair -- shaped to be trivially folded into the PR 1 wire format
    (see ``app.models.ontology.ExtractedConstraint``). The dict is
    intentionally *not* a Pydantic model; this function does NOT touch
    the database and is fully pure, so it's safe to test in isolation.

    Keys returned per dict:

    * ``class_uri``         the class the restriction is attached to
    * ``property_uri``      the constrained property's URI
    * ``restriction_type``  one of the values in PR 1's ``RestrictionType``
                            enum (``"minCardinality"`` / ``"cardinality"``
                            / ``"allValuesFrom"`` / etc.)
    * ``restriction_value`` ``int`` for cardinality kinds, ``str`` (URI or
                            datatype URI or literal) for value kinds
    * ``attachment``        ``"subClassOf"`` or ``"equivalentClass"`` --
                            kept for diagnostics, the rule engine doesn't
                            care which it was
    * ``source_node``       the rdflib node id of the restriction (for log
                            context only)

    Restrictions that can't be interpreted (missing ``owl:onProperty``,
    no recognized restriction predicate, qualified cardinality without
    a follow-up scope) are skipped with a WARNING line so they're not
    silently dropped -- this matches the PR 1 ``property_id`` resolution
    failure handling.
    """
    out: list[dict[str, Any]] = []

    # Pre-fetch the class URIs once -- iterating rdflib triples is cheap
    # but ``g.subjects(RDF.type, OWL.Class)`` returns a generator, and
    # we walk it twice (once for ``rdfs:subClassOf``, once for
    # ``owl:equivalentClass``).
    class_uris = sorted(
        {str(s) for s in rdf_graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    )

    for class_uri_str in class_uris:
        class_uri = URIRef(class_uri_str)
        for attachment_predicate in _OWL_RESTRICTION_ATTACHMENT_PREDICATES:
            attachment_name = (
                "subClassOf" if attachment_predicate == RDFS.subClassOf else "equivalentClass"
            )
            for candidate in rdf_graph.objects(class_uri, attachment_predicate):
                # Only blank nodes are restrictions in the textbook sense.
                # A named superclass on the same edge is just a regular
                # subClassOf / equivalentClass and is handled elsewhere.
                if not isinstance(candidate, BNode):
                    continue
                if (candidate, RDF.type, OWL.Restriction) not in rdf_graph:
                    continue

                on_property = rdf_graph.value(candidate, OWL.onProperty)
                if on_property is None or not isinstance(on_property, URIRef):
                    log.warning(
                        "owl:Restriction on class %s missing owl:onProperty; skipping",
                        class_uri_str,
                    )
                    continue
                property_uri = str(on_property)

                row = _interpret_owl_restriction(
                    rdf_graph,
                    restriction_node=candidate,
                    class_uri=class_uri_str,
                    property_uri=property_uri,
                    attachment=attachment_name,
                )
                if row is not None:
                    out.append(row)

    return out


def _interpret_owl_restriction(
    rdf_graph: RDFGraph,
    *,
    restriction_node: BNode,
    class_uri: str,
    property_uri: str,
    attachment: str,
) -> dict[str, Any] | None:
    """Identify the restriction's kind and value.

    Returns ``None`` when no recognized restriction predicate is found
    or the value can't be coerced into the PR 1 wire type. Qualified
    cardinality is recognized but explicitly skipped (deferred).
    """
    # Qualified cardinality is structurally different (it pairs the
    # bound with an ``owl:onClass`` / ``owl:onDataRange`` scope) and
    # requires a wire-shape extension. Detect & warn rather than fall
    # through and emit a half-shaped row.
    for q_pred in _OWL_QUALIFIED_CARDINALITY_PREDICATES:
        if rdf_graph.value(restriction_node, q_pred) is not None:
            log.warning(
                "owl:Restriction on class %s property %s uses qualified cardinality "
                "(%s); deferred until PR adds qualified-cardinality support",
                class_uri,
                property_uri,
                q_pred,
            )
            return None

    for pred, rtype in _OWL_CARDINALITY_PREDICATES.items():
        raw = rdf_graph.value(restriction_node, pred)
        if raw is None:
            continue
        ivalue = _coerce_cardinality_int(raw)
        if ivalue is None:
            log.warning(
                "owl:Restriction on class %s property %s has %s with non-integer "
                "value %r; skipping",
                class_uri,
                property_uri,
                rtype,
                raw,
            )
            return None
        return {
            "class_uri": class_uri,
            "property_uri": property_uri,
            "restriction_type": rtype,
            "restriction_value": ivalue,
            "attachment": attachment,
            "source_node": str(restriction_node),
        }

    for pred, rtype in _OWL_VALUE_RESTRICTION_PREDICATES.items():
        raw = rdf_graph.value(restriction_node, pred)
        if raw is None:
            continue
        # ``owl:allValuesFrom`` / ``owl:someValuesFrom`` carry a class or
        # datatype URI; ``owl:hasValue`` carries an individual URI or a
        # literal. PR 1's wire shape stores the URI as a string and a
        # literal's lexical form as a string -- the rule engine + UI
        # disambiguate by ``restriction_type``.
        if isinstance(raw, URIRef):
            value: str = str(raw)
        elif isinstance(raw, Literal):
            value = str(raw)
        else:
            log.warning(
                "owl:Restriction on class %s property %s has %s pointing at a blank "
                "node (%r) -- nested class expressions are not yet supported; skipping",
                class_uri,
                property_uri,
                rtype,
                raw,
            )
            return None
        return {
            "class_uri": class_uri,
            "property_uri": property_uri,
            "restriction_type": rtype,
            "restriction_value": value,
            "attachment": attachment,
            "source_node": str(restriction_node),
        }

    log.warning(
        "owl:Restriction on class %s property %s has no recognized restriction "
        "predicate (expected one of: min/max/cardinality, all/someValuesFrom, hasValue); "
        "skipping",
        class_uri,
        property_uri,
    )
    return None


def _coerce_cardinality_int(raw: Any) -> int | None:
    """Pull an integer out of an rdflib cardinality literal.

    Tolerates::

        "1"^^xsd:nonNegativeInteger
        "1"^^xsd:integer
        "1"   (bare untyped literal)
        1     (python int)

    Returns ``None`` for anything else.
    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, Literal):
        try:
            value = raw.toPython()
        except Exception:
            value = None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        # Last-ditch: a literal whose datatype rdflib doesn't recognise
        # may still have a digit string in its lexical form.
        lex = str(raw).strip()
        if lex.isdigit():
            return int(lex)
    return None


def _resolve_class_ids(
    db: StandardDatabase,
    *,
    ontology_id: str,
    class_uris: list[str],
) -> dict[str, str]:
    """Return ``{class_uri: ontology_classes/<key>}`` for known classes.

    URIs that don't resolve to a live class in this ontology are simply
    omitted from the returned mapping; the caller logs and skips the
    corresponding restriction (an orphan-on-class row would never be
    matched by the rule engine).
    """
    if not class_uris or not db.has_collection("ontology_classes"):
        return {}
    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND c.uri IN @uris "
            "RETURN {uri: c.uri, id: c._id}",
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "uris": class_uris,
            },
        )
    )
    return {row["uri"]: row["id"] for row in rows if row.get("uri") and row.get("id")}


def _resolve_property_ids(
    db: StandardDatabase,
    *,
    ontology_id: str,
    property_uris: list[str],
) -> dict[str, str]:
    """Return ``{property_uri: ontology_<kind>_properties/<key>}``.

    Scans both ``ontology_object_properties`` and
    ``ontology_datatype_properties`` (PR 1's resolution pattern). When a
    URI lives in both -- which would mean the import produced a bug,
    not a valid OWL graph -- the object-property hit wins, matching
    the iteration order in ``_import_with_rdflib_fallback`` and PGT.
    """
    if not property_uris:
        return {}
    out: dict[str, str] = {}
    for col_name in ("ontology_object_properties", "ontology_datatype_properties"):
        if not db.has_collection(col_name):
            continue
        rows = list(
            run_aql(
                db,
                f"FOR p IN {col_name} "
                "FILTER p.ontology_id == @oid AND p.expired == @never "
                "  AND p.uri IN @uris "
                "RETURN {uri: p.uri, id: p._id}",
                bind_vars={
                    "oid": ontology_id,
                    "never": NEVER_EXPIRES,
                    "uris": property_uris,
                },
            )
        )
        for row in rows:
            uri = row.get("uri")
            pid = row.get("id")
            if uri and pid and uri not in out:
                out[uri] = pid
    return out


def _import_owl_restrictions(
    db: StandardDatabase,
    *,
    rdf_graph: RDFGraph,
    ontology_id: str,
    now: float | None = None,
) -> int:
    """Materialise OWL restrictions from ``rdf_graph`` into ``ontology_constraints``.

    Called from ``import_owl_to_graph`` AFTER the PGT (or rdflib
    fallback) import has placed classes + properties in the graph, so
    that ``on_class`` and ``property_id`` can be resolved to real
    Arango ``_id`` values. The row shape matches PR 1's extraction
    materializer exactly -- the rule engine + ``/library/{id}/constraints``
    API treat both rows identically -- with the addition of an
    ``import_source`` marker so provenance is recoverable.

    Returns the number of constraint rows successfully written.

    Failure modes (all non-fatal, all logged):

    * No ``owl:Restriction`` blank nodes in the graph        -> early return 0
    * Restriction missing ``owl:onProperty``                  -> skip 1 row
    * Restriction's cardinality has a non-int value           -> skip 1 row
    * Restriction's value pointer is a blank-node class expr  -> skip 1 row (deferred)
    * Qualified cardinality                                   -> skip 1 row (deferred)
    * Class URI not in ``ontology_classes`` for this ontology -> skip 1 row
    * Property URI not resolvable to a live property          -> persist with
                                                                ``property_id=null``,
                                                                matches PR 1's
                                                                resolver-miss path
    """
    raw_rows = _extract_owl_restrictions(rdf_graph)
    if not raw_rows:
        return 0

    if not db.has_collection("ontology_constraints"):
        # Defensive: ``_ensure_import_collections`` ran earlier for the
        # rdflib-fallback path, and PGT init-collections covers the rest,
        # but this importer can be invoked in tests with a minimal mock.
        db.create_collection("ontology_constraints")

    if now is None:
        now = time.time()

    class_id_map = _resolve_class_ids(
        db,
        ontology_id=ontology_id,
        class_uris=sorted({r["class_uri"] for r in raw_rows}),
    )
    property_id_map = _resolve_property_ids(
        db,
        ontology_id=ontology_id,
        property_uris=sorted({r["property_uri"] for r in raw_rows}),
    )

    constraint_col = db.collection("ontology_constraints")
    written = 0
    skipped_no_class = 0
    skipped_no_property = 0

    for row in raw_rows:
        class_uri = row["class_uri"]
        property_uri = row["property_uri"]
        class_id = class_id_map.get(class_uri)
        if class_id is None:
            # An orphan-on-class row would never be matched by the rule
            # engine (it joins on ``on_class``); skipping is the
            # honest move and matches the PR 1 contract that every
            # constraint references a known class.
            log.warning(
                "owl:Restriction targets class %s which is not in ontology %s "
                "after import; skipping constraint for property %s",
                class_uri,
                ontology_id,
                property_uri,
            )
            skipped_no_class += 1
            continue

        property_id = property_id_map.get(property_uri)
        if property_id is None:
            skipped_no_property += 1
            log.warning(
                "owl:Restriction on class %s references property %s which is not "
                "in ontology %s after import; persisting constraint with "
                "property_id=null so post-hoc repair can recover the link",
                class_uri,
                property_uri,
                ontology_id,
            )

        constraint_doc: dict[str, Any] = {
            "constraint_type": "owl:Restriction",
            "on_class": class_id,
            "property_id": property_id,
            "property_uri": property_uri,
            "restriction_type": row["restriction_type"],
            "restriction_value": row["restriction_value"],
            "description": (f"Imported from OWL ({row.get('attachment', 'subClassOf')})"),
            "ontology_id": ontology_id,
            "import_source": _IMPORT_SOURCE_OWL_RESTRICTION,
            # Imported axioms are explicit in the source file -- treat
            # the import as ground truth (1.0). Extraction-sourced rows
            # carry the LLM's own confidence on this same field.
            "confidence": 1.0,
            "evidence": [],
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            constraint_col.insert(constraint_doc)
            written += 1
        except Exception as exc:
            log.warning(
                "constraint insert failed for class %s property %s: %s",
                class_uri,
                property_uri,
                exc,
            )

    log.info(
        "owl restrictions imported",
        extra={
            "ontology_id": ontology_id,
            "written": written,
            "skipped_no_class": skipped_no_class,
            "skipped_no_property_resolution": skipped_no_property,
            "total_candidates": len(raw_rows),
        },
    )
    return written


def _ensure_import_collections(db: StandardDatabase) -> None:
    for name, edge in (
        ("ontology_classes", False),
        ("ontology_properties", False),
        ("ontology_object_properties", False),
        ("ontology_datatype_properties", False),
        ("ontology_constraints", False),
        ("subclass_of", True),
        ("has_property", True),
        ("equivalent_class", True),
        ("related_to", True),
        ("rdfs_domain", True),
        ("rdfs_range_class", True),
    ):
        if not db.has_collection(name):
            db.create_collection(name, edge=edge)


def _label_for(graph: RDFGraph, subject: URIRef) -> str:
    label = graph.value(subject, RDFS.label)
    if label:
        return str(label)
    return subject.split("#")[-1].split("/")[-1]


def _comment_for(graph: RDFGraph, subject: URIRef) -> str:
    comment = graph.value(subject, RDFS.comment)
    return str(comment) if comment else ""


def _import_with_rdflib_fallback(
    db: StandardDatabase,
    *,
    rdf_graph: RDFGraph,
    ontology_id: str,
) -> None:
    """Minimal OWL importer used when ``arango_rdf`` is unavailable.

    Writes ``owl:ObjectProperty`` instances to ``ontology_object_properties``
    and ``owl:DatatypeProperty`` instances to ``ontology_datatype_properties``.
    Creates ``rdfs_domain`` edges (property → domain class) and
    ``rdfs_range_class`` edges (object property → range class) per ADR-006.
    """
    _ensure_import_collections(db)

    class_ids: dict[str, str] = {}

    for class_uri in sorted({str(s) for s in rdf_graph.subjects(RDF.type, OWL.Class)}):
        doc = create_class(
            db,
            ontology_id=ontology_id,
            data={
                "uri": class_uri,
                "label": _label_for(rdf_graph, URIRef(class_uri)),
                "description": _comment_for(rdf_graph, URIRef(class_uri)),
                "status": "approved",
                "tier": "domain",
                "rdf_type": "owl:Class",
            },
            created_by="import",
        )
        class_ids[class_uri] = doc["_id"]

    prop_type_map: dict[str, tuple[str, str]] = {
        "object": ("ontology_object_properties", "owl:ObjectProperty"),
        "datatype": ("ontology_datatype_properties", "owl:DatatypeProperty"),
    }

    property_ids: dict[str, str] = {}
    property_meta: list[dict[str, Any]] = []

    for rdf_type, property_kind in (
        (OWL.ObjectProperty, "object"),
        (OWL.DatatypeProperty, "datatype"),
    ):
        target_col, rdf_type_label = prop_type_map[property_kind]
        for prop_uri in sorted({str(s) for s in rdf_graph.subjects(RDF.type, rdf_type)}):
            domain = rdf_graph.value(URIRef(prop_uri), RDFS.domain)
            range_value = rdf_graph.value(URIRef(prop_uri), RDFS.range)

            prop_data: dict[str, Any] = {
                "uri": prop_uri,
                "label": _label_for(rdf_graph, URIRef(prop_uri)),
                "description": _comment_for(rdf_graph, URIRef(prop_uri)),
                "property_type": property_kind,
                "rdf_type": rdf_type_label,
                "status": "approved",
            }
            if property_kind == "datatype" and range_value:
                prop_data["range_datatype"] = str(range_value)
            if range_value:
                prop_data["range"] = str(range_value)

            doc = create_property(
                db,
                ontology_id=ontology_id,
                data=prop_data,
                created_by="import",
                collection=target_col,
            )
            property_ids[prop_uri] = doc["_id"]
            property_meta.append(
                {
                    "uri": prop_uri,
                    "kind": property_kind,
                    "domain": str(domain) if domain else None,
                    "range": str(range_value) if range_value else None,
                }
            )

    for child, parent in rdf_graph.subject_objects(RDFS.subClassOf):
        child_id = class_ids.get(str(child))
        parent_id = class_ids.get(str(parent))
        if child_id and parent_id:
            create_edge(
                db,
                edge_collection="subclass_of",
                from_id=child_id,
                to_id=parent_id,
                data={"ontology_id": ontology_id},
            )

    for meta in property_meta:
        prop_id = property_ids.get(meta["uri"])
        domain_id = class_ids.get(meta["domain"] or "")
        if prop_id and domain_id:
            create_edge(
                db,
                edge_collection="rdfs_domain",
                from_id=prop_id,
                to_id=domain_id,
                data={"ontology_id": ontology_id},
            )
        if meta["kind"] == "object" and prop_id:
            range_id = class_ids.get(meta["range"] or "")
            if range_id:
                create_edge(
                    db,
                    edge_collection="rdfs_range_class",
                    from_id=prop_id,
                    to_id=range_id,
                    data={"ontology_id": ontology_id},
                )


def _tag_documents_with_ontology_id(
    db: StandardDatabase,
    *,
    ontology_id: str,
    ontology_uri_prefix: str | None,
    graph_name: str,
) -> int:
    """Tag all imported documents with ``ontology_id`` field.

    Queries documents that lack an ontology_id and match the graph's collections.
    """
    tagged = 0
    vertex_collections = [
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_constraints",
    ]

    for col_name in vertex_collections:
        if not db.has_collection(col_name):
            continue

        bind_vars: dict[str, Any] = {"@col": col_name, "oid": ontology_id}
        filter_clause = "FILTER doc.ontology_id == null OR doc.ontology_id == ''"

        if ontology_uri_prefix:
            filter_clause += " FILTER STARTS_WITH(doc.uri, @prefix)"
            bind_vars["prefix"] = ontology_uri_prefix

        query = f"""\
FOR doc IN @@col
  {filter_clause}
  UPDATE doc WITH {{ ontology_id: @oid }} IN @@col
  RETURN 1"""

        result = list(run_aql(db, query, bind_vars=bind_vars))
        tagged += len(result)

    log.info(
        "tagged documents with ontology_id",
        extra={"ontology_id": ontology_id, "tagged_count": tagged},
    )
    return tagged


def _ensure_named_graph(db: StandardDatabase, *, graph_name: str) -> None:
    """Create a per-ontology named graph if it doesn't exist."""
    full_name = f"ontology_{graph_name}" if not graph_name.startswith("ontology_") else graph_name

    if db.has_graph(full_name):
        return

    vertex_cols = [
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_constraints",
    ]
    edge_definitions = [
        {
            "edge_collection": "subclass_of",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "rdfs_domain",
            "from_vertex_collections": [
                "ontology_object_properties",
                "ontology_datatype_properties",
            ],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "rdfs_range_class",
            "from_vertex_collections": ["ontology_object_properties"],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "equivalent_class",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
        # Backward compat: include legacy edges if they exist
        {
            "edge_collection": "has_property",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_properties"],
        },
        {
            "edge_collection": "related_to",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
    ]

    cols = cast("list[dict[str, Any]]", db.collections())
    existing_cols = {c["name"] for c in cols if not c["system"]}
    edge_defs_to_use = [ed for ed in edge_definitions if ed["edge_collection"] in existing_cols]
    orphan_cols = [vc for vc in vertex_cols if vc in existing_cols]

    try:
        db.create_graph(
            full_name,
            edge_definitions=edge_defs_to_use,
            orphan_collections=orphan_cols,
        )
        log.info("named graph created", extra={"graph_name": full_name})
    except Exception:
        log.warning(
            "could not create named graph (may already exist)",
            extra={"graph_name": full_name},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Format detection helpers
# ---------------------------------------------------------------------------

_FORMAT_BY_EXTENSION: dict[str, str] = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".rdf": "xml",
    ".xml": "xml",
    ".owl": "xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
    ".n3": "n3",
    ".nt": "nt",
}


def _detect_format(filename: str) -> str:
    """Detect RDF serialization format from file extension."""
    suffix = PurePosixPath(filename).suffix.lower()
    fmt = _FORMAT_BY_EXTENSION.get(suffix)
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension '{suffix}'. "
            f"Supported: {', '.join(sorted(_FORMAT_BY_EXTENSION))}"
        )
    return fmt


def _sniff_format_from_content(text: str, hint: str) -> str:
    """Override the extension-based ``hint`` when content disagrees.

    The ``.owl`` extension is widely used as a generic "ontology file"
    label regardless of the actual serialization -- LLMs, ontology
    editors, and exporters routinely emit Turtle into a ``.owl`` file.
    Without this sniffer we hand Turtle text to the rdflib XML parser,
    which fails with an opaque ``Document is empty`` / ``not well-formed``
    XML error and the user has no way to know that the fix is "rename
    the file to .ttl".

    Strategy: skip BOM / leading whitespace / leading comments, then
    look for unambiguous opening tokens:

        ``@prefix`` / ``@base``  -> turtle
        ``<?xml`` / ``<rdf:RDF`` -> xml
        ``{`` with ``@context``  -> json-ld

    If no strong signal is found, return ``hint`` unchanged and let
    rdflib produce its own error. We do NOT try to be clever about
    ambiguous content (e.g. a bare XML element that *might* also be
    valid N-Triples) -- the goal is to fix the common .owl-contains-
    Turtle case without ever wrongly overriding a correct hint.
    """
    if not text:
        return hint

    stripped = text.lstrip("\ufeff").lstrip()
    # Skip leading Turtle-style comments so a file that starts with
    # "# Comment\n@prefix ..." still sniffs as turtle. Cap iterations
    # so a pathological all-comments file can't loop forever.
    for _ in range(64):
        if not stripped.startswith("#"):
            break
        nl = stripped.find("\n")
        if nl == -1:
            break
        stripped = stripped[nl + 1 :].lstrip()

    head = stripped[:2048]
    # XML signals (look at the very start -- comments before the XML
    # decl are syntactically invalid, so we don't accept them).
    if head.startswith("<?xml") or head.startswith("<rdf:RDF") or head.startswith("<RDF"):
        if hint != "xml":
            log.warning(
                "format hint overridden by content sniff",
                extra={"hint": hint, "sniffed": "xml"},
            )
        return "xml"

    # Turtle signals.
    if head.startswith("@prefix") or head.startswith("@base"):
        if hint != "turtle":
            log.warning(
                "format hint overridden by content sniff",
                extra={"hint": hint, "sniffed": "turtle"},
            )
        return "turtle"

    # JSON-LD signals: a JSON document with an @context key reasonably
    # near the front. The exact key may be quoted so allow either.
    if head.startswith("{") and ('"@context"' in head[:1024] or "'@context'" in head[:1024]):
        if hint != "json-ld":
            log.warning(
                "format hint overridden by content sniff",
                extra={"hint": hint, "sniffed": "json-ld"},
            )
        return "json-ld"

    return hint


def _human_title_from_filename(filename: str) -> str:
    stem = PurePosixPath(filename).stem
    if not stem:
        return ""
    return stem.replace("-", " ").replace("_", " ").strip().title()


def _owl_ontology_label_from_graph(g: RDFGraph) -> str | None:
    """First non-empty ``rdfs:label`` on any ``owl:Ontology`` resource, if present."""
    try:
        for _ont in g.subjects(RDF.type, OWL.Ontology):
            for label in g.objects(_ont, RDFS.label):
                s = str(label).strip()
                if s:
                    return s
    except Exception:
        log.debug("owl ontology label extraction failed", exc_info=True)
    return None


def _registry_display_name_for_file_import(
    *,
    filename: str,
    ontology_id: str,
    ontology_label: str | None,
    rdf_graph: RDFGraph,
) -> str:
    """Resolve a human-readable ontology name for the registry (matches extraction-style naming)."""
    if ontology_label and str(ontology_label).strip():
        return str(ontology_label).strip()
    from_graph = _owl_ontology_label_from_graph(rdf_graph)
    if from_graph:
        return from_graph
    titled = _human_title_from_filename(filename)
    if titled:
        return titled
    return ontology_id


# ---------------------------------------------------------------------------
# File / URL import (Week 20)
# ---------------------------------------------------------------------------


def import_from_file(
    file_content: bytes,
    filename: str,
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_label: str | None = None,
    ontology_uri_prefix: str | None = None,
) -> dict[str, Any]:
    """Import an OWL/TTL/RDF-XML/JSON-LD file into ArangoDB.

    1. Detect format from file extension
    2. Parse with rdflib to validate
    3. Import via PGT (``import_owl_to_graph``)
    4. Create an ``ontology_registry`` entry

    Returns:
        Dict with import stats and registry entry key.
    """
    if db is None:
        db = get_db()

    hint = _detect_format(filename)
    text = file_content.decode("utf-8")
    # Override the extension-based hint when the file's actual content
    # disagrees -- the .owl extension is routinely used as a generic
    # "ontology file" label even when the body is Turtle, and the
    # bare rdflib XML parser fails with an opaque "Document is empty"
    # error on Turtle input. The sniffer only fires on STRONG signals
    # (``@prefix`` / ``<?xml`` / ``{"@context"``) so a correct hint is
    # never overridden by ambiguous content.
    fmt = _sniff_format_from_content(text, hint)

    rdf_graph = RDFGraph()
    try:
        rdf_graph.parse(data=text, format=fmt)
    except Exception as exc:
        # Surface a diagnosis the user can act on. The common failure
        # mode is "extension says X but content is Y and Y didn't sniff
        # cleanly either" -- in that case suggest the likely format.
        suggestion = ""
        head_preview = text.lstrip("\ufeff").lstrip()[:120].replace("\n", " ")
        if fmt == "xml" and ("@prefix" in text[:512] or "@base" in text[:512]):
            suggestion = (
                " The file has a .owl/.xml extension but its content "
                "looks like Turtle (starts with '@prefix' or '@base'). "
                "Rename the file with a .ttl extension and re-upload."
            )
        elif fmt == "turtle" and ("<?xml" in text[:512] or "<rdf:RDF" in text[:512]):
            suggestion = (
                " The file has a .ttl extension but its content looks "
                "like RDF/XML. Rename the file with a .rdf or .owl "
                "extension and re-upload."
            )
        raise ValueError(
            f"Failed to parse {filename!r} as {fmt!r}: {exc}.{suggestion} "
            f"First bytes: {head_preview!r}"
        ) from exc

    triple_count = len(rdf_graph)
    if triple_count == 0:
        raise ValueError("Parsed file contains no RDF triples")

    ttl_content = rdf_graph.serialize(format="turtle")

    graph_name = ontology_id.replace("-", "_").replace(" ", "_")

    stats = import_owl_to_graph(
        db,
        ttl_content=ttl_content,
        graph_name=graph_name,
        ontology_id=ontology_id,
        ontology_uri_prefix=ontology_uri_prefix,
    )

    display_name = _registry_display_name_for_file_import(
        filename=filename,
        ontology_id=ontology_id,
        ontology_label=ontology_label,
        rdf_graph=rdf_graph,
    )

    registry_entry = create_registry_entry(
        {
            "_key": ontology_id,
            "name": display_name,
            "label": display_name,
            "description": f"Imported from {filename}",
            "tier": "local",
            "source": "file_import",
            "source_filename": filename,
            "format": fmt,
            "triple_count": triple_count,
            "graph_name": f"ontology_{graph_name}",
            "uri": ontology_uri_prefix or f"http://example.org/ontology/{ontology_id}",
        },
        db=db,
    )

    imports_sync = sync_owl_imports_edges(db, rdf_graph, ontology_id)

    log.info(
        "file import completed",
        extra={
            "ontology_id": ontology_id,
            "source_filename": filename,
            "format": fmt,
            "triple_count": triple_count,
            "registry_key": registry_entry["_key"],
            "imports_edges_created": imports_sync.get("created", 0),
        },
    )

    return {
        **stats,
        "source": "file_import",
        "filename": filename,
        "format": fmt,
        "registry_key": registry_entry["_key"],
        "imports_sync": imports_sync,
    }


def import_from_url(
    url: str,
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_label: str | None = None,
) -> dict[str, Any]:
    """Fetch an OWL/RDF file from a URL and import it.

    Determines format from the URL path extension, downloads the content,
    and delegates to ``import_from_file``.

    Returns:
        Dict with import stats and registry entry key.
    """
    if db is None:
        db = get_db()

    filename = PurePosixPath(urlparse(url).path).name
    if not filename:
        filename = "ontology.ttl"

    log.info("downloading ontology from URL", extra={"url": url, "ontology_id": ontology_id})

    response = httpx.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()

    result = import_from_file(
        file_content=response.content,
        filename=filename,
        ontology_id=ontology_id,
        db=db,
        ontology_label=ontology_label,
    )
    result["source"] = "url_import"
    result["source_url"] = url
    return result
