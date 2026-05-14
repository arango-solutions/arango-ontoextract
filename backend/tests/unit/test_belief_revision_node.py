"""Unit tests for :mod:`app.extraction.agents.belief_revision` (Stream 11 IBR.10).

Mocks the IBR services (touchpoint discovery, classify, revise_batch,
supersede helpers) to verify:

* Skip paths (no extraction / no ontology / no document / no concepts /
  no touchpoints).
* Routing: auto-applicable verdicts -> mechanical supersede;
  contested verdicts (CONTRADICTED / UNCERTAIN) and
  ``auto_applicable=False`` -> LLM agent then supersede.
* FR-11.15: LLM is NOT invoked when there are zero contested verdicts.
* Failure isolation: one bad apply -> ``status=failed`` action, others
  still recorded.
* State delta shape: ``revision_actions[]``, ``step_logs[]``,
  ``errors[]``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_GAP_FILL,
    ACTION_REINFORCE,
    ACTION_REVISE,
    AGENT_LLM,
    AGENT_MECHANICAL,
    STATUS_APPLIED,
    STATUS_PENDING,
    VERDICT_CONTRADICTED,
    VERDICT_GAP_FILLING,
    VERDICT_REINFORCED,
    VERDICT_UNCERTAIN,
)
from app.db.temporal_revisions_repo import SupersedeResult
from app.extraction.agents.belief_revision import (
    _build_new_concepts,
    _evidence_quotes_from_doc,
    _evidence_quotes_from_extracted,
    belief_revision_node,
)
from app.services.revision_verdict import MechanicalRevision
from app.services.touchpoint_discovery import (
    Touchpoint,
    TouchpointReport,
    TouchpointSignals,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ev(text: str, chunk_ids: list[str] | None = None) -> Any:
    """Fake :class:`SourceEvidence` with the fields the node reads."""
    e = MagicMock()
    e.evidence_text = text
    e.source_chunk_ids = chunk_ids or []
    return e


def _cls(label: str, *, uri: str | None = None, evidence: list[Any] | None = None) -> Any:
    """Fake :class:`ExtractedClass`."""
    c = MagicMock()
    c.label = label
    c.uri = uri
    c.description = f"description of {label}"
    c.evidence = evidence or []
    return c


def _result(classes: list[Any]) -> Any:
    """Fake :class:`ExtractionResult`."""
    r = MagicMock()
    r.classes = list(classes)
    return r


def _touchpoint(
    *,
    new_label: str,
    existing_id: str,
    score: float = 0.6,
    new_uri: str | None = None,
) -> Touchpoint:
    return Touchpoint(
        new_concept_label=new_label,
        new_concept_uri=new_uri,
        existing_class_id=existing_id,
        existing_class_label=existing_id.split("/", 1)[1] if "/" in existing_id else existing_id,
        signals=TouchpointSignals(
            uri_exact=0.0,
            label_exact=0.0,
            label_fuzzy=score,
            chunk_overlap=0.0,
            embedding_sim=None,
        ),
        combined_score=score,
        reasoning="fixture",
    )


def _mech(
    tp: Touchpoint,
    *,
    verdict: str,
    action: str,
    rule_id: str = "R7_REFINED_NAMING",
    confidence: float = 0.7,
) -> MechanicalRevision:
    return MechanicalRevision(
        touchpoint=tp,
        verdict=verdict,
        action=action,
        rule_id=rule_id,
        confidence=confidence,
        reasoning="mech-fixture",
    )


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run-1",
        "document_id": "doc-1",
        "consistency_result": _result([_cls("ExtendedTransaction")]),
        "metadata": {"ontology_id": "ont-1"},
        "errors": [],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default IBR.10 tests run with the feature flag ON.

    Tests that need the flag OFF (the new IBR.11 gating tests) override
    this fixture explicitly via ``monkeypatch.setattr``.
    """
    monkeypatch.setattr(settings, "belief_revision_pipeline_enabled", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestBuildNewConcepts:
    def test_skips_classes_with_no_label(self) -> None:
        cs = [_cls(""), _cls("Foo")]
        out = _build_new_concepts(cs)
        assert len(out) == 1
        assert out[0].label == "Foo"

    def test_collects_chunk_ids_dedup_preserves_order(self) -> None:
        c = _cls("Foo", evidence=[_ev("e1", ["c1", "c2"]), _ev("e2", ["c2", "c3"])])
        out = _build_new_concepts([c])
        assert out[0].chunk_ids == ("c1", "c2", "c3")

    def test_uri_passed_through(self) -> None:
        c = _cls("Foo", uri="http://x/Foo")
        out = _build_new_concepts([c])
        assert out[0].uri == "http://x/Foo"

    def test_embedding_left_unset(self) -> None:
        out = _build_new_concepts([_cls("Foo")])
        assert out[0].embedding is None


class TestEvidenceHelpers:
    def test_doc_evidence_extracts_text_skips_empty(self) -> None:
        doc = {
            "evidence": [
                {"evidence_text": "quote A"},
                {"evidence_text": "  "},  # empty after strip
                {"evidence_text": "quote B", "other": 1},
                "quote C",  # bare string allowed
                {"no_text": "x"},
            ]
        }
        assert _evidence_quotes_from_doc(doc) == ("quote A", "quote B", "quote C")

    def test_doc_evidence_handles_missing_field(self) -> None:
        assert _evidence_quotes_from_doc({}) == ()

    def test_extracted_evidence_handles_none(self) -> None:
        assert _evidence_quotes_from_extracted(None) == ()

    def test_extracted_evidence_extracts_text(self) -> None:
        c = _cls("Foo", evidence=[_ev("alpha"), _ev("  "), _ev("beta")])
        assert _evidence_quotes_from_extracted(c) == ("alpha", "beta")


# ---------------------------------------------------------------------------
# Skip paths
# ---------------------------------------------------------------------------


class TestSkipPaths:
    def test_no_consistency_result(self) -> None:
        out = belief_revision_node(_state(consistency_result=None))
        assert out["revision_actions"] == []
        log = out["step_logs"][0]
        assert log["status"] == "completed"
        assert log["metadata"]["touchpoints_discovered"] == 0

    def test_no_classes(self) -> None:
        out = belief_revision_node(_state(consistency_result=_result([])))
        assert out["revision_actions"] == []

    def test_no_ontology_id(self) -> None:
        out = belief_revision_node(_state(metadata={}))
        assert out["revision_actions"] == []
        assert out["step_logs"][0]["status"] == "completed"

    def test_no_document_id(self) -> None:
        out = belief_revision_node(_state(document_id=""))
        assert out["revision_actions"] == []

    def test_no_touchpoints(self) -> None:
        report = TouchpointReport(ontology_id="ont-1", new_concept_count=1, candidates_examined=0)
        with (
            patch(
                "app.extraction.agents.belief_revision.get_db",
                return_value=MagicMock(),
            ),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
        ):
            out = belief_revision_node(_state())
        assert out["revision_actions"] == []
        assert out["step_logs"][0]["metadata"]["touchpoints_discovered"] == 0


# ---------------------------------------------------------------------------
# Routing: auto-apply path
# ---------------------------------------------------------------------------


class TestAutoApplyPath:
    def test_reinforced_auto_applies_mechanical_no_llm(self) -> None:
        tp = _touchpoint(new_label="ExtendedTransaction", existing_id="oc/Transaction")
        mech = _mech(tp, verdict=VERDICT_REINFORCED, action=ACTION_REINFORCE)
        report = TouchpointReport(
            ontology_id="ont-1",
            new_concept_count=1,
            candidates_examined=1,
            touchpoints=[tp],
        )
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                return_value=SupersedeResult(
                    revision_meta_key="rev-1",
                    action=ACTION_REINFORCE,
                    status=STATUS_APPLIED,
                    new_version_key="oc/Transaction",
                ),
            ) as supmech,
            patch("app.extraction.agents.belief_revision.asyncio.run") as asyrun,
        ):
            out = belief_revision_node(_state())
        assert len(out["revision_actions"]) == 1
        action = out["revision_actions"][0]
        assert action["status"] == STATUS_APPLIED
        assert action["agent_type"] == AGENT_MECHANICAL
        assert action["verdict"] == VERDICT_REINFORCED
        assert action["action"] == ACTION_REINFORCE
        assert action["revision_meta_key"] == "rev-1"
        supmech.assert_called_once()
        # FR-11.15: no contested verdicts -> no LLM call.
        asyrun.assert_not_called()
        assert out["step_logs"][0]["metadata"]["llm_invocations"] == 0
        assert out["step_logs"][0]["metadata"]["auto_applied"] == 1

    def test_gap_filling_auto_applies_then_records_action(self) -> None:
        tp = _touchpoint(new_label="EscrowAccount", existing_id="oc/Account")
        mech = _mech(
            tp,
            verdict=VERDICT_GAP_FILLING,
            action=ACTION_GAP_FILL,
            rule_id="R7_GAP_SIBLING",
        )
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                return_value=SupersedeResult(
                    revision_meta_key="rev-2",
                    action=ACTION_GAP_FILL,
                    status=STATUS_APPLIED,
                    new_edge_key="edge-1",
                ),
            ),
        ):
            out = belief_revision_node(_state())
        action = out["revision_actions"][0]
        assert action["new_edge_key"] == "edge-1"
        assert action["agent_type"] == AGENT_MECHANICAL
        assert action["rule_id"] == "R7_GAP_SIBLING"


