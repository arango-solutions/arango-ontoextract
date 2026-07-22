"""Export ontology graphs as OWL Turtle, JSON-LD, CSV, or SHACL Turtle.

Queries current (non-expired) classes, properties, edges, and constraints
from the database, builds an rdflib Graph representing valid OWL 2 (plus a
parallel SHACL shapes graph), and serializes to the requested format. All
exports are temporal-aware: only current versions are included.

Stream 3 PR 5 adds:

* OWL ``owl:Restriction`` emission in the standard Turtle export -- pulls
  ``ontology_constraints`` rows whose ``constraint_type == "owl:Restriction"``
  (covers both PR 1 LLM-extracted rows and PR 2 OWL-imported rows; SHACL
  rows go to the SHACL export, not Turtle).
* ``export_shacl()`` -- a new exporter that emits a SHACL shapes graph
  from ``constraint_type IN ("sh:NodeShape", "sh:PropertyShape")`` rows.
  Grouped per target class as one ``sh:NodeShape`` with one
  ``sh:PropertyShape`` per property.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Any, cast

from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef

from app.config import settings
from app.db.client import get_db
from app.db.constraints_repo import list_constraints_for_ontology
from app.db.ontology_repo import list_classes, list_properties
from app.db.registry_repo import get_registry_entry
from app.services.temporal import NEVER_EXPIRES

SH = Namespace("http://www.w3.org/ns/shacl#")

log = logging.getLogger(__name__)

_XSD_MAP: dict[str, URIRef] = {
    "string": XSD.string,
    "xsd:string": XSD.string,
    "integer": XSD.integer,
    "xsd:integer": XSD.integer,
    "int": XSD.integer,
    "xsd:int": XSD.int,
    "float": XSD.float,
    "xsd:float": XSD.float,
    "double": XSD.double,
    "xsd:double": XSD.double,
    "boolean": XSD.boolean,
    "xsd:boolean": XSD.boolean,
    "date": XSD.date,
    "xsd:date": XSD.date,
    "datetime": XSD.dateTime,
    "xsd:dateTime": XSD.dateTime,
    "decimal": XSD.decimal,
    "xsd:decimal": XSD.decimal,
    "anyuri": XSD.anyURI,
    "xsd:anyURI": XSD.anyURI,
}


def _build_rdf_graph(ontology_id: str, *, include_individuals: bool = True) -> Graph:
    """Build an rdflib Graph from current DB state for the given ontology.

    Only exports entities whose ``expired == NEVER_EXPIRES`` (temporal-aware).
    When ``include_individuals`` (default), the A-box is emitted too:
    ``owl:NamedIndividual`` declarations with their ``rdf:type`` class and object
    assertions (AB-PR6). Ontologies with no A-box add zero triples.
    """
    db = get_db()

    registry = get_registry_entry(ontology_id, db=db)
    ontology_uri = settings.default_ontology_uri.rstrip("#") + "/" + ontology_id
    ontology_label = ontology_id
    if registry:
        ontology_uri = registry.get("uri", ontology_uri)
        ontology_label = registry.get("label", ontology_label)

    ns_str = ontology_uri.rstrip("/") + "#"
    ont_ns = Namespace(ns_str)

    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("xsd", XSD)
    g.bind("ont", ont_ns)

    ont_node = URIRef(ontology_uri)
    g.add((ont_node, RDF.type, OWL.Ontology))
    g.add((ont_node, RDFS.label, Literal(ontology_label)))

    # H.10 -- emit `owl:imports` triples for every live import edge.
    # Done BEFORE classes/properties so the import header sits at the
    # top of the Turtle serialization (consistent with how every
    # standards body publishes their ontology files).
    _add_imports_to_graph(db, g, ont_node, ontology_id)

    classes = list_classes(db, ontology_id=ontology_id, include_expired=False)
    for cls in classes:
        cls_uri = URIRef(cls["uri"])
        g.add((cls_uri, RDF.type, OWL.Class))
        if cls.get("label"):
            g.add((cls_uri, RDFS.label, Literal(cls["label"])))
        if cls.get("description"):
            g.add((cls_uri, RDFS.comment, Literal(cls["description"])))

    properties = list_properties(db, ontology_id=ontology_id)
    for prop in properties:
        prop_uri = URIRef(prop["uri"])
        ptype = prop.get("property_type", "datatype")
        if ptype == "object":
            g.add((prop_uri, RDF.type, OWL.ObjectProperty))
        else:
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))

        if prop.get("label"):
            g.add((prop_uri, RDFS.label, Literal(prop["label"])))
        if prop.get("description"):
            g.add((prop_uri, RDFS.comment, Literal(prop["description"])))
        if prop.get("domain_class"):
            g.add((prop_uri, RDFS.domain, URIRef(prop["domain_class"])))
        if prop.get("range"):
            g.add((prop_uri, RDFS.range, _resolve_range(prop["range"])))

    _add_edges_to_graph(db, g, ontology_id)

    # Stream 3 PR 5 -- emit owl:Restriction blank nodes for every
    # OWL-typed constraint row. SHACL rows are intentionally excluded;
    # they belong in the SHACL shapes graph (export_shacl), not in
    # the OWL document.
    # ``_id`` is the join key constraints store in ``on_class`` /
    # ``property_id``. Some legacy / mocked rows omit it; we filter
    # so the dict comp doesn't crash on them. Such rows simply won't
    # match any constraint join and are quietly dropped from the
    # restriction lookup (constraints without a target class were
    # already a no-op before this PR).
    class_id_to_uri = {
        cls["_id"]: URIRef(cls["uri"]) for cls in classes if cls.get("uri") and cls.get("_id")
    }
    property_id_to_uri = {
        p["_id"]: URIRef(p["uri"]) for p in properties if p.get("uri") and p.get("_id")
    }
    restrictions_emitted = _add_owl_restrictions_to_graph(
        db,
        g,
        ontology_id=ontology_id,
        class_id_to_uri=class_id_to_uri,
        property_id_to_uri=property_id_to_uri,
    )

    individuals_emitted = 0
    if include_individuals:
        prop_label_to_uri = {
            str(p["label"]).lower(): URIRef(p["uri"])
            for p in properties
            if p.get("uri") and p.get("label")
        }
        individuals_emitted = _add_individuals_to_graph(
            db,
            g,
            ontology_id=ontology_id,
            ns=ont_ns,
            class_id_to_uri=class_id_to_uri,
            prop_label_to_uri=prop_label_to_uri,
        )

    log.info(
        "built RDF graph for export",
        extra={
            "ontology_id": ontology_id,
            "classes": len(classes),
            "properties": len(properties),
            "restrictions_emitted": restrictions_emitted,
            "individuals_emitted": individuals_emitted,
            "triples": len(g),
        },
    )
    return g


def _slug(text: str) -> str:
    """Namespace-safe local name for a minted individual/predicate IRI."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_")
    return cleaned or "x"


