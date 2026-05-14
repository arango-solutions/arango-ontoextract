"""Admin endpoints — system operations and review artifacts."""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.client import get_db
from app.services.confidence_decay import apply_confidence_decay
from app.services.consolidation import run_consolidation
from app.services.edge_dedup import (
    DEDUPABLE_COLLECTIONS,
    dedupe_live_edges,
)
from app.services.edge_repair import repair_orphan_object_property_ranges
from app.services.feedback_learning import build_feedback_learning_examples
from app.services.ontology_rule_engine import evaluate_rules
from app.services.revision_safety import (
    get_default_limiter,
    list_recent_jobs,
    load_cursor,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ONTOLOGY_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
    "ontology_constraints",
    "subclass_of",
    "has_property",
    "has_constraint",
    "extracted_from",
    "extends_domain",
    "related_to",
    "rdfs_domain",
    "rdfs_range_class",
    "imports",
    "has_chunk",
    "produced_by",
    "extraction_runs",
    "ontology_registry",
    "ontology_releases",
    "curation_decisions",
    "quality_history",
]

ALL_COLLECTIONS = [*ONTOLOGY_COLLECTIONS, "documents", "chunks"]


def _remove_ontology_graphs(db) -> list[str]:
    """Remove all per-ontology named graphs (ontology_*)."""
    removed: list[str] = []
    try:
        for g in db.graphs():
            name = g["name"] if isinstance(g, dict) else g
            if isinstance(name, str) and name.startswith("ontology_"):
                db.delete_graph(name, drop_collections=False)
                removed.append(name)
    except Exception:
        log.warning("failed to list/remove ontology graphs", exc_info=True)
    return removed


def _require_reset_enabled() -> None:
    """Allow ``/admin/reset*`` only when the operator opts in via Settings.

    Reads ``settings.allow_system_reset`` (env: ``ALLOW_SYSTEM_RESET``) so the
    knob lives in one place — see ``app.config.Settings`` and
    ``backend/app/AGENTS.md`` ("Configuration comes from app/config.py via the
    settings singleton — never read env vars directly").
    """
    if not settings.allow_system_reset:
        raise HTTPException(
            status_code=403,
            detail="System reset disabled. Set ALLOW_SYSTEM_RESET=true in .env to enable.",
        )


@router.post("/reset")
async def reset_ontology_data() -> dict[str, Any]:
    """Purge extracted ontology data while keeping documents and chunks."""
    _require_reset_enabled()
    db = get_db()
    truncated: list[str] = []
    for name in ONTOLOGY_COLLECTIONS:
        if db.has_collection(name):
            db.collection(name).truncate()
            truncated.append(name)
    graphs_removed = _remove_ontology_graphs(db)
    log.warning("system reset: truncated %s, removed graphs %s", truncated, graphs_removed)
    return {"reset": True, "collections_truncated": truncated, "graphs_removed": graphs_removed}


@router.post("/reset/full")
async def reset_all_data() -> dict[str, Any]:
    """Full purge including documents and chunks."""
    _require_reset_enabled()
    db = get_db()
    truncated: list[str] = []
    for name in ALL_COLLECTIONS:
        if db.has_collection(name):
            db.collection(name).truncate()
            truncated.append(name)
    graphs_removed = _remove_ontology_graphs(db)
    log.warning("full system reset: truncated %s, removed graphs %s", truncated, graphs_removed)
    return {"reset": True, "collections_truncated": truncated, "graphs_removed": graphs_removed}


