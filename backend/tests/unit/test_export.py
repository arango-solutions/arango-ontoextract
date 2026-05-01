"""Unit tests for export service — mock DB, test Turtle/JSON-LD/CSV output."""

from __future__ import annotations

import csv
import io
import json
from unittest.mock import MagicMock, patch

from rdflib import OWL, RDF, RDFS, Graph, URIRef

_MOCK_CLASSES = [
    {
        "_key": "cls1",
        "uri": "http://example.org/test#Organization",
        "label": "Organization",
        "description": "A business entity",
        "status": "approved",
        "tier": "domain",
        "ontology_id": "test_ont",
    },
    {
        "_key": "cls2",
        "uri": "http://example.org/test#Department",
        "label": "Department",
        "description": "A subdivision",
        "status": "approved",
        "tier": "domain",
        "parent_uri": "http://example.org/test#Organization",
        "ontology_id": "test_ont",
    },
]

_MOCK_PROPERTIES = [
    {
        "_key": "prop1",
        "uri": "http://example.org/test#hasName",
        "label": "has name",
        "description": "Name of entity",
        "property_type": "datatype",
        "domain_class": "http://example.org/test#Organization",
        "range": "xsd:string",
        "status": "approved",
        "ontology_id": "test_ont",
    },
    {
        "_key": "prop2",
        "uri": "http://example.org/test#manages",
        "label": "manages",
        "description": "Management relationship",
        "property_type": "object",
        "domain_class": "http://example.org/test#Organization",
        "range": "http://example.org/test#Department",
        "status": "approved",
        "ontology_id": "test_ont",
    },
]

_MOCK_REGISTRY = {
    "_key": "test_ont",
    "label": "Test Ontology",
    "uri": "http://example.org/test",
    "status": "active",
}


def _mock_db():
    """Create a mock DB that returns empty edge results."""
    db = MagicMock()
    db.has_collection.return_value = True
    cursor_mock = MagicMock()
    cursor_mock.__iter__ = MagicMock(return_value=iter([]))
    db.aql.execute.return_value = cursor_mock
    return db


class TestExportOntology:
    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_turtle_produces_valid_rdf(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont", fmt="turtle")

        assert isinstance(ttl, str)
        assert len(ttl) > 0

        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_turtle_contains_owl_classes(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        org_uri = URIRef("http://example.org/test#Organization")
        dept_uri = URIRef("http://example.org/test#Department")

        assert (org_uri, RDF.type, OWL.Class) in g
        assert (dept_uri, RDF.type, OWL.Class) in g

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_turtle_contains_properties(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        has_name = URIRef("http://example.org/test#hasName")
        manages = URIRef("http://example.org/test#manages")

        assert (has_name, RDF.type, OWL.DatatypeProperty) in g
        assert (manages, RDF.type, OWL.ObjectProperty) in g

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_turtle_contains_ontology_declaration(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        assert (ont_uri, RDF.type, OWL.Ontology) in g

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_turtle_contains_labels_and_comments(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        org_uri = URIRef("http://example.org/test#Organization")
        labels = [str(lbl) for lbl in g.objects(org_uri, RDFS.label)]
        comments = [str(c) for c in g.objects(org_uri, RDFS.comment)]

        assert "Organization" in labels
        assert "A business entity" in comments

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_empty_ontology_produces_minimal_graph(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        assert len(g) >= 2  # ontology type + label


class TestExportJsonld:
    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_jsonld_returns_dict(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_jsonld

        result = export_jsonld("test_ont")

        assert isinstance(result, (dict, list))

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_jsonld_is_serializable(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_jsonld

        result = export_jsonld("test_ont")
        serialized = json.dumps(result)
        assert len(serialized) > 0

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_jsonld_roundtrips_through_rdflib(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_jsonld

        result = export_jsonld("test_ont")
        jsonld_str = json.dumps(result)

        g = Graph()
        g.parse(data=jsonld_str, format="json-ld")
        assert len(g) > 0


class TestExportCsv:
    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    def test_csv_contains_class_data(self, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_csv

        csv_content = export_csv("test_ont")

        assert "Organization" in csv_content
        assert "Department" in csv_content

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    def test_csv_contains_property_data(self, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_csv

        csv_content = export_csv("test_ont")

        assert "has name" in csv_content
        assert "manages" in csv_content

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    def test_csv_is_parseable(self, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_csv

        csv_content = export_csv("test_ont")
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) > 4  # header rows + data rows

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    def test_csv_empty_ontology(self, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_csv

        csv_content = export_csv("test_ont")

        assert "# Classes" in csv_content
        assert "# Properties" in csv_content

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=_MOCK_PROPERTIES)
    @patch("app.services.export.list_classes", return_value=_MOCK_CLASSES)
    def test_csv_has_correct_headers(self, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = _mock_db()
        from app.services.export import export_csv

        csv_content = export_csv("test_ont")
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        class_header = rows[1]
        assert "uri" in class_header
        assert "label" in class_header
        assert "description" in class_header
