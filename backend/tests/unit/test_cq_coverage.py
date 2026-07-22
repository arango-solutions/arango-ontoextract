"""Unit tests for competency-question coverage validation (Stream 22 / CQ-PR4+5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import cq_coverage as cov


class TestReadOnlyGuard:
    def test_rejects_write_queries(self) -> None:
        assert cov._is_read_only("FOR c IN ontology_classes RETURN c") is True
        assert cov._is_read_only("FOR c IN x REMOVE c IN x") is False
        assert cov._is_read_only("INSERT {} INTO x") is False
        assert cov._is_read_only("FOR c IN x UPDATE c WITH {} IN x") is False


class TestRunCoverage:
    def test_missing_spec_raises(self) -> None:
        db = MagicMock()
        with (
            patch.object(cov.requirements_repo, "get_requirements", return_value=None),
            pytest.raises(ValueError, match="no requirements spec"),
        ):
            cov.run_coverage(db, ontology_id="o1")

    def test_classifies_each_cq_and_aggregates(self) -> None:
        db = MagicMock()
        spec = {
            "use_cases": [
                {
                    "name": "UC1",
                    "competency_questions": [
                        {"text": "a", "query": "FOR x IN c RETURN x /*ANSWERABLE*/"},
                        {"text": "b", "query": "FOR x IN c RETURN x /*EMPTY*/"},
                    ],
                },
                {
                    "name": "UC2",
                    "competency_questions": [
                        {"text": "c"},  # no query -> unformalized
                        # write query -> error, never executed:
                        {"text": "d", "query": "FOR x IN c REMOVE x IN c"},
                        {"text": "e", "query": "FOR x IN c RETURN x /*BOOM*/"},  # raises -> error
                    ],
                },
            ]
        }
        ran: list[str] = []

        def fake_run_aql(_db, query, bind_vars=None):
            ran.append(query)
            if "ANSWERABLE" in query:
                return iter([{"x": 1}])
            if "BOOM" in query:
                raise RuntimeError("bad query")
            return iter([])  # EMPTY

        with (
            patch.object(cov.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cov, "run_aql", side_effect=fake_run_aql),
        ):
            report = cov.run_coverage(db, ontology_id="o1")

        assert report["total"] == 5
        assert report["answerable"] == 1
        assert report["unanswerable"] == 1
        assert report["unformalized"] == 1
        assert report["error"] == 2
        assert report["coverage_pct"] == 20.0
        # only the two read-only, formalized queries were executed (a, b, e -> but
        # 'e' raises; 'd' write-guarded and never run; 'c' has no query)
        assert len(ran) == 3
        assert all("REMOVE" not in q for q in ran)  # write query never executed
        # per-use-case breakdown
        assert report["by_use_case"]["UC1"] == {"total": 2, "answerable": 1}
        assert report["by_use_case"]["UC2"] == {"total": 3, "answerable": 0}
        # gaps = every non-answerable CQ
        assert len(report["gaps"]) == 4

    def test_bind_var_passed_only_when_referenced(self) -> None:
        db = MagicMock()
        spec = {
            "use_cases": [
                {
                    "name": "UC",
                    "competency_questions": [
                        {
                            "text": "with",
                            "query": "FOR c IN x FILTER c.ontology_id==@ontology_id RETURN c",
                        },
                        {"text": "without", "query": "FOR c IN x RETURN c"},
                    ],
                }
            ]
        }
        seen: list[dict | None] = []

        def fake_run_aql(_db, query, bind_vars=None):
            seen.append(bind_vars)
            return iter([{"c": 1}])

        with (
            patch.object(cov.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cov, "run_aql", side_effect=fake_run_aql),
        ):
            cov.run_coverage(db, ontology_id="o1")

        assert {"ontology_id": "o1"} in seen  # referenced -> bound
        assert None in seen  # not referenced -> no bind vars

    def test_empty_spec_zero_coverage(self) -> None:
        db = MagicMock()
        with patch.object(
            cov.requirements_repo, "get_requirements", return_value={"use_cases": []}
        ):
            report = cov.run_coverage(db, ontology_id="o1")
        assert report["total"] == 0
        assert report["coverage_pct"] == 0.0


class TestByPriority:
    def test_run_coverage_breaks_down_by_priority(self) -> None:
        db = MagicMock()
        spec = {
            "use_cases": [
                {
                    "name": "UC",
                    "competency_questions": [
                        {"text": "a", "priority": "high", "query": "FOR x IN c RETURN x /*A*/"},
                        {"text": "b", "priority": "high", "query": "FOR x IN c RETURN x /*E*/"},
                        {"text": "c", "priority": "low", "query": "FOR x IN c RETURN x /*A*/"},
                    ],
                }
            ]
        }

        def fake_run_aql(_db, query, bind_vars=None):
            return iter([{"x": 1}]) if "/*A*/" in query else iter([])

        with (
            patch.object(cov.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cov, "run_aql", side_effect=fake_run_aql),
        ):
            report = cov.run_coverage(db, ontology_id="o1")

        assert report["by_priority"]["high"] == {"total": 2, "answerable": 1}
        assert report["by_priority"]["low"] == {"total": 1, "answerable": 1}
        # gaps carry priority now
        assert any(g["priority"] == "high" for g in report["gaps"])


class TestRouteGapsToBacklog:
    def test_opens_active_and_resolves_stale(self) -> None:
        db = MagicMock()
        report = {
            "gaps": [
                {"text": "a", "use_case": "UC", "priority": "high", "status": "unanswerable"},
                {"text": "", "use_case": "UC", "priority": "low", "status": "unanswerable"},  # skip
            ]
        }
        with (
            patch.object(cov.cq_gap_repo, "upsert_gap", return_value=True) as mk_up,
            patch.object(cov.cq_gap_repo, "resolve_gaps_not_in", return_value=2) as mk_res,
            patch.object(cov.cq_gap_repo, "list_gaps", return_value=[{"_key": "k"}]),
        ):
            out = cov.route_gaps_to_backlog(db, ontology_id="o1", report=report)

        assert out == {"opened": 1, "resolved": 2, "open_total": 1}
        mk_up.assert_called_once()  # empty-text gap skipped
        # active key set passed to resolver contains exactly the one real gap
        active = mk_res.call_args.args[2]
        assert len(active) == 1


class TestEvaluateReleaseGate:
    def _report(self, high_total, high_ans):
        return {
            "by_priority": {
                "high": {"total": high_total, "answerable": high_ans},
                "low": {"total": 5, "answerable": 0},
            },
            "gaps": [
                {"text": "x", "priority": "high", "status": "unanswerable"},
                {"text": "y", "priority": "low", "status": "unanswerable"},
            ],
        }

    def test_passes_when_priority_coverage_meets_threshold(self) -> None:
        gate = cov.evaluate_release_gate(self._report(4, 4), min_priority_pct=80.0)
        assert gate["passed"] is True
        assert gate["actual_pct"] == 100.0
        # only the high-priority gap blocks (low ignored)
        assert [g["priority"] for g in gate["blocking_gaps"]] == ["high"]

    def test_fails_below_threshold(self) -> None:
        gate = cov.evaluate_release_gate(self._report(4, 2), min_priority_pct=80.0)
        assert gate["passed"] is False
        assert gate["actual_pct"] == 50.0
        assert gate["considered"] == 4

    def test_vacuous_pass_when_no_priority_cqs(self) -> None:
        report = {"by_priority": {"low": {"total": 3, "answerable": 0}}, "gaps": []}
        gate = cov.evaluate_release_gate(report, min_priority_pct=90.0)
        assert gate["passed"] is True
        assert gate["considered"] == 0
        assert gate["actual_pct"] == 100.0
