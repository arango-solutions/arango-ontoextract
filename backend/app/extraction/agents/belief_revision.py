"""Belief Revision LangGraph agent node (Stream 11 IBR.10).

Bridges the IBR substrate (touchpoint discovery -> mechanical verdict
-> [LLM agent] -> Levi-identity supersede) to the extraction pipeline.

PRD references:

* §6.11 FR-11.14 -- runs after ER, before Quality Judge
* §6.11 FR-11.15 -- skips the LLM round-trip when there are zero
  contested mechanical verdicts (CONTRADICTED / UNCERTAIN)
* §6.11 FR-11.16 -- persists ``revision_actions[]`` on pipeline state
* §6.16     FR-16.4..7 -- audit + safety + idempotency contracts

Design contract
---------------

The node is *boundary-thin*: all real work lives in the IBR services
(:mod:`app.services.touchpoint_discovery`,
:mod:`app.services.revision_verdict`, :mod:`app.services.revision_agent`)
and the supersede helper (:mod:`app.db.temporal_revisions_repo`). This
node only:

1. Materialises ``NewConcept`` records from the consistency-checked
   extraction.
2. Calls touchpoint discovery once.
3. Classifies each touchpoint mechanically.
4. Routes contested verdicts (CONTRADICTED, UNCERTAIN, or any verdict
   whose ``auto_applicable`` is False) to the LLM agent.
5. Calls :func:`supersede` for each final action.
6. Returns ``revision_actions[]`` plus a step-log entry.

It deliberately does NOT mutate the ontology directly -- the supersede
helper is the only writer.

Failure mode
------------

A touchpoint or supersede failure is logged and converted to a
``revision_action`` with ``status="failed"``. This keeps one bad
touchpoint from torpedoing the rest of the run. The node returns a
``failed`` step status only when the entire phase couldn't run (e.g.
DB unreachable).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Any

from app.config import settings
from app.db.client import get_db
from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    AGENT_LLM,
    AGENT_MECHANICAL,
    VERDICT_CONTRADICTED,
    VERDICT_UNCERTAIN,
)
from app.db.temporal_revisions_repo import (
    SupersedeResult,
    supersede_from_llm_proposal,
    supersede_from_mechanical_revision,
)
from app.db.utils import doc_get
from app.extraction.state import ExtractionPipelineState, StepLog
from app.services.revision_agent import RevisionContext, revise_batch
from app.services.revision_safety import should_flag_for_curation
from app.services.revision_verdict import (
    MechanicalRevision,
    StructuralFeatures,
    classify,
)
from app.services.touchpoint_discovery import (
    NewConcept,
    Touchpoint,
    discover_touchpoints,
)

log = logging.getLogger(__name__)


# Verdicts that always escalate to the LLM agent regardless of the
# mechanical action's auto_applicable flag. Belt-and-suspenders against
# a future rule that returns auto_applicable=True for one of these.
_CONTESTED_VERDICTS = frozenset({VERDICT_CONTRADICTED, VERDICT_UNCERTAIN})


def belief_revision_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node -- runs the four-phase IBR pipeline on the latest extraction.

    Sync wrapper around :func:`_run_phase`; delegates to ``asyncio.run``
    when the LLM agent needs to be invoked. Matches the calling
    convention used by :mod:`app.extraction.agents.er_agent`.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    document_id = state.get("document_id", "")
    consistency_result = state.get("consistency_result")
    metadata = dict(state.get("metadata", {}))
    ontology_id = str(metadata.get("ontology_id") or "")
    errors = list(state.get("errors", []))

    log.info("belief_revision started", extra={"run_id": run_id})

    revision_actions: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "touchpoints_discovered": 0,
        "verdict_counts": {},
        "auto_applied": 0,
        "flagged_for_curation": 0,
        "llm_invocations": 0,
        "skipped_idempotency": 0,
    }

    try:
        if not settings.belief_revision_pipeline_enabled:
            summary["reason"] = "feature_flag_off"
            log.info(
                "belief_revision skipped: feature flag off",
                extra={"run_id": run_id},
            )
        elif consistency_result is None or not getattr(consistency_result, "classes", None):
            summary["reason"] = "no_extraction_results"
            log.info(
                "belief_revision skipped: no extraction results",
                extra={"run_id": run_id},
            )
        elif not ontology_id:
            summary["reason"] = "no_ontology_id"
            log.info(
                "belief_revision skipped: no ontology id",
                extra={"run_id": run_id},
            )
        elif not document_id:
            summary["reason"] = "no_document_id"
            log.info(
                "belief_revision skipped: no document id",
                extra={"run_id": run_id},
            )
        else:
            revision_actions, summary = _run_phase(
                run_id=run_id,
                ontology_id=ontology_id,
                document_id=document_id,
                extracted_classes=list(consistency_result.classes),
                domain_context=str(state.get("domain_context") or ""),
            )
    except Exception as exc:
        error_msg = f"belief_revision error: {exc}"
        errors.append(error_msg)
        summary = {**summary, "status": "failed", "error": str(exc)}
        log.exception("belief_revision failed", extra={"run_id": run_id})

    duration = time.time() - start
    step_log = StepLog(
        step="belief_revision",
        status="completed" if summary.get("status") != "failed" else "failed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=errors[-1] if errors and summary.get("status") == "failed" else None,
        metadata={
            "touchpoints_discovered": summary.get("touchpoints_discovered", 0),
            "auto_applied": summary.get("auto_applied", 0),
            "flagged_for_curation": summary.get("flagged_for_curation", 0),
            "llm_invocations": summary.get("llm_invocations", 0),
            "skipped_idempotency": summary.get("skipped_idempotency", 0),
            "verdict_counts": dict(summary.get("verdict_counts") or {}),
        },
    )

    log.info(
        "belief_revision completed",
        extra={
            "run_id": run_id,
            "duration_seconds": round(duration, 3),
            "summary": summary,
        },
    )

    # Surface the summary on state too (IBR.12). step_log.metadata is
    # for audit; ``belief_revision_summary`` is the typed contract the
    # extraction service reads when persisting ``stats.belief_revision``
    # on the run document. Never None on a normal exit path -- ``summary``
    # is initialised at the top of this function with the skipped/zero
    # defaults, then populated by ``_run_phase`` when the pipeline runs.
    return {
        "revision_actions": revision_actions,
        "errors": errors,
        "step_logs": [step_log],
        "belief_revision_summary": dict(summary),
    }


# ---------------------------------------------------------------------------
# Phase orchestrator
# ---------------------------------------------------------------------------


def _run_phase(
    *,
    run_id: str,
    ontology_id: str,
    document_id: str,
    extracted_classes: list[Any],
    domain_context: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the four IBR phases for one document.

    Returns ``(revision_actions, summary)``. Never raises -- failures
    on individual touchpoints become ``status="failed"`` actions.
    """
    db = get_db()

    # ---- 1. Touchpoint discovery ----------------------------------
    new_concepts = _build_new_concepts(extracted_classes)
    if not new_concepts:
        return [], {
            "status": "skipped",
            "reason": "no_new_concepts",
            "touchpoints_discovered": 0,
            "verdict_counts": {},
            "auto_applied": 0,
            "flagged_for_curation": 0,
            "llm_invocations": 0,
            "skipped_idempotency": 0,
        }

    report = discover_touchpoints(db, ontology_id, new_concepts)
    log.info(
        "belief_revision touchpoints discovered",
        extra={
            "run_id": run_id,
            "concepts": len(new_concepts),
            "candidates_examined": report.candidates_examined,
            "touchpoints": len(report.touchpoints),
        },
    )

    if not report.touchpoints:
        return [], {
            "status": "completed",
            "reason": "no_touchpoints",
            "touchpoints_discovered": 0,
            "verdict_counts": {},
            "auto_applied": 0,
            "flagged_for_curation": 0,
            "llm_invocations": 0,
            "skipped_idempotency": 0,
        }

    # ---- 2. Mechanical classification -----------------------------
    mechanicals: list[MechanicalRevision] = [
        classify(tp, _structural_features_for(tp)) for tp in report.touchpoints
    ]

    verdict_counts: dict[str, int] = {}
    for m in mechanicals:
        verdict_counts[m.verdict] = verdict_counts.get(m.verdict, 0) + 1

    # ---- 3. Partition: auto-apply vs escalate to LLM ---------------
    contested: list[tuple[Touchpoint, MechanicalRevision]] = []
    auto_apply: list[MechanicalRevision] = []
    for m in mechanicals:
        if m.verdict in _CONTESTED_VERDICTS or not m.auto_applicable:
            contested.append((m.touchpoint, m))
        else:
            auto_apply.append(m)

    # ---- 4. LLM round (FR-11.15: skip when nothing contested) -----
    llm_proposals: list[Any] = []
    if contested:
        llm_proposals = _invoke_llm_for_contested(
            db=db,
            contested=contested,
            extracted_classes=extracted_classes,
            document_id=document_id,
        )
    else:
        log.info(
            "belief_revision LLM skipped (no contested verdicts)",
            extra={"run_id": run_id, "verdicts": verdict_counts},
        )
    # Domain context is currently unused at the LLM-call boundary but is
    # kept on the function signature so IBR.11+ can thread it into the
    # prompt without changing the node API.
    _ = domain_context

    # ---- 5. Apply via supersede -----------------------------------
    revision_actions: list[dict[str, Any]] = []
    auto_applied_count = 0
    flagged_count = 0
    skipped_idem = 0

    for mech in auto_apply:
        action_record = _apply_mechanical(mech, ontology_id=ontology_id, document_id=document_id)
        revision_actions.append(action_record)
        if action_record.get("skipped"):
            skipped_idem += 1
        elif action_record.get("status") == "applied":
            auto_applied_count += 1

    for (touchpoint, mech), proposal in zip(contested, llm_proposals, strict=False):
        action_record = _apply_llm(
            touchpoint=touchpoint,
            mech=mech,
            proposal=proposal,
            ontology_id=ontology_id,
            document_id=document_id,
        )
        revision_actions.append(action_record)
        if action_record.get("skipped"):
            skipped_idem += 1
        elif action_record.get("status") == "applied":
            auto_applied_count += 1
        else:
            # pending / FLAG_FOR_CURATION
            flagged_count += 1

    summary = {
        "status": "completed",
        "reason": "",
        "touchpoints_discovered": len(report.touchpoints),
        "verdict_counts": verdict_counts,
        "auto_applied": auto_applied_count,
        "flagged_for_curation": flagged_count,
        "llm_invocations": len(contested),
        "skipped_idempotency": skipped_idem,
    }
    return revision_actions, summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_new_concepts(extracted_classes: list[Any]) -> list[NewConcept]:
    """Convert :class:`ExtractedClass` records to :class:`NewConcept` rows.

    Skips entries with no label. Pulls ``source_chunk_ids`` from the
    aggregated evidence. Embeddings are not yet attached at this stage
    (extraction does not embed); ``embedding=None`` is the right
    signal for "absent" in the touchpoint blender.
    """
    concepts: list[NewConcept] = []
    for cls in extracted_classes:
        label = str(getattr(cls, "label", "") or "").strip()
        if not label:
            continue
        uri = getattr(cls, "uri", None)
        chunk_ids: list[str] = []
        for ev in getattr(cls, "evidence", []) or []:
            chunk_ids.extend(getattr(ev, "source_chunk_ids", []) or [])
        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for cid in chunk_ids:
            if cid not in seen:
                seen.add(cid)
                deduped.append(cid)
        concepts.append(
            NewConcept(
                label=label,
                uri=str(uri) if uri else None,
                chunk_ids=tuple(deduped),
                embedding=None,
            )
        )
    return concepts


