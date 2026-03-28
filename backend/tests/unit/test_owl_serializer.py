"""Unit tests for OWL serializer — convert ExtractionResult → OWL TTL → verify triples."""

from __future__ import annotations

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from app.models.ontology import ExtractedClass, ExtractedProperty, ExtractionResult
from app.services.owl_serializer import extraction_to_owl


def _make_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        classes=[
            ExtractedClass(
                uri="http://example.org/test#Organization",
                label="Organization",
                description="A business entity",
                parent_uri=None,
                confidence=0.95,
                properties=[
                    ExtractedProperty(
                        uri="http://example.org/test#hasName",
                        label="has name",
                        description="The name of the organization",
                        property_type="datatype",
                        range="xsd:string",
                        confidence=0.9,
                    ),
                ],
            ),
            ExtractedClass(
                uri="http://example.org/test#Department",
                label="Department",
                description="A subdivision of an organization",
                parent_uri="http://example.org/test#Organization",
                confidence=0.90,
                properties=[
                    ExtractedProperty(
                        uri="http://example.org/test#hasBudget",
                        label="has budget",
                        description="The budget of the department",
                        property_type="datatype",
                        range="xsd:decimal",
                        confidence=0.85,
                    ),
                    ExtractedProperty(
                        uri="http://example.org/test#managedBy",
                        label="managed by",
                        description="The manager of the department",
                        property_type="object",
                        range="http://example.org/test#Person",
                        confidence=0.88,
                    ),
                ],
            ),
        ],
        pass_number=1,
        model="test-model",
    )


class TestExtractionToOwl:
    def test_produces_valid_turtle(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)

        assert isinstance(ttl, str)
        assert len(ttl) > 0

        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    def test_contains_owl_classes(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        org_uri = URIRef("http://example.org/test#Organization")
        dept_uri = URIRef("http://example.org/test#Department")

        assert (org_uri, RDF.type, OWL.Class) in g
        assert (dept_uri, RDF.type, OWL.Class) in g

    def test_contains_rdfs_labels(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        org_uri = URIRef("http://example.org/test#Organization")
        labels = list(g.objects(org_uri, RDFS.label))
        assert any(str(l) == "Organization" for l in labels)

    def test_contains_subclass_relationship(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        dept_uri = URIRef("http://example.org/test#Department")
        org_uri = URIRef("http://example.org/test#Organization")
        assert (dept_uri, RDFS.subClassOf, org_uri) in g

    def test_contains_datatype_property(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        has_name = URIRef("http://example.org/test#hasName")
        assert (has_name, RDF.type, OWL.DatatypeProperty) in g

    def test_contains_object_property(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        managed_by = URIRef("http://example.org/test#managedBy")
        assert (managed_by, RDF.type, OWL.ObjectProperty) in g

    def test_contains_domain_and_range(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        has_name = URIRef("http://example.org/test#hasName")
        org_uri = URIRef("http://example.org/test#Organization")

        assert (has_name, RDFS.domain, org_uri) in g
        ranges = list(g.objects(has_name, RDFS.range))
        assert len(ranges) > 0

    def test_contains_ontology_declaration(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(
            result,
            ontology_uri="http://example.org/test",
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        assert (ont_uri, RDF.type, OWL.Ontology) in g

    def test_roundtrip_parse_produces_expected_triple_count(self):
        result = _make_extraction_result()
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        # Ontology: 2 triples (type + label)
        # 2 classes: 2 * (type + label + comment) = 6, + 1 subClassOf = 7
        # 3 properties: 3 * (type + label + comment + domain + range) = 15
        # Total >= 24
        assert len(g) >= 20

    def test_empty_extraction_produces_minimal_graph(self):
        result = ExtractionResult(classes=[], pass_number=1, model="test")
        ttl = extraction_to_owl(result)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        assert len(g) >= 2  # Ontology type + label