# ---------------------------------------------------------------------------
# Routing: LLM escalation
# ---------------------------------------------------------------------------


def _llm_proposal(
    *,
    action: str = ACTION_FLAG_FOR_CURATION,
    confidence: float = 0.5,
    reasoning: str = "llm-fixture",
) -> Any:
    p = MagicMock()
    p.action = action
    p.confidence = confidence
    p.reasoning = reasoning
    p.evidence_quotes = ("q1",)
    p.cross_check_passed = True
    p.cross_check_notes = ()
    return p


class TestLlmEscalationPath:
    def test_uncertain_routes_to_llm_then_supersede(self) -> None:
        tp = _touchpoint(new_label="AccountStatus", existing_id="oc/Account")
        mech = _mech(
            tp,
            verdict=VERDICT_UNCERTAIN,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id="R7_UNCERTAIN_SUFFIX",
        )
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        proposal = _llm_proposal(action=ACTION_FLAG_FOR_CURATION)
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value.get.return_value = {
            "label": "Account",
            "evidence": [{"evidence_text": "existing"}],
        }
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=db),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.revise_batch",
                new=MagicMock(return_value="not-a-coroutine"),
            ),
            patch(
                "app.extraction.agents.belief_revision.asyncio.run",
                return_value=[proposal],
            ) as asyrun,
            patch(
                "app.extraction.agents.belief_revision.supersede_from_llm_proposal",
                return_value=SupersedeResult(
                    revision_meta_key="rev-3",
                    action=ACTION_FLAG_FOR_CURATION,
                    status=STATUS_PENDING,
                ),
            ) as suplm,
        ):
            out = belief_revision_node(_state())
        asyrun.assert_called_once()
        suplm.assert_called_once()
        assert out["revision_actions"][0]["agent_type"] == AGENT_LLM
        assert out["revision_actions"][0]["status"] == STATUS_PENDING
        assert out["revision_actions"][0]["verdict"] == VERDICT_UNCERTAIN
        log_meta = out["step_logs"][0]["metadata"]
        assert log_meta["llm_invocations"] == 1
        assert log_meta["flagged_for_curation"] == 1
        assert log_meta["auto_applied"] == 0

    def test_contradicted_routes_to_llm(self) -> None:
        tp = _touchpoint(new_label="X", existing_id="oc/Y")
        mech = _mech(
            tp,
            verdict=VERDICT_CONTRADICTED,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id="R7_CONTRADICTED",
        )
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        proposal = _llm_proposal(action=ACTION_REVISE)
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.revise_batch",
                new=MagicMock(return_value="not-a-coroutine"),
            ),
            patch(
                "app.extraction.agents.belief_revision.asyncio.run",
                return_value=[proposal],
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_llm_proposal",
                return_value=SupersedeResult(
                    revision_meta_key="rev-4",
                    action=ACTION_REVISE,
                    status=STATUS_APPLIED,
                    new_version_key="oc/Y_v2",
                ),
            ),
        ):
            out = belief_revision_node(_state())
        assert out["revision_actions"][0]["agent_type"] == AGENT_LLM
        assert out["revision_actions"][0]["action"] == ACTION_REVISE


