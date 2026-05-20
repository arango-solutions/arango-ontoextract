"""Unit tests for OWL restriction import (Stream 3 PR 2).

Two layers exercised here:

1. ``_extract_owl_restrictions`` -- pure rdflib walking; no DB. Pinned
   against the textbook ``rdfs:subClassOf [a owl:Restriction; ...]``
   pattern and the rarer ``owl:equivalentClass`` attachment.
2. ``_import_owl_restrictions`` -- full materialization with mocked
   ArangoDB. Verifies the row shape matches the PR 1 contract
   (``constraint_type="owl:Restriction"``, ``on_class`` as a full
   document id, ``property_id`` resolved or null, etc.).

We also pin the ``import_owl_to_graph`` integration point so the
returned stats dict carries ``restrictions_imported``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rdflib import Graph as RDFGraph

from app.db.temporal_constants import NEVER_EXPIRES
from app.services.arangordf_bridge import (
    _coerce_cardinality_int,
    _extract_owl_restrictions,
    _import_owl_restrictions,
    import_owl_to_graph,
)

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _parse(ttl: str) -> RDFGraph:
    g = RDFGraph()
    g.parse(data=ttl, format="turtle")
    return g


_PREFIXES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://example.org/onto#> .
"""


# ---------------------------------------------------------------------------
# _extract_owl_restrictions
# ---------------------------------------------------------------------------


