"""Unit tests for ontology context serialization."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from app.services.ontology_context import (
    get_domain_ontology_for_org,
    serialize_domain_context,
    serialize_multi_domain_context,
    set_domain_ontology_for_org,
)

NEVER_EXPIRES = sys.maxsize


def _mock_db(
    *,
    classes: list[dict] | None = None,
    edges: list[dict] | None = None,
    properties: list[dict] | None = None,
    rdfs_domain_rows: list[dict] | None = None,
    registry_name: str | None = None,
    org_ontologies: list[str] | None = None,
):
    """Create a mock ArangoDB database with configurable query results.

    ``has_collection`` reflects which collections exist: by default registry,
    classes, subclass_of, and ontology_properties (no ``rdfs_domain``).
    Pass ``rdfs_domain_rows`` to simulate PGT: adds ``rdfs_domain`` and an
    extra AQL result row after subclass edges.
    """
    db = MagicMock()

    present_cols = {
        "ontology_registry",
        "ontology_classes",
        "subclass_of",
        "ontology_properties",
    }
    if rdfs_domain_rows is not None:
        present_cols.add("rdfs_domain")
    if properties is None and rdfs_domain_rows is not None:
        present_cols.discard("ontology_properties")

    db.has_collection.side_effect = lambda name: name in present_cols

    call_count = {"n": 0}
    query_results = []

    if registry_name is not None:
        query_results.append(iter([registry_name]))
    else:
        query_results.append(iter(["test_ontology"]))

    if classes is not None:
        query_results.append(iter(classes))
    else:
        query_results.append(iter([]))

    if edges is not None:
        query_results.append(iter(edges))
    else:
        query_results.append(iter([]))

    if rdfs_domain_rows is not None:
        query_results.append(iter(rdfs_domain_rows))

    if properties is not None:
        query_results.append(iter(properties))
    elif rdfs_domain_rows is None:
        query_results.append(iter([]))

    def execute_side_effect(query, bind_vars=None):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(query_results):
            return query_results[idx]
        return iter([])

    db.aql.execute.side_effect = execute_side_effect
    return db


class TestSerializeDomainContext:
    def test_empty_ontology_returns_none_marker(self):
        db = _mock_db(classes=[])
        result = serialize_domain_context(db, ontology_id="test")
        assert "Domain: test_ontology" in result
        assert "(none)" in result

    def test_single_root_class(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Vehicle",
                "label": "Vehicle",
                "ontology_id": "test",
            }
        ]
        db = _mock_db(classes=classes)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Vehicle" in result
        assert "Domain:" in result

    def test_hierarchy_with_children(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Vehicle",
                "label": "Vehicle",
                "ontology_id": "test",
            },
            {
                "_id": "ontology_classes/2",
                "_key": "2",
                "uri": "http://ex.org#Car",
                "label": "Car",
                "ontology_id": "test",
            },
        ]
        edges = [
            {
                "_from": "ontology_classes/2",
                "_to": "ontology_classes/1",
            }
        ]
        db = _mock_db(classes=classes, edges=edges)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Vehicle" in result
        assert "Car" in result

    def test_with_properties(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Person",
                "label": "Person",
                "ontology_id": "test",
            }
        ]
        properties = [
            {
                "domain_class_id": "ontology_classes/1",
                "label": "name",
                "uri": "http://ex.org#name",
            },
            {
                "domain_class_id": "ontology_classes/1",
                "label": "age",
                "uri": "http://ex.org#age",
            },
        ]
        db = _mock_db(classes=classes, properties=properties)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Person" in result
        assert "props:" in result

    def test_pgt_property_labels_via_rdfs_domain(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Person",
                "label": "Person",
                "ontology_id": "test",
            }
        ]
        rdfs_rows = [
            {"class_id": "ontology_classes/1", "label": "fullName"},
            {"class_id": "ontology_classes/1", "label": "age"},
        ]
        db = _mock_db(
            classes=classes,
            edges=[],
            rdfs_domain_rows=rdfs_rows,
        )
        result = serialize_domain_context(db, ontology_id="test")
        assert "Person" in result
        assert "fullName" in result
        assert "age" in result
        assert "props:" in result


class TestGetDomainOntologyForOrg:
    def test_returns_empty_when_no_collection(self):
        db = MagicMock()
        db.has_collection.return_value = False
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == []

    def test_returns_empty_when_no_org(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([None])
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == []

    def test_returns_ontology_ids(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([["onto_1", "onto_2"]])
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == ["onto_1", "onto_2"]


class TestSetDomainOntologyForOrg:
    def test_validates_ontology_ids_exist(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([])

        with pytest.raises(ValueError, match="not found in registry"):
            set_domain_ontology_for_org(db, org_id="org1", ontology_ids=["bad_id"])

    def test_creates_org_if_not_exists(self):
        db = MagicMock()
        db.has_collection.side_effect = lambda col: col != "organizations"

        call_count = {"n": 0}

        def execute_side(query, bind_vars=None):
            call_count["n"] += 1
            return iter([])

        db.aql.execute.side_effect = execute_side
        col_mock = MagicMock()
        col_mock.insert.return_value = {"new": {"_key": "org1", "selected_ontologies": []}}
        db.collection.return_value = col_mock
        db.create_collection.return_value = None

        result = set_domain_ontology_for_org(db, org_id="org1", ontology_ids=[])
        assert result["_key"] == "org1"


class TestSerializeMultiDomainContext:
    def test_empty_ontology_ids(self):
        db = MagicMock()
        result = serialize_multi_domain_context(db, ontology_ids=[])
        assert result == ""