# ---------------------------------------------------------------------------
# FR-11.15: LLM skipped when no contested verdicts
# ---------------------------------------------------------------------------


class TestLlmSkippedFr1115:
    def test_zero_contested_means_no_llm_call(self) -> None:
        tp1 = _touchpoint(new_label="A", existing_id="oc/A")
        tp2 = _touchpoint(new_label="B", existing_id="oc/B")
        m1 = _mech(tp1, verdict=VERDICT_REINFORCED, action=ACTION_REINFORCE)
        m2 = _mech(tp2, verdict=VERDICT_GAP_FILLING, action=ACTION_GAP_FILL)
        report = TouchpointReport(
            ontology_id="ont-1",
            new_concept_count=2,
            candidates_examined=2,
            touchpoints=[tp1, tp2],
        )
        # classify is called once per touchpoint, so use side_effect.
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                side_effect=[m1, m2],
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                side_effect=[
                    SupersedeResult(
                        revision_meta_key="r1", action=ACTION_REINFORCE, status=STATUS_APPLIED
                    ),
                    SupersedeResult(
                        revision_meta_key="r2", action=ACTION_GAP_FILL, status=STATUS_APPLIED
                    ),
                ],
            ),
            patch("app.extraction.agents.belief_revision.asyncio.run") as asyrun,
        ):
            out = belief_revision_node(_state(consistency_result=_result([_cls("A"), _cls("B")])))
        asyrun.assert_not_called()
        assert out["step_logs"][0]["metadata"]["llm_invocations"] == 0
        assert len(out["revision_actions"]) == 2