def _structural_features_for(_touchpoint: Touchpoint) -> StructuralFeatures:
    """Hook for populating structural features from the live ontology graph.

    For IBR.10's first cut we leave this empty. IBR.11+ will fill in
    ``polymorphic_range_count``, ``shared_property_names``,
    ``existing_has_subclasses`` and ``is_already_linked`` from AQL
    queries against the touchpoint's ``existing_class_id``. The
    classifier remains correct with empty structural features (it
    falls back to naming-only signals).
    """
    return StructuralFeatures()


def _invoke_llm_for_contested(
    *,
    db: Any,
    contested: list[tuple[Touchpoint, MechanicalRevision]],
    extracted_classes: list[Any],
    document_id: str,
) -> list[Any]:
    """Build :class:`RevisionContext` rows and call :func:`revise_batch`.

    Synchronous bridge: the LLM agent is async, but the LangGraph node
    is sync. Uses ``asyncio.run`` (safe because the node is invoked
    from a sync graph executor).

    For each contested touchpoint we look up the existing class document
    by ``existing_class_id`` so the LLM has the current label,
    description, and evidence quotes to ground its revision.
    """
    label_to_class = {str(getattr(c, "label", "") or "").lower(): c for c in extracted_classes}

    contexts: list[RevisionContext] = []
    for tp, mech in contested:
        existing_belief = _fetch_existing_belief(db, tp.existing_class_id)
        existing_evidence = _evidence_quotes_from_doc(existing_belief)

        new_cls = label_to_class.get(tp.new_concept_label.lower())
        new_evidence = _evidence_quotes_from_extracted(new_cls)
        new_concept_text = (
            str(getattr(new_cls, "description", "") or "") if new_cls else ""
        ) or tp.new_concept_label

        contexts.append(
            RevisionContext(
                mechanical_revision=mech,
                existing_belief=existing_belief,
                existing_evidence=existing_evidence,
                new_concept_text=new_concept_text,
                new_evidence=new_evidence,
                triggering_doc_id=document_id,
            )
        )
    try:
        return asyncio.run(revise_batch(contexts))
    except Exception:
        log.exception(
            "belief_revision LLM batch failed",
            extra={"contested_count": len(contested)},
        )
        return [None] * len(contested)


