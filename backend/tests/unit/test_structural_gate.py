"""Unit tests for the Structural Gate agent (Stream 15 SO.1).

Covers the class index / resolver, the health report metrics, the two
deterministic repair rules (URI normalization + link recovery), input purity,
and the LangGraph node's flag-gated pass-through behaviour.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.extraction.agents.structural_gate import (
    _ClassIndex,
    compute_health_report,
    repair_relationship_targets,
    structural_gate_node,
)
from app.models.ontology import (
    ExtractedAttribute,
    ExtractedClass,
    ExtractedRelationship,
    ExtractionResult,
    SourceEvidence,
)

NS = "http://ex.org/onto"


def _cls(
    fragment: str,
    label: str,
    *,
    parent_uri: str | None = None,
    attributes: list[ExtractedAttribute] | None = None,
    relationships: list[ExtractedRelationship] | None = None,
) -> ExtractedClass:
    return ExtractedClass(
        uri=f"{NS}#{fragment}",
        label=label,
        description=f"{label} test class",
        parent_uri=parent_uri,
        confidence=0.9,
        attributes=attributes or [],
        relationships=relationships or [],
    )


def _rel(
    fragment: str,
    label: str,
    target_class_uri: str,
    *,
    description: str = "",
    evidence_text: str = "",
) -> ExtractedRelationship:
    evidence = []
    if evidence_text:
        evidence = [SourceEvidence(evidence_text=evidence_text)]
    return ExtractedRelationship(
        uri=f"{NS}#{fragment}",
        label=label,
        description=description,
        target_class_uri=target_class_uri,
        confidence=0.8,
        evidence=evidence,
    )


def _state(classes: list[ExtractedClass] | None) -> dict:
    result = (
        ExtractionResult(classes=classes, pass_number=0, model="test")
        if classes is not None
        else None
    )
    return {
        "run_id": "r1",
        "document_id": "d1",
        "consistency_result": result,
        "step_logs": [],
    }


@pytest.fixture
def gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "structural_gate_enabled", True)


# ---------------------------------------------------------------------------
# _ClassIndex resolution tiers
# ---------------------------------------------------------------------------


class TestClassIndexResolution:
    def test_exact_uri_resolves_to_itself(self):
        idx = _ClassIndex([_cls("Customer", "Customer")])
        assert idx.resolution_tier(f"{NS}#Customer") == ("uri", f"{NS}#Customer")

    def test_bare_fragment_resolves_to_canonical_uri(self):
        idx = _ClassIndex([_cls("Customer", "Customer")])
        # A target that is only the fragment matches tier 2 and yields the URI.
        assert idx.resolution_tier("Customer") == ("fragment", f"{NS}#Customer")

    def test_label_tier_resolves_humanized_fragment(self):
        idx = _ClassIndex([_cls("CustomerAccount", "Customer Account")])
        # snake_case target -> humanized "customer account" -> normalized label hit.
        tier, canonical = idx.resolution_tier("http://other#customer_account")
        assert tier == "label"
        assert canonical == f"{NS}#CustomerAccount"

    def test_unknown_target_is_a_miss(self):
        idx = _ClassIndex([_cls("Customer", "Customer")])
        assert idx.resolution_tier(f"{NS}#Ghost") == ("miss", None)

    def test_resolve_returns_none_on_miss(self):
        idx = _ClassIndex([_cls("Customer", "Customer")])
        assert idx.resolve(f"{NS}#Ghost") is None
        assert idx.resolve("") is None


# ---------------------------------------------------------------------------
# compute_health_report
# ---------------------------------------------------------------------------


class TestHealthReport:
    def test_counts_dangling_islands_orphans_and_propertyless(self):
        account = _cls(
            "Account",
            "Account",
            attributes=[ExtractedAttribute(uri=f"{NS}#balance", label="balance")],
            relationships=[
                _rel("hasHolder", "has holder", f"{NS}#Customer"),  # resolvable
                _rel("ghostLink", "links to", f"{NS}#Ghost"),  # dangling
            ],
        )
        customer = _cls("Customer", "Customer")  # targeted -> not island; no props/parent
        island = _cls("Island", "Island")  # never targeted, no rels/props/parent

        classes = [account, customer, island]
        report = compute_health_report(classes, _ClassIndex(classes))

        assert report["class_count"] == 3
        assert report["relationship_count"] == 2
        assert report["dangling_relationship_target_count"] == 1
        assert report["dangling_relationship_targets"][0]["target_class_uri"] == f"{NS}#Ghost"
        assert report["island_class_count"] == 1
        assert report["island_classes"] == [f"{NS}#Island"]
        assert report["classes_without_parent_count"] == 3
        # Customer + Island have neither attributes nor relationships.
        assert report["classes_without_properties_count"] == 2

    def test_parent_link_keeps_class_off_the_island_list(self):
        parent = _cls("Vehicle", "Vehicle")
        child = _cls("Car", "Car", parent_uri=f"{NS}#Vehicle")
        report = compute_health_report([parent, child], _ClassIndex([parent, child]))
        # Child has a resolvable parent; parent is referenced as a parent.
        assert report["island_class_count"] == 0


# ---------------------------------------------------------------------------
# repair_relationship_targets
# ---------------------------------------------------------------------------


class TestRepair:
    def test_uri_normalization_rewrites_fragment_target_to_canonical(self):
        account = _cls("Account", "Account", relationships=[_rel("r1", "has holder", "Customer")])
        customer = _cls("Customer", "Customer")
        classes = [account, customer]

        repaired, repairs = repair_relationship_targets(classes, _ClassIndex(classes))

        assert len(repairs) == 1
        assert repairs[0]["rule"] == "uri_normalization"
        assert repairs[0]["from_target"] == "Customer"
        assert repairs[0]["to_target"] == f"{NS}#Customer"
        assert repaired[0].relationships[0].target_class_uri == f"{NS}#Customer"

    def test_link_recovery_repoints_missing_target_from_evidence(self):
        account = _cls(
            "Account",
            "Account",
            relationships=[
                _rel(
                    "r1",
                    "is held by",
                    f"{NS}#Ghost",
                    description="Each account is held by a Customer.",
                )
            ],
        )
        customer = _cls("Customer", "Customer")
        classes = [account, customer]

        repaired, repairs = repair_relationship_targets(classes, _ClassIndex(classes))

        assert len(repairs) == 1
        assert repairs[0]["rule"] == "link_recovery"
        assert repairs[0]["to_target"] == f"{NS}#Customer"
        assert repaired[0].relationships[0].target_class_uri == f"{NS}#Customer"

    def test_canonical_target_is_left_untouched(self):
        account = _cls("Account", "Account", relationships=[_rel("r1", "h", f"{NS}#Customer")])
        customer = _cls("Customer", "Customer")
        classes = [account, customer]

        repaired, repairs = repair_relationship_targets(classes, _ClassIndex(classes))

        assert repairs == []
        assert repaired[0] is classes[0]  # unchanged object reused

    def test_unrecoverable_target_stays_dangling(self):
        account = _cls(
            "Account",
            "Account",
            relationships=[_rel("r1", "x", f"{NS}#Ghost", description="no class names here")],
        )
        classes = [account]
        repaired, repairs = repair_relationship_targets(classes, _ClassIndex(classes))
        assert repairs == []
        assert repaired[0].relationships[0].target_class_uri == f"{NS}#Ghost"

    def test_does_not_mutate_input_classes(self):
        account = _cls("Account", "Account", relationships=[_rel("r1", "h", "Customer")])
        customer = _cls("Customer", "Customer")
        classes = [account, customer]

        repair_relationship_targets(classes, _ClassIndex(classes))

        # Original relationship target is still the un-normalized fragment.
        assert account.relationships[0].target_class_uri == "Customer"

    def test_link_recovery_excludes_owning_class_to_avoid_self_loop(self):
        # The description names the owning class; recovery must not self-loop.
        account = _cls(
            "Account",
            "Account",
            relationships=[
                _rel("r1", "x", f"{NS}#Ghost", description="An Account relates to an Account.")
            ],
        )
        classes = [account]
        repaired, repairs = repair_relationship_targets(classes, _ClassIndex(classes))
        assert repairs == []
        assert repaired[0].relationships[0].target_class_uri == f"{NS}#Ghost"


# ---------------------------------------------------------------------------
# structural_gate_node
# ---------------------------------------------------------------------------


class TestStructuralGateNode:
    def test_disabled_is_passthrough(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "structural_gate_enabled", False)
        account = _cls("Account", "Account", relationships=[_rel("r1", "h", "Customer")])
        out = structural_gate_node(_state([account, _cls("Customer", "Customer")]))

        assert "consistency_result" not in out  # no rewrite
        assert "structural_health" not in out
        assert out["step_logs"][0]["status"] == "skipped"
        assert out["step_logs"][0]["metadata"]["reason"] == "disabled"

    def test_no_input_is_skipped(self, gate_enabled):
        out = structural_gate_node(_state(None))
        assert out["structural_health"] is None
        assert out["step_logs"][0]["status"] == "skipped"
        assert out["step_logs"][0]["metadata"]["reason"] == "no_input"

    def test_empty_classes_is_skipped(self, gate_enabled):
        out = structural_gate_node(_state([]))
        assert out["structural_health"] is None
        assert out["step_logs"][0]["status"] == "skipped"

    def test_enabled_applies_repairs_and_reports_before_after(self, gate_enabled):
        account = _cls(
            "Account",
            "Account",
            relationships=[
                _rel("r1", "has holder", "Customer"),  # fragment -> normalized
                _rel(
                    "r2",
                    "is held by",
                    f"{NS}#Ghost",
                    description="held by a Customer",
                ),  # miss -> recovered
            ],
        )
        customer = _cls("Customer", "Customer")
        out = structural_gate_node(_state([account, customer]))

        health = out["structural_health"]
        assert health["status"] == "completed"
        assert health["repair_count"] == 2
        # Before: r1 is resolvable by fragment, r2 is a true miss -> 1 dangling.
        assert health["before"]["dangling_relationship_target_count"] == 1
        # After: both relationships point at the canonical Customer URI.
        assert health["after"]["dangling_relationship_target_count"] == 0

        repaired_account = out["consistency_result"].classes[0]
        assert all(
            rel.target_class_uri == f"{NS}#Customer" for rel in repaired_account.relationships
        )

        step = out["step_logs"][0]
        assert step["step"] == "structural_gate"
        assert step["status"] == "completed"
        assert step["metadata"]["repair_count"] == 2
        assert step["metadata"]["dangling_after"] == 0
