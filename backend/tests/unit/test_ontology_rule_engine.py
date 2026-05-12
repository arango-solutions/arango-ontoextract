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
    RULE_R3_ORPHAN_RANGE,
    RULE_R4_REDUNDANT_CLASS,
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


# ---------------------------------------------------------------------------
# R3 -- orphan object property range
# ---------------------------------------------------------------------------


class TestR3OrphanObjectPropertyRange:
    """The orphan-range rule wraps ``edge_repair`` in dry-run mode and
    must convert all three categories from ``RepairReport`` (repaired,
    unrecoverable, no_domain) into ``Violation`` records with the right
    severity and a stable ``GAP-FILLING`` action."""

    @staticmethod
    def _required_collections() -> tuple[str, ...]:
        return (
            "ontology_object_properties",
            "ontology_classes",
            "rdfs_domain",
            "rdfs_range_class",
        )

    @staticmethod
    def _stub_repair(monkeypatch, report):
        """Patch the rule's local import target so we don't have to
        construct a full DB fixture for the orphan-detection AQL.
        ``edge_repair`` is the source of truth for what counts as an
        orphan; this rule's job is only the conversion to Violations.
        """
        from app.services import edge_repair

        monkeypatch.setattr(
            edge_repair,
            "repair_orphan_object_property_ranges",
            lambda _db, _oid, *, dry_run: report,
        )

    def test_returns_empty_when_required_collections_missing(self, monkeypatch):
        db = _db_with_collections()
        # Stub edge_repair to ensure it's NOT called when collections are missing
        # (rule must short-circuit before touching the service).
        called = {"n": 0}

        def _spy(_db, _oid, *, dry_run):
            called["n"] += 1
            raise AssertionError("edge_repair must not be invoked when collections are missing")

        from app.services import edge_repair

        monkeypatch.setattr(edge_repair, "repair_orphan_object_property_ranges", _spy)
        assert engine._r3_orphan_object_property_range(db, "OID") == []
        assert called["n"] == 0

    def test_repaired_orphan_emits_warning_with_gap_filling(self, monkeypatch):
        from app.services.edge_repair import RepairedEdge, RepairReport

        report = RepairReport(
            ontology_id="OID",
            orphans_found=1,
            repaired=[
                RepairedEdge(
                    prop_key="LSA_is_contributed_to_by",
                    domain_class_key="LifestyleSpendingAccount",
                    range_class_key="Employer",
                    matched_text="employer matched in description",
                    matched_via="label",
                )
            ],
        )
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")

        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == RULE_R3_ORPHAN_RANGE
        assert v.severity == SEVERITY_WARNING
        assert v.suggested_action == "GAP-FILLING"
        assert v.entity_ids == (
            "LSA_is_contributed_to_by",
            "LifestyleSpendingAccount",
            "Employer",
        )
        # Description must include the inferred range AND a hint at how
        # to apply it -- this is the curator's primary affordance.
        assert "Employer" in v.description
        assert "/repair-edges" in v.description

    def test_unrecoverable_orphan_emits_warning_with_gap_filling(self, monkeypatch):
        from app.services.edge_repair import RepairReport, UnrecoverableOrphan

        report = RepairReport(
            ontology_id="OID",
            orphans_found=1,
            unrecoverable=[
                UnrecoverableOrphan(
                    prop_key="MaskMandatePolicy_applies_in_location",
                    domain_class_key="MaskMandatePolicy",
                    label="applies in location",
                    description="A policy that applies in a given location.",
                )
            ],
        )
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")

        assert len(violations) == 1
        v = violations[0]
        assert v.severity == SEVERITY_WARNING
        assert v.suggested_action == "GAP-FILLING"
        assert v.entity_ids == (
            "MaskMandatePolicy_applies_in_location",
            "MaskMandatePolicy",
        )
        # Must explain WHY no candidate matched so the curator knows
        # to look for new evidence rather than an existing class.
        assert (
            "no candidate" in v.description.lower()
            or "new evidence" in v.description.lower()
        )

    def test_unrecoverable_with_no_domain_class_uses_single_entity(self, monkeypatch):
        """Edge case: an orphan with no domain SHOULD still emit a
        violation, just with a one-element entity_ids tuple."""
        from app.services.edge_repair import RepairReport, UnrecoverableOrphan

        report = RepairReport(
            ontology_id="OID",
            orphans_found=1,
            unrecoverable=[
                UnrecoverableOrphan(
                    prop_key="loose_property",
                    domain_class_key=None,
                    label="loose",
                    description="",
                )
            ],
        )
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")
        assert violations[0].entity_ids == ("loose_property",)

    def test_no_domain_emits_error_severity(self, monkeypatch):
        """A property with neither domain nor range is structurally
        broken (the canvas can't render it at all) -- must escalate to
        ``error``, not ``warning``."""
        from app.services.edge_repair import RepairReport

        report = RepairReport(
            ontology_id="OID",
            orphans_found=0,
            no_domain=["floating_property_1", "floating_property_2"],
        )
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")

        assert len(violations) == 2
        assert all(v.severity == SEVERITY_ERROR for v in violations)
        assert all(v.suggested_action == "GAP-FILLING" for v in violations)
        assert {v.entity_ids for v in violations} == {
            ("floating_property_1",),
            ("floating_property_2",),
        }

    def test_mixed_report_aggregates_all_three_buckets(self, monkeypatch):
        """End-to-end: a real-world report mixing all three categories
        must produce one violation per item with the right shape."""
        from app.services.edge_repair import (
            RepairedEdge,
            RepairReport,
            UnrecoverableOrphan,
        )

        report = RepairReport(
            ontology_id="OID",
            orphans_found=4,
            repaired=[
                RepairedEdge(
                    prop_key="p1",
                    domain_class_key="D1",
                    range_class_key="R1",
                    matched_text="r1 matched",
                    matched_via="label",
                ),
                RepairedEdge(
                    prop_key="p2",
                    domain_class_key="D2",
                    range_class_key="R2",
                    matched_text="r2 matched",
                    matched_via="key",
                ),
            ],
            unrecoverable=[
                UnrecoverableOrphan(
                    prop_key="p3",
                    domain_class_key="D3",
                    label="p3 label",
                    description="",
                ),
            ],
            no_domain=["p4"],
        )
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")

        assert len(violations) == 4
        sev = [v.severity for v in violations]
        assert sev.count(SEVERITY_WARNING) == 3
        assert sev.count(SEVERITY_ERROR) == 1
        # All four MUST share the same suggested action so a downstream
        # consumer can group them under one curator workflow.
        assert {v.suggested_action for v in violations} == {"GAP-FILLING"}

    def test_orchestrator_isolates_edge_repair_failure(self, monkeypatch):
        """If ``edge_repair`` raises, the rule must surface the
        exception to the orchestrator so the orchestrator marks R3 as
        ``skipped`` (per IBR.4 contract) instead of silently returning
        zero violations."""
        from app.services import edge_repair

        def _boom(_db, _oid, *, dry_run):
            raise RuntimeError("AQL exploded")

        monkeypatch.setattr(edge_repair, "repair_orphan_object_property_ranges", _boom)
        db = _db_with_collections(*self._required_collections())

        report = evaluate_rules(
            db, "OID", rules=((RULE_R3_ORPHAN_RANGE, engine._r3_orphan_object_property_range),)
        )
        assert RULE_R3_ORPHAN_RANGE in report.rules_skipped
        assert RULE_R3_ORPHAN_RANGE not in report.rules_evaluated
        assert report.violations == []

    def test_empty_report_yields_no_violations(self, monkeypatch):
        from app.services.edge_repair import RepairReport

        report = RepairReport(ontology_id="OID")
        db = _db_with_collections(*self._required_collections())
        self._stub_repair(monkeypatch, report)

        violations = engine._r3_orphan_object_property_range(db, "OID")
        assert violations == []


