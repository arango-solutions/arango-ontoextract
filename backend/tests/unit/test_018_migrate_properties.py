"""Unit tests for migration 018 — property migration to PGT-aligned collections."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_mod = importlib.import_module("migrations.018_migrate_properties")
up = _mod.up
NEVER_EXPIRES: int = _mod.NEVER_EXPIRES


def _make_db(
    collections: set[str],
    aql_results: dict[int, list] | None = None,
):
    """Build a mock DB with selective collection existence and AQL results."""
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name in collections

    col_mocks: dict[str, MagicMock] = {}
    for name in collections:
        col_mocks[name] = MagicMock(name=f"col_{name}")
    db.collection.side_effect = lambda name: col_mocks.get(name, MagicMock())
    db.create_collection.side_effect = lambda name, **kw: col_mocks.setdefault(name, MagicMock())

    _results = aql_results or {}
    _call_n = {"n": 0}

    def execute(query, bind_vars=None, **kwargs):
        key = _call_n["n"]
        _call_n["n"] += 1
        return iter(_results.get(key, []))

    db.aql.execute.side_effect = execute
    return db, col_mocks


class TestMigration018:
    """Tests for the property migration."""

    def test_skips_when_ontology_properties_missing(self):
        db, _ = _make_db(set())
        up(db)
        db.aql.execute.assert_not_called()

    def test_creates_missing_target_collections(self):
        db, _cols = _make_db(
            {"ontology_properties"},
            {0: [], 1: []},  # class_keys query, properties query
        )
        up(db)
        db.create_collection.assert_any_call("ontology_object_properties")
        db.create_collection.assert_any_call("ontology_datatype_properties")
        db.create_collection.assert_any_call("rdfs_domain", edge=True)
        db.create_collection.assert_any_call("rdfs_range_class", edge=True)

    def test_migrates_object_property_with_edges(self):
        obj_prop = {
            "_key": "holds",
            "uri": "http://example.org#holds",
            "label": "holds",
            "description": "Customer holds Account",
            "rdf_type": "owl:ObjectProperty",
            "domain_class": "Customer",
            "range": "Account",
            "ontology_id": "onto_1",
            "confidence": 0.9,
            "status": "approved",
            "created": 1000.0,
            "expired": NEVER_EXPIRES,
        }
        db, cols = _make_db(
            {
                "ontology_properties",
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "rdfs_domain",
                "rdfs_range_class",
            },
            {
                0: ["Customer", "Account"],  # class keys
                1: [obj_prop],  # properties
            },
        )
        up(db)

        obj_col = cols["ontology_object_properties"]
        obj_col.insert.assert_called_once()
        inserted = obj_col.insert.call_args
        assert inserted[0][0]["_key"] == "holds"
        assert inserted[1]["overwrite"] is True

        domain_col = cols["rdfs_domain"]
        domain_col.insert.assert_called_once()
        domain_edge = domain_col.insert.call_args[0][0]
        assert domain_edge["_from"] == "ontology_object_properties/holds"
        assert domain_edge["_to"] == "ontology_classes/Customer"

        range_col = cols["rdfs_range_class"]
        range_col.insert.assert_called_once()
        range_edge = range_col.insert.call_args[0][0]
        assert range_edge["_from"] == "ontology_object_properties/holds"
        assert range_edge["_to"] == "ontology_classes/Account"

    def test_migrates_datatype_property_with_domain_edge(self):
        dt_prop = {
            "_key": "customerName",
            "uri": "http://example.org#customerName",
            "label": "Customer Name",
            "description": "Name of customer",
            "rdf_type": "owl:DatatypeProperty",
            "domain_class": "Customer",
            "range": "xsd:string",
            "ontology_id": "onto_1",
            "confidence": 0.85,
            "status": None,
            "created": 1000.0,
            "expired": NEVER_EXPIRES,
        }
        db, cols = _make_db(
            {
                "ontology_properties",
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "rdfs_domain",
                "rdfs_range_class",
            },
            {
                0: ["Customer"],  # class keys
                1: [dt_prop],  # properties
            },
        )
        up(db)

        dt_col = cols["ontology_datatype_properties"]
        dt_col.insert.assert_called_once()
        inserted = dt_col.insert.call_args[0][0]
        assert inserted["_key"] == "customerName"
        assert inserted["range_datatype"] == "xsd:string"
        assert dt_col.insert.call_args[1]["overwrite"] is True

        domain_col = cols["rdfs_domain"]
        domain_col.insert.assert_called_once()
        edge = domain_col.insert.call_args[0][0]
        assert edge["_from"] == "ontology_datatype_properties/customerName"
        assert edge["_to"] == "ontology_classes/Customer"

        cols["rdfs_range_class"].insert.assert_not_called()

    def test_range_class_skipped_when_not_in_classes(self):
        """Object property whose range does not match a known class key."""
        obj_prop = {
            "_key": "refersTo",
            "uri": "http://example.org#refersTo",
            "label": "refers to",
            "description": "",
            "rdf_type": "owl:ObjectProperty",
            "domain_class": "Document",
            "range": "ExternalEntity",
            "ontology_id": "onto_1",
            "confidence": 0.7,
            "status": None,
            "created": 1000.0,
            "expired": NEVER_EXPIRES,
        }
        db, cols = _make_db(
            {
                "ontology_properties",
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "rdfs_domain",
                "rdfs_range_class",
            },
            {
                0: ["Document"],  # class keys — ExternalEntity NOT present
                1: [obj_prop],
            },
        )
        up(db)

        cols["ontology_object_properties"].insert.assert_called_once()
        cols["rdfs_domain"].insert.assert_called_once()
        cols["rdfs_range_class"].insert.assert_not_called()

    def test_idempotent_with_overwrite(self):
        """Running twice with overwrite=True should not raise."""
        dt_prop = {
            "_key": "age",
            "uri": "http://example.org#age",
            "label": "age",
            "description": "",
            "rdf_type": "owl:DatatypeProperty",
            "domain_class": "Person",
            "range": "xsd:integer",
            "ontology_id": "onto_1",
            "confidence": 0.5,
            "status": None,
            "created": 1000.0,
            "expired": NEVER_EXPIRES,
        }
        db, cols = _make_db(
            {
                "ontology_properties",
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "rdfs_domain",
                "rdfs_range_class",
            },
            {
                0: ["Person"],
                1: [dt_prop],
            },
        )
        up(db)
        assert cols["ontology_datatype_properties"].insert.call_args[1]["overwrite"] is True
        assert cols["rdfs_domain"].insert.call_args[1]["overwrite"] is True
