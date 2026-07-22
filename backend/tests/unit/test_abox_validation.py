"""Unit tests for A-box validation + hallucination control (Stream 21 / AB-PR5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import abox_validation as av


class TestUngrounded:
    def test_flags_individuals_without_span(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"key": "i1", "label": "Ghost"}]  # AQL already filtered to ungrounded
        with patch.object(av, "run_aql", return_value=iter(rows)):
            out = av._ungrounded_individuals(db, "o1")
        assert len(out) == 1
        assert out[0].rule_id == av.RULE_ABOX_UNGROUNDED
        assert out[0].suggested_action == av.VERDICT_UNCERTAIN

    def test_skips_when_collection_missing(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert av._ungrounded_individuals(db, "o1") == []


class TestDanglingType:
    def test_flags_missing_class(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"ind": "ontology_individuals/i1", "cls": "ontology_classes/Gone"}]
        with patch.object(av, "run_aql", return_value=iter(rows)):
            out = av._dangling_type_references(db, "o1")
        assert len(out) == 1
        assert out[0].rule_id == av.RULE_ABOX_DANGLING_TYPE
        assert out[0].severity == av.SEVERITY_ERROR


class TestCardinality:
    def test_resolve_bounds_groups_min_max(self) -> None:
        db = MagicMock()
        rows = [
            {"class_id": "C", "predicate": "hasPart", "rtype": "minCardinality", "value": 1},
            {"class_id": "C", "predicate": "hasPart", "rtype": "maxCardinality", "value": 3},
            {"class_id": "C", "predicate": "hasName", "rtype": "cardinality", "value": 1},
            {"class_id": "C", "predicate": "bad", "rtype": "minCardinality", "value": "x"},  # skip
        ]
        with patch.object(av, "run_aql", return_value=iter(rows)):
            bounds = av._resolve_cardinality_bounds(db, "o1")
        out = {(b["class_id"], b["predicate"]): b for b in bounds}
        assert out[("C", "hasPart")]["min"] == 1
        assert out[("C", "hasPart")]["max"] == 3
        assert out[("C", "hasName")]["min"] == 1 and out[("C", "hasName")]["max"] == 1
        assert ("C", "bad") not in out  # non-int value dropped

    def test_flags_under_min_and_over_max(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        bounds = [{"class_id": "C", "predicate": "hasPart", "min": 1, "max": 2}]
        counts = [
            {"key": "i_none", "label": "None", "n": 0},  # under min
            {"key": "i_ok", "label": "Ok", "n": 2},  # within bounds
            {"key": "i_many", "label": "Many", "n": 5},  # over max
        ]
        with (
            patch.object(av, "_resolve_cardinality_bounds", return_value=bounds),
            patch.object(av, "run_aql", return_value=iter(counts)),
        ):
            out = av._cardinality_violations(db, "o1")
        keys = sorted(v.entity_ids[0] for v in out)
        assert keys == ["i_many", "i_none"]  # i_ok passes
        assert all(v.rule_id == av.RULE_ABOX_CARDINALITY for v in out)

    def test_skips_when_no_bounds(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(av, "_resolve_cardinality_bounds", return_value=[]):
            assert av._cardinality_violations(db, "o1") == []


class TestValidateAbox:
    def test_aggregates_and_records_skips(self) -> None:
        db = MagicMock()
        v = av.Violation(
            rule_id=av.RULE_ABOX_UNGROUNDED,
            severity=av.SEVERITY_WARNING,
            entity_ids=("i1",),
            description="x",
        )
        with (
            patch.object(av, "_ungrounded_individuals", return_value=[v]),
            patch.object(av, "_dangling_type_references", side_effect=RuntimeError("boom")),
            patch.object(av, "_cardinality_violations", return_value=[]),
        ):
            report = av.validate_abox(db, "o1")
        d = report.to_dict()
        assert d["violation_count"] == 1
        assert av.RULE_ABOX_UNGROUNDED in d["rules_evaluated"]
        assert av.RULE_ABOX_DANGLING_TYPE in d["rules_skipped"]  # raised -> skipped
        assert av.RULE_ABOX_CARDINALITY in d["rules_evaluated"]