class TestExtractOwlRestrictions:
    def test_subclass_of_min_cardinality(self):
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality "1"^^xsd:nonNegativeInteger
                ] .
            """
        )

        rows = _extract_owl_restrictions(_parse(ttl))

        assert len(rows) == 1
        row = rows[0]
        assert row["class_uri"] == "http://example.org/onto#Account"
        assert row["property_uri"] == "http://example.org/onto#holder"
        assert row["restriction_type"] == "minCardinality"
        assert row["restriction_value"] == 1
        assert row["attachment"] == "subClassOf"

    def test_min_and_max_emit_two_rows(self):
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] , [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:maxCardinality 5
                ] .
            """
        )

        rows = _extract_owl_restrictions(_parse(ttl))

        kinds = sorted(r["restriction_type"] for r in rows)
        assert kinds == ["maxCardinality", "minCardinality"]
        # Both row dicts must reference the SAME (class, property) pair --
        # this is exactly the input shape the rule engine groups on.
        assert {(r["class_uri"], r["property_uri"]) for r in rows} == {
            ("http://example.org/onto#Account", "http://example.org/onto#holder")
        }
        # Bare untyped literal "1" must coerce to int.
        values = sorted(int(r["restriction_value"]) for r in rows)
        assert values == [1, 5]

    def test_exact_cardinality(self):
        ttl = (
            _PREFIXES
            + """
            :id a owl:DatatypeProperty .
            :Customer a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :id ;
                    owl:cardinality 1
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "cardinality"
        assert rows[0]["restriction_value"] == 1

    def test_all_values_from_carries_target_class_uri(self):
        ttl = (
            _PREFIXES
            + """
            :nationality a owl:ObjectProperty .
            :Country a owl:Class .
            :Person a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :nationality ;
                    owl:allValuesFrom :Country
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "allValuesFrom"
        assert rows[0]["restriction_value"] == "http://example.org/onto#Country"

    def test_some_values_from_supported(self):
        ttl = (
            _PREFIXES
            + """
            :member a owl:ObjectProperty .
            :Club a owl:Class .
            :Person a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :member ;
                    owl:someValuesFrom :Club
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "someValuesFrom"
        assert rows[0]["restriction_value"] == "http://example.org/onto#Club"

    def test_has_value_literal(self):
        ttl = (
            _PREFIXES
            + """
            :status a owl:DatatypeProperty .
            :ActiveAccount a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :status ;
                    owl:hasValue "Open"
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "hasValue"
        assert rows[0]["restriction_value"] == "Open"

    def test_equivalent_class_attachment_also_walked(self):
        """A class *defined by* a restriction uses owl:equivalentClass, not
        rdfs:subClassOf."""
        ttl = (
            _PREFIXES
            + """
            :age a owl:DatatypeProperty .
            :HasAge a owl:Class ;
                owl:equivalentClass [
                    a owl:Restriction ;
                    owl:onProperty :age ;
                    owl:minCardinality 1
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["attachment"] == "equivalentClass"
        assert rows[0]["restriction_type"] == "minCardinality"

    def test_named_superclass_not_treated_as_restriction(self):
        """``rdfs:subClassOf :Animal`` is just a parent class, not a
        blank-node restriction. Must not produce a constraint row."""
        ttl = (
            _PREFIXES
            + """
            :Animal a owl:Class .
            :Dog a owl:Class ; rdfs:subClassOf :Animal .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []

    def test_qualified_cardinality_skipped_with_warning(self, caplog):
        """Qualified cardinality requires onClass/onDataRange scope and a
        wider wire shape -- deferred."""
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minQualifiedCardinality 1 ;
                    owl:onClass :Customer
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("qualified cardinality" in m.lower() for m in caplog.messages)

    def test_missing_on_property_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:minCardinality 1
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("owl:onProperty" in m for m in caplog.messages)

    def test_unrecognized_predicate_skipped_with_warning(self, caplog):
        """An owl:Restriction with no cardinality / value predicate at
        all -- e.g. only ``owl:onProperty`` -- is malformed."""
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("no recognized restriction predicate" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# _coerce_cardinality_int
# ---------------------------------------------------------------------------


class TestCoerceCardinalityInt:
    def test_python_int(self):
        assert _coerce_cardinality_int(3) == 3

    def test_python_bool_rejected(self):
        # Python's ``True == 1`` but a literal bool here would mean the
        # rdflib parse picked up an ``xsd:boolean`` -- never a valid
        # cardinality.
        assert _coerce_cardinality_int(True) is None

    def test_typed_literal(self):
        from rdflib import XSD, Literal

        assert _coerce_cardinality_int(Literal("5", datatype=XSD.nonNegativeInteger)) == 5

    def test_untyped_digit_literal(self):
        from rdflib import Literal

        assert _coerce_cardinality_int(Literal("7")) == 7

    def test_non_numeric_literal_rejected(self):
        from rdflib import Literal

        assert _coerce_cardinality_int(Literal("five")) is None

    def test_random_object_rejected(self):
        assert _coerce_cardinality_int(object()) is None


# ---------------------------------------------------------------------------
# _import_owl_restrictions -- full materialization with mocked DB
# ---------------------------------------------------------------------------


def _mock_db_with_constraint_col() -> tuple[MagicMock, MagicMock]:
    """Return ``(db, constraint_col)`` with the constraint collection
    auto-routed and ``has_collection`` True for everything."""
    db = MagicMock()
    db.has_collection.return_value = True
    constraint_col = MagicMock()
    constraint_col.insert.return_value = {"_key": "auto"}

    def collection_router(name):  # type: ignore[no-untyped-def]
        if name == "ontology_constraints":
            return constraint_col
        return MagicMock()

    db.collection.side_effect = collection_router
    return db, constraint_col


class TestImportOwlRestrictions:
    def test_no_restrictions_returns_zero_and_writes_nothing(self):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(_PREFIXES + ":Plain a owl:Class .\n")

        written = _import_owl_restrictions(
            db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1000.0
        )

        assert written == 0
        constraint_col.insert.assert_not_called()

    def test_full_row_shape_matches_pr1_contract(self):
        db, constraint_col = _mock_db_with_constraint_col()

        rdf_graph = _parse(
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] .
            """
        )

        # Two AQL passes: class id resolution, then property id resolution.
        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Account",
                        "id": "ontology_classes/Account",
                    }
                ]
            ),
            iter(
                [
                    {
                        "uri": "http://example.org/onto#holder",
                        "id": "ontology_object_properties/holder",
                    }
                ]
            ),
            # Datatype-property pass returns nothing (object props ran first).
            iter([]),
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = _import_owl_restrictions(
                db,
                rdf_graph=rdf_graph,
                ontology_id="onto_1",
                now=1234.0,
            )

        assert written == 1
        constraint_col.insert.assert_called_once()
        doc = constraint_col.insert.call_args[0][0]

        # PR 1 wire-shape contract -- these field names MUST match
        # ``app.services.extraction._materialize_to_graph``.
        assert doc["constraint_type"] == "owl:Restriction"
        assert doc["on_class"] == "ontology_classes/Account"
        assert doc["property_id"] == "ontology_object_properties/holder"
        assert doc["property_uri"] == "http://example.org/onto#holder"
        assert doc["restriction_type"] == "minCardinality"
        assert doc["restriction_value"] == 1
        assert doc["ontology_id"] == "onto_1"
        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] == 1234.0
        # PR 2-specific provenance marker so import rows are
        # distinguishable from extraction rows.
        assert doc["import_source"] == "owl_restriction"
        assert doc["confidence"] == 1.0
        # PR 1 rows have ``extraction_run_id``; import rows must NOT, so
        # the source is unambiguous.
        assert "extraction_run_id" not in doc

    def test_unresolved_class_skipped(self, caplog):
        """A restriction targeting a class that didn't make it into
        ``ontology_classes`` after import is dropped -- the rule engine
        joins on ``on_class``, so an orphan row would never fire."""
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] .
            """
        )

        # Empty class lookup, empty property lookups.
        with (
            patch(
                "app.services.arangordf_bridge.run_aql",
                side_effect=lambda *a, **k: iter([]),
            ),
            caplog.at_level("WARNING"),
        ):
            written = _import_owl_restrictions(
                db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0
            )

        assert written == 0
        constraint_col.insert.assert_not_called()
        assert any("not in ontology" in m for m in caplog.messages)

    def test_unresolved_property_persisted_with_null_property_id(self):
        """If the class resolves but the property doesn't, write the row
        with ``property_id=null`` so post-hoc repair can recover the
        link -- mirrors PR 1's resolver-miss path."""
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :nonexistent a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :nonexistent ;
                    owl:minCardinality 1
                ] .
            """
        )

        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Account",
                        "id": "ontology_classes/Account",
                    }
                ]
            ),
            iter([]),  # object property lookup miss
            iter([]),  # datatype property lookup miss
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = _import_owl_restrictions(
                db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0
            )

        assert written == 1
        doc = constraint_col.insert.call_args[0][0]
        assert doc["property_id"] is None
        assert doc["property_uri"] == "http://example.org/onto#nonexistent"
        assert doc["on_class"] == "ontology_classes/Account"


# ---------------------------------------------------------------------------
# import_owl_to_graph integration -- restrictions_imported in stats
# ---------------------------------------------------------------------------


class TestImportOwlToGraphReturnsRestrictionsCount:
    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._import_owl_restrictions")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_stats_carries_restrictions_imported(
        self,
        mock_ensure_rdf,
        mock_import_restrictions,
        mock_tag,
        mock_ensure_graph,
    ):
        mock_ensure_rdf.return_value = MagicMock()
        mock_tag.return_value = 0
        mock_import_restrictions.return_value = 3
        db = MagicMock()

        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://x> a owl:Class .
        """

        result = import_owl_to_graph(db, ttl_content=ttl, graph_name="g", ontology_id="onto_1")

        # The restriction hook runs once, with the parsed graph + the
        # active ontology id, and its return count surfaces verbatim in
        # the stats dict.
        mock_import_restrictions.assert_called_once()
        kwargs = mock_import_restrictions.call_args.kwargs
        assert kwargs["ontology_id"] == "onto_1"
        assert "rdf_graph" in kwargs
        assert result["restrictions_imported"] == 3
