"""Unit tests for app.services.relational_schema_extraction.

Covers the relational SQL-schema -> OWL/SHACL mapping (AOE owns the mapping,
consuming a ``PhysicalSchema`` from the relational-schema-analyzer library). The
pure builder needs no database; ``rdflib`` parses the emitted Turtle to assert the
ontology shape + provenance annotations.
"""

from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
rsa_types = pytest.importorskip("relational_schema_analyzer.types")

from rdflib import OWL, RDF, RDFS, Graph, Namespace  # noqa: E402

from app.services import relational_schema_extraction as rse  # noqa: E402
from app.services.relational_schema_extraction import (  # noqa: E402
    RelationalSchemaExtractionConfig,
    build_relational_owl,
    list_relational_tables,
)

SH = Namespace("http://www.w3.org/ns/shacl#")

Column = rsa_types.Column
ForeignKey = rsa_types.ForeignKey
Table = rsa_types.Table
PhysicalSchema = rsa_types.PhysicalSchema
CheckConstraint = rsa_types.CheckConstraint
SourceProvenance = rsa_types.SourceProvenance

NS = Namespace("http://aoe.example.org/schema/shop#")
AOE = Namespace("http://aoe.example.org/vocab#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")


def _physical():
    users = Table(
        name="users",
        columns=[
            Column(name="id", data_type="integer", is_primary_key=True, is_unique=True),
            Column(
                name="email",
                data_type="varchar",
                is_nullable=False,
                is_unique=True,
                comment="contact email",
            ),
            Column(name="status", data_type="varchar", is_nullable=True),
            Column(name="created_at", data_type="timestamp", is_nullable=True),
        ],
        primary_key=["id"],
        comment="people",
        check_constraints=[
            CheckConstraint(
                name="status_enum",
                expression="status IN ('active','inactive')",
                columns=["status"],
                enum_values=["active", "inactive"],
            ),
        ],
    )
    orders = Table(
        name="orders",
        columns=[
            Column(name="id", data_type="integer", is_primary_key=True, is_unique=True),
            Column(name="user_id", data_type="integer", is_nullable=False),
            Column(name="total", data_type="numeric", is_nullable=True),
        ],
        primary_key=["id"],
        foreign_keys=[ForeignKey(column="user_id", foreign_table="users", foreign_column="id")],
    )
    reviews = Table(
        name="active_reviews",
        columns=[Column(name="id", data_type="integer", is_primary_key=True, is_unique=True)],
        primary_key=["id"],
        is_view=True,
    )
    return PhysicalSchema(
        tables={t.name: t for t in (users, orders, reviews)},
        source=SourceProvenance(dialect="postgresql", server_version="16.1", database="shop"),
    )


@pytest.fixture
def graph_and_map():
    ttl, uri_to_table = build_relational_owl(_physical(), db_label="shop")
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g, uri_to_table


class TestClasses:
    def test_tables_become_classes(self, graph_and_map):
        g, _ = graph_and_map
        for t in ("users", "orders", "active_reviews"):
            assert (NS[t], RDF.type, OWL.Class) in g

    def test_class_provenance_annotations(self, graph_and_map):
        g, _ = graph_and_map
        assert (NS["users"], AOE.sourceDb, rdflib.Literal("shop")) in g
        assert (NS["users"], AOE.sourceCollection, rdflib.Literal("users")) in g

    def test_uri_to_table_map(self, graph_and_map):
        _, uri_to_table = graph_and_map
        assert uri_to_table[str(NS["users"])] == "users"
        assert uri_to_table[str(NS["orders"])] == "orders"


class TestDatatypeProperties:
    def test_columns_become_datatype_properties(self, graph_and_map):
        g, _ = graph_and_map
        email = NS["users.email"]
        assert (email, RDF.type, OWL.DatatypeProperty) in g
        assert (email, RDFS.domain, NS["users"]) in g
        assert (email, RDFS.range, XSD.string) in g

    def test_temporal_and_numeric_xsd(self, graph_and_map):
        g, _ = graph_and_map
        assert (NS["users.created_at"], RDFS.range, XSD.dateTime) in g
        assert (NS["orders.total"], RDFS.range, XSD.decimal) in g
        assert (NS["users.id"], RDFS.range, XSD.integer) in g

    def test_unique_column_is_functional(self, graph_and_map):
        g, _ = graph_and_map
        assert (NS["users.email"], RDF.type, OWL.FunctionalProperty) in g
        assert (NS["users.email"], RDF.type, OWL.InverseFunctionalProperty) in g


