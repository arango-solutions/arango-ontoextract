"""Export ontology graphs as OWL Turtle, JSON-LD, or CSV.

Queries current (non-expired) classes, properties, and edges from the database,
builds an rdflib Graph representing valid OWL 2, and serializes to the requested
format. All exports are temporal-aware: only current versions are included.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from app.config import settings
from app.db.client import get_db
from app.db.ontology_repo import list_classes, list_properties
from app.db.registry_repo import get_registry_entry
from app.services.temporal import NEVER_EXPIRES

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


def _build_rdf_graph(ontology_id: str) -> Graph:
    """Build an rdflib Graph from current DB state for the given ontology.

    Only exports entities whose ``expired == NEVER_EXPIRES`` (temporal-aware).
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

    log.info(
        "built RDF graph for export",
        extra={
            "ontology_id": ontology_id,
            "classes": len(classes),
            "properties": len(properties),
            "triples": len(g),
        },
    )
    return g


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


def export_jsonld(ontology_id: str) -> dict:
    """Export an ontology as JSON-LD.

    Returns:
        A JSON-LD dict with ``@context`` and ``@graph``.
    """
    g = _build_rdf_graph(ontology_id)
    jsonld_str = g.serialize(format="json-ld")
    result = json.loads(jsonld_str)
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
