"""Unit tests for export service — mock DB, test Turtle/JSON-LD/CSV output."""

from __future__ import annotations

import csv
import io
import json
from unittest.mock import MagicMock, patch

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef

SH = Namespace("http://www.w3.org/ns/shacl#")

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


# ===========================================================================
# Stream 3 PR 5 -- OWL restriction emission + SHACL shapes export
# ===========================================================================


_CLASSES_WITH_IDS = [
    {
        "_id": "ontology_classes/Customer",
        "_key": "Customer",
        "uri": "http://example.org/test#Customer",
        "label": "Customer",
        "description": "",
        "status": "approved",
        "ontology_id": "test_ont",
    }
]

_PROPS_WITH_IDS = [
    {
        "_id": "ontology_datatype_properties/customer_hasName",
        "_key": "customer_hasName",
        "uri": "http://example.org/test#hasName",
        "label": "has name",
        "property_type": "datatype",
        "range": "xsd:string",
        "status": "approved",
        "ontology_id": "test_ont",
    },
    {
        "_id": "ontology_object_properties/customer_hasFavoriteColor",
        "_key": "customer_hasFavoriteColor",
        "uri": "http://example.org/test#hasFavoriteColor",
        "label": "has favorite colour",
        "property_type": "object",
        "range": "http://example.org/test#Color",
        "status": "approved",
        "ontology_id": "test_ont",
    },
]


def _constraint(**overrides):
    """Build an ``ontology_constraints`` row with sensible defaults."""
    base = {
        "_key": "c1",
        "_id": "ontology_constraints/c1",
        "constraint_type": "owl:Restriction",
        "on_class": "ontology_classes/Customer",
        "property_id": "ontology_datatype_properties/customer_hasName",
        "property_uri": "http://example.org/test#hasName",
        "restriction_type": "minCardinality",
        "restriction_value": 1,
        "ontology_id": "test_ont",
    }
    base.update(overrides)
    return base