@router.post("/ontology/{ontology_id}/repair-edges")
async def repair_ontology_edges(
    ontology_id: str,
    dry_run: bool = Query(
        default=False,
        description=(
            "When true, run the matcher and return the would-be repairs "
            "without inserting any rdfs_range_class edges."
        ),
    ),
) -> dict[str, Any]:
    """Repair orphan ``ontology_object_properties`` for one ontology.

    Calls :func:`app.services.edge_repair.repair_orphan_object_property_ranges`
    -- see that module's docstring for the matching algorithm and the rules
    for what counts as an orphan. Idempotent: a second call after a
    successful repair finds zero orphans.

    Returns the :class:`RepairReport` as a dict so the caller can see
    exactly which properties were repaired (and which couldn't be).
    """
    try:
        db = get_db()
        report = repair_orphan_object_property_ranges(
            db,
            ontology_id,
            dry_run=dry_run,
        )
        return report.to_dict()
    except Exception as exc:
        log.exception(
            "edge repair failed for ontology %s (dry_run=%s)",
            ontology_id,
            dry_run,
        )
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/ontology/{ontology_id}/dedupe-edges")
async def dedupe_ontology_edges(
    ontology_id: str,
    collection: str = Query(
        default="rdfs_domain",
        description=(
            "Edge collection to dedupe. Must be in the dedup allowlist "
            "(currently rdfs_domain / rdfs_range_class). subclass_of "
            "is intentionally excluded -- its edges carry per-edge "
            "evidence and need a different cleanup contract."
        ),
    ),
    dry_run: bool = Query(
        default=True,
        description=(
            "When true, return the would-be dedup report without "
            "expiring any edges. Defaults to true so a curl typo "
            "doesn't quietly mutate live data."
        ),
    ),
) -> dict[str, Any]:
    """Find and (optionally) expire duplicate live structural edges.

    Companion to the writer-side fix in
    :func:`app.db.utils.insert_temporal_edge_if_absent`. Ontologies
    extracted before that helper landed accumulated duplicate live
    ``rdfs_domain`` edges -- one per logical pair per re-extraction
    pass. This endpoint expires the extras (keeping the oldest
    ``created`` so provenance reads "this relationship has held
    since X") and stamps each expired edge with ``dedup_meta`` so
    a future audit can find them.

    Idempotent: re-running against a clean collection finds zero
    duplicates and is a no-op.

    Returns the :class:`DedupReport` as a dict so the caller can
    inspect every (kept, expired) decision.
    """
    if collection not in DEDUPABLE_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"collection {collection!r} is not in the dedup allowlist "
                f"{sorted(DEDUPABLE_COLLECTIONS)}"
            ),
        )
    try:
        db = get_db()
        report = dedupe_live_edges(
            db, ontology_id, collection, dry_run=dry_run
        )
        return report.to_dict()
    except ValueError as exc:
        # Defensive: dedupe_live_edges has its own allowlist gate
        # that raises ValueError; surface as 400, not 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception(
            "edge dedup failed for ontology %s (collection=%s, dry_run=%s)",
            ontology_id,
            collection,
            dry_run,
        )
        raise HTTPException(
            status_code=500, detail="Internal server error"
        ) from exc


@router.get("/ontology/{ontology_id}/reflection-report")
async def ontology_reflection_report(
    ontology_id: str,
    half_life_days: float | None = Query(
        default=None,
        gt=0,
        description=(
            "Override decay half-life (days) for this what-if. "
            "Defaults to settings.belief_revision_decay_half_life_days."
        ),
    ),
    floor: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override decay floor for this what-if. "
            "Defaults to settings.belief_revision_decay_floor."
        ),
    ),
) -> dict[str, Any]:
    """Read-only reflection: rule-engine violations + decay preview.

    Composes two existing services with no DB writes:

    * :func:`app.services.ontology_rule_engine.evaluate_rules` --
      runs the four built-in rule families (synonym triangles,
      subClassOf cycles, disjointness, cardinality) against the live
      ontology and returns structured ``Violation`` records.
    * :func:`app.services.confidence_decay.apply_confidence_decay`
      with ``dry_run=True`` -- previews what each class's confidence
      would become if decay were applied right now, without touching
      the graph.

    The combined response is the artifact a curator (or the planned
    IBR.14 background-consolidation pass) inspects to decide whether
    a corrective belief-revision cycle is warranted. ALWAYS dry-run
    by definition: hitting this endpoint cannot mutate the ontology.

    The ``half_life_days`` and ``floor`` query params let curators
    explore "what if we tightened the decay floor?" without changing
    deployment configuration.
    """
    try:
        db = get_db()

        rules_report = evaluate_rules(db, ontology_id)
        decay_report = apply_confidence_decay(
            db,
            ontology_id,
            dry_run=True,
            half_life_days=half_life_days,
            floor=floor,
        )

        violations_by_severity: dict[str, int] = dict(
            Counter(v.severity for v in rules_report.violations)
        )
        violations_by_rule: dict[str, int] = dict(
            Counter(v.rule_id for v in rules_report.violations)
        )

        return {
            "ontology_id": ontology_id,
            "evaluated_at": time.time(),
            "rule_violations": rules_report.to_dict(),
            "decay_preview": decay_report.to_dict(),
            "summary": {
                "total_violations": len(rules_report.violations),
                "violations_by_severity": violations_by_severity,
                "violations_by_rule": violations_by_rule,
                "rules_evaluated": list(rules_report.rules_evaluated),
                "rules_skipped": list(rules_report.rules_skipped),
                "decay_classes_examined": decay_report.classes_examined,
                "decay_classes_would_change": decay_report.classes_decayed,
                "decay_skipped_no_age": decay_report.skipped_no_age,
            },
        }
    except Exception as exc:
        log.exception(
            "reflection report failed for ontology %s",
            ontology_id,
        )
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/feedback-learning")
async def feedback_learning_artifacts(
    ontology_id: str | None = Query(
        default=None,
        description="Optional ontology ID used to scope curation feedback.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of curation decisions to convert into artifacts.",
    ),
) -> dict[str, Any]:
    """Return gated HITL learning artifacts for offline review/export."""
    try:
        db = get_db()
        return build_feedback_learning_examples(
            db,
            ontology_id=ontology_id,
            limit=limit,
        )
    except Exception as exc:
        log.exception("failed to build feedback-learning artifacts")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Belief-revision consolidation (Stream 11 IBR.17)