# ---------------------------------------------------------------------------
# Mixed: auto + escalate, both apply
# ---------------------------------------------------------------------------


class TestMixedRouting:
    def test_one_auto_one_escalated_both_recorded(self) -> None:
        tp1 = _touchpoint(new_label="A", existing_id="oc/A")
        tp2 = _touchpoint(new_label="AccountStatus", existing_id="oc/Account")
        m_auto = _mech(tp1, verdict=VERDICT_REINFORCED, action=ACTION_REINFORCE)
        m_contested = _mech(tp2, verdict=VERDICT_UNCERTAIN, action=ACTION_FLAG_FOR_CURATION)
        report = TouchpointReport(
            ontology_id="ont-1",
            new_concept_count=2,
            candidates_examined=2,
            touchpoints=[tp1, tp2],
        )
        proposal = _llm_proposal(action=ACTION_FLAG_FOR_CURATION)
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value.get.return_value = {"label": "Account", "evidence": []}
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=db),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                side_effect=[m_auto, m_contested],
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                return_value=SupersedeResult(
                    revision_meta_key="r-auto",
                    action=ACTION_REINFORCE,
                    status=STATUS_APPLIED,
                ),
            ) as supmech,
            patch(
                "app.extraction.agents.belief_revision.revise_batch",
                new=MagicMock(return_value="not-a-coroutine"),
            ),
            patch(
                "app.extraction.agents.belief_revision.asyncio.run",
                return_value=[proposal],
            ) as asyrun,
            patch(
                "app.extraction.agents.belief_revision.supersede_from_llm_proposal",
                return_value=SupersedeResult(
                    revision_meta_key="r-llm",
                    action=ACTION_FLAG_FOR_CURATION,
                    status=STATUS_PENDING,
                ),
            ) as suplm,
        ):
            out = belief_revision_node(
                _state(
                    consistency_result=_result([_cls("A"), _cls("AccountStatus")]),
                )
            )
        supmech.assert_called_once()
        suplm.assert_called_once()
        asyrun.assert_called_once()
        assert len(out["revision_actions"]) == 2
        log_meta = out["step_logs"][0]["metadata"]
        assert log_meta["llm_invocations"] == 1
        assert log_meta["auto_applied"] == 1
        assert log_meta["flagged_for_curation"] == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    def test_supersede_failure_records_failed_action_does_not_crash(self) -> None:
        tp = _touchpoint(new_label="A", existing_id="oc/A")
        mech = _mech(tp, verdict=VERDICT_REINFORCED, action=ACTION_REINFORCE)
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                side_effect=RuntimeError("db boom"),
            ),
        ):
            out = belief_revision_node(_state())
        action = out["revision_actions"][0]
        assert action["status"] == "failed"
        assert "db boom" in action["error"]
        # Step still completes (only the per-action failed).
        assert out["step_logs"][0]["status"] == "completed"

    def test_llm_batch_failure_records_failed_actions(self) -> None:
        tp = _touchpoint(new_label="A", existing_id="oc/A")
        mech = _mech(tp, verdict=VERDICT_UNCERTAIN, action=ACTION_FLAG_FOR_CURATION)
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        # Patch revise_batch to a sync MagicMock so the coroutine isn't created;
        # asyncio.run then raises before any LLM activity can happen.
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.revise_batch",
                new=MagicMock(return_value="not-a-coroutine"),
            ),
            patch(
                "app.extraction.agents.belief_revision.asyncio.run",
                side_effect=RuntimeError("openai 500"),
            ),
        ):
            out = belief_revision_node(_state())
        action = out["revision_actions"][0]
        assert action["status"] == "failed"
        assert action["error"] == "llm_batch_failed"

    def test_phase_failure_records_error_and_failed_step(self) -> None:
        with patch(
            "app.extraction.agents.belief_revision.get_db",
            side_effect=RuntimeError("no db"),
        ):
            out = belief_revision_node(_state())
        assert out["step_logs"][0]["status"] == "failed"
        assert any("no db" in e for e in out["errors"])
        assert out["revision_actions"] == []