class TestOwlRestrictionEmission:
    """The Turtle export must emit one ``owl:Restriction`` blank node per
    OWL-typed constraint row, attached to the target class via
    ``rdfs:subClassOf``. The shape is the inverse of PR 2's import:
    a Turtle file produced by this exporter and re-imported via
    ``import_owl_to_graph`` should reproduce the same constraints in
    ``ontology_constraints`` (round-trip).
    """

    @staticmethod
    def _ttl_for_constraints(constraints, *, classes=None, properties=None):
        from app.services.export import export_ontology

        cls = classes if classes is not None else _CLASSES_WITH_IDS
        props = properties if properties is not None else _PROPS_WITH_IDS
        with (
            patch("app.services.export.get_db", return_value=_mock_db()),
            patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY),
            patch("app.services.export.list_classes", return_value=cls),
            patch("app.services.export.list_properties", return_value=props),
            patch(
                "app.services.export.list_constraints_for_ontology",
                return_value=constraints,
            ),
        ):
            return export_ontology("test_ont", fmt="turtle")

    def test_min_cardinality_emits_one_restriction(self):
        ttl = self._ttl_for_constraints([_constraint()])
        g = Graph()
        g.parse(data=ttl, format="turtle")

        from rdflib import OWL, RDF, RDFS, XSD, Literal, URIRef

        customer = URIRef("http://example.org/test#Customer")
        has_name = URIRef("http://example.org/test#hasName")

        # Exactly one subClassOf -> owl:Restriction blank node.
        restrictions = list(g.objects(customer, RDFS.subClassOf))
        assert len(restrictions) == 1
        r = restrictions[0]
        assert (r, RDF.type, OWL.Restriction) in g
        assert (r, OWL.onProperty, has_name) in g
        assert (r, OWL.minCardinality, Literal(1, datatype=XSD.nonNegativeInteger)) in g

    def test_min_and_max_emit_two_separate_restrictions(self):
        """One restriction per row -- mirrors PR 1's "one row per OWL
        bound" semantics and matches how every standards body publishes
        OWL files (min and max are independent axioms)."""
        ttl = self._ttl_for_constraints(
            [
                _constraint(_key="c1", restriction_type="minCardinality", restriction_value=1),
                _constraint(_key="c2", restriction_type="maxCardinality", restriction_value=5),
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")

        from rdflib import OWL, RDFS, URIRef

        customer = URIRef("http://example.org/test#Customer")
        rs = list(g.objects(customer, RDFS.subClassOf))
        assert len(rs) == 2
        preds = {p for r in rs for p in g.predicates(r, None)}
        assert OWL.minCardinality in preds
        assert OWL.maxCardinality in preds

    def test_exact_cardinality_emits_owl_cardinality(self):
        ttl = self._ttl_for_constraints(
            [_constraint(restriction_type="cardinality", restriction_value=3)]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, RDFS, URIRef

        customer = URIRef("http://example.org/test#Customer")
        r = next(iter(g.objects(customer, RDFS.subClassOf)))
        cards = list(g.objects(r, OWL.cardinality))
        assert len(cards) == 1
        assert int(cards[0]) == 3

    def test_all_values_from_emits_owl_all_values_from_iri(self):
        ttl = self._ttl_for_constraints(
            [
                _constraint(
                    property_id="ontology_object_properties/customer_hasFavoriteColor",
                    property_uri="http://example.org/test#hasFavoriteColor",
                    restriction_type="allValuesFrom",
                    restriction_value="http://example.org/test#Color",
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, URIRef

        color = URIRef("http://example.org/test#Color")
        assert (None, OWL.allValuesFrom, color) in g

    def test_some_values_from_emits_owl_some_values_from_iri(self):
        ttl = self._ttl_for_constraints(
            [
                _constraint(
                    property_id="ontology_object_properties/customer_hasFavoriteColor",
                    property_uri="http://example.org/test#hasFavoriteColor",
                    restriction_type="someValuesFrom",
                    restriction_value="http://example.org/test#Color",
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, URIRef

        assert (None, OWL.someValuesFrom, URIRef("http://example.org/test#Color")) in g

    def test_has_value_iri_emits_uri_object(self):
        ttl = self._ttl_for_constraints(
            [
                _constraint(
                    restriction_type="hasValue",
                    restriction_value="http://example.org/test#Red",
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, URIRef

        red = URIRef("http://example.org/test#Red")
        assert (None, OWL.hasValue, red) in g

    def test_has_value_literal_emits_literal_object(self):
        ttl = self._ttl_for_constraints(
            [_constraint(restriction_type="hasValue", restriction_value="Acme Corp")]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, Literal

        assert (None, OWL.hasValue, Literal("Acme Corp")) in g

    def test_unresolved_class_skipped_not_crashed(self):
        ttl = self._ttl_for_constraints([_constraint(on_class="ontology_classes/DoesNotExist")])
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL

        # Nothing emitted -- silent drop is fine because the warning
        # is logged. The point is the export doesn't crash and doesn't
        # produce a dangling subClassOf to a non-existent class.
        assert (None, None, OWL.Restriction) not in g

    def test_null_property_id_falls_back_to_property_uri(self):
        """PR 1/PR 2 may persist a constraint with ``property_id=null``
        when the LLM extractor or OWL importer couldn't resolve the
        URI. The exporter SHOULD still produce a valid restriction
        using the raw ``property_uri`` -- losing the constraint on
        export would be worse than the resolver miss it represents."""
        ttl = self._ttl_for_constraints(
            [_constraint(property_id=None, property_uri="http://example.org/test#hasName")]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, URIRef

        assert (None, OWL.onProperty, URIRef("http://example.org/test#hasName")) in g

    def test_negative_cardinality_skipped_not_emitted(self):
        ttl = self._ttl_for_constraints([_constraint(restriction_value=-1)])
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL

        assert (None, None, OWL.Restriction) not in g

    def test_shacl_typed_rows_excluded_from_owl_export(self):
        """Cross-vocabulary firewall: SHACL rows MUST NOT appear in the
        OWL Turtle export -- they belong in the SHACL shapes graph.
        Pinned because the constraint store mixes both, and a future
        refactor could accidentally widen the filter."""

        # The exporter only requests ``constraint_type="owl:Restriction"``
        # rows, so a SHACL-typed row passed here would only appear if
        # the call site changes. Simulate the bug-defense by patching
        # to return both kinds via constraint_type filter awareness.
        def _ret(*args, **kwargs):
            if kwargs.get("constraint_type") == "owl:Restriction":
                return []
            return [_constraint(constraint_type="sh:PropertyShape", restriction_type="sh:minCount")]

        from app.services.export import export_ontology

        with (
            patch("app.services.export.get_db", return_value=_mock_db()),
            patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY),
            patch("app.services.export.list_classes", return_value=_CLASSES_WITH_IDS),
            patch("app.services.export.list_properties", return_value=_PROPS_WITH_IDS),
            patch(
                "app.services.export.list_constraints_for_ontology",
                side_effect=_ret,
            ),
        ):
            ttl = export_ontology("test_ont", fmt="turtle")

        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL

        assert (None, None, OWL.Restriction) not in g

    def test_no_constraints_does_not_change_existing_classes_or_properties(self):
        """Empty constraint set must not alter the base ontology's
        classes / properties / declarations -- a pure no-op."""
        ttl = self._ttl_for_constraints([])
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import OWL, RDF, URIRef

        customer = URIRef("http://example.org/test#Customer")
        assert (customer, RDF.type, OWL.Class) in g
        assert (None, None, OWL.Restriction) not in g


class TestExportShacl:
    """``export_shacl`` builds the SHACL shapes graph from constraint
    rows whose ``constraint_type`` is ``"sh:NodeShape"`` /
    ``"sh:PropertyShape"``. Output is the standard SHACL Turtle a
    downstream validator (TopBraid / pyshacl) would consume."""

    @staticmethod
    def _ttl_for_shacl(constraints, *, classes=None, properties=None):
        from app.services.export import export_shacl

        cls = classes if classes is not None else _CLASSES_WITH_IDS
        props = properties if properties is not None else _PROPS_WITH_IDS

        # The repo helper filters by ontology_id and (when requested)
        # constraint_type. _build_shacl_graph calls it WITHOUT a
        # constraint_type filter and then filters in Python; mirror that.
        def _list(*args, **kwargs):
            if kwargs.get("constraint_type"):
                return [
                    c for c in constraints if c.get("constraint_type") == kwargs["constraint_type"]
                ]
            return constraints

        with (
            patch("app.services.export.get_db", return_value=_mock_db()),
            patch("app.services.export.get_registry_entry", return_value=_MOCK_REGISTRY),
            patch("app.services.export.list_classes", return_value=cls),
            patch("app.services.export.list_properties", return_value=props),
            patch(
                "app.services.export.list_constraints_for_ontology",
                side_effect=_list,
            ),
        ):
            return export_shacl("test_ont")

    def test_no_shacl_rows_produces_header_only_graph(self):
        ttl = self._ttl_for_shacl([])
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import URIRef

        assert (None, None, SH.NodeShape) not in g
        # Header ontology node IS present so the file is self-describing.
        ont_node = URIRef("http://example.org/test/shapes")
        from rdflib import OWL, RDF

        assert (ont_node, RDF.type, OWL.Ontology) in g

    def test_min_count_emits_node_shape_with_property_shape(self):
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:minCount",
                    restriction_value=1,
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import XSD, Literal, URIRef

        customer = URIRef("http://example.org/test#Customer")
        customer_shape = URIRef("http://example.org/test#CustomerShape")
        has_name = URIRef("http://example.org/test#hasName")

        assert (customer_shape, SH.targetClass, customer) in g
        # NodeShape declaration.
        from rdflib import RDF

        assert (customer_shape, RDF.type, SH.NodeShape) in g
        # PropertyShape bnode with sh:path -> hasName and sh:minCount 1.
        pshape = next(iter(g.objects(customer_shape, SH.property)))
        assert (pshape, SH.path, has_name) in g
        assert (pshape, SH.minCount, Literal(1, datatype=XSD.nonNegativeInteger)) in g

    def test_multiple_constraints_on_same_property_share_one_property_shape(self):
        """A property with sh:minCount AND sh:datatype must appear as
        ONE PropertyShape carrying BOTH triples -- not two separate
        PropertyShapes, which would obscure the intent in tooling."""
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    _key="c1",
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:minCount",
                    restriction_value=1,
                ),
                _constraint(
                    _key="c2",
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:datatype",
                    restriction_value="http://www.w3.org/2001/XMLSchema#string",
                ),
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import URIRef

        customer_shape = URIRef("http://example.org/test#CustomerShape")
        pshapes = list(g.objects(customer_shape, SH.property))
        assert len(pshapes) == 1
        ps = pshapes[0]
        # Both triples land on the same bnode.
        assert (ps, SH.minCount, None) in g
        assert (ps, SH.datatype, URIRef("http://www.w3.org/2001/XMLSchema#string")) in g

    def test_sh_in_emits_rdf_list(self):
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:in",
                    restriction_value=["S", "M", "L"],
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import URIRef
        from rdflib.collection import Collection

        customer_shape = URIRef("http://example.org/test#CustomerShape")
        ps = next(iter(g.objects(customer_shape, SH.property)))
        head = next(iter(g.objects(ps, SH["in"])))
        items = [str(it) for it in Collection(g, head)]
        assert items == ["S", "M", "L"]

    def test_severity_and_message_carry_to_property_shape(self):
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:minCount",
                    restriction_value=1,
                    severity="http://www.w3.org/ns/shacl#Warning",
                    description="Name is recommended.",
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import Literal, URIRef

        customer_shape = URIRef("http://example.org/test#CustomerShape")
        ps = next(iter(g.objects(customer_shape, SH.property)))
        assert (ps, SH.severity, URIRef("http://www.w3.org/ns/shacl#Warning")) in g
        assert (ps, SH.message, Literal("Name is recommended.")) in g

    def test_two_classes_produce_two_node_shapes(self):
        order_class = {
            "_id": "ontology_classes/Order",
            "_key": "Order",
            "uri": "http://example.org/test#Order",
            "label": "Order",
            "ontology_id": "test_ont",
        }
        order_prop = {
            "_id": "ontology_datatype_properties/order_amount",
            "_key": "order_amount",
            "uri": "http://example.org/test#amount",
            "label": "amount",
            "property_type": "datatype",
            "ontology_id": "test_ont",
        }
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:minCount",
                    restriction_value=1,
                ),
                _constraint(
                    _key="c2",
                    on_class="ontology_classes/Order",
                    property_id="ontology_datatype_properties/order_amount",
                    property_uri="http://example.org/test#amount",
                    constraint_type="sh:PropertyShape",
                    restriction_type="sh:minCount",
                    restriction_value=1,
                ),
            ],
            classes=[*_CLASSES_WITH_IDS, order_class],
            properties=[*_PROPS_WITH_IDS, order_prop],
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        from rdflib import URIRef

        assert (URIRef("http://example.org/test#CustomerShape"), SH.targetClass, None) in g
        assert (URIRef("http://example.org/test#OrderShape"), SH.targetClass, None) in g

    def test_owl_typed_rows_excluded_from_shacl_export(self):
        """The cross-vocabulary firewall in reverse: OWL rows MUST NOT
        leak into the SHACL graph. Pinned so a future filter loosening
        doesn't quietly produce a bogus shapes file."""
        ttl = self._ttl_for_shacl(
            [
                _constraint(
                    constraint_type="owl:Restriction",
                    restriction_type="minCardinality",
                    restriction_value=1,
                )
            ]
        )
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert (None, None, SH.NodeShape) not in g