# ---------------------------------------------------------------------------


@router.post("/ontology/{ontology_id}/consolidate")
async def consolidate_ontology(
    ontology_id: str,
    dry_run: bool = Query(
        default=False,
        description=(
            "When True, returns the planned actions without writing any "
            "revision_meta rows or applying decay. Use to preview impact "
            "before kicking off the real run."
        ),
    ),
    job_key: str | None = Query(
        default=None,
        description=(
            "Optional explicit job key. Pass an existing key to resume a "
            "checkpointed job (see GET /admin/consolidation-jobs)."
        ),
    ),
    stale_after_days: float | None = Query(
        default=None,
        gt=0,
        description=(
            "Override the stale-belief threshold. Defaults to the "
            "configured decay half-life."
        ),
    ),
    stale_inbox_limit: int = Query(
        default=200,
        ge=1,
        le=5000,
        description="Cap on the number of inbox rows written for stale beliefs.",
    ),
) -> dict[str, Any]:
    """Run a consolidation pass on one ontology (rules + decay + stale).

    Three sequential stages:
      1. Re-runs the ontology rule engine and writes one
         FLAG_FOR_CURATION revision_meta row per violation.
      2. Applies confidence decay to live classes (already-existing
         service; respects the global decay flag unless dry_run=True
         which forces a preview).
      3. Scans for stale beliefs (live classes not re-evidenced
         within the threshold) and writes one FLAG_FOR_CURATION
         row per stale class.

    Resumable via job_key cursor (consolidation_jobs collection);
    safe to dry-run before hitting for real.
    """
    try:
        report = run_consolidation(
            ontology_id,
            dry_run=dry_run,
            job_key=job_key,
            stale_after_days=stale_after_days,
            stale_inbox_limit=stale_inbox_limit,
        )
        return report.to_dict()
    except Exception as exc:
        log.exception("consolidation failed for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/consolidation-jobs")
async def list_consolidation_jobs(
    ontology_id: str | None = Query(
        default=None,
        description="Optional ontology filter; omit for global recent runs.",
    ),
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """List the most-recent consolidation jobs (newest-first).

    Powers the admin dashboard's "recent runs" panel and gives operators
    the job_key needed to resume a partially-completed job.
    """
    try:
        return {
            "data": list_recent_jobs(ontology_id=ontology_id, limit=limit),
            "ontology_id": ontology_id,
        }
    except Exception as exc:
        log.exception("failed to list consolidation jobs")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/consolidation-jobs/{job_key}")
async def get_consolidation_job(job_key: str) -> dict[str, Any]:
    """Fetch one consolidation job's checkpointed state by ``job_key``."""
    cursor = load_cursor(job_key)
    if cursor is None:
        raise HTTPException(status_code=404, detail=f"Job {job_key!r} not found")
    return cursor.to_doc()


@router.get("/belief-revision/circuit-breaker")
async def get_circuit_breaker_state() -> dict[str, Any]:
    """Return a snapshot of the LLM-revision-agent circuit-breaker state.

    Powers the dashboard tile that warns operators when the breaker
    is tripped (or close to it).
    """
    return get_default_limiter().current_rate()
