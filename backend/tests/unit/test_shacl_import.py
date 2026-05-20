"""Unit tests for SHACL shapes import (Stream 3 PR 3).

Two layers under test:

1. ``_extract_shacl_property_constraints`` -- pure rdflib walking
   (no DB). One test per supported SHACL constraint kind, plus the
   warn-skip paths for deferred constructs (complex paths, combinators,
   target subjects/objects/node) and malformed input (non-int counts,
   bad rdf lists, missing path).
2. ``import_shacl_shapes`` -- full materialization with mocked
   ArangoDB. Pins the row shape, the severity inheritance, the
   ``import_source`` marker, and the failure modes (orphan class
   skipped, unresolved property persisted with ``property_id=null``).

Also exercises the bridge integration point so the import pipeline
surfaces ``shacl_constraints_imported`` in its returned stats.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rdflib import Graph as RDFGraph

from app.db.temporal_constants import NEVER_EXPIRES
from app.services.arangordf_bridge import import_owl_to_graph
from app.services.shacl_import import (
    _coerce_count_int,
    _extract_shacl_property_constraints,
    _read_rdf_list,
    import_shacl_shapes,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_PREFIXES = """\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://example.org/onto#> .
"""


def _parse(ttl: str) -> RDFGraph:
    g = RDFGraph()
    g.parse(data=ttl, format="turtle")
    return g


def _mock_db_with_constraint_col() -> tuple[MagicMock, MagicMock]:
    """Return ``(db, constraint_col)`` with every collection 'present'
    and ``db.collection("ontology_constraints")`` routed to the
    inspectable mock."""
    db = MagicMock()
    db.has_collection.return_value = True
    constraint_col = MagicMock()
    constraint_col.insert.return_value = {"_key": "auto"}

    def router(name):  # type: ignore[no-untyped-def]
        return constraint_col if name == "ontology_constraints" else MagicMock()

    db.collection.side_effect = router
    return db, constraint_col


# ---------------------------------------------------------------------------
# _extract_shacl_property_constraints -- pure walker
# ---------------------------------------------------------------------------


class TestExtractShaclPropertyConstraints:
    def test_node_shape_with_target_class_and_min_count(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert len(rows) == 1
        r = rows[0]
        assert r["class_uri"] == "http://example.org/onto#Customer"
        assert r["property_uri"] == "http://example.org/onto#email"
        assert r["restriction_type"] == "sh:minCount"
        assert r["restriction_value"] == 1
        # Default severity per SHACL spec.
        assert r["severity"] == "sh:Violation"
        assert r["shape_iri"] == "http://example.org/onto#CustomerShape"

    def test_min_and_max_count_produce_two_rows(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1 ;
                    sh:maxCount 3
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert sorted(r["restriction_type"] for r in rows) == ["sh:maxCount", "sh:minCount"]
        # Both rows reference the SAME (class, property), so the rule
        # engine will group them into one bound check.
        assert {(r["class_uri"], r["property_uri"]) for r in rows} == {
            ("http://example.org/onto#Customer", "http://example.org/onto#email")
        }

    def test_datatype_class_haspvalue_pattern_nodekind(self):
        ttl = (
            _PREFIXES
            + """
            :Address a owl:Class .
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:datatype xsd:string ;
                    sh:pattern "^[^@]+@[^@]+$"
                ] ;
                sh:property [
                    sh:path :address ;
                    sh:class :Address
                ] ;
                sh:property [
                    sh:path :status ;
                    sh:hasValue "Open"
                ] ;
                sh:property [
                    sh:path :id ;
                    sh:nodeKind sh:IRI
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        by_kind = {(r["property_uri"], r["restriction_type"]): r["restriction_value"] for r in rows}

        assert (
            by_kind[("http://example.org/onto#email", "sh:datatype")]
            == "http://www.w3.org/2001/XMLSchema#string"
        )
        assert by_kind[("http://example.org/onto#email", "sh:pattern")] == "^[^@]+@[^@]+$"
        assert (
            by_kind[("http://example.org/onto#address", "sh:class")]
            == "http://example.org/onto#Address"
        )
        assert by_kind[("http://example.org/onto#status", "sh:hasValue")] == "Open"
        assert (
            by_kind[("http://example.org/onto#id", "sh:nodeKind")]
            == "http://www.w3.org/ns/shacl#IRI"
        )

    def test_sh_in_enumeration(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :tier ;
                    sh:in ("gold" "silver" "bronze")
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "sh:in"
        # Order-insensitive: rdflib may walk the list in any consistent
        # order. The wire shape stores a list of strings.
        assert sorted(rows[0]["restriction_value"]) == ["bronze", "gold", "silver"]

    def test_implicit_class_target(self):
        """A shape that IS itself an owl:Class targets itself."""
        ttl = (
            _PREFIXES
            + """
            :Customer a owl:Class, sh:NodeShape ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["class_uri"] == "http://example.org/onto#Customer"

    def test_node_severity_inherited_by_property_shape(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:severity sh:Warning ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows[0]["severity"] == "sh:Warning"

    def test_property_severity_overrides_node_severity(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:severity sh:Warning ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1 ;
                    sh:severity sh:Info
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows[0]["severity"] == "sh:Info"

    def test_message_captured(self):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1 ;
                    sh:message "Customers must have at least one email."
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows[0]["message"] == "Customers must have at least one email."

    def test_anonymous_node_shape(self):
        """No IRI on the shape -- still walked, shape_iri == ''. Rare
        in real files but legal SHACL."""
        ttl = (
            _PREFIXES
            + """
            [ a sh:NodeShape ;
              sh:targetClass :Customer ;
              sh:property [
                  sh:path :email ;
                  sh:minCount 1
              ] ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["shape_iri"] == ""

    def test_shape_targeting_multiple_classes_produces_row_per_class(self):
        """A shape with sh:targetClass declared twice (rare but legal)
        should emit one constraint per (target, property, kind)."""
        ttl = (
            _PREFIXES
            + """
            :ContactShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:targetClass :Supplier ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )
        rows = _extract_shacl_property_constraints(_parse(ttl))
        classes = sorted(r["class_uri"] for r in rows)
        assert classes == [
            "http://example.org/onto#Customer",
            "http://example.org/onto#Supplier",
        ]

    # --- Deferred / malformed paths ---

    def test_complex_path_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path [ sh:inversePath :hasCustomer ] ;
                    sh:minCount 1
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []
        assert any("complex sh:path" in m for m in caplog.messages)

    def test_missing_sh_path_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:minCount 1
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []
        assert any("no sh:path" in m for m in caplog.messages)

    def test_combinator_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:or (
                        [ sh:datatype xsd:string ]
                        [ sh:datatype xsd:anyURI ]
                    )
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []
        assert any("combinators" in m.lower() for m in caplog.messages)

    def test_target_subjects_of_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :EmailShape a sh:NodeShape ;
                sh:targetSubjectsOf :email ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []
        assert any("targetSubjectsOf" in m for m in caplog.messages)

    def test_non_integer_count_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount "many"
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []
        assert any("non-integer value" in m for m in caplog.messages)

    def test_named_class_not_treated_as_shape_without_type(self):
        """A plain owl:Class without sh:NodeShape type and without any
        sh: predicates should NOT produce shape rows."""
        ttl = _PREFIXES + ":Plain a owl:Class .\n"
        rows = _extract_shacl_property_constraints(_parse(ttl))
        assert rows == []


# ---------------------------------------------------------------------------
# _coerce_count_int / _read_rdf_list
# ---------------------------------------------------------------------------


class TestCoerceCountInt:
    def test_python_int(self):
        assert _coerce_count_int(3) == 3

    def test_negative_rejected(self):
        # SHACL counts are non-negative; -1 means malformed input.
        assert _coerce_count_int(-1) is None

    def test_bool_rejected(self):
        assert _coerce_count_int(True) is None

    def test_typed_literal(self):
        from rdflib import XSD, Literal

        assert _coerce_count_int(Literal("5", datatype=XSD.nonNegativeInteger)) == 5

    def test_untyped_digit_literal(self):
        from rdflib import Literal

        assert _coerce_count_int(Literal("7")) == 7

    def test_non_numeric_literal_rejected(self):
        from rdflib import Literal

        assert _coerce_count_int(Literal("many")) is None


class TestReadRdfList:
    def test_well_formed_list(self):
        # Parse a TTL with a simple list and walk it via the helper.
        g = _parse(_PREFIXES + ':Holder :items ("a" "b" "c") .\n')
        head = g.value(
            subject=__import__("rdflib").URIRef("http://example.org/onto#Holder"),
            predicate=__import__("rdflib").URIRef("http://example.org/onto#items"),
        )
        assert head is not None
        assert _read_rdf_list(g, head) == ["a", "b", "c"]

    def test_empty_list(self):
        g = _parse(_PREFIXES + ":Holder :items () .\n")
        head = g.value(
            subject=__import__("rdflib").URIRef("http://example.org/onto#Holder"),
            predicate=__import__("rdflib").URIRef("http://example.org/onto#items"),
        )
        assert head is not None
        # An empty rdf list is rdf:nil; walker returns [].
        assert _read_rdf_list(g, head) == []

    def test_non_list_input_returns_none(self):
        from rdflib import Literal

        assert _read_rdf_list(RDFGraph(), Literal("not a list")) is None


# ---------------------------------------------------------------------------
# import_shacl_shapes -- full materialization with mocked DB
# ---------------------------------------------------------------------------


class TestImportShaclShapes:
    def test_no_shapes_returns_zero_and_writes_nothing(self):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(_PREFIXES + ":Plain a owl:Class .\n")

        written = import_shacl_shapes(db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0)

        assert written == 0
        constraint_col.insert.assert_not_called()

    def test_full_row_shape_matches_pr1_contract(self):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :email a owl:DatatypeProperty .
            :Customer a owl:Class .
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1 ;
                    sh:message "Customers must have email."
                ] .
            """
        )

        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Customer",
                        "id": "ontology_classes/Customer",
                    }
                ]
            ),
            iter([]),  # object property resolution
            iter(
                [
                    {
                        "uri": "http://example.org/onto#email",
                        "id": "ontology_datatype_properties/email",
                    }
                ]
            ),
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = import_shacl_shapes(db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1234.0)

        assert written == 1
        doc = constraint_col.insert.call_args[0][0]

        # PR 1 wire shape fields, with SHACL-specific values.
        assert doc["constraint_type"] == "sh:PropertyShape"
        assert doc["on_class"] == "ontology_classes/Customer"
        assert doc["property_id"] == "ontology_datatype_properties/email"
        assert doc["property_uri"] == "http://example.org/onto#email"
        assert doc["restriction_type"] == "sh:minCount"
        assert doc["restriction_value"] == 1
        assert doc["ontology_id"] == "onto_1"
        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] == 1234.0

        # PR 3-specific provenance + metadata.
        assert doc["import_source"] == "shacl_shape"
        assert doc["severity"] == "sh:Violation"
        assert doc["shape_iri"] == "http://example.org/onto#CustomerShape"
        # User-facing sh:message wins over the synthetic shape-iri default.
        assert doc["description"] == "Customers must have email."
        # Imported axioms are explicit -> 1.0 (matches PR 2 behaviour).
        assert doc["confidence"] == 1.0
        # PR 1 rows have extraction_run_id; SHACL rows MUST NOT, so the
        # source is unambiguous.
        assert "extraction_run_id" not in doc

    def test_unresolved_class_skipped_with_warning(self, caplog):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )

        with (
            patch(
                "app.services.arangordf_bridge.run_aql",
                side_effect=lambda *a, **k: iter([]),
            ),
            caplog.at_level("WARNING"),
        ):
            written = import_shacl_shapes(db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0)

        assert written == 0
        constraint_col.insert.assert_not_called()
        assert any("not in ontology" in m for m in caplog.messages)

    def test_unresolved_property_persisted_with_null_property_id(self):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :nonexistent ;
                    sh:minCount 1
                ] .
            """
        )

        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Customer",
                        "id": "ontology_classes/Customer",
                    }
                ]
            ),
            iter([]),  # object property miss
            iter([]),  # datatype property miss
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = import_shacl_shapes(db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0)

        assert written == 1
        doc = constraint_col.insert.call_args[0][0]
        assert doc["property_id"] is None
        assert doc["property_uri"] == "http://example.org/onto#nonexistent"
        assert doc["on_class"] == "ontology_classes/Customer"

    def test_synthetic_description_when_no_message(self):
        """Without sh:message, the description should fall back to the
        synthetic 'Imported from SHACL shape <iri>' string so curators
        always have something to read."""
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :CustomerShape a sh:NodeShape ;
                sh:targetClass :Customer ;
                sh:property [
                    sh:path :email ;
                    sh:minCount 1
                ] .
            """
        )

        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Customer",
                        "id": "ontology_classes/Customer",
                    }
                ]
            ),
            iter(
                [
                    {
                        "uri": "http://example.org/onto#email",
                        "id": "ontology_object_properties/email",
                    }
                ]
            ),
            iter([]),
        ]

        with patch(
            "app.services.arangordf_bridge.run_aql",
            side_effect=lambda *a, **k: responses.pop(0),
        ):
            import_shacl_shapes(db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0)

        doc = constraint_col.insert.call_args[0][0]
        expected = "Imported from SHACL shape http://example.org/onto#CustomerShape"
        assert expected in doc["description"]


# ---------------------------------------------------------------------------
# import_owl_to_graph integration -- shacl_constraints_imported in stats
# ---------------------------------------------------------------------------


class TestImportOwlToGraphSurfacesShaclCount:
    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.shacl_import.import_shacl_shapes")
    @patch("app.services.arangordf_bridge._import_owl_restrictions")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_stats_carries_shacl_constraints_imported(
        self,
        mock_ensure_rdf,
        mock_tag,
        mock_import_restrictions,
        mock_import_shacl,
        mock_ensure_graph,
    ):
        mock_ensure_rdf.return_value = MagicMock()
        mock_tag.return_value = 0
        mock_import_restrictions.return_value = 0
        mock_import_shacl.return_value = 7

        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://x> a owl:Class .
        """

        result = import_owl_to_graph(
            MagicMock(), ttl_content=ttl, graph_name="g", ontology_id="onto_1"
        )

        mock_import_shacl.assert_called_once()
        kwargs = mock_import_shacl.call_args.kwargs
        assert kwargs["ontology_id"] == "onto_1"
        assert "rdf_graph" in kwargs
        assert result["shacl_constraints_imported"] == 7
        # PR 2's count still surfaces too (separate field, no regression).
        assert result["restrictions_imported"] == 0