def _fetch_existing_belief(db: Any, entity_id: str) -> dict[str, Any]:
    """Load the current version of an existing class for the LLM prompt.

    Returns an empty dict on failure -- the LLM agent's cross-check
    will then downgrade to FLAG_FOR_CURATION rather than fabricate.
    """
    if not entity_id or "/" not in entity_id:
        return {}
    collection, key = entity_id.split("/", 1)
    try:
        if not db.has_collection(collection):
            return {}
        doc = db.collection(collection).get(key)
        if doc is None:
            return {}
        return {
            "label": doc.get("label"),
            "description": doc.get("description"),
            "uri": doc.get("uri"),
            "current_confidence": doc.get("current_confidence", doc.get("confidence")),
        }
    except Exception:
        log.warning(
            "belief_revision could not fetch existing belief",
            extra={"entity_id": entity_id},
            exc_info=True,
        )
        return {}


def _evidence_quotes_from_doc(doc: dict[str, Any]) -> tuple[str, ...]:
    """Extract evidence_text quotes from a stored class document."""
    quotes: list[str] = []
    for ev in doc.get("evidence") or []:
        if isinstance(ev, dict):
            text = str(ev.get("evidence_text") or "").strip()
            if text:
                quotes.append(text)
        elif isinstance(ev, str) and ev.strip():
            quotes.append(ev.strip())
    return tuple(quotes)


