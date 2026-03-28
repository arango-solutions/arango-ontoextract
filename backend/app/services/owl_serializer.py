"""Converts ExtractionResult Pydantic models to OWL Turtle strings via rdflib."""

from __future__ import annotations

import logging

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from app.models.ontology import ExtractionResult

log = logging.getLogger(__name__)

_DEFAULT_NS = "http://example.org/ontology#"


def extraction_to_owl(
    result: ExtractionResult,
    *,
    ontology_uri: str | None = None,
    namespace: str | None = None,
) -> str:
    """Convert an ExtractionResult to an OWL Turtle string.

    Creates rdflib Graph with triples for each class (owl:Class, rdfs:subClassOf,
    rdfs:label, rdfs:comment) and each property (owl:ObjectProperty or
    owl:DatatypeProperty, rdfs:domain, rdfs:range).
    """
    ns = namespace or _DEFAULT_NS
    ont_uri = ontology_uri or ns.rstrip("#")
    ont_ns = Namespace(ns)

    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("xsd", XSD)
    g.bind("ont", ont_ns)

    ont_node = URIRef(ont_uri)
    g.add((ont_node, RDF.type, OWL.Ontology))
    g.add((ont_node, RDFS.label, Literal("Extracted Ontology")))

    for cls in result.classes:
        cls_uri = URIRef(cls.uri)
        g.add((cls_uri, RDF.type, OWL.Class))
        g.add((cls_uri, RDFS.label, Literal(cls.label)))
        g.add((cls_uri, RDFS.comment, Literal(cls.description)))

        if cls.parent_uri:
            g.add((cls_uri, RDFS.subClassOf, URIRef(cls.parent_uri)))

        for prop in cls.properties:
            prop_uri = URIRef(prop.uri)

            if prop.property_type == "object":
                g.add((prop_uri, RDF.type, OWL.ObjectProperty))
            else:
                g.add((prop_uri, RDF.type, OWL.DatatypeProperty))

            g.add((prop_uri, RDFS.label, Literal(prop.label)))
            g.add((prop_uri, RDFS.comment, Literal(prop.description)))
            g.add((prop_uri, RDFS.domain, cls_uri))

            range_ref = _resolve_range(prop.range)
            g.add((prop_uri, RDFS.range, range_ref))

    serialized = g.serialize(format="turtle")
    log.info(
        "OWL serialization complete",
        extra={
            "classes": len(result.classes),
            "triples": len(g),
        },
    )
    return serialized


def _resolve_range(range_str: str) -> URIRef:
    """Resolve a range string to a URIRef.

    Handles XSD datatypes (xsd:string, xsd:integer, etc.) and class URIs.
    """
    xsd_map = {
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
        "dateTime": XSD.dateTime,
        "xsd:dateTime": XSD.dateTime,
        "decimal": XSD.decimal,
        "xsd:decimal": XSD.decimal,
        "anyURI": XSD.anyURI,
        "xsd:anyURI": XSD.anyURI,
    }
    lower = range_str.lower().strip()
    if lower in xsd_map:
        return xsd_map[lower]
    return URIRef(range_str)
