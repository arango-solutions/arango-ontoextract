"""Unit tests for the background consolidation job (Stream 11 IBR.17).

Mocks the underlying services (rule engine, decay, revision_meta_repo,
cursor checkpointing) so we can exercise the orchestration logic --
stage sequencing, dry-run semantics, error handling, cursor checkpoints,
inbox-row writes -- without needing a live ArangoDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import revision_meta_repo as rev_repo
from app.services import (
    confidence_decay,
    consolidation,
    ontology_rule_engine,
    revision_safety,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _violation(rule_id="R1_synonym_triangle", entity="ontology_classes/Account"):
    return ontology_rule_engine.Violation(
        rule_id=rule_id,
        severity="warning",
        entity_ids=(entity,),
        description="example violation",
        suggested_action=rev_repo.VERDICT_GAP_FILLING,
    )


def _rules_report(violations=()):
    rep = ontology_rule_engine.RuleEngineReport(ontology_id="onto_1")
    rep.rules_evaluated = [
        ontology_rule_engine.RULE_R1_SYNONYM_TRIANGLE,
        ontology_rule_engine.RULE_R2_SUBCLASS_CYCLE,
    ]
    rep.violations.extend(violations)
    return rep


def _decay_report(decayed_count=0):
    return confidence_decay.DecayReport(
        ontology_id="onto_1",
        enabled=True,
        dry_run=False,
        half_life_days=90.0,
        floor=0.05,
        classes_examined=10,
        classes_decayed=decayed_count,
    )


# ---------------------------------------------------------------------------
# Happy-path orchestration
# ---------------------------------------------------------------------------


class TestRunConsolidationHappyPath:
    def test_all_three_stages_run_with_writes_when_not_dry_run(self):
        rules = _rules_report(violations=[_violation(), _violation(rule_id="R4")])
        decay = _decay_report(decayed_count=3)
        stale = [
            consolidation.StaleBelief(
                class_key="Account",
                label="Account",
                age_days=120.0,
                current_confidence=0.6,
            )
        ]
        with (
            patch.object(ontology_rule_engine, "evaluate_rules", return_value=rules) as mock_rules,
            patch.object(
                confidence_decay, "apply_confidence_decay", return_value=decay
            ) as mock_decay,
            patch.object(consolidation, "_scan_stale_beliefs", return_value=stale) as mock_stale,
            patch.object(revision_safety, "checkpoint_cursor") as mock_checkpoint,
            patch.object(rev_repo, "record_revision", return_value={"_key": "r1"}),
        ):
            report = consolidation.run_consolidation("onto_1", dry_run=False, db=MagicMock())

        assert report.status == "completed"
        assert report.rules is rules
        assert report.decay is decay
        assert report.stale_beliefs == stale
        # Two violations + one stale = three FLAG_FOR_CURATION rows
        assert report.revisions_written_rules == 2
        assert report.revisions_written_stale == 1
        assert report.total_planned_actions == 2 + 3 + 1  # rules + decay + stale
        # Cursor must be checkpointed at start, after rules, after decay, after stale
        assert mock_checkpoint.call_count >= 4
        mock_rules.assert_called_once()
        mock_decay.assert_called_once()
        mock_stale.assert_called_once()

    def test_dry_run_skips_revision_meta_writes(self):
        rules = _rules_report(violations=[_violation()])
        decay = _decay_report(decayed_count=2)
        stale = [
            consolidation.StaleBelief(
                class_key="X", label="X", age_days=200.0, current_confidence=0.4
            )
        ]
        with (
            patch.object(ontology_rule_engine, "evaluate_rules", return_value=rules),
            patch.object(
                confidence_decay, "apply_confidence_decay", return_value=decay
            ) as mock_decay,
            patch.object(consolidation, "_scan_stale_beliefs", return_value=stale),
            patch.object(revision_safety, "checkpoint_cursor"),
            patch.object(rev_repo, "record_revision") as mock_record,
        ):
            report = consolidation.run_consolidation("onto_1", dry_run=True, db=MagicMock())

        assert report.dry_run is True
        assert report.revisions_written_rules == 0
        assert report.revisions_written_stale == 0
        # Not a single record_revision call when dry_run=True
        mock_record.assert_not_called()
        # Decay must be called with dry_run=True
        decay_kwargs = mock_decay.call_args.kwargs
        assert decay_kwargs["dry_run"] is True
        assert decay_kwargs["force"] is True

    def test_explicit_job_key_propagates(self):
        rules = _rules_report()
        with (
            patch.object(ontology_rule_engine, "evaluate_rules", return_value=rules),
            patch.object(
                confidence_decay,
                "apply_confidence_decay",
                return_value=_decay_report(),
            ),
            patch.object(consolidation, "_scan_stale_beliefs", return_value=[]),
            patch.object(revision_safety, "checkpoint_cursor") as mock_checkpoint,
        ):
            report = consolidation.run_consolidation(
                "onto_1", dry_run=False, job_key="my_resumable_job", db=MagicMock()
            )
        assert report.job_key == "my_resumable_job"
        # Every checkpoint must carry the same job_key
        for call in mock_checkpoint.call_args_list:
            cur = call.args[0]
            assert cur.job_key == "my_resumable_job"


# ---------------------------------------------------------------------------
# Stage failure handling
# ---------------------------------------------------------------------------


class TestStageFailureHandling:
    def test_rules_failure_marks_report_failed_and_does_not_run_decay(self):
        with (
            patch.object(
                ontology_rule_engine,
                "evaluate_rules",
                side_effect=RuntimeError("AQL boom"),
            ),
            patch.object(confidence_decay, "apply_confidence_decay") as mock_decay,
            patch.object(consolidation, "_scan_stale_beliefs") as mock_stale,
            patch.object(revision_safety, "checkpoint_cursor"),
        ):
            report = consolidation.run_consolidation("onto_1", dry_run=False, db=MagicMock())
        assert report.status == "failed"
        assert "AQL boom" in (report.error or "")
        # Subsequent stages must NOT have run on rules failure
        mock_decay.assert_not_called()
        mock_stale.assert_not_called()

    def test_decay_failure_marks_report_failed_after_rules(self):
        with (
            patch.object(
                ontology_rule_engine,
                "evaluate_rules",
                return_value=_rules_report(),
            ),
            patch.object(
                confidence_decay,
                "apply_confidence_decay",
                side_effect=RuntimeError("decay boom"),
            ),
            patch.object(consolidation, "_scan_stale_beliefs") as mock_stale,
            patch.object(revision_safety, "checkpoint_cursor"),
        ):
            report = consolidation.run_consolidation("onto_1", dry_run=False, db=MagicMock())
        assert report.status == "failed"
        assert "decay boom" in (report.error or "")
        # Stale stage must NOT have run
        mock_stale.assert_not_called()

    def test_record_revision_failure_does_not_abort_pass(self):
        rules = _rules_report(violations=[_violation(), _violation(rule_id="R4")])
        with (
            patch.object(ontology_rule_engine, "evaluate_rules", return_value=rules),
            patch.object(
                confidence_decay,
                "apply_confidence_decay",
                return_value=_decay_report(),
            ),
            patch.object(consolidation, "_scan_stale_beliefs", return_value=[]),
            patch.object(revision_safety, "checkpoint_cursor"),
            # First record_revision raises, second succeeds
            patch.object(
                rev_repo,
                "record_revision",
                side_effect=[RuntimeError("disk full"), {"_key": "r2"}],
            ),
        ):
            report = consolidation.run_consolidation("onto_1", dry_run=False, db=MagicMock())
        # Pass still completes; only one row was actually written
        assert report.status == "completed"
        assert report.revisions_written_rules == 1


# ---------------------------------------------------------------------------
# Inbox row writers
# ---------------------------------------------------------------------------


class TestInboxRowWriters:
    def test_violations_write_flag_for_curation_with_rule_id_in_agent_version(
        self,
    ):
        captured = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return {"_key": f"r{len(captured)}"}

        with patch.object(rev_repo, "record_revision", side_effect=_capture):
            written = consolidation._write_inbox_rows_for_violations(
                ontology_id="onto_1",
                violations=[
                    _violation(rule_id="R1_synonym_triangle"),
                    _violation(rule_id="R4_redundant_class"),
                ],
                job_key="job_xyz",
                db=MagicMock(),
            )
        assert written == 2
        # Each row must reference the consolidation job via triggering_doc_id
        for kwargs in captured:
            assert kwargs["triggering_doc_id"] == "consolidation:job_xyz"
            assert kwargs["action"] == rev_repo.ACTION_FLAG_FOR_CURATION
            assert kwargs["agent_type"] == rev_repo.AGENT_MECHANICAL
            assert kwargs["agent_version"].startswith("consolidation+")

    def test_stale_beliefs_write_with_class_key_in_entity_id(self):
        captured = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return {"_key": f"r{len(captured)}"}

        with patch.object(rev_repo, "record_revision", side_effect=_capture):
            written = consolidation._write_inbox_rows_for_stale(
                ontology_id="onto_1",
                stale=[
                    consolidation.StaleBelief(
                        class_key="Account",
                        label="Account",
                        age_days=200.0,
                        current_confidence=0.5,
                    )
                ],
                job_key="job_xyz",
                db=MagicMock(),
            )
        assert written == 1
        assert captured[0]["existing_entity_id"] == "ontology_classes/Account"
        assert "200.0 days" in captured[0]["reasoning"]


# ---------------------------------------------------------------------------
# ConsolidationReport serialisation
# ---------------------------------------------------------------------------


class TestConsolidationReport:
    def test_to_dict_round_trip_with_all_stages(self):
        report = consolidation.ConsolidationReport(
            job_key="job_1",
            ontology_id="onto_1",
            dry_run=False,
            started_at=1700000000.0,
        )
        report.rules = _rules_report(violations=[_violation()])
        report.decay = _decay_report(decayed_count=2)
        report.stale_beliefs = [
            consolidation.StaleBelief(
                class_key="X", label="X", age_days=100.0, current_confidence=0.7
            )
        ]
        report.revisions_written_rules = 1
        report.revisions_written_stale = 1
        report.ms_rules = 12.3
        report.ms_decay = 4.5
        report.ms_stale = 2.1
        report.finished_at = 1700000010.0
        report.status = "completed"

        d = report.to_dict()
        assert d["job_key"] == "job_1"
        assert d["status"] == "completed"
        assert d["total_planned_actions"] == 1 + 2 + 1
        assert d["rules"]["violation_count"] == 1
        assert d["decay"]["classes_decayed"] == 2
        assert len(d["stale_beliefs"]) == 1
        assert d["duration_ms"] == 10000.0


# ---------------------------------------------------------------------------
# Stale-belief scan
# ---------------------------------------------------------------------------


class TestScanStaleBeliefs:
    def test_returns_empty_when_collection_missing(self):
        db = MagicMock()
        db.has_collection.return_value = False
        result = consolidation._scan_stale_beliefs(
            db, "onto_1", stale_after_days=90.0, now=1700000000.0, limit=100
        )
        assert result == []

    def test_parses_rows_and_computes_age(self):
        db = MagicMock()
        db.has_collection.return_value = True
        now = 1700000000.0
        with patch(
            "app.services.consolidation.run_aql",
            return_value=iter(
                [
                    {
                        "_key": "Account",
                        "label": "Account",
                        "last_evidenced_at": now - (200 * 86400),
                        "created": now - (300 * 86400),
                        "current_confidence": 0.5,
                    },
                    {
                        # No last_evidenced_at -- falls back to created
                        "_key": "Customer",
                        "label": "Customer",
                        "created": now - (100 * 86400),
                        "current_confidence": 0.8,
                    },
                ]
            ),
        ):
            result = consolidation._scan_stale_beliefs(
                db, "onto_1", stale_after_days=90.0, now=now, limit=10
            )
        assert len(result) == 2
        assert result[0].class_key == "Account"
        assert result[0].age_days == pytest.approx(200.0, rel=1e-3)
        assert result[1].class_key == "Customer"
        assert result[1].age_days == pytest.approx(100.0, rel=1e-3)
