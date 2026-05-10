"""Unit tests for ``app.services.edge_repair``.

Two layers exercised:

* :func:`find_range_class_for_orphan` -- pure matcher; tested with
  hand-built dicts.
* :func:`repair_orphan_object_property_ranges` -- orchestrator; tested
  against a ``MagicMock`` DB so we can assert the AQL inputs and the
  edges it would have inserted, without needing live ArangoDB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.db.temporal_constants import NEVER_EXPIRES
from app.services.edge_repair import (
    REPAIR_SOURCE,
    RangeMatch,
    find_range_class_for_orphan,
    repair_orphan_object_property_ranges,
)

# ---------------------------------------------------------------------------
# find_range_class_for_orphan
# ---------------------------------------------------------------------------


def _cls(key: str, label: str | None = None) -> dict[str, Any]:
    return {"_key": key, "label": label if label is not None else key}


def _orphan(
    *,
    description: str = "",
    evidence_text: str = "",
    source_spans: list[str] | None = None,
    label: str = "",
) -> dict[str, Any]:
    ev: list[dict[str, Any]] = []
    if evidence_text or source_spans:
        ev.append(
            {
                "evidence_text": evidence_text,
                "source_spans": source_spans or [],
                "evidence_confidence": 0.9,
            }
        )
    return {
        "_key": "Domain_does_thing",
        "_id": "ontology_object_properties/Domain_does_thing",
        "label": label,
        "description": description,
        "evidence": ev,
    }


class TestFindRangeClassForOrphanHappyPath:
    def test_class_key_present_in_description(self):
        match = find_range_class_for_orphan(
            _orphan(description="A Customer holds an Account."),
            [_cls("Account"), _cls("Customer")],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "Account"
        assert match.matched_via == "key"

    def test_class_label_with_spaces_present_in_description(self):
        match = find_range_class_for_orphan(
            _orphan(description="Generates a Customer Risk Profile."),
            [_cls("CustomerRiskProfile", "Customer Risk Profile")],
            domain_class_key="KYCAssessment",
        )
        assert match is not None
        assert match.class_key == "CustomerRiskProfile"
        # Either the normalised key or the normalised label can win since
        # they normalise to the same string -- just confirm match_via is set.
        assert match.matched_via in ("key", "label")

    def test_match_in_evidence_text(self):
        match = find_range_class_for_orphan(
            _orphan(evidence_text="The Mortgage covers the property."),
            [_cls("Mortgage")],
            domain_class_key="Application",
        )
        assert match is not None
        assert match.class_key == "Mortgage"

    def test_match_in_source_spans(self):
        match = find_range_class_for_orphan(
            _orphan(source_spans=["...Reconciliation Break..."]),
            [_cls("ReconciliationBreak", "Reconciliation Break")],
            domain_class_key="Reconciliation",
        )
        assert match is not None
        assert match.class_key == "ReconciliationBreak"


class TestFindRangeClassForOrphanDisambiguation:
    def test_longest_match_wins(self):
        # Both "Account" and "BankAccount" appear as substrings of the
        # description. Longest-first ensures the right one wins.
        match = find_range_class_for_orphan(
            _orphan(description="Customer opens a Bank Account."),
            [_cls("Account"), _cls("BankAccount", "Bank Account")],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "BankAccount"
        # The shorter one is recorded as an other_candidate so the report
        # can flag ambiguity for human review.
        assert "Account" in match.other_candidates

    def test_domain_class_excluded_to_prevent_self_loop(self):
        # "Customer" appears in the signal text but is the domain. If we
        # didn't exclude it, the property would self-loop.
        match = find_range_class_for_orphan(
            _orphan(description="The Customer's Risk Profile is generated."),
            [
                _cls("Customer"),
                _cls("CustomerRiskProfile", "Customer Risk Profile"),
            ],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "CustomerRiskProfile"

    def test_multiple_distinct_candidates_records_others(self):
        match = find_range_class_for_orphan(
            _orphan(description="Connects an Account to a Mortgage."),
            [_cls("Account"), _cls("Mortgage")],
            domain_class_key="Application",
        )
        assert match is not None
        assert match.class_key in ("Account", "Mortgage")
        assert len(match.other_candidates) == 1


class TestFindRangeClassForOrphanNoMatch:
    def test_signal_mentions_no_extracted_class(self):
        # Mirrors real unrecoverable orphans -- the LLM mentioned "ACH Batch"
        # but never extracted it as a class.
        match = find_range_class_for_orphan(
            _orphan(description="An ACH Batch contains multiple ACH Entries."),
            [_cls("ACHPaymentProcessing", "ACH Payment Processing")],
            domain_class_key="ACHPaymentProcessing",
        )
        assert match is None

    def test_empty_signal_text_returns_none(self):
        assert find_range_class_for_orphan(
            _orphan(),
            [_cls("Account")],
            domain_class_key="Customer",
        ) is None

    def test_no_classes_returns_none(self):
        assert find_range_class_for_orphan(
            _orphan(description="Customer holds Account."),
            [],
            domain_class_key="Customer",
        ) is None

    def test_only_domain_class_present_returns_none(self):
        assert find_range_class_for_orphan(
            _orphan(description="Customer is mentioned again."),
            [_cls("Customer")],
            domain_class_key="Customer",
        ) is None


class TestFindRangeClassForOrphanNormalisation:
    def test_case_insensitive(self):
        match = find_range_class_for_orphan(
            _orphan(description="customer signs a MORTGAGE."),
            [_cls("Mortgage")],
            domain_class_key="Customer",
        )
        assert match is not None and match.class_key == "Mortgage"

    def test_punctuation_and_whitespace_ignored(self):
        # Class label "ACH Batch" must match "ACH-Batch" or "ACHBatch".
        match = find_range_class_for_orphan(
            _orphan(description="processes ACH-Batch records"),
            [_cls("ACHBatch", "ACH Batch")],
            domain_class_key="Processor",
        )
        assert match is not None and match.class_key == "ACHBatch"

    def test_skips_non_string_class_key_safely(self):
        # Defensive: a malformed class doc shouldn't blow up the matcher.
        match = find_range_class_for_orphan(
            _orphan(description="Customer holds Account."),
            [{"_key": 12345, "label": "weird"}, _cls("Account")],
            domain_class_key="Customer",
        )
        assert match is not None and match.class_key == "Account"

    def test_skips_non_string_label_safely(self):
        match = find_range_class_for_orphan(
            _orphan(description="Customer holds Account."),
            [{"_key": "Account", "label": None}],
            domain_class_key="Customer",
        )
        assert match is not None and match.class_key == "Account"

    def test_possessive_apostrophe_s_is_stripped(self):
        # "Customer's Risk Profile" must still match "CustomerRiskProfile"
        # (the apostrophe-s would otherwise leave a stray "s" between
        # "customer" and "risk" after normalisation).
        match = find_range_class_for_orphan(
            _orphan(description="The Customer's Risk Profile is generated."),
            [_cls("Customer"), _cls("CustomerRiskProfile", "Customer Risk Profile")],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "CustomerRiskProfile"

    def test_curly_quote_possessive_is_stripped(self):
        # Some LLMs / tokenisers normalise apostrophes to U+2019.
        match = find_range_class_for_orphan(
            _orphan(description="The Customer\u2019s Risk Profile is generated."),
            [_cls("CustomerRiskProfile", "Customer Risk Profile")],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "CustomerRiskProfile"

    def test_label_only_match_when_key_does_not_match(self):
        # Class key is "X1" but its human label is "Mortgage"; the description
        # only mentions "Mortgage".
        match = find_range_class_for_orphan(
            _orphan(description="customer signs a Mortgage."),
            [_cls("X1", "Mortgage")],
            domain_class_key="Customer",
        )
        assert match is not None
        assert match.class_key == "X1"
        assert match.matched_via == "label"


class TestFindRangeClassForOrphanReturnContract:
    def test_returns_range_match_instance(self):
        m = find_range_class_for_orphan(
            _orphan(description="Mortgage details"),
            [_cls("Mortgage")],
            domain_class_key="Customer",
        )
        assert isinstance(m, RangeMatch)
        assert m.class_key == "Mortgage"
        assert m.matched_text  # non-empty
        assert m.matched_via in ("key", "label")
        assert isinstance(m.other_candidates, tuple)


# ---------------------------------------------------------------------------
# repair_orphan_object_property_ranges
# ---------------------------------------------------------------------------


def _mock_db(
    *,
    classes: list[dict[str, Any]],
    properties: list[dict[str, Any]],
    domain_edges: list[dict[str, Any]],
    range_edges: list[dict[str, Any]],
    insert_should_raise: bool = False,
) -> tuple[MagicMock, MagicMock]:
    """Build a MagicMock DB whose ``run_aql`` (via the module under test)
    returns the right slice for each query.

    Returns ``(db_mock, range_collection_mock)`` so tests can assert on
    insert calls.
    """
    db = MagicMock()
    db.has_collection.return_value = True

    range_col = MagicMock()
    if insert_should_raise:
        range_col.insert.side_effect = RuntimeError("simulated insert failure")
    db.collection.return_value = range_col

    # The matcher reads from a separate aql.execute path -- the service uses
    # ``app.db.utils.run_aql``. Patch via monkeypatch in the test using
    # this helper.
    return db, range_col


def _patched_run_aql(monkeypatch, *, classes, properties, domain_edges, range_edges):
    """Patch ``app.services.edge_repair.run_aql`` to return per-query data."""

    def fake_run_aql(_db, query, bind_vars=None):
        # _db / bind_vars are accepted to match the real signature; the fake
        # only branches on the query text.
        del bind_vars
        q = query
        if "FOR c IN ontology_classes" in q:
            return iter(classes)
        if "FOR p IN ontology_object_properties" in q:
            return iter(properties)
        if "FOR e IN rdfs_domain" in q:
            return iter(
                [
                    {"prop_id": e["_from"], "class_id": e["_to"]}
                    for e in domain_edges
                ]
            )
        if "FOR e IN rdfs_range_class" in q:
            return iter([e["_from"] for e in range_edges])
        raise AssertionError(f"unexpected query: {q!r}")

    monkeypatch.setattr("app.services.edge_repair.run_aql", fake_run_aql)


class TestRepairOrchestrator:
    def test_repairs_one_clear_orphan(self, monkeypatch):
        classes = [_cls("KYCAssessment"), _cls("CustomerRiskProfile", "Customer Risk Profile")]
        prop = {
            "_id": "ontology_object_properties/KYC_generates_risk_profile",
            "_key": "KYC_generates_risk_profile",
            "label": "generates Risk Profile",
            "description": "Generates a Customer Risk Profile.",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {
                "_from": "ontology_object_properties/KYC_generates_risk_profile",
                "_to": "ontology_classes/KYCAssessment",
            }
        ]
        range_edges: list[dict[str, Any]] = []

        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 1
        assert len(report.repaired) == 1
        assert len(report.unrecoverable) == 0
        r = report.repaired[0]
        assert r.prop_key == "KYC_generates_risk_profile"
        assert r.domain_class_key == "KYCAssessment"
        assert r.range_class_key == "CustomerRiskProfile"

        # Edge insert was called exactly once with the expected shape.
        assert range_col.insert.call_count == 1
        edge_doc = range_col.insert.call_args.args[0]
        assert edge_doc["_from"] == "ontology_object_properties/KYC_generates_risk_profile"
        assert edge_doc["_to"] == "ontology_classes/CustomerRiskProfile"
        assert edge_doc["ontology_id"] == "OID"
        assert edge_doc["expired"] == NEVER_EXPIRES
        assert edge_doc["repair_meta"]["source"] == REPAIR_SOURCE
        assert edge_doc["repair_meta"]["matched_via"] in ("key", "label")
        assert "matched_text" in edge_doc["repair_meta"]
        assert "repaired_at" in edge_doc["repair_meta"]

    def test_unrecoverable_orphan_does_not_insert(self, monkeypatch):
        classes = [_cls("ACHPaymentProcessing", "ACH Payment Processing")]
        prop = {
            "_id": "ontology_object_properties/ACH_contains",
            "_key": "ACH_contains",
            "label": "contains",
            "description": "An ACH Batch contains multiple ACH Entries.",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {
                "_from": "ontology_object_properties/ACH_contains",
                "_to": "ontology_classes/ACHPaymentProcessing",
            }
        ]
        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 1
        assert len(report.repaired) == 0
        assert len(report.unrecoverable) == 1
        assert report.unrecoverable[0].prop_key == "ACH_contains"
        assert range_col.insert.call_count == 0

    def test_dry_run_does_not_insert_but_populates_report(self, monkeypatch):
        classes = [_cls("KYCAssessment"), _cls("CustomerRiskProfile", "Customer Risk Profile")]
        prop = {
            "_id": "ontology_object_properties/p1",
            "_key": "p1",
            "label": "x",
            "description": "links to Customer Risk Profile",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {
                "_from": "ontology_object_properties/p1",
                "_to": "ontology_classes/KYCAssessment",
            }
        ]
        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )

        report = repair_orphan_object_property_ranges(db, "OID", dry_run=True)

        assert len(report.repaired) == 1
        assert range_col.insert.call_count == 0  # the whole point of dry-run

    def test_already_ranged_property_is_skipped(self, monkeypatch):
        classes = [_cls("A"), _cls("B")]
        prop = {
            "_id": "ontology_object_properties/p1",
            "_key": "p1",
            "label": "x",
            "description": "mentions B",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/A"}
        ]
        range_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/B"}
        ]
        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 0
        assert range_col.insert.call_count == 0

    def test_property_without_domain_edge_is_recorded_separately(self, monkeypatch):
        classes = [_cls("A")]
        prop = {
            "_id": "ontology_object_properties/orphan_no_domain",
            "_key": "orphan_no_domain",
            "label": "x",
            "description": "mentions A",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=[],
            range_edges=[],
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=[],
            range_edges=[],
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 1
        assert report.repaired == []
        assert report.unrecoverable == []
        assert "orphan_no_domain" in report.no_domain
        assert range_col.insert.call_count == 0

    def test_insert_failure_demotes_to_unrecoverable(self, monkeypatch):
        # An insert failure must NOT be silently swallowed (the original bug
        # we're fixing did exactly that). The report must reflect reality.
        classes = [_cls("KYCAssessment"), _cls("CustomerRiskProfile", "Customer Risk Profile")]
        prop = {
            "_id": "ontology_object_properties/p1",
            "_key": "p1",
            "label": "x",
            "description": "links to Customer Risk Profile",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/KYCAssessment"}
        ]
        # ``insert_should_raise=True`` wires the side_effect on range_col;
        # we don't need a direct handle to it after that.
        db, _range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
            insert_should_raise=True,
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 1
        assert len(report.repaired) == 0
        assert len(report.unrecoverable) == 1
        assert "insert failed" in report.unrecoverable[0].description

    def test_idempotent_second_run_finds_no_orphans(self, monkeypatch):
        # First-run state: an orphan exists.
        classes = [_cls("A"), _cls("B")]
        prop = {
            "_id": "ontology_object_properties/p1",
            "_key": "p1",
            "label": "x",
            "description": "mentions B",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/A"}
        ]
        # Simulate the world AFTER the first repair: range edge now exists.
        range_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/B"}
        ]
        db, range_col = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=range_edges,
        )

        report = repair_orphan_object_property_ranges(db, "OID")

        assert report.orphans_found == 0
        assert report.repaired == []
        assert range_col.insert.call_count == 0

    def test_missing_required_collection_returns_empty_report(self):
        db = MagicMock()
        db.has_collection.return_value = False
        report = repair_orphan_object_property_ranges(db, "OID")
        assert report.orphans_found == 0
        assert report.repaired == []
        # The contract: nothing was inserted; nothing was queried.
        db.collection.assert_not_called()

    def test_report_to_dict_round_trip(self, monkeypatch):
        classes = [_cls("KYC"), _cls("CRP", "Customer Risk Profile")]
        prop = {
            "_id": "ontology_object_properties/p1",
            "_key": "p1",
            "label": "x",
            "description": "Customer Risk Profile.",
            "evidence": [],
            "ontology_id": "OID",
            "expired": NEVER_EXPIRES,
        }
        domain_edges = [
            {"_from": "ontology_object_properties/p1", "_to": "ontology_classes/KYC"}
        ]
        db, _ = _mock_db(
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )
        _patched_run_aql(
            monkeypatch,
            classes=classes,
            properties=[prop],
            domain_edges=domain_edges,
            range_edges=[],
        )
        report = repair_orphan_object_property_ranges(db, "OID")
        d = report.to_dict()
        assert d["ontology_id"] == "OID"
        assert d["orphans_found"] == 1
        assert d["repaired_count"] == 1
        assert d["repaired"][0]["range_class_key"] == "CRP"
        # Ensure all expected keys are present so the admin endpoint contract
        # is stable.
        for k in (
            "ontology_id",
            "orphans_found",
            "repaired_count",
            "unrecoverable_count",
            "no_domain_count",
            "repaired",
            "unrecoverable",
            "no_domain",
        ):
            assert k in d


