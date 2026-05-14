"""Unit tests for ``app.services.ontology_dependency`` (Stream 1 H.4).

The service exists to give callers (the DELETE dry-run path and the new
``GET /library/{id}/deletion-impact`` endpoint) a single, complete view of
what a cascade-on-delete will affect. These tests pin down the contract:

* Missing ontology -> ``ValueError``.
* Direct, transitive, and outgoing imports are computed independently.
* Cross-ontology ``extends_domain`` edges are counted only when they
  originate in a different ontology.
* Per-collection expire counts are reported even for empty/missing
  collections (so the frontend can render a stable table).
* ``warnings``, ``has_dependents``, and ``safe_to_delete`` reflect the
  combined state.

The DB is mocked at the AQL level via a ``side_effect`` dispatcher that
matches on substrings of the query text. This is brittle by design: any
future query refactor is forced through these tests, which keeps the
contract honest.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.ontology_dependency import analyze_deletion_impact

# --- Fixtures --------------------------------------------------------------


def _make_db(
    *,
    registry_entry: dict[str, Any] | None,
    aql_responses: dict[str, list[Any]],
    missing_collections: tuple[str, ...] = (),
) -> MagicMock:
    """Build a MagicMock ArangoDB handle with controllable AQL behaviour.

    ``aql_responses`` maps a substring of the AQL query to the list of
    rows that query should yield. The first matching substring wins; if
    no key matches, the dispatcher returns an empty cursor so unrelated
    queries (e.g. ones a future change might add) don't crash the test.
    """
    db = MagicMock()

    def _has_collection(name: str) -> bool:
        return name not in missing_collections

    db.has_collection.side_effect = _has_collection

    registry_collection = MagicMock()
    registry_collection.get.return_value = registry_entry
    db.collection.return_value = registry_collection

    def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        for needle, rows in aql_responses.items():
            if needle in query:
                return iter(list(rows))
        return iter([])

    db.aql.execute = MagicMock(side_effect=_execute)
    return db


# --- Tests -----------------------------------------------------------------


class TestRegistryLookup:
    def test_raises_when_registry_collection_missing(self) -> None:
        db = _make_db(
            registry_entry=None,
            aql_responses={},
            missing_collections=("ontology_registry",),
        )
        with pytest.raises(ValueError, match="ontology_registry"):
            analyze_deletion_impact(db, "ont-missing")

    def test_raises_when_ontology_not_found(self) -> None:
        db = _make_db(registry_entry=None, aql_responses={})
        with pytest.raises(ValueError, match="ont-missing"):
            analyze_deletion_impact(db, "ont-missing")


class TestNoDependentsHappyPath:
    def test_isolated_ontology_is_safe_to_delete(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont-1", "name": "Lonely", "status": "active"},
            aql_responses={},  # Every count returns empty -> 0
        )

        result = analyze_deletion_impact(db, "ont-1")

        assert result["ontology_id"] == "ont-1"
        assert result["ontology_name"] == "Lonely"
        assert result["status"] == "active"
        assert result["direct_dependents"] == []
        assert result["transitive_dependents"] == []
        assert result["imports_outgoing"] == []
        assert result["cross_ontology_extends_edges"] == 0
        assert result["extraction_runs"] == {"as_target": 0, "as_domain": 0, "total": 0}
        assert result["quality_history_snapshots"] == 0
        assert result["released_versions"] == 0
        assert result["open_revisions"] == 0
        assert result["has_dependents"] is False
        assert result["safe_to_delete"] is True
        assert result["warnings"] == []

    def test_expire_counts_table_lists_every_known_collection(self) -> None:
        """Even when collections are empty, the table includes a row per
        collection so the frontend can render a stable shape."""
        db = _make_db(
            registry_entry={"_key": "ont-1", "name": "Lonely"},
            aql_responses={},
        )
        result = analyze_deletion_impact(db, "ont-1")
        # Vertex collections.
        for col in (
            "ontology_classes",
            "ontology_properties",
            "ontology_object_properties",
            "ontology_datatype_properties",
            "ontology_constraints",
        ):
            assert col in result["expire_counts"]
            assert result["expire_counts"][col] == 0
        # Edge collections.
        for col in (
            "subclass_of",
            "has_property",
            "extends_domain",
            "rdfs_domain",
            "rdfs_range_class",
        ):
            assert col in result["expire_counts"]


class TestDependentTraversal:
    def test_direct_dependents_use_imports_inbound_one_hop(self) -> None:
        db = _make_db(
            registry_entry={"_key": "core", "name": "Core"},
            aql_responses={
                # Direct: a single 1-hop INBOUND edge over `imports`.
                "FOR e IN imports": [
                    {"_key": "consumer-a", "name": "Consumer A", "status": "active"},
                ],
                # Transitive (must also include the direct dependent).
                "INBOUND @target imports": [
                    {"_key": "consumer-a", "name": "Consumer A", "status": "active", "depth": 1},
                    {"_key": "consumer-b", "name": "Consumer B", "status": "active", "depth": 2},
                ],
            },
        )

        result = analyze_deletion_impact(db, "core")

        assert [d["_key"] for d in result["direct_dependents"]] == ["consumer-a"]
        depths = {d["_key"]: d["depth"] for d in result["transitive_dependents"]}
        assert depths == {"consumer-a": 1, "consumer-b": 2}
        assert result["has_dependents"] is True
        assert result["safe_to_delete"] is False
        assert any("ontology(ies) depend" in w for w in result["warnings"])

    def test_transitive_dependents_sorted_by_depth_then_name(self) -> None:
        db = _make_db(
            registry_entry={"_key": "core"},
            aql_responses={
                "INBOUND @target imports": [
                    {"_key": "z", "name": "Zeta", "status": "active", "depth": 1},
                    {"_key": "a", "name": "Alpha", "status": "active", "depth": 2},
                    {"_key": "b", "name": "Beta", "status": "active", "depth": 1},
                ]
            },
        )
        result = analyze_deletion_impact(db, "core")
        order = [d["_key"] for d in result["transitive_dependents"]]
        # Depth 1 first (Beta, Zeta alphabetised), then depth 2.
        assert order == ["b", "z", "a"]

    def test_outgoing_imports_are_reported_separately(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={
                # The outgoing query is the only one with `_from == @target`;
                # we keep dependents empty so this is the only data signal.
                "FILTER e._from == @target": [
                    {"_key": "fibo", "name": "FIBO Core", "status": "active"},
                ],
            },
        )
        result = analyze_deletion_impact(db, "ont")
        assert [o["_key"] for o in result["imports_outgoing"]] == ["fibo"]
        # Outgoing imports do NOT block deletion.
        assert result["safe_to_delete"] is True

    def test_missing_imports_collection_yields_empty_lists(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={},
            missing_collections=("imports",),
        )
        result = analyze_deletion_impact(db, "ont")
        assert result["direct_dependents"] == []
        assert result["transitive_dependents"] == []
        assert result["imports_outgoing"] == []


class TestCrossOntologyEdges:
    def test_counts_extends_domain_edges_only_when_collections_present(self) -> None:
        db = _make_db(
            registry_entry={"_key": "core"},
            aql_responses={
                # The extends-edges query is the only one whose body
                # mentions `extends_domain` AND `target_class_ids`.
                "target_class_ids": [3],
            },
        )
        result = analyze_deletion_impact(db, "core")
        assert result["cross_ontology_extends_edges"] == 3
        assert result["safe_to_delete"] is False
        assert any("extends_domain" in w for w in result["warnings"])

    def test_returns_zero_when_extends_domain_missing(self) -> None:
        db = _make_db(
            registry_entry={"_key": "core"},
            aql_responses={"target_class_ids": [99]},  # Should be ignored.
            missing_collections=("extends_domain",),
        )
        result = analyze_deletion_impact(db, "core")
        assert result["cross_ontology_extends_edges"] == 0


class TestExpireCountsAndRunSummary:
    def test_counts_live_entities_per_collection(self) -> None:
        # The query for live counts uses ``LENGTH(FOR d IN <col> ...)``;
        # we route by collection name appearing in that fragment.
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={
                "FOR d IN ontology_classes": [12],
                "FOR d IN ontology_properties": [4],
                "FOR d IN subclass_of": [9],
                # ``ontology_object_properties`` and ``has_property`` are
                # also live count queries; the FOR-d substring would also
                # match the property's plural form, so we use the full
                # collection name to scope.
            },
        )
        result = analyze_deletion_impact(db, "ont")
        assert result["expire_counts"]["ontology_classes"] == 12
        assert result["expire_counts"]["ontology_properties"] == 4
        assert result["expire_counts"]["subclass_of"] == 9
        assert result["expire_counts"]["has_property"] == 0  # No matching response.

    def test_run_summary_separates_target_and_domain(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={
                "r.target_ontology_id == @oid RETURN 1": [5],
                "@oid IN (r.domain_ontology_ids || []) RETURN 1": [3],
                "UNIQUE(": [7],  # Total is the deduped union.
            },
        )
        result = analyze_deletion_impact(db, "ont")
        assert result["extraction_runs"]["as_target"] == 5
        assert result["extraction_runs"]["as_domain"] == 3
        assert result["extraction_runs"]["total"] == 7

    def test_quality_history_and_releases_counted(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={
                "FOR q IN quality_history": [11],
                "FOR r IN ontology_releases": [2],
            },
        )
        result = analyze_deletion_impact(db, "ont")
        assert result["quality_history_snapshots"] == 11
        assert result["released_versions"] == 2
        # A released version blocks "safe to delete" on its own.
        assert result["safe_to_delete"] is False
        assert any("released" in w.lower() for w in result["warnings"])

    def test_proposed_revisions_counted_and_warned(self) -> None:
        db = _make_db(
            registry_entry={"_key": "ont"},
            aql_responses={"FOR rm IN revision_meta": [4]},
        )
        result = analyze_deletion_impact(db, "ont")
        assert result["open_revisions"] == 4
        assert any("belief-revision" in w for w in result["warnings"])
