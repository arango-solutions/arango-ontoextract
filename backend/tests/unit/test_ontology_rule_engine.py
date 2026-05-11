"""Unit tests for ``app.services.ontology_rule_engine`` (Stream 11 IBR.4).

Pattern: MagicMock DB with ``run_aql`` patched per-test to return
deterministic edge sets. Each rule has its own test class; the engine
itself has integration-style tests over the four built-ins.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services import ontology_rule_engine as engine
from app.services.ontology_rule_engine import (
    RULE_CARDINALITY_VIOLATION,
    RULE_DISJOINT_VIOLATION,
    RULE_R1_SYNONYM_TRIANGLE,
    RULE_R2_SUBCLASS_CYCLE,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleEngineReport,
    Violation,
    evaluate_rules,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_with_collections(*present: str) -> MagicMock:
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name in present
    return db


def _patch_run_aql(monkeypatch, responses: dict[str, list[dict[str, Any]]]):
    """Patch ``run_aql`` to return the next response matched by an AQL substring.

    ``responses`` is keyed by a substring that uniquely identifies the
    target query (e.g. ``"FOR e IN subclass_of"``). Tests fail loudly
    if a query arrives that doesn't match any key, which catches
    accidental query changes that would silently bypass these tests.
    """

    def fake(_db, aql, *, bind_vars=None):
        for needle, rows in responses.items():
            if needle in aql:
                return iter(rows)
        raise AssertionError(f"unexpected AQL query in test: {aql!r}")

    monkeypatch.setattr(engine, "run_aql", fake)


# ---------------------------------------------------------------------------
# R1 -- synonym triangle
# ---------------------------------------------------------------------------


class TestR1SynonymTriangle:
    def test_no_collections_returns_empty(self, monkeypatch):
        db = _db_with_collections()  # neither subclass_of nor equivalent_class
        result = engine._r1_synonym_triangle(db, "OID")
        assert result == []

    def test_empty_ontology_returns_empty(self, monkeypatch):
        db = _db_with_collections("subclass_of", "equivalent_class")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [],
                "FOR e IN equivalent_class": [],
            },
        )
        assert engine._r1_synonym_triangle(db, "OID") == []

    def test_missing_triangle_emits_warning(self, monkeypatch):
        # A subClassOf B, B equivalent C, but no A subClassOf C edge.
        db = _db_with_collections("subclass_of", "equivalent_class")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                ],
                "FOR e IN equivalent_class": [
                    {"from": "ontology_classes/B", "to": "ontology_classes/C"},
                ],
            },
        )
        violations = engine._r1_synonym_triangle(db, "OID")
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == RULE_R1_SYNONYM_TRIANGLE
        assert v.severity == SEVERITY_WARNING
        assert "ontology_classes/A" in v.entity_ids
        assert "ontology_classes/C" in v.entity_ids

    def test_closed_triangle_emits_no_violation(self, monkeypatch):
        db = _db_with_collections("subclass_of", "equivalent_class")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                    {"from": "ontology_classes/A", "to": "ontology_classes/C"},
                ],
                "FOR e IN equivalent_class": [
                    {"from": "ontology_classes/B", "to": "ontology_classes/C"},
                ],
            },
        )
        assert engine._r1_synonym_triangle(db, "OID") == []

    def test_synonym_cycle_emits_error(self, monkeypatch):
        # A subClassOf B and B equivalent A -- duplicate concept.
        db = _db_with_collections("subclass_of", "equivalent_class")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                ],
                "FOR e IN equivalent_class": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                ],
            },
        )
        violations = engine._r1_synonym_triangle(db, "OID")
        # One ERROR violation only (no extra warning); the cycle short-
        # circuits the closure logic.
        assert len(violations) == 1
        assert violations[0].severity == SEVERITY_ERROR
        assert violations[0].suggested_action == "REDUNDANT"

    def test_equivalent_class_treated_as_undirected(self, monkeypatch):
        # The equivalent edge is materialised B -> A (single direction)
        # but reasoning must still find the cycle via undirected
        # interpretation.
        db = _db_with_collections("subclass_of", "equivalent_class")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                ],
                "FOR e IN equivalent_class": [
                    {"from": "ontology_classes/B", "to": "ontology_classes/A"},
                ],
            },
        )
        violations = engine._r1_synonym_triangle(db, "OID")
        assert len(violations) == 1
        assert violations[0].severity == SEVERITY_ERROR


# ---------------------------------------------------------------------------
# R2 -- subClassOf cycle detection
# ---------------------------------------------------------------------------


class TestR2SubclassCycle:
    def test_no_collection_returns_empty(self):
        db = _db_with_collections()
        assert engine._r2_subclass_cycle(db, "OID") == []

    def test_empty_returns_empty(self, monkeypatch):
        db = _db_with_collections("subclass_of")
        _patch_run_aql(monkeypatch, {"FOR e IN subclass_of": []})
        assert engine._r2_subclass_cycle(db, "OID") == []

    def test_self_loop_emits_error(self, monkeypatch):
        db = _db_with_collections("subclass_of")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/A"},
                ],
            },
        )
        violations = engine._r2_subclass_cycle(db, "OID")
        assert any(
            v.severity == SEVERITY_ERROR
            and v.entity_ids == ("ontology_classes/A",)
            and "subClassOf itself" in v.description
            for v in violations
        )

    def test_two_node_cycle_detected(self, monkeypatch):
        db = _db_with_collections("subclass_of")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                    {"from": "ontology_classes/B", "to": "ontology_classes/A"},
                ],
            },
        )
        violations = engine._r2_subclass_cycle(db, "OID")
        # Exactly one SCC violation for the {A, B} cycle.
        scc_vs = [v for v in violations if "cycle among" in v.description]
        assert len(scc_vs) == 1
        assert set(scc_vs[0].entity_ids) == {"ontology_classes/A", "ontology_classes/B"}
        assert scc_vs[0].suggested_action == "CONTRADICTED"

    def test_three_node_cycle_detected(self, monkeypatch):
        db = _db_with_collections("subclass_of")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                    {"from": "ontology_classes/B", "to": "ontology_classes/C"},
                    {"from": "ontology_classes/C", "to": "ontology_classes/A"},
                ],
            },
        )
        violations = engine._r2_subclass_cycle(db, "OID")
        scc_vs = [v for v in violations if "cycle among" in v.description]
        assert len(scc_vs) == 1
        assert set(scc_vs[0].entity_ids) == {
            "ontology_classes/A",
            "ontology_classes/B",
            "ontology_classes/C",
        }

    def test_dag_emits_no_violation(self, monkeypatch):
        # Linear chain A -> B -> C -> D plus a side branch C -> E.
        db = _db_with_collections("subclass_of")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR e IN subclass_of": [
                    {"from": "ontology_classes/A", "to": "ontology_classes/B"},
                    {"from": "ontology_classes/B", "to": "ontology_classes/C"},
                    {"from": "ontology_classes/C", "to": "ontology_classes/D"},
                    {"from": "ontology_classes/C", "to": "ontology_classes/E"},
                ],
            },
        )
        assert engine._r2_subclass_cycle(db, "OID") == []


# ---------------------------------------------------------------------------
# Disjointness
# ---------------------------------------------------------------------------


class TestDisjointViolation:
    def test_no_disjoint_collection_returns_empty(self):
        db = _db_with_collections("subclass_of")  # missing disjoint_with
        assert engine._disjoint_violation(db, "OID") == []

    def test_violation_detected(self, monkeypatch):
        db = _db_with_collections("subclass_of", "disjoint_with")
        # The query is one big AQL join; we just return the rows that
        # join would have produced.
        _patch_run_aql(
            monkeypatch,
            {
                "FOR sub1 IN subclass_of": [
                    {
                        "child": "ontology_classes/Foo",
                        "p1": "ontology_classes/Animal",
                        "p2": "ontology_classes/Plant",
                    },
                ],
            },
        )
        violations = engine._disjoint_violation(db, "OID")
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == RULE_DISJOINT_VIOLATION
        assert v.severity == SEVERITY_ERROR
        assert "ontology_classes/Foo" in v.entity_ids

    def test_duplicate_orderings_deduped(self, monkeypatch):
        db = _db_with_collections("subclass_of", "disjoint_with")
        # The AQL join can produce both (p1=Animal, p2=Plant) and
        # (p1=Plant, p2=Animal) for the same triple; ensure the rule
        # emits only one violation per (child, parent_pair).
        _patch_run_aql(
            monkeypatch,
            {
                "FOR sub1 IN subclass_of": [
                    {
                        "child": "ontology_classes/Foo",
                        "p1": "ontology_classes/Animal",
                        "p2": "ontology_classes/Plant",
                    },
                    {
                        "child": "ontology_classes/Foo",
                        "p1": "ontology_classes/Plant",
                        "p2": "ontology_classes/Animal",
                    },
                ],
            },
        )
        assert len(engine._disjoint_violation(db, "OID")) == 1


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


class TestCardinalityViolation:
    def test_missing_collection_returns_empty(self):
        db = _db_with_collections()
        assert engine._cardinality_violation(db, "OID") == []

    def test_no_constraints_returns_empty(self, monkeypatch):
        db = _db_with_collections("ontology_constraints", "rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            {"FOR c IN ontology_constraints": []},
        )
        assert engine._cardinality_violation(db, "OID") == []

    def test_below_min_emits_violation(self, monkeypatch):
        db = _db_with_collections("ontology_constraints", "rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR c IN ontology_constraints": [
                    {
                        "class_id": "ontology_classes/Customer",
                        "property_uri": "http://example.org/onto#hasName",
                        "min_cardinality": 1,
                        "max_cardinality": 5,
                    }
                ],
                "FOR e IN rdfs_domain": [0],  # zero occurrences
            },
        )
        violations = engine._cardinality_violation(db, "OID")
        assert len(violations) == 1
        assert "below declared min cardinality" in violations[0].description

    def test_above_max_emits_violation(self, monkeypatch):
        db = _db_with_collections("ontology_constraints", "rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR c IN ontology_constraints": [
                    {
                        "class_id": "ontology_classes/Customer",
                        "property_uri": "http://example.org/onto#hasName",
                        "max_cardinality": 1,
                    }
                ],
                "FOR e IN rdfs_domain": [3],
            },
        )
        violations = engine._cardinality_violation(db, "OID")
        assert len(violations) == 1
        assert "above declared max cardinality" in violations[0].description

    def test_within_bounds_emits_no_violation(self, monkeypatch):
        db = _db_with_collections("ontology_constraints", "rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR c IN ontology_constraints": [
                    {
                        "class_id": "ontology_classes/Customer",
                        "property_uri": "http://example.org/onto#hasName",
                        "min_cardinality": 1,
                        "max_cardinality": 5,
                    }
                ],
                "FOR e IN rdfs_domain": [3],
            },
        )
        assert engine._cardinality_violation(db, "OID") == []

    def test_constraint_missing_required_fields_skipped(self, monkeypatch):
        db = _db_with_collections("ontology_constraints", "rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            {
                "FOR c IN ontology_constraints": [
                    {"min_cardinality": 1},  # no class_id / property_uri
                ],
            },
        )
        assert engine._cardinality_violation(db, "OID") == []


# ---------------------------------------------------------------------------
# evaluate_rules orchestrator
# ---------------------------------------------------------------------------


class TestEvaluateRulesOrchestrator:
    def test_collects_violations_from_all_registered_rules(self):
        db = MagicMock()

        def rule_a(_db, _oid):
            return [Violation("A", SEVERITY_WARNING, ("x",), "from A")]

        def rule_b(_db, _oid):
            return [Violation("B", SEVERITY_ERROR, ("y",), "from B")]

        report = evaluate_rules(db, "OID", rules=(("A", rule_a), ("B", rule_b)))
        assert isinstance(report, RuleEngineReport)
        assert {v.rule_id for v in report.violations} == {"A", "B"}
        assert report.rules_evaluated == ["A", "B"]
        assert report.rules_skipped == []

    def test_one_failing_rule_does_not_abort_the_others(self):
        db = MagicMock()

        def boom(_db, _oid):
            raise RuntimeError("intentional")

        def good(_db, _oid):
            return [Violation("good", SEVERITY_WARNING, (), "ok")]

        report = evaluate_rules(
            db, "OID", rules=(("bad", boom), ("good", good))
        )
        assert "bad" in report.rules_skipped
        assert "good" in report.rules_evaluated
        assert len(report.violations) == 1

    def test_zero_violation_rule_still_marked_evaluated(self):
        db = MagicMock()

        def empty(_db, _oid):
            return []

        report = evaluate_rules(db, "OID", rules=(("empty", empty),))
        assert report.rules_evaluated == ["empty"]
        assert report.violations == []

    def test_to_dict_round_trip(self):
        db = MagicMock()

        def rule(_db, _oid):
            return [
                Violation(
                    "X",
                    SEVERITY_ERROR,
                    ("a", "b"),
                    "desc",
                    suggested_action="CONTRADICTED",
                )
            ]

        report = evaluate_rules(db, "OID", rules=(("X", rule),))
        d = report.to_dict()
        assert d["ontology_id"] == "OID"
        assert d["violation_count"] == 1
        assert d["violations"][0]["rule_id"] == "X"
        assert d["violations"][0]["entity_ids"] == ["a", "b"]
        assert d["violations"][0]["suggested_action"] == "CONTRADICTED"

    def test_by_rule_filters(self):
        db = MagicMock()

        def rule(_db, _oid):
            return [
                Violation("X", SEVERITY_WARNING, (), "1"),
                Violation("Y", SEVERITY_WARNING, (), "2"),
                Violation("X", SEVERITY_ERROR, (), "3"),
            ]

        report = evaluate_rules(db, "OID", rules=(("any", rule),))
        assert len(report.by_rule("X")) == 2
        assert len(report.by_rule("Y")) == 1
        assert report.by_rule("Z") == []


# ---------------------------------------------------------------------------
# Defaults wiring
# ---------------------------------------------------------------------------


class TestDefaultRulesWiring:
    """The default _DEFAULT_RULES tuple is a public contract for how Phase 2
    consumes the engine. Lock it in so silent re-ordering / removal is a
    test failure rather than a behaviour change."""

    def test_default_set_includes_all_four_rules(self):
        ids = [rid for rid, _ in engine._DEFAULT_RULES]
        assert ids == [
            RULE_R1_SYNONYM_TRIANGLE,
            RULE_R2_SUBCLASS_CYCLE,
            RULE_DISJOINT_VIOLATION,
            RULE_CARDINALITY_VIOLATION,
        ]

    def test_evaluate_rules_with_defaults_runs_against_empty_db(self, monkeypatch):
        # Evaluate against a DB with NO collections; every rule should
        # gracefully degrade to zero violations and the orchestrator
        # should mark them all as evaluated.
        db = _db_with_collections()
        report = evaluate_rules(db, "OID")
        # Every rule recognised "no collections" and returned [],
        # which the orchestrator records as "evaluated" -- not "skipped"
        # (skipped is reserved for rules that raised).
        assert sorted(report.rules_evaluated) == sorted(
            [
                RULE_R1_SYNONYM_TRIANGLE,
                RULE_R2_SUBCLASS_CYCLE,
                RULE_DISJOINT_VIOLATION,
                RULE_CARDINALITY_VIOLATION,
            ]
        )
        assert report.violations == []
        assert report.rules_skipped == []


def test_violation_is_frozen_dataclass():
    from dataclasses import FrozenInstanceError

    v = Violation(rule_id="R", severity=SEVERITY_WARNING, entity_ids=("x",), description="d")
    with pytest.raises(FrozenInstanceError):
        v.severity = SEVERITY_ERROR  # type: ignore[misc]