def _evidence_quotes_from_extracted(cls: Any) -> tuple[str, ...]:
    """Extract evidence_text quotes from an :class:`ExtractedClass`."""
    if cls is None:
        return ()
    quotes: list[str] = []
    for ev in getattr(cls, "evidence", []) or []:
        text = str(getattr(ev, "evidence_text", "") or "").strip()
        if text:
            quotes.append(text)
    return tuple(quotes)


def _load_existing_entity(entity_id: str) -> dict[str, Any] | None:
    """Best-effort fetch of the entity referenced by a touchpoint.

    Used by the published-item guard to decide whether a structural
    revision must be downgraded. Returns ``None`` on any lookup
    failure -- the guard interprets that as "not published" rather
    than blocking on a transient error.
    """
    if not entity_id or "/" not in entity_id:
        return None
    collection, key = entity_id.split("/", 1)
    if not collection or not key:
        return None
    try:
        db = get_db()
        if not db.has_collection(collection):
            return None
        return doc_get(db.collection(collection), key)
    except Exception:  # pragma: no cover -- defensive against driver errors
        log.exception("belief_revision: entity load failed for %s", entity_id)
        return None


def _apply_mechanical(
    mech: MechanicalRevision,
    *,
    ontology_id: str,
    document_id: str,
) -> dict[str, Any]:
    """Apply one mechanical revision via supersede; convert to a state record.

    Honors the published-item guard (Stream 11 IBR.18): structural
    revisions on ``status: approved`` entities are recorded as
    FLAG_FOR_CURATION rather than auto-applied, regardless of the
    rule's confidence.
    """
    existing_entity = _load_existing_entity(mech.touchpoint.existing_class_id)
    if should_flag_for_curation(entity=existing_entity, proposed_action=mech.action):
        log.info(
            "belief_revision mechanical revision downgraded (published entity)",
            extra={
                "existing_entity_id": mech.touchpoint.existing_class_id,
                "original_action": mech.action,
            },
        )
        # Override the action to FLAG_FOR_CURATION while preserving the
        # verdict and reasoning so the curator sees what the rule said.
        mech = MechanicalRevision(
            touchpoint=mech.touchpoint,
            verdict=mech.verdict,
            action=ACTION_FLAG_FOR_CURATION,
            rule_id=f"{mech.rule_id}+published_protection",
            confidence=mech.confidence,
            reasoning=(
                f"{mech.reasoning} | safety guard: published-item "
                f"protection downgraded action to FLAG_FOR_CURATION"
            ),
        )

    try:
        result: SupersedeResult = supersede_from_mechanical_revision(
            mech,
            ontology_id=ontology_id,
            triggering_doc_id=document_id,
            agent_version="rule-engine-1.0",
        )
        return _record_from_result(
            result,
            verdict=mech.verdict,
            agent_type=AGENT_MECHANICAL,
            existing_entity_id=mech.touchpoint.existing_class_id,
            new_concept_label=mech.touchpoint.new_concept_label,
            reasoning=mech.reasoning,
            rule_id=mech.rule_id,
        )
    except Exception as exc:
        log.exception(
            "belief_revision mechanical apply failed",
            extra={
                "existing_entity_id": mech.touchpoint.existing_class_id,
                "action": mech.action,
            },
        )
        return {
            "status": "failed",
            "verdict": mech.verdict,
            "action": mech.action,
            "agent_type": AGENT_MECHANICAL,
            "rule_id": mech.rule_id,
            "existing_entity_id": mech.touchpoint.existing_class_id,
            "new_concept_label": mech.touchpoint.new_concept_label,
            "reasoning": mech.reasoning,
            "error": str(exc),
            "skipped": False,
            "revision_meta_key": None,
        }