def _add_individuals_to_graph(
    db: Any,
    g: Graph,
    *,
    ontology_id: str,
    ns: Namespace,
    class_id_to_uri: dict[str, URIRef],
    prop_label_to_uri: dict[str, URIRef],
) -> int:
    """Emit the A-box: ``owl:NamedIndividual`` + ``rdf:type`` + object assertions.

    Returns the count of individuals emitted. Assertions are emitted only when
    both endpoints are individuals of this ontology; a cross-ontology (AB-PR4
    ``cross_domain``) object lives in another file and is skipped here (logged),
    since a single-ontology document should not declare foreign individuals.
    """
    if not db.has_collection("ontology_individuals"):
        return 0

    rows = list(
        db.aql.execute(
            """\
FOR i IN ontology_individuals
  FILTER i.ontology_id == @oid AND i.expired == @never
  LET type_id = FIRST(
    FOR e IN rdf_type
      FILTER e._from == i._id AND e.expired == @never
      RETURN e._to
  )
  RETURN { id: i._id, key: i._key, label: i.label, uri: i.uri, type_id: type_id }""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )

    id_to_uri: dict[str, URIRef] = {}
    for r in rows:
        ind_uri = URIRef(r["uri"]) if r.get("uri") else ns[f"individual_{_slug(str(r['key']))}"]
        id_to_uri[str(r["id"])] = ind_uri
        g.add((ind_uri, RDF.type, OWL.NamedIndividual))
        if r.get("label"):
            g.add((ind_uri, RDFS.label, Literal(r["label"])))
        cls_uri = class_id_to_uri.get(str(r.get("type_id")))
        if cls_uri is not None:
            g.add((ind_uri, RDF.type, cls_uri))

    if not db.has_collection("individual_assertion"):
        return len(id_to_uri)

    skipped_cross = 0
    for a in db.aql.execute(
        """\
FOR e IN individual_assertion
  FILTER e.ontology_id == @oid AND e.expired == @never
  RETURN { from: e._from, to: e._to, predicate: e.predicate }""",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ):
        subj = id_to_uri.get(str(a.get("from")))
        obj = id_to_uri.get(str(a.get("to")))
        predicate = str(a.get("predicate") or "").strip()
        if subj is None or not predicate:
            continue
        if obj is None:
            skipped_cross += 1  # cross-ontology object, declared in another file
            continue
        pred_uri = prop_label_to_uri.get(predicate.lower()) or ns[_slug(predicate)]
        g.add((subj, pred_uri, obj))

    if skipped_cross:
        log.info(
            "A-box export skipped cross-ontology assertions",
            extra={"ontology_id": ontology_id, "skipped": skipped_cross},
        )
    return len(id_to_uri)


def _add_imports_to_graph(
    db: Any,
    g: Graph,
    ont_node: URIRef,
    ontology_id: str,
) -> None:
    """Emit one ``owl:imports`` triple per live ``imports`` edge (Stream 1 H.10).

    The target URI comes from the target ontology's ``ontology_registry``
    entry. If the target entry has no ``uri`` (older entries can predate
    the URI requirement), we fall back to ``import_iri`` recorded on the
    edge by ``sync_owl_imports_edges``; if neither is present the edge
    is silently skipped rather than emitting a broken triple. The
    skipped count is logged so operators can audit a stale registry
    after the fact.
    """
    if not db.has_collection("imports"):
        return

    rows = list(
        db.aql.execute(
            """
            FOR e IN imports
              FILTER e._from == @from_id
              FILTER e.expired == @never
              LET target = DOCUMENT(e._to)
              RETURN {
                target_uri: target.uri,
                import_iri: e.import_iri
              }
            """,
            bind_vars={
                "from_id": f"ontology_registry/{ontology_id}",
                "never": NEVER_EXPIRES,
            },
        )
    )

    emitted = 0
    skipped = 0
    for row in rows:
        target_uri = row.get("target_uri") or row.get("import_iri")
        if not target_uri:
            skipped += 1
            continue
        g.add((ont_node, OWL.imports, URIRef(str(target_uri))))
        emitted += 1

    if emitted or skipped:
        log.info(
            "emitted owl:imports triples",
            extra={
                "ontology_id": ontology_id,
                "imports_emitted": emitted,
                "imports_skipped": skipped,
            },
        )


def _add_edges_to_graph(db: Any, g: Graph, ontology_id: str) -> None:
    """Query edge collections and add relationship triples to the graph."""
    edge_mapping: dict[str, URIRef] = {
        "subclass_of": RDFS.subClassOf,
        "equivalent_class": OWL.equivalentClass,
    }

    for edge_col, predicate in edge_mapping.items():
        if not db.has_collection(edge_col):
            continue

        query = """\
FOR e IN @@col
  FILTER e.expired == @never
  LET from_doc = DOCUMENT(e._from)
  LET to_doc = DOCUMENT(e._to)
  FILTER from_doc != null AND to_doc != null
  FILTER from_doc.ontology_id == @oid OR to_doc.ontology_id == @oid
  RETURN { from_uri: from_doc.uri, to_uri: to_doc.uri }"""

        results = list(
            db.aql.execute(
                query,
                bind_vars={"@col": edge_col, "never": NEVER_EXPIRES, "oid": ontology_id},
            )
        )
        for edge in results:
            if edge.get("from_uri") and edge.get("to_uri"):
                g.add((URIRef(edge["from_uri"]), predicate, URIRef(edge["to_uri"])))


def _resolve_range(range_str: str) -> URIRef:
    """Resolve a range string to a URIRef — XSD datatypes or class URI."""
    lower = range_str.lower().strip()
    if lower in _XSD_MAP:
        return _XSD_MAP[lower]
    return URIRef(range_str)


# ---------------------------------------------------------------------------
# OWL restriction emission (Stream 3 PR 5)
# ---------------------------------------------------------------------------

# Mapping from our internal restriction_type token (matches
# RestrictionType in app.models.ontology) to the OWL predicate that
# carries the value on the restriction blank node.
_OWL_CARDINALITY_PREDICATE: dict[str, URIRef] = {
    "minCardinality": OWL.minCardinality,
    "maxCardinality": OWL.maxCardinality,
    "cardinality": OWL.cardinality,
}

_OWL_QUANTIFIED_PREDICATE: dict[str, URIRef] = {
    "allValuesFrom": OWL.allValuesFrom,
    "someValuesFrom": OWL.someValuesFrom,
}


def _add_owl_restrictions_to_graph(
    db: Any,
    g: Graph,
    *,
    ontology_id: str,
    class_id_to_uri: dict[str, URIRef],
    property_id_to_uri: dict[str, URIRef],
) -> int:
    """Emit `owl:Restriction` blank nodes for OWL-typed constraint rows.

    For each row from ``ontology_constraints`` where
    ``constraint_type == "owl:Restriction"``, materialises:

        <on_class_uri> rdfs:subClassOf [
            a owl:Restriction ;
            owl:onProperty <property_uri> ;
            <restriction_predicate> <restriction_value>
        ] .

    Rows whose ``on_class`` cannot be resolved to a known class URI
    (e.g. the class was deleted but the constraint row was orphaned)
    are skipped with a warning -- a dangling subClassOf would produce
    a syntactically valid but semantically broken Turtle document.

    Rows whose ``property_id`` is null (the LLM extractor or OWL
    importer couldn't resolve the property URI) are skipped with a
    warning rather than emitting a restriction with no ``owl:onProperty``.
    Such a triple would be malformed OWL.

    Returns the count of restriction blank nodes successfully emitted.
    """
    rows = list_constraints_for_ontology(
        db,
        ontology_id=ontology_id,
        constraint_type="owl:Restriction",
    )
    if not rows:
        return 0

    emitted = 0
    skipped_class = 0
    skipped_property = 0
    skipped_value = 0

    for row in rows:
        on_class_id = row.get("on_class")
        class_uri = class_id_to_uri.get(on_class_id or "")
        if class_uri is None:
            skipped_class += 1
            continue

        prop_id = row.get("property_id")
        prop_uri: URIRef | None = None
        if prop_id:
            prop_uri = property_id_to_uri.get(prop_id)
        if prop_uri is None:
            # Fall back on the raw property_uri stored on the row.
            # This keeps the export useful even when the importer
            # couldn't link the constraint to a known property -- the
            # output Turtle remains round-trip valid (the OWL parser
            # accepts any IRI as the value of owl:onProperty).
            raw_uri = row.get("property_uri")
            if raw_uri:
                prop_uri = URIRef(raw_uri)
        if prop_uri is None:
            skipped_property += 1
            continue

        rkind = row.get("restriction_type", "")
        rvalue = row.get("restriction_value")

        # Build the restriction body. We add ALL triples to a working
        # list first and only commit them if the value is well-formed,
        # so a half-emitted restriction never appears in the graph.
        restriction_predicate: URIRef | None = None
        restriction_object: URIRef | Literal | None = None

        if rkind in _OWL_CARDINALITY_PREDICATE:
            if not isinstance(rvalue, int) or isinstance(rvalue, bool) or rvalue < 0:
                # Cardinality MUST be xsd:nonNegativeInteger. A bool
                # would silently pass `isinstance(int)` so we filter
                # it explicitly; a negative integer is a contract bug
                # we'd rather surface than serialise.
                skipped_value += 1
                continue
            restriction_predicate = _OWL_CARDINALITY_PREDICATE[rkind]
            restriction_object = Literal(rvalue, datatype=XSD.nonNegativeInteger)

        elif rkind in _OWL_QUANTIFIED_PREDICATE:
            if not isinstance(rvalue, str) or not rvalue:
                skipped_value += 1
                continue
            restriction_predicate = _OWL_QUANTIFIED_PREDICATE[rkind]
            restriction_object = URIRef(rvalue)

        elif rkind == "hasValue":
            if rvalue is None:
                skipped_value += 1
                continue
            restriction_predicate = OWL.hasValue
            # owl:hasValue can be a literal OR an IRI individual. We
            # treat any string that parses as an http(s) IRI as a URI
            # reference (matching the typical OWL convention); other
            # strings become plain literals; numbers / booleans become
            # typed literals so a round-trip preserves the datatype.
            if isinstance(rvalue, str) and (
                rvalue.startswith("http://") or rvalue.startswith("https://")
            ):
                restriction_object = URIRef(rvalue)
            else:
                restriction_object = Literal(rvalue)
        else:
            # Unknown restriction kind -- skip with a warning rather
            # than emit a malformed restriction. Examples that could
            # land here in the future: qualified cardinality (PR 2
            # warn-skip), or any custom kind a future extraction prompt
            # decides to invent.
            skipped_value += 1
            continue

        r = BNode()
        g.add((r, RDF.type, OWL.Restriction))
        g.add((r, OWL.onProperty, prop_uri))
        g.add((r, restriction_predicate, restriction_object))
        g.add((class_uri, RDFS.subClassOf, r))
        emitted += 1

    if skipped_class or skipped_property or skipped_value:
        log.warning(
            "owl:Restriction emission skipped some constraint rows",
            extra={
                "ontology_id": ontology_id,
                "skipped_unresolved_class": skipped_class,
                "skipped_unresolved_property": skipped_property,
                "skipped_malformed_value": skipped_value,
                "emitted": emitted,
            },
        )

    return emitted


# ---------------------------------------------------------------------------
# SHACL shapes graph emission (Stream 3 PR 5)
# ---------------------------------------------------------------------------

# Map our stored SHACL ``restriction_type`` tokens to the predicate that
# carries the value on the property shape blank node.
_SHACL_VALUE_PREDICATE: dict[str, URIRef] = {
    "sh:minCount": SH.minCount,
    "sh:maxCount": SH.maxCount,
    "sh:datatype": SH.datatype,
    "sh:class": SH["class"],
    "sh:hasValue": SH.hasValue,
    "sh:pattern": SH.pattern,
    "sh:nodeKind": SH.nodeKind,
    "sh:in": SH["in"],
}

_SHACL_INTEGER_KINDS = {"sh:minCount", "sh:maxCount"}
_SHACL_URI_KINDS = {"sh:datatype", "sh:class", "sh:nodeKind"}


def _emit_shacl_value(g: Graph, shape: BNode, kind: str, value: Any) -> bool:
    """Add the value triple for one SHACL constraint to the property shape.

    Returns ``True`` if a triple was emitted; ``False`` to indicate the
    row should be skipped (malformed value for its kind). The caller
    is responsible for counting / logging the skip -- this keeps the
    helper pure and unit-testable.
    """
    predicate = _SHACL_VALUE_PREDICATE.get(kind)
    if predicate is None:
        return False

    if kind in _SHACL_INTEGER_KINDS:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
        g.add((shape, predicate, Literal(value, datatype=XSD.nonNegativeInteger)))
        return True

    if kind in _SHACL_URI_KINDS:
        if not isinstance(value, str) or not value:
            return False
        g.add((shape, predicate, URIRef(value)))
        return True

    if kind == "sh:hasValue":
        if value is None:
            return False
        if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            g.add((shape, predicate, URIRef(value)))
        else:
            g.add((shape, predicate, Literal(value)))
        return True

    if kind == "sh:pattern":
        if not isinstance(value, str) or not value:
            return False
        g.add((shape, predicate, Literal(value)))
        return True

    if kind == "sh:in":
        if not isinstance(value, list) or not value:
            return False
        # sh:in expects an RDF list. rdflib's Collection helper would
        # work but adds a dependency; for v1 we build the list inline
        # so the dependency surface stays exactly what _build_rdf_graph
        # already uses.
        from rdflib.collection import Collection

        node = BNode()
        Collection(g, node, [Literal(v) for v in value])
        g.add((shape, predicate, node))
        return True

    return False


def _build_shacl_graph(ontology_id: str) -> Graph:
    """Build a SHACL shapes graph for ``ontology_id`` (Stream 3 PR 5).

    Reads ``ontology_constraints`` rows with
    ``constraint_type IN ("sh:NodeShape", "sh:PropertyShape")`` and
    groups them by ``on_class``. Each class becomes one ``sh:NodeShape``
    with ``sh:targetClass`` set; each unique property under that class
    becomes one ``sh:PropertyShape`` (a blank node attached via
    ``sh:property``) carrying all of its SHACL constraints
    (``sh:minCount``, ``sh:datatype``, ``sh:pattern``, etc.).

    Severity (``sh:severity``) and message (``sh:message``) inherit
    from the original imported shape -- captured per row at PR 3
    import time. When multiple rows for the same property carry
    different severities (because a curator hand-mixed them later)
    we take the *first* non-empty severity / message and warn -- the
    SHACL spec doesn't allow per-constraint severity on a property
    shape, only per-shape.
    """
    db = get_db()

    registry = get_registry_entry(ontology_id, db=db)
    ontology_uri = settings.default_ontology_uri.rstrip("#") + "/" + ontology_id
    if registry:
        ontology_uri = registry.get("uri", ontology_uri)

    g = Graph()
    g.bind("sh", SH)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.bind("owl", OWL)

    # Header so a SHACL parser sees the shapes-graph as an ontology
    # of its own -- matches what the SHACL community publishes.
    ont_node = URIRef(ontology_uri.rstrip("#") + "/shapes")
    g.add((ont_node, RDF.type, OWL.Ontology))
    g.add((ont_node, RDFS.label, Literal(f"SHACL shapes for {ontology_id}")))

    rows = [
        row
        for row in list_constraints_for_ontology(db, ontology_id=ontology_id)
        if row.get("constraint_type") in {"sh:NodeShape", "sh:PropertyShape"}
    ]
    if not rows:
        log.info(
            "no SHACL constraints to export",
            extra={"ontology_id": ontology_id, "triples": len(g)},
        )
        return g

    classes = list_classes(db, ontology_id=ontology_id, include_expired=False)
    properties = list_properties(db, ontology_id=ontology_id)
    # See note in ``_build_rdf_graph`` -- same ``_id`` guard rule.
    class_id_to_uri = {
        cls["_id"]: URIRef(cls["uri"]) for cls in classes if cls.get("uri") and cls.get("_id")
    }
    property_id_to_uri = {
        p["_id"]: URIRef(p["uri"]) for p in properties if p.get("uri") and p.get("_id")
    }

    # Group: { class_uri -> { property_uri -> [constraint rows] } }
    grouped: dict[URIRef, dict[URIRef, list[dict[str, Any]]]] = {}
    skipped_class = 0
    skipped_property = 0

    for row in rows:
        class_uri = class_id_to_uri.get(row.get("on_class") or "")
        if class_uri is None:
            skipped_class += 1
            continue
        prop_uri: URIRef | None = None
        if row.get("property_id"):
            prop_uri = property_id_to_uri.get(row["property_id"])
        if prop_uri is None and row.get("property_uri"):
            prop_uri = URIRef(row["property_uri"])
        if prop_uri is None:
            skipped_property += 1
            continue
        grouped.setdefault(class_uri, {}).setdefault(prop_uri, []).append(row)

    shapes_emitted = 0
    properties_emitted = 0
    skipped_value = 0

    for class_uri, props in grouped.items():
        # One NodeShape per class. The shape IRI is derived from the
        # class URI with a "Shape" suffix; deterministic so re-export
        # produces stable IRIs (good for diff tooling and downstream
        # citation). When PR 3 captured the original shape_iri, future
        # work can prefer that over the synthetic IRI -- for v1 we
        # stay deterministic.
        shape_iri = URIRef(str(class_uri) + "Shape")
        g.add((shape_iri, RDF.type, SH.NodeShape))
        g.add((shape_iri, SH.targetClass, class_uri))
        shapes_emitted += 1

        for prop_uri, prop_rows in props.items():
            pshape = BNode()
            g.add((shape_iri, SH.property, pshape))
            g.add((pshape, SH.path, prop_uri))

            severity_iri: str | None = None
            message_text: str | None = None
            for r in prop_rows:
                ok = _emit_shacl_value(
                    g,
                    pshape,
                    r.get("restriction_type", ""),
                    r.get("restriction_value"),
                )
                if not ok:
                    skipped_value += 1
                if severity_iri is None and r.get("severity"):
                    severity_iri = r["severity"]
                if message_text is None and r.get("description"):
                    message_text = r["description"]

            if severity_iri:
                g.add((pshape, SH.severity, URIRef(severity_iri)))
            if message_text:
                g.add((pshape, SH.message, Literal(message_text)))
            properties_emitted += 1

    if skipped_class or skipped_property or skipped_value:
        log.warning(
            "SHACL export skipped some constraint rows",
            extra={
                "ontology_id": ontology_id,
                "skipped_unresolved_class": skipped_class,
                "skipped_unresolved_property": skipped_property,
                "skipped_malformed_value": skipped_value,
                "shapes_emitted": shapes_emitted,
                "properties_emitted": properties_emitted,
            },
        )

    log.info(
        "built SHACL shapes graph",
        extra={
            "ontology_id": ontology_id,
            "shapes_emitted": shapes_emitted,
            "properties_emitted": properties_emitted,
            "triples": len(g),
        },
    )
    return g


def export_shacl(ontology_id: str, fmt: str = "turtle") -> str:
    """Export the SHACL shapes graph for ``ontology_id`` (Stream 3 PR 5).

    Args:
        ontology_id: The registry ID of the ontology to export.
        fmt: rdflib serialization format (default ``turtle`` -- the
            canonical SHACL serialization).

    Returns:
        Serialized SHACL shapes graph. Empty-ish (header triples only)
        when the ontology has no SHACL constraints.
    """
    g = _build_shacl_graph(ontology_id)
    serialized = g.serialize(format=fmt)
    log.info(
        "exported SHACL shapes",
        extra={"ontology_id": ontology_id, "format": fmt, "triples": len(g)},
    )
    return serialized


def export_ontology(ontology_id: str, fmt: str = "turtle") -> str:
    """Export an ontology graph as valid OWL 2 Turtle (or other rdflib format).

    Args:
        ontology_id: The registry ID of the ontology to export.
        fmt: rdflib serialization format (``turtle``, ``xml``, ``n3``).

    Returns:
        Serialized ontology string.
    """
    g = _build_rdf_graph(ontology_id)
    serialized = g.serialize(format=fmt)
    log.info(
        "exported ontology",
        extra={"ontology_id": ontology_id, "format": fmt, "triples": len(g)},
    )
    return serialized


def export_jsonld(ontology_id: str) -> dict[str, Any]:
    """Export an ontology as JSON-LD.

    Returns:
        A JSON-LD dict with ``@context`` and ``@graph``.
    """
    g = _build_rdf_graph(ontology_id)
    jsonld_str = g.serialize(format="json-ld")
    result = cast(dict[str, Any], json.loads(jsonld_str))
    log.info(
        "exported ontology as JSON-LD",
        extra={"ontology_id": ontology_id, "triples": len(g)},
    )
    return result


def export_csv(ontology_id: str) -> str:
    """Export an ontology as CSV — two tables (classes + properties) separated by a blank line.

    Returns:
        CSV string with classes table followed by properties table.
    """
    db = get_db()
    classes = list_classes(db, ontology_id=ontology_id, include_expired=False)
    properties = list_properties(db, ontology_id=ontology_id)

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["# Classes"])
    writer.writerow(["uri", "label", "description", "parent_uri", "status", "tier"])
    for cls in classes:
        writer.writerow(
            [
                cls.get("uri", ""),
                cls.get("label", ""),
                cls.get("description", ""),
                cls.get("parent_uri", ""),
                cls.get("status", ""),
                cls.get("tier", ""),
            ]
        )

    writer.writerow([])

    writer.writerow(["# Properties"])
    writer.writerow(
        [
            "uri",
            "label",
            "description",
            "property_type",
            "domain_class",
            "range",
            "status",
        ]
    )
    for prop in properties:
        writer.writerow(
            [
                prop.get("uri", ""),
                prop.get("label", ""),
                prop.get("description", ""),
                prop.get("property_type", ""),
                prop.get("domain_class", ""),
                prop.get("range", ""),
                prop.get("status", ""),
            ]
        )

    log.info(
        "exported ontology as CSV",
        extra={
            "ontology_id": ontology_id,
            "classes": len(classes),
            "properties": len(properties),
        },
    )
    return buf.getvalue()
