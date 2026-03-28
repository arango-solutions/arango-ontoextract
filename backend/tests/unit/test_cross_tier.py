"""Unit tests for cross-tier edge creation and conflict detection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from app.services.cross_tier import (
    ConflictType,
    create_cross_tier_edges,
    detect_conflicts,
)

NEVER_EXPIRES = sys.maxsize


def _mock_db_for_edges(
    staging_classes: list[dict] | None = None,
    domain_classes: list[dict] | None = None,
):
    """Create a mock DB for cross-tier edge creation."""
    db = MagicMock()
    db.has_collection.return_value = True

    call_count = {"n": 0}

    staging = staging_classes or []
    domain = domain_classes or []

    def execute_side(query, bind_vars=None):
        call_count["n"] += 1
        if "classification" in query:
            return iter(staging)
        if bind_vars and bind_vars.get("uri"):
            uri = bind_vars["uri"]
            for d in domain:
                if d.get("uri") == uri:
                    return iter([d])
            return iter([])
        return iter([])

    db.aql.execute.side_effect = execute_side

    col_mock = MagicMock()
    col_mock.insert.return_value = {"new": {"_key": "edge1"}}
    db.collection.return_value = col_mock

    return db


def _mock_db_for_conflicts(
    same_uri_results: list[dict] | None = None,
    range_results: list[dict] | None = None,
    domain_edges: list[dict] | None = None,
    staging_classes_with_parents: list[dict] | None = None,
):
    """Create a mock DB for conflict detection."""
    db = MagicMock()
    db.has_collection.return_value = True

    call_count = {"n": 0}

    def execute_side(query, bind_vars=None):
        call_count["n"] += 1
        if "local.uri == domain.uri" in query:
            return iter(same_uri_results or [])
        if "local_prop.range != domain_prop.range" in query:
            return iter(range_results or [])
        if "DOCUMENT(e._from)" in query:
            return iter(domain_edges or [])
        if "cls.parent_uri != null" in query:
            return iter(staging_classes_with_parents or [])
        return iter([])

    db.aql.execute.side_effect = execute_side
    return db


class TestCreateCrossTierEdges:
    def test_creates_edges_for_extension_classes(self):
        staging = [
            {
                "_id": "ontology_classes/local1",
                "_key": "local1",
                "uri": "http://local.org#SpecialVehicle",
                "classification": "extension",
                "parent_domain_uri": "http://ex.org#Vehicle",
            }
        ]
        domain = [
            {
                "_id": "ontology_classes/domain1",
                "_key": "domain1",
                "uri": "http://ex.org#Vehicle",
                "label": "Vehicle",
            }
        ]
        db = _mock_db_for_edges(staging_classes=staging, domain_classes=domain)
        result = create_cross_tier_edges(db, run_id="run1", ontology_id="domain_onto")
        assert result.edges_created == 1

    def test_skips_when_no_parent_uri(self):
        staging = [
            {
                "_id": "ontology_classes/local1",
                "_key": "local1",
                "uri": "http://local.org#SomeThing",
                "classification": "extension",
            }
        ]
        db = _mock_db_for_edges(staging_classes=staging)
        result = create_cross_tier_edges(db, run_id="run1", ontology_id="domain_onto")
        assert result.edges_created == 0

    def test_no_staging_classes(self):
        db = _mock_db_for_edges(staging_classes=[])
        result = create_cross_tier_edges(db, run_id="run1", ontology_id="domain_onto")
        assert result.edges_created == 0


class TestDetectConflicts:
    def test_detects_same_uri_conflicts(self):
        same_uri = [
            {
                "local_key": "local1",
                "domain_key": "domain1",
                "uri": "http://ex.org#Vehicle",
            }
        ]
        db = _mock_db_for_conflicts(same_uri_results=same_uri)
        conflicts = detect_conflicts(db, run_id="run1", ontology_id="domain_onto")
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == ConflictType.SAME_URI

    def test_detects_range_conflicts(self):
        range_conflict = [
            {
                "local_key": "prop1",
                "domain_key": "dprop1",
                "uri": "http://ex.org#hasColor",
                "local_range": "xsd:integer",
                "domain_range": "xsd:string",
            }
        ]
        db = _mock_db_for_conflicts(range_results=range_conflict)
        conflicts = detect_conflicts(db, run_id="run1", ontology_id="domain_onto")
        assert any(c.conflict_type == ConflictType.CONTRADICTING_RANGE for c in conflicts)

    def test_no_conflicts_when_clean(self):
        db = _mock_db_for_conflicts()
        conflicts = detect_conflicts(db, run_id="run1", ontology_id="domain_onto")
        assert len(conflicts) == 0

    def test_detects_hierarchy_redefinition(self):
        domain_edges = [
            {"child_uri": "http://ex.org#Car", "parent_uri": "http://ex.org#Vehicle"}
        ]
        staging_with_parents = [
            {
                "key": "local1",
                "uri": "http://ex.org#Car",
                "parent_uri": "http://ex.org#Machine",
            }
        ]
        db = _mock_db_for_conflicts(
            domain_edges=domain_edges,
            staging_classes_with_parents=staging_with_parents,
        )

        def execute_side(query, bind_vars=None):
            if "local.uri == domain.uri" in query:
                return iter([])
            if "local_prop.range != domain_prop.range" in query:
                return iter([])
            if "DOCUMENT(e._from)" in query:
                return iter(domain_edges)
            if "cls.parent_uri != null" in query:
                return iter(staging_with_parents)
            if "cls.uri == @uri" in query:
                return iter([{"_key": "domain_car", "uri": "http://ex.org#Car"}])
            return iter([])

        db.aql.execute.side_effect = execute_side
        conflicts = detect_conflicts(db, run_id="run1", ontology_id="domain_onto")
        assert any(c.conflict_type == ConflictType.HIERARCHY_REDEFINITION for c in conflicts)