class TestObjectProperties:
    def test_foreign_key_becomes_object_property(self, graph_and_map):
        g, _ = graph_and_map
        obj = NS["orders_user_id_fk"]
        assert (obj, RDF.type, OWL.ObjectProperty) in g
        assert (obj, RDFS.domain, NS["orders"]) in g
        assert (obj, RDFS.range, NS["users"]) in g


class TestShacl:
    def test_not_null_becomes_min_count(self, graph_and_map):
        g, _ = graph_and_map
        shape = NS["usersShape"]
        assert (shape, RDF.type, SH.NodeShape) in g
        assert (shape, SH.targetClass, NS["users"]) in g
        assert NS["users.email"] in set(g.objects(None, SH.path))
        min_counts = {int(v) for v in g.objects(None, SH.minCount)}
        assert 1 in min_counts

    def test_enum_check_becomes_sh_in(self, graph_and_map):
        g, _ = graph_and_map
        in_lists = list(g.objects(None, SH["in"]))
        assert in_lists, "expected at least one sh:in list from the enum CHECK"
        values = set()
        for lst in in_lists:
            values |= {str(v) for v in rdflib.collection.Collection(g, lst)}
        assert {"active", "inactive"} <= values


def test_valid_turtle_and_counts():
    ttl, uri_to_table = build_relational_owl(_physical(), db_label="shop")
    g = Graph()
    g.parse(data=ttl, format="turtle")
    assert sum(1 for _ in g.subjects(RDF.type, OWL.Class)) == 3
    assert sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)) == 1
    assert len(uri_to_table) >= 3


class _FakeConnector:
    """Stand-in for a ``relational_schema_analyzer`` connector.

    Mirrors the real ``create_connector(...).get_schema()`` contract: the factory
    is called with ``(source_type, connection_string, schema_name=..., source_params=...)``
    and returns an object whose ``.get_schema()`` yields a ``PhysicalSchema``.
    """

    def __init__(self, physical):
        self._physical = physical
        self.calls: list[tuple] = []

    def __call__(self, source_type, connection_string, *, schema_name="public", source_params=None):
        self.calls.append((source_type, connection_string, schema_name, source_params))
        return self

    def get_schema(self):
        return self._physical


@pytest.fixture
def preview_config():
    return RelationalSchemaExtractionConfig(source_type="postgresql", url="postgresql://x/shop")


class TestListRelationalTables:
    def test_returns_table_topology(self, monkeypatch, preview_config):
        fake = _FakeConnector(_physical())
        monkeypatch.setattr(rse, "_try_import_relational_analyzer", lambda: fake)

        result = list_relational_tables(preview_config)

        assert result["source_type"] == "postgresql"
        assert result["db_label"] == "shop"
        assert result["dialect"] == "postgresql"
        assert result["server_version"] == "16.1"
        assert result["table_count"] == 3
        assert result["view_count"] == 1
        assert result["foreign_key_count"] == 1
        names = {t["name"] for t in result["tables"]}
        assert names == {"users", "orders", "active_reviews"}

    def test_column_and_fk_detail(self, monkeypatch, preview_config):
        fake = _FakeConnector(_physical())
        monkeypatch.setattr(rse, "_try_import_relational_analyzer", lambda: fake)

        result = list_relational_tables(preview_config)
        by_name = {t["name"]: t for t in result["tables"]}

        users = by_name["users"]
        assert users["is_view"] is False
        assert users["primary_key"] == ["id"]
        email = next(c for c in users["columns"] if c["name"] == "email")
        assert email["nullable"] is False
        assert email["unique"] is True

        orders = by_name["orders"]
        assert orders["foreign_keys"] == [
            {"columns": ["user_id"], "foreign_table": "users", "foreign_columns": ["id"]}
        ]
        assert by_name["active_reviews"]["is_view"] is True

    def test_never_echoes_credentials(self, monkeypatch):
        fake = _FakeConnector(_physical())
        monkeypatch.setattr(rse, "_try_import_relational_analyzer", lambda: fake)
        config = RelationalSchemaExtractionConfig(
            source_type="postgresql", url="postgresql://user:secret@host/shop"
        )

        result = list_relational_tables(config)

        assert "secret" not in str(result)
        # The connector still received the real DSN.
        assert fake.calls[0][1] == "postgresql://user:secret@host/shop"

    def test_missing_library_raises_runtimeerror(self, monkeypatch, preview_config):
        monkeypatch.setattr(rse, "_try_import_relational_analyzer", lambda: None)
        with pytest.raises(RuntimeError, match="relational-schema-analyzer is not installed"):
            list_relational_tables(preview_config)
