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


class TestExportOwlImports:
    """H.10 -- live `imports` edges must surface as `owl:imports` triples in exports.

    The exporter mocks the ``imports`` AQL query directly (via a dispatcher
    on ``db.aql.execute``) so we don't pull in the full bridge stack.
    """

    @staticmethod
    def _db_with_imports(rows: list[dict[str, str | None]]) -> MagicMock:
        """Mock DB whose ``imports`` query returns ``rows`` and whose
        other edge queries (subclass_of, equivalent_class) return empty.
        """
        db = MagicMock()
        db.has_collection.return_value = True

        def _execute(query: str, bind_vars: dict[str, object] | None = None):
            if "FOR e IN imports" in query:
                return iter(list(rows))
            return iter([])

        db.aql.execute.side_effect = _execute
        return db

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_imports_emitted_as_owl_imports(self, mock_reg, mock_cls, mock_props, mock_get_db):
        mock_get_db.return_value = self._db_with_imports(
            [
                {"target_uri": "http://xmlns.com/foaf/0.1/", "import_iri": None},
                {
                    "target_uri": "http://purl.org/dc/terms/",
                    "import_iri": "http://purl.org/dc/terms/",
                },
            ]
        )

        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        imports = {str(o) for o in g.objects(ont_uri, OWL.imports)}
        assert imports == {
            "http://xmlns.com/foaf/0.1/",
            "http://purl.org/dc/terms/",
        }

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_imports_fallback_to_import_iri_when_target_uri_missing(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        """Older registry rows can lack `uri`; the edge's own `import_iri`
        is used as a safety net before silently skipping."""
        mock_get_db.return_value = self._db_with_imports(
            [
                {"target_uri": None, "import_iri": "http://example.org/legacy"},
            ]
        )

        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        imports = list(g.objects(ont_uri, OWL.imports))
        assert imports == [URIRef("http://example.org/legacy")]

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_imports_skipped_when_no_uri_at_all(self, mock_reg, mock_cls, mock_props, mock_get_db):
        """If both target.uri and import_iri are missing, drop the edge
        rather than emit a malformed triple."""
        mock_get_db.return_value = self._db_with_imports([{"target_uri": None, "import_iri": None}])

        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        assert list(g.objects(ont_uri, OWL.imports)) == []

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_no_imports_emits_no_owl_imports_triples(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        mock_get_db.return_value = self._db_with_imports([])

        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        assert list(g.objects(ont_uri, OWL.imports)) == []

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_imports_query_filters_by_source_and_temporal_expiry(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        """Verify the AQL filters on both `_from = ontology_registry/{id}`
        and `expired == NEVER_EXPIRES`. A regression here would either
        leak imports from other ontologies or surface soft-deleted edges.
        """
        captured: list[tuple[str, dict[str, object]]] = []

        db = MagicMock()
        db.has_collection.return_value = True

        def _execute(query: str, bind_vars: dict[str, object] | None = None):
            captured.append((query, bind_vars or {}))
            return iter([])

        db.aql.execute.side_effect = _execute
        mock_get_db.return_value = db

        from app.services.export import export_ontology

        export_ontology("test_ont")

        imports_calls = [(q, b) for q, b in captured if "FOR e IN imports" in q]
        assert len(imports_calls) == 1, "imports must be queried exactly once"
        query, bind_vars = imports_calls[0]
        assert "e.expired == @never" in query
        assert "e._from == @from_id" in query
        assert bind_vars["from_id"] == "ontology_registry/test_ont"
        # NEVER_EXPIRES sentinel must be bound -- value is sys.maxsize.
        import sys

        assert bind_vars["never"] == sys.maxsize

    @patch("app.services.export.get_db")
    @patch("app.services.export.list_properties", return_value=[])
    @patch("app.services.export.list_classes", return_value=[])
    @patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY)
    def test_imports_skipped_when_collection_missing(
        self, mock_reg, mock_cls, mock_props, mock_get_db
    ):
        """Defensive: a fresh test DB without the `imports` collection
        should export cleanly rather than crash with `collection not
        found`. Mirrors the H.2 defensive guards.
        """
        db = MagicMock()
        db.has_collection.side_effect = lambda name: name != "imports"
        db.aql.execute.return_value = iter([])
        mock_get_db.return_value = db

        from app.services.export import export_ontology

        ttl = export_ontology("test_ont")
        g = Graph()
        g.parse(data=ttl, format="turtle")

        ont_uri = URIRef("http://example.org/test")
        assert list(g.objects(ont_uri, OWL.imports)) == []
        # AQL must not have been called for imports.
        assert all("FOR e IN imports" not in str(call.args) for call in db.aql.execute.mock_calls)


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
