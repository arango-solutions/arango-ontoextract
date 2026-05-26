"""Unit tests for ``app.services.schema_diff``.

Stream 5 PR 3 sub-B -- S.5. We exercise the pure helpers (no DB), then
the orchestrator (with a mocked StandardDatabase that returns
deterministic rowsets via ``run_aql``). The DB-touching helpers mock
``run_aql`` at the boundary because the AQL itself is the unit under
test in integration suites, not here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.schema_diff import (
    _by_uri,
    _constraint_join_key,
    _diff_by_uri,
    _diff_constraints,
    _evaluate_provenance,
    _schema_data_changed,
    diff_ontologies,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestByUri:
    def test_indexes_rows_by_uri(self) -> None:
        rows = [
            {"uri": "http://x/A", "label": "A"},
            {"uri": "http://x/B", "label": "B"},
        ]
        assert _by_uri(rows) == {
            "http://x/A": rows[0],
            "http://x/B": rows[1],
        }

    def test_drops_rows_without_uri(self) -> None:
        # A malformed class without a URI has no join key for the diff;
        # silently dropping it (with the rest of the rowset still
        # indexed) is the right move -- raising would force every
        # caller to pre-filter and most callers don't care.
        rows = [
            {"uri": "http://x/A", "label": "A"},
            {"label": "B"},
            {"uri": "", "label": "C"},
            {"uri": None, "label": "D"},
        ]
        out = _by_uri(rows)
        assert list(out.keys()) == ["http://x/A"]

    def test_later_row_wins_on_uri_collision(self) -> None:
        # Defensive: a malformed snapshot could have two rows with the
        # same URI (eg if temporal filtering missed one). dict
        # semantics give us last-wins which is at least deterministic.
        rows = [
            {"uri": "http://x/A", "label": "old"},
            {"uri": "http://x/A", "label": "new"},
        ]
        out = _by_uri(rows)
        assert out["http://x/A"]["label"] == "new"


class TestSchemaDataChanged:
    def test_identical_rows_not_changed(self) -> None:
        a = {"_key": "1", "uri": "x", "label": "A", "rdfs_range": "xsd:string"}
        b = {"_key": "1", "uri": "x", "label": "A", "rdfs_range": "xsd:string"}
        assert _schema_data_changed(a, b) is False

    def test_label_change_is_change(self) -> None:
        a = {"uri": "x", "label": "Old"}
        b = {"uri": "x", "label": "New"}
        assert _schema_data_changed(a, b) is True

    def test_rdfs_range_change_is_change(self) -> None:
        # The schema-evolution headliner: a datatype property went from
        # xsd:string to xsd:integer. The curator MUST see this.
        a = {"uri": "x", "rdfs_range": "http://www.w3.org/2001/XMLSchema#string"}
        b = {"uri": "x", "rdfs_range": "http://www.w3.org/2001/XMLSchema#integer"}
        assert _schema_data_changed(a, b) is True

    def test_metadata_only_change_not_a_change(self) -> None:
        # _rev, version, created, expired, ontology_id, source_run_id
        # all change on every write even when the semantic content is
        # identical. None of them must produce a 'changed' row.
        a = {
            "uri": "x",
            "label": "A",
            "_key": "k1",
            "_id": "ontology_classes/k1",
            "_rev": "1",
            "created": 1.0,
            "expired": 2.0,
            "version": 1,
            "ttlExpireAt": 100.0,
            "ontology_id": "onto_a",
            "source_run_id": "run_a",
        }
        b = {
            "uri": "x",
            "label": "A",
            "_key": "k2",
            "_id": "ontology_classes/k2",
            "_rev": "2",
            "created": 3.0,
            "expired": 4.0,
            "version": 2,
            "ttlExpireAt": 200.0,
            "ontology_id": "onto_b",
            "source_run_id": "run_b",
        }
        assert _schema_data_changed(a, b) is False

    def test_source_db_change_is_a_change(self) -> None:
        # A re-extraction repointed at a different source DB is exactly
        # the kind of schema-evolution event a curator must see. This
        # belongs IN the diff, not in the metadata-skip list.
        a = {"uri": "x", "source_db": "prod"}
        b = {"uri": "x", "source_db": "staging"}
        assert _schema_data_changed(a, b) is True

    def test_field_added_on_one_side_is_a_change(self) -> None:
        a = {"uri": "x", "label": "A"}
        b = {"uri": "x", "label": "A", "rdfs_range": "xsd:string"}
        assert _schema_data_changed(a, b) is True


class TestDiffByUri:
    def test_disjoint_uris_all_added_or_removed(self) -> None:
        a = [{"uri": "http://x/A", "label": "A"}]
        b = [{"uri": "http://x/B", "label": "B"}]
        out = _diff_by_uri(a, b)
        assert [r["uri"] for r in out["added"]] == ["http://x/B"]
        assert [r["uri"] for r in out["removed"]] == ["http://x/A"]
        assert out["changed"] == []

    def test_identical_uris_no_diff(self) -> None:
        rows = [{"uri": "http://x/A", "label": "A"}]
        out = _diff_by_uri(rows, list(rows))
        assert out["added"] == []
        assert out["removed"] == []
        assert out["changed"] == []

    def test_changed_row_carries_before_and_after(self) -> None:
        a = [{"uri": "http://x/A", "label": "Old", "rdfs_range": "xsd:string"}]
        b = [{"uri": "http://x/A", "label": "Old", "rdfs_range": "xsd:integer"}]
        out = _diff_by_uri(a, b)
        assert len(out["changed"]) == 1
        ch = out["changed"][0]
        assert ch["uri"] == "http://x/A"
        assert ch["before"]["rdfs_range"] == "xsd:string"
        assert ch["after"]["rdfs_range"] == "xsd:integer"

    def test_output_is_uri_sorted(self) -> None:
        # Stable ordering matters for human review and for test
        # determinism downstream.
        a: list[dict[str, Any]] = []
        b = [
            {"uri": "http://x/C", "label": "C"},
            {"uri": "http://x/A", "label": "A"},
            {"uri": "http://x/B", "label": "B"},
        ]
        out = _diff_by_uri(a, b)
        assert [r["uri"] for r in out["added"]] == [
            "http://x/A",
            "http://x/B",
            "http://x/C",
        ]

    def test_mixed_add_remove_change(self) -> None:
        # Realistic scenario: one class kept-and-changed, one added,
        # one removed.
        a = [
            {"uri": "http://x/Keep", "label": "Old"},
            {"uri": "http://x/Gone", "label": "ToRemove"},
        ]
        b = [
            {"uri": "http://x/Keep", "label": "New"},
            {"uri": "http://x/New", "label": "ToAdd"},
        ]
        out = _diff_by_uri(a, b)
        assert [r["uri"] for r in out["added"]] == ["http://x/New"]
        assert [r["uri"] for r in out["removed"]] == ["http://x/Gone"]
        assert [c["uri"] for c in out["changed"]] == ["http://x/Keep"]


class TestConstraintJoinKey:
    def test_complete_row_yields_tuple(self) -> None:
        row = {
            "class_uri": "http://x/C",
            "property_uri": "http://x/p",
            "restriction_type": "sh:minCount",
            "restriction_value": 1,
        }
        assert _constraint_join_key(row) == (
            "http://x/C",
            "http://x/p",
            "sh:minCount",
        )

    def test_missing_class_uri_returns_none(self) -> None:
        row = {"property_uri": "p", "restriction_type": "sh:minCount"}
        assert _constraint_join_key(row) is None

    def test_missing_property_uri_returns_none(self) -> None:
        # Class-level constraints (eg sh:closed on a NodeShape with no
        # path) have no property to join on. Skipping them is the v1
        # contract.
        row = {"class_uri": "C", "restriction_type": "sh:closed"}
        assert _constraint_join_key(row) is None

    def test_empty_string_treated_as_missing(self) -> None:
        row = {"class_uri": "", "property_uri": "p", "restriction_type": "x"}
        assert _constraint_join_key(row) is None


class TestDiffConstraints:
    def test_value_change_flagged(self) -> None:
        a = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 1,
            },
        ]
        b = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 2,  # tightened from 1 to 2
            },
        ]
        out = _diff_constraints(a, b)
        assert len(out["changed"]) == 1
        ch = out["changed"][0]
        assert ch["before"]["restriction_value"] == 1
        assert ch["after"]["restriction_value"] == 2

    def test_severity_change_alone_does_not_flag(self) -> None:
        # Severity is curator metadata, not schema. Two constraints
        # with the same (class, property, type, value) but different
        # severity are 'the same constraint' for diff purposes.
        a = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 1,
                "severity": "sh:Violation",
            }
        ]
        b = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 1,
                "severity": "sh:Warning",
            }
        ]
        out = _diff_constraints(a, b)
        assert out["changed"] == []

    def test_different_restriction_types_are_separate_constraints(self) -> None:
        # Two constraints on the same (class, property) with different
        # restriction_type are two distinct constraints. Adding a
        # pattern alongside an existing minCount means ONE added, ZERO
        # changed, ZERO removed.
        a = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 1,
            }
        ]
        b = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:minCount",
                "restriction_value": 1,
            },
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:pattern",
                "restriction_value": "^[A-Z]+$",
            },
        ]
        out = _diff_constraints(a, b)
        assert len(out["added"]) == 1
        assert out["added"][0]["restriction_type"] == "sh:pattern"
        assert out["removed"] == []
        assert out["changed"] == []

    def test_rows_with_incomplete_keys_skipped(self) -> None:
        # A constraint that doesn't carry a property_uri (eg a class-
        # level NodeShape constraint) doesn't have a join key in v1
        # and must not poison the diff. We drop those silently.
        a = [
            {"class_uri": "C", "restriction_type": "sh:closed"},
        ]
        b: list[dict[str, Any]] = []
        out = _diff_constraints(a, b)
        # Without a join key, the constraint can't be classified --
        # the contract is "skip", not "treat as removed".
        assert out["added"] == []
        assert out["removed"] == []
        assert out["changed"] == []

    def test_sh_in_list_value_change_is_change(self) -> None:
        # sh:in stores a list. The diff treats any list inequality as
        # a change, including order shifts. That's intentional for v1:
        # the underlying schema rule preserves order, so any drift is
        # signal.
        a = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:in",
                "restriction_value": ["S", "M", "L"],
            }
        ]
        b = [
            {
                "class_uri": "C",
                "property_uri": "p",
                "restriction_type": "sh:in",
                "restriction_value": ["S", "M", "L", "XL"],
            }
        ]
        out = _diff_constraints(a, b)
        assert len(out["changed"]) == 1


class TestEvaluateProvenance:
    def test_matching_db_and_host_is_compatible(self) -> None:
        a = {"source_db": "prod", "source_host": "http://h:8529"}
        b = {"source_db": "prod", "source_host": "http://h:8529"}
        compat, warning = _evaluate_provenance(a, b)
        assert compat is True
        assert warning is None

    def test_different_db_is_warned(self) -> None:
        a = {"source_db": "prod", "source_host": "http://h:8529"}
        b = {"source_db": "staging", "source_host": "http://h:8529"}
        compat, warning = _evaluate_provenance(a, b)
        assert compat is False
        assert warning is not None
        assert "prod" in warning
        assert "staging" in warning

    def test_different_host_is_warned(self) -> None:
        a = {"source_db": "x", "source_host": "http://a:8529"}
        b = {"source_db": "x", "source_host": "http://b:8529"}
        compat, warning = _evaluate_provenance(a, b)
        assert compat is False
        assert warning is not None

    def test_one_side_missing_provenance_is_warned(self) -> None:
        # If only one of the two ontologies was created via schema
        # extraction, the diff is still legal but ``compatible=False``
        # signals "not schema evolution".
        a = {"source_db": "prod", "source_host": "http://h:8529"}
        b: dict[str, Any] = {}
        compat, warning = _evaluate_provenance(a, b)
        assert compat is False
        assert warning is not None
        assert "not created via schema extraction" in warning

    def test_both_missing_provenance_is_warned(self) -> None:
        compat, warning = _evaluate_provenance({}, {})
        assert compat is False
        assert warning is not None


# ---------------------------------------------------------------------------
# Orchestrator (diff_ontologies)
# ---------------------------------------------------------------------------


def _mock_db() -> MagicMock:
    """Mock StandardDatabase with the three required collections
    declared present. ``run_aql`` is patched separately per test."""
    db = MagicMock()
    db.has_collection.return_value = True
    return db


class TestDiffOntologies:
    def test_raises_when_same_ontology_id(self) -> None:
        # Self-diff would silently return all-empty buckets, which
        # would mislead a caller into thinking nothing changed when in
        # fact they passed the same ID twice by mistake. Fail loud.
        with pytest.raises(ValueError, match="against itself"):
            diff_ontologies(db=_mock_db(), ontology_a="x", ontology_b="x")

    @patch("app.services.schema_diff.run_aql")
    def test_empty_ontologies_yield_empty_diff(self, mock_aql: MagicMock) -> None:
        mock_aql.return_value = iter([])
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        for bucket in ("classes", "properties", "constraints"):
            assert out[bucket] == {"added": [], "removed": [], "changed": []}
        assert all(v == 0 for v in out["summary"].values())
        # Neither side has provenance -> not "schema evolution"
        # but the diff still completes.
        assert out["provenance"]["compatible"] is False
        assert out["provenance"]["warning"] is not None

    @patch("app.services.schema_diff.run_aql")
    def test_added_class_appears_in_classes_added(self, mock_aql: MagicMock) -> None:
        """End-to-end: one extraction had no classes, the next added
        one. The 'added' bucket must surface it; summary count must
        match.
        """
        # AQL call order in diff_ontologies:
        # 1. classes for ontology_a
        # 2. classes for ontology_b
        # 3. properties for ontology_a x3 collections
        # 4. properties for ontology_b x3 collections
        # 5. constraints for ontology_a
        # 6. constraints for ontology_b
        # 7. provenance for ontology_a
        # 8. provenance for ontology_b
        new_class = {
            "_key": "k1",
            "uri": "http://x/Customer",
            "label": "Customer",
            "ontology_id": "b",
        }
        mock_aql.side_effect = [
            iter([]),  # classes a
            iter([new_class]),  # classes b
            iter([]),  # properties_a/ontology_properties
            iter([]),  # properties_a/ontology_object_properties
            iter([]),  # properties_a/ontology_datatype_properties
            iter([]),  # properties_b/ontology_properties
            iter([]),  # properties_b/ontology_object_properties
            iter([]),  # properties_b/ontology_datatype_properties
            iter([]),  # constraints a
            iter([]),  # constraints b
            iter([]),  # provenance a
            iter([]),  # provenance b
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert len(out["classes"]["added"]) == 1
        assert out["classes"]["added"][0]["uri"] == "http://x/Customer"
        assert out["summary"]["classes_added"] == 1
        assert out["summary"]["classes_removed"] == 0

    @patch("app.services.schema_diff.run_aql")
    def test_property_range_drift_appears_in_changed(self, mock_aql: MagicMock) -> None:
        prop_a = {
            "_key": "p1",
            "uri": "http://x/Customer.age",
            "label": "age",
            "rdfs_range": "http://www.w3.org/2001/XMLSchema#integer",
            "ontology_id": "a",
        }
        prop_b = {
            "_key": "p2",
            "uri": "http://x/Customer.age",
            "label": "age",
            "rdfs_range": "http://www.w3.org/2001/XMLSchema#string",
            "ontology_id": "b",
        }
        mock_aql.side_effect = [
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([prop_a]),  # one prop in datatype collection for a
            iter([]),
            iter([]),
            iter([prop_b]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert len(out["properties"]["changed"]) == 1
        change = out["properties"]["changed"][0]
        assert "integer" in change["before"]["rdfs_range"]
        assert "string" in change["after"]["rdfs_range"]
        assert out["summary"]["properties_changed"] == 1

    @patch("app.services.schema_diff.run_aql")
    def test_constraint_tightened_appears_in_constraints_changed(self, mock_aql: MagicMock) -> None:
        # The flagship schema-evolution case: minCount went from 0
        # (effectively absent) to 1 (required). Curator must see it.
        ca = {
            "class_uri": "http://x/Customer",
            "property_uri": "http://x/Customer.email",
            "restriction_type": "sh:minCount",
            "restriction_value": 0,
        }
        cb = {
            "class_uri": "http://x/Customer",
            "property_uri": "http://x/Customer.email",
            "restriction_type": "sh:minCount",
            "restriction_value": 1,
        }
        mock_aql.side_effect = [
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([ca]),
            iter([cb]),
            iter([]),
            iter([]),
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert len(out["constraints"]["changed"]) == 1
        ch = out["constraints"]["changed"][0]
        assert ch["before"]["restriction_value"] == 0
        assert ch["after"]["restriction_value"] == 1
        assert ch["restriction_type"] == "sh:minCount"

    @patch("app.services.schema_diff.run_aql")
    def test_provenance_match_marks_compatible(self, mock_aql: MagicMock) -> None:
        prov = {"source_db": "prod", "source_host": "http://h:8529"}
        mock_aql.side_effect = [
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([prov]),
            iter([prov]),
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert out["provenance"]["compatible"] is True
        assert out["provenance"]["warning"] is None
        assert out["provenance"]["a"] == prov
        assert out["provenance"]["b"] == prov

    @patch("app.services.schema_diff.run_aql")
    def test_provenance_mismatch_emits_warning_but_still_returns_diff(
        self, mock_aql: MagicMock
    ) -> None:
        prov_a = {"source_db": "prod", "source_host": "http://h:8529"}
        prov_b = {"source_db": "staging", "source_host": "http://h:8529"}
        mock_aql.side_effect = [
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([prov_a]),
            iter([prov_b]),
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert out["provenance"]["compatible"] is False
        assert out["provenance"]["warning"] is not None
        assert "prod" in out["provenance"]["warning"]
        assert "staging" in out["provenance"]["warning"]
        # And critically: the diff itself is still returned, not refused.
        assert "classes" in out
        assert "properties" in out

    @patch("app.services.schema_diff.run_aql")
    def test_summary_counts_match_buckets(self, mock_aql: MagicMock) -> None:
        # Belt-and-braces: the summary section must not drift from
        # actual bucket lengths. A growing diff API is easy to break
        # here as new categories get added.
        added_cls = {"_key": "1", "uri": "http://x/A", "label": "A"}
        removed_cls = {"_key": "2", "uri": "http://x/B", "label": "B"}
        kept_cls_a = {"_key": "3", "uri": "http://x/C", "label": "Old"}
        kept_cls_b = {"_key": "4", "uri": "http://x/C", "label": "New"}
        mock_aql.side_effect = [
            iter([removed_cls, kept_cls_a]),  # classes a
            iter([added_cls, kept_cls_b]),  # classes b
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
        ]
        out = diff_ontologies(db=_mock_db(), ontology_a="a", ontology_b="b")
        assert out["summary"]["classes_added"] == len(out["classes"]["added"]) == 1
        assert out["summary"]["classes_removed"] == len(out["classes"]["removed"]) == 1
        assert out["summary"]["classes_changed"] == len(out["classes"]["changed"]) == 1

    @patch("app.services.schema_diff.run_aql")
    def test_missing_classes_collection_yields_empty_buckets(self, mock_aql: MagicMock) -> None:
        """If the AOE database has no ``ontology_classes`` collection
        at all (eg fresh install, mid-migration), the diff must
        degrade to empty buckets rather than raising. This mirrors
        ``temporal.get_diff``'s defensive collection check.
        """
        db = MagicMock()
        db.has_collection.return_value = False  # nothing exists
        # No AQL is even invoked when all collections are absent.
        mock_aql.return_value = iter([])
        out = diff_ontologies(db=db, ontology_a="a", ontology_b="b")
        for bucket in ("classes", "properties", "constraints"):
            assert out[bucket] == {"added": [], "removed": [], "changed": []}