def _apply_llm(
    *,
    touchpoint: Touchpoint,
    mech: MechanicalRevision,
    proposal: Any,
    ontology_id: str,
    document_id: str,
) -> dict[str, Any]:
    """Apply one LLM proposal via supersede; convert to a state record.

    If ``proposal is None`` (LLM batch failed entirely), record the
    touchpoint as ``status=failed`` so the curator still sees it.

    Honors the published-item guard (Stream 11 IBR.18): if the LLM
    proposed a structural action against a ``status: approved`` entity,
    the action is downgraded to FLAG_FOR_CURATION before the
    supersede helper is invoked. The original proposal text is
    preserved in the reasoning so the curator can still see what the
    LLM said.
    """
    if proposal is None:
        return {
            "status": "failed",
            "verdict": mech.verdict,
            "action": mech.action,
            "agent_type": AGENT_LLM,
            "rule_id": mech.rule_id,
            "existing_entity_id": touchpoint.existing_class_id,
            "new_concept_label": touchpoint.new_concept_label,
            "reasoning": "LLM batch failed",
            "error": "llm_batch_failed",
            "skipped": False,
            "revision_meta_key": None,
        }
    proposed_action = str(getattr(proposal, "action", ""))
    if proposed_action and proposed_action != ACTION_FLAG_FOR_CURATION:
        existing_entity = _load_existing_entity(touchpoint.existing_class_id)
        if should_flag_for_curation(entity=existing_entity, proposed_action=proposed_action):
            log.info(
                "belief_revision LLM proposal downgraded (published entity)",
                extra={
                    "existing_entity_id": touchpoint.existing_class_id,
                    "original_action": proposed_action,
                },
            )
            proposal = dataclasses.replace(
                proposal,
                action=ACTION_FLAG_FOR_CURATION,
                reasoning=(
                    f"{getattr(proposal, 'reasoning', '')} | safety guard: "
                    f"published-item protection downgraded "
                    f"{proposed_action} to FLAG_FOR_CURATION"
                ).strip(" |"),
            )
    try:
        result: SupersedeResult = supersede_from_llm_proposal(
            proposal,
            ontology_id=ontology_id,
            existing_entity_id=touchpoint.existing_class_id,
            verdict=mech.verdict,
            triggering_doc_id=document_id,
            agent_version=settings.llm_extraction_model,
        )
        return _record_from_result(
            result,
            verdict=mech.verdict,
            agent_type=AGENT_LLM,
            existing_entity_id=touchpoint.existing_class_id,
            new_concept_label=touchpoint.new_concept_label,
            reasoning=getattr(proposal, "reasoning", ""),
            rule_id=mech.rule_id,
        )
    except Exception as exc:
        log.exception(
            "belief_revision LLM apply failed",
            extra={
                "existing_entity_id": touchpoint.existing_class_id,
                "action": getattr(proposal, "action", ""),
            },
        )
        return {
            "status": "failed",
            "verdict": mech.verdict,
            "action": getattr(proposal, "action", mech.action),
            "agent_type": AGENT_LLM,
            "rule_id": mech.rule_id,
            "existing_entity_id": touchpoint.existing_class_id,
            "new_concept_label": touchpoint.new_concept_label,
            "reasoning": getattr(proposal, "reasoning", ""),
            "error": str(exc),
            "skipped": False,
            "revision_meta_key": None,
        }


def _record_from_result(
    result: SupersedeResult,
    *,
    verdict: str,
    agent_type: str,
    existing_entity_id: str,
    new_concept_label: str,
    reasoning: str,
    rule_id: str,
) -> dict[str, Any]:
    """Build the dict that goes into ``revision_actions[]``."""
    return {
        "status": result.status,
        "verdict": verdict,
        "action": result.action,
        "agent_type": agent_type,
        "rule_id": rule_id,
        "existing_entity_id": existing_entity_id,
        "new_concept_label": new_concept_label,
        "reasoning": reasoning,
        "revision_meta_key": result.revision_meta_key,
        "new_version_key": result.new_version_key,
        "expired_version_key": result.expired_version_key,
        "new_edge_key": result.new_edge_key,
        "skipped": result.skipped,
        "skipped_reason": result.skipped_reason,
    }
