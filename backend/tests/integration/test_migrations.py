"""Integration tests for the database migration framework.

These tests require a running ArangoDB instance.  The ``test_db`` fixture
(from conftest.py) creates an ephemeral database for the session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from arango.database import StandardDatabase

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from migrations.runner import apply_all, discover_migrations  # noqa: E402

pytestmark = pytest.mark.integration

EXPECTED_DOCUMENT_COLLECTIONS = {
    "documents",
    "chunks",
    "extraction_runs",
    "curation_decisions",
    "notifications",
    "organizations",
    "users",
    "aoe_system_meta",
    "ontology_registry",
}

EXPECTED_VERSIONED_VERTEX_COLLECTIONS = {
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
}

EXPECTED_EDGE_COLLECTIONS = {
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
}


def test_apply_all_migrations_on_fresh_db(test_db: StandardDatabase) -> None:
    """All discovered migrations apply cleanly on a fresh database."""
    applied = apply_all(test_db)
    assert len(applied) == len(discover_migrations())

    existing = {c["name"] for c in test_db.collections() if not c["name"].startswith("_")}

    all_expected = (
        EXPECTED_DOCUMENT_COLLECTIONS
        | EXPECTED_VERSIONED_VERTEX_COLLECTIONS
        | EXPECTED_EDGE_COLLECTIONS
    )

    assert all_expected.issubset(existing), (
        f"Missing collections: {all_expected - existing}"
    )


def test_migrations_are_idempotent(test_db: StandardDatabase) -> None:
    """Running migrations twice produces no errors and applies nothing new."""
    first_run = apply_all(test_db)
    second_run = apply_all(test_db)

    assert len(second_run) == 0, f"Second run should apply nothing, got: {second_run}"
    assert len(first_run) >= 0


def test_mdi_index_exists(test_db: StandardDatabase) -> None:
    """Persistent (mdi-prefixed or fallback) index on ontology_classes [created, expired]."""
    apply_all(test_db)

    col = test_db.collection("ontology_classes")
    indexes = col.indexes()
    temporal_indexes = [
        idx for idx in indexes
        if idx.get("name", "").startswith("idx_ontology_classes_mdi_temporal")
    ]
    assert len(temporal_indexes) >= 1, (
        f"Expected temporal index on ontology_classes, found: "
        f"{[i.get('name') for i in indexes]}"
    )


def test_ttl_index_exists(test_db: StandardDatabase) -> None:
    """TTL index on ontology_classes.ttlExpireAt."""
    apply_all(test_db)

    col = test_db.collection("ontology_classes")
    indexes = col.indexes()
    ttl_indexes = [
        idx for idx in indexes
        if idx.get("name", "").startswith("idx_ontology_classes_ttl")
    ]
    assert len(ttl_indexes) >= 1, (
        f"Expected TTL index on ontology_classes, found: "
        f"{[i.get('name') for i in indexes]}"
    )


def test_named_graph_structure(test_db: StandardDatabase) -> None:
    """domain_ontology graph has correct edge definitions."""
    apply_all(test_db)

    assert test_db.has_graph("domain_ontology")
    graph = test_db.graph("domain_ontology")
    edge_defs = graph.edge_definitions()

    edge_names = {ed["edge_collection"] for ed in edge_defs}
    assert edge_names == {
        "subclass_of",
        "equivalent_class",
        "has_property",
        "related_to",
        "extracted_from",
    }

    for ed in edge_defs:
        if ed["edge_collection"] == "subclass_of":
            assert "ontology_classes" in ed["from_vertex_collections"]
            assert "ontology_classes" in ed["to_vertex_collections"]
        elif ed["edge_collection"] == "has_property":
            assert "ontology_classes" in ed["from_vertex_collections"]
            assert "ontology_properties" in ed["to_vertex_collections"]


def test_arangosearch_view(test_db: StandardDatabase) -> None:
    """ArangoSearch view on ontology_classes exists."""
    apply_all(test_db)

    view_names = {v["name"] for v in test_db.views()}
    assert "ontology_classes_search" in view_names, (
        f"Expected ontology_classes_search view, found: {view_names}"
    )