# ---------------------------------------------------------------------------
# R4 -- redundant class
# ---------------------------------------------------------------------------


class TestR4RedundantClass:
    """The redundant-class rule clusters classes whose labels collapse
    to the same normalised form, with a conservative singular/plural
    union pass on top. Each cluster of size >=2 -> one warning
    violation with ``suggested_action=REDUNDANT``."""

    @staticmethod
    def _patch_classes(monkeypatch, rows: list[dict[str, Any]]) -> None:
        """Patch ``run_aql`` to return ``rows`` for the R4 query."""

        def fake(_db, aql, *, bind_vars=None):
            assert "FOR c IN ontology_classes" in aql
            return iter(rows)

        monkeypatch.setattr(engine, "run_aql", fake)

    def test_returns_empty_when_collection_missing(self, monkeypatch):
        db = _db_with_collections()
        # Should short-circuit before ``run_aql`` -- patch it to fail
        # if the rule reaches it.

        def fake(*args, **kwargs):
            raise AssertionError("R4 must short-circuit when collection missing")

        monkeypatch.setattr(engine, "run_aql", fake)
        assert engine._r4_redundant_class(db, "OID") == []

    def test_returns_empty_when_fewer_than_two_classes(self, monkeypatch):
        db = _db_with_collections("ontology_classes")
        self._patch_classes(monkeypatch, [{"_key": "A", "label": "Alpha"}])
        assert engine._r4_redundant_class(db, "OID") == []

    def test_exact_normalised_match_clusters_classes(self, monkeypatch):
        """The classic case: two classes with the same name modulo
        whitespace + casing + punctuation."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "TotalRewards", "label": "TotalRewards"},
                {"_key": "Total_Rewards_v2", "label": "Total Rewards"},
                {"_key": "Unrelated", "label": "Wellbeing"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == RULE_R4_REDUNDANT_CLASS
        assert v.severity == SEVERITY_WARNING
        assert v.suggested_action == "REDUNDANT"
        assert set(v.entity_ids) == {"TotalRewards", "Total_Rewards_v2"}
        # Description must mention BOTH labels so a curator can decide
        # which to keep without opening another panel.
        assert "TotalRewards" in v.description
        assert "Total Rewards" in v.description

    def test_possessive_apostrophe_is_dropped(self, monkeypatch):
        """``Customer's Risk Profile`` clusters with ``CustomerRiskProfile``."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "CustomerRiskProfile", "label": "Customer Risk Profile"},
                {"_key": "CustomersRiskProfile", "label": "Customer's Risk Profile"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        assert set(violations[0].entity_ids) == {
            "CustomerRiskProfile",
            "CustomersRiskProfile",
        }

    def test_singular_plural_pass_merges_employee_and_employees(self, monkeypatch):
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Employee", "label": "Employee"},
                {"_key": "Employees", "label": "Employees"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        assert set(violations[0].entity_ids) == {"Employee", "Employees"}

    def test_plural_es_form_merges(self, monkeypatch):
        """``Class`` + ``Classes`` -- ``+es`` plural."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Class", "label": "Class"},
                {"_key": "Classes", "label": "Classes"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1

    def test_plural_ies_form_merges(self, monkeypatch):
        """``Country`` + ``Countries`` -- ``y`` -> ``ies`` plural."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Country", "label": "Country"},
                {"_key": "Countries", "label": "Countries"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        assert set(violations[0].entity_ids) == {"Country", "Countries"}

    def test_plural_pass_does_not_merge_when_only_one_form_present(
        self, monkeypatch
    ):
        """``Address`` alone should NOT be flagged just because the
        plural pass would generate ``Addresss``/``Addresses`` candidates."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Address", "label": "Address"},
                {"_key": "Other", "label": "Something completely different"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert violations == []

    def test_short_words_are_excluded_from_plural_pass(self, monkeypatch):
        """Plural pass skips forms shorter than 4 chars to avoid
        ``Cat`` matching a hypothetical ``Cats`` only by length-3
        coincidence -- prevents low-signal noise."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Cat", "label": "Cat"},
                {"_key": "Cats", "label": "Cats"},
            ],
        )

        # ``cat`` is 3 chars, below the threshold, so the plural pass
        # does NOT union them. This is intentionally conservative; the
        # cost of a false positive (curator merges legitimate distinct
        # acronyms) is higher than missing a 3-letter duplicate.
        violations = engine._r4_redundant_class(db, "OID")
        assert violations == []

    def test_falls_back_to_key_when_label_missing(self, monkeypatch):
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Account", "label": None},
                {"_key": "ACCOUNT", "label": ""},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        assert set(violations[0].entity_ids) == {"Account", "ACCOUNT"}

    def test_three_way_cluster_emits_one_violation_listing_all(self, monkeypatch):
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "HealthPlan", "label": "Health Plan"},
                {"_key": "Health_plan", "label": "health-plan"},
                {"_key": "HEALTHPLAN", "label": "HEALTHPLAN"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 1
        v = violations[0]
        assert len(v.entity_ids) == 3
        assert set(v.entity_ids) == {"HealthPlan", "Health_plan", "HEALTHPLAN"}
        assert "3 classes look redundant" in v.description

    def test_no_violations_when_all_classes_unique(self, monkeypatch):
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "A", "label": "Apple"},
                {"_key": "B", "label": "Banana"},
                {"_key": "C", "label": "Carrot"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert violations == []

    def test_violations_are_sorted_by_entity_ids_for_diffability(
        self, monkeypatch
    ):
        """Two independent clusters in one ontology -- the report's
        violation order MUST be deterministic so re-running the rule
        produces a diffable output (audit log + reflection report).

        Both base words are >= 4 chars so the plural-pass threshold
        (see ``test_short_words_are_excluded_from_plural_pass``) does
        not exclude them.
        """
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "Vehicle", "label": "Vehicle"},
                {"_key": "Vehicles", "label": "Vehicles"},
                {"_key": "Apple", "label": "Apple"},
                {"_key": "Apples", "label": "Apples"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert len(violations) == 2
        # Apple cluster sorts before Vehicle cluster (lexicographic
        # on the first entity id).
        assert violations[0].entity_ids[0].startswith("Apple")
        assert violations[1].entity_ids[0].startswith("Vehicle")

    def test_skips_rows_with_blank_keys(self, monkeypatch):
        """Defensive: a class doc without a key shouldn't crash the
        rule or contribute to clusters."""
        db = _db_with_collections("ontology_classes")
        self._patch_classes(
            monkeypatch,
            [
                {"_key": "", "label": "Phantom"},
                {"_key": "RealClass", "label": "Real Class"},
            ],
        )

        violations = engine._r4_redundant_class(db, "OID")
        assert violations == []


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

    def test_default_set_includes_all_registered_rules(self):
        ids = [rid for rid, _ in engine._DEFAULT_RULES]
        assert ids == [
            RULE_R1_SYNONYM_TRIANGLE,
            RULE_R2_SUBCLASS_CYCLE,
            RULE_R3_ORPHAN_RANGE,
            RULE_R4_REDUNDANT_CLASS,
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
                RULE_R3_ORPHAN_RANGE,
                RULE_R4_REDUNDANT_CLASS,
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