# ---------------------------------------------------------------------------
# State delta contract
# ---------------------------------------------------------------------------


class TestStateDeltaContract:
    def test_returns_only_expected_keys(self) -> None:
        out = belief_revision_node(_state(consistency_result=None))
        # IBR.12: ``belief_revision_summary`` is the typed channel the
        # extraction service reads when persisting
        # ``stats.belief_revision`` on the run document. Locking the
        # full set here means a future return-shape change can't
        # silently drop the field on the floor.
        assert set(out.keys()) == {
            "revision_actions",
            "errors",
            "step_logs",
            "belief_revision_summary",
        }

    def test_belief_revision_summary_mirrors_step_log_metadata(self) -> None:
        """The typed summary on state must match the audit metadata in
        the step log -- they're two views of the same numbers and
        drift between them would confuse anyone debugging IBR."""
        out = belief_revision_node(_state(consistency_result=None))
        summary = out["belief_revision_summary"]
        meta = out["step_logs"][0]["metadata"]
        for key in (
            "touchpoints_discovered",
            "auto_applied",
            "flagged_for_curation",
            "llm_invocations",
            "skipped_idempotency",
            "verdict_counts",
        ):
            assert summary[key] == meta[key], f"summary/log mismatch on {key}"
        # status / reason live only on the typed summary -- they let
        # the Pipeline Monitor render "skipped: feature_flag_off"
        # without inspecting the (status,error) tuple on StepLog.
        assert "status" in summary
        assert "reason" in summary

    def test_step_log_has_required_metadata(self) -> None:
        out = belief_revision_node(_state(consistency_result=None))
        meta = out["step_logs"][0]["metadata"]
        for key in (
            "touchpoints_discovered",
            "auto_applied",
            "flagged_for_curation",
            "llm_invocations",
            "skipped_idempotency",
            "verdict_counts",
        ):
            assert key in meta, f"missing {key}"


# ---------------------------------------------------------------------------
# Idempotency surfaced from supersede
# ---------------------------------------------------------------------------


class TestIdempotencyCounted:
    def test_skipped_supersede_counts_in_summary(self) -> None:
        tp = _touchpoint(new_label="A", existing_id="oc/A")
        mech = _mech(tp, verdict=VERDICT_REINFORCED, action=ACTION_REINFORCE)
        report = TouchpointReport(
            ontology_id="ont-1", new_concept_count=1, candidates_examined=1, touchpoints=[tp]
        )
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch(
                "app.extraction.agents.belief_revision.discover_touchpoints",
                return_value=report,
            ),
            patch(
                "app.extraction.agents.belief_revision.classify",
                return_value=mech,
            ),
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision",
                return_value=SupersedeResult(
                    revision_meta_key="rev-old",
                    action=ACTION_REINFORCE,
                    status=STATUS_APPLIED,
                    skipped=True,
                    skipped_reason="prior",
                ),
            ),
        ):
            out = belief_revision_node(_state())
        log_meta = out["step_logs"][0]["metadata"]
        assert log_meta["skipped_idempotency"] == 1
        assert log_meta["auto_applied"] == 0
        assert out["revision_actions"][0]["skipped"] is True


# ---------------------------------------------------------------------------
# Edge case: empty extracted classes after filtering
# ---------------------------------------------------------------------------


class TestEmptyAfterFiltering:
    @pytest.mark.parametrize("classes", [[], [_cls("")]])
    def test_no_concepts_after_filter_skips(self, classes: list[Any]) -> None:
        with (
            patch("app.extraction.agents.belief_revision.get_db", return_value=MagicMock()),
            patch("app.extraction.agents.belief_revision.discover_touchpoints") as disco,
        ):
            out = belief_revision_node(_state(consistency_result=_result(classes)))
        disco.assert_not_called()
        assert out["revision_actions"] == []


# ---------------------------------------------------------------------------
# IBR.11: feature-flag gating
# ---------------------------------------------------------------------------


class TestFeatureFlagGating:
    def test_flag_off_skips_immediately_without_calling_services(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the feature flag is OFF the node returns immediately.

        No DB lookup, no touchpoint discovery, no classification, no
        LLM. Only the empty state delta and a "feature_flag_off"
        step-log reason.
        """
        monkeypatch.setattr(settings, "belief_revision_pipeline_enabled", False)
        with (
            patch("app.extraction.agents.belief_revision.get_db") as get_db,
            patch("app.extraction.agents.belief_revision.discover_touchpoints") as disco,
            patch("app.extraction.agents.belief_revision.classify") as clas,
            patch("app.extraction.agents.belief_revision.asyncio.run") as asyrun,
            patch(
                "app.extraction.agents.belief_revision.supersede_from_mechanical_revision"
            ) as supmech,
        ):
            out = belief_revision_node(_state())
        get_db.assert_not_called()
        disco.assert_not_called()
        clas.assert_not_called()
        asyrun.assert_not_called()
        supmech.assert_not_called()
        assert out["revision_actions"] == []
        assert out["step_logs"][0]["status"] == "completed"

    def test_flag_off_state_delta_is_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "belief_revision_pipeline_enabled", False)
        out = belief_revision_node(_state())
        # Same return-key contract regardless of whether IBR ran or
        # was skipped -- the summary is non-None ("skipped" with a
        # reason) so the Pipeline Monitor always has something to
        # render; see IBR.12.
        assert set(out.keys()) == {
            "revision_actions",
            "errors",
            "step_logs",
            "belief_revision_summary",
        }
        meta = out["step_logs"][0]["metadata"]
        assert meta["touchpoints_discovered"] == 0
        assert meta["auto_applied"] == 0
        assert meta["llm_invocations"] == 0
        # The state-level summary signals *why* IBR was a no-op so the
        # frontend can show "IBR disabled in this environment" instead
        # of an ambiguous bag of zeros.
        summary = out["belief_revision_summary"]
        assert summary["status"] == "skipped"
        assert summary["reason"] == "feature_flag_off"
        assert summary["touchpoints_discovered"] == 0


# ---------------------------------------------------------------------------
# IBR.11: pipeline topology
# ---------------------------------------------------------------------------


class TestPipelineTopologyWiring:
    """Belief revision must sit between ER/QualityJudge and the filter.

    Verified via the ``_NEXT_STEPS`` table the WebSocket emitter uses:
    quality_judge -> belief_revision, er_agent -> belief_revision,
    belief_revision -> filter. We don't instantiate the LangGraph
    object here -- it requires a checkpointer, ASGI, etc. -- but the
    NEXT_STEPS table is the source of truth for the WS-event order
    and is what would have to drift first if someone broke the wiring.
    """

    def test_quality_judge_routes_to_belief_revision(self) -> None:
        from app.extraction.pipeline import _NEXT_STEPS

        assert "belief_revision" in _NEXT_STEPS["quality_judge"]
        assert "filter" not in _NEXT_STEPS["quality_judge"]

    def test_er_agent_routes_to_belief_revision(self) -> None:
        from app.extraction.pipeline import _NEXT_STEPS

        assert "belief_revision" in _NEXT_STEPS["er_agent"]
        assert "filter" not in _NEXT_STEPS["er_agent"]

    def test_belief_revision_routes_to_filter(self) -> None:
        from app.extraction.pipeline import _NEXT_STEPS

        assert _NEXT_STEPS["belief_revision"] == ["filter"]

    def test_build_pipeline_includes_belief_revision_node(self) -> None:
        from app.extraction.pipeline import build_pipeline

        graph = build_pipeline()
        # StateGraph stores nodes on .nodes; private but stable across LG versions.
        assert "belief_revision" in graph.nodes
