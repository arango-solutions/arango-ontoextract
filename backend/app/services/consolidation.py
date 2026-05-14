"""Background ontology consolidation job (Stream 11 IBR.17).

Sweeps an ontology and:

1. **Re-runs the rule engine** (:mod:`app.services.ontology_rule_engine`)
   to surface contradictions / redundancies introduced since the last
   consolidation. Each violation becomes a planned action (and, if
   not dry-run, a ``revision_meta`` row with action FLAG_FOR_CURATION
   so a curator triages it).

2. **Applies confidence decay** (:mod:`app.services.confidence_decay`).
   The decay function already supports dry-run; we pass it through.

3. **Flags stale beliefs** -- live classes whose ``last_evidenced_at``
   is older than a configurable threshold, regardless of decay being
   enabled. Each becomes a planned ``FLAG_FOR_CURATION`` so the
   curator can decide whether the class is still meaningful.

The job is **resumable**: a :class:`~revision_safety.ConsolidationCursor`
is checkpointed to ``consolidation_jobs`` after every stage so a
restart picks up where it left off (see IBR.18).

The job is **dry-run-safe**: ``dry_run=True`` returns the would-be
plan without writing to the graph or to ``revision_meta``. Callers
(the admin endpoint) use this to preview impact before applying.

Telemetry-wise, every stage logs structured ``ms_*`` timings and the
final :class:`ConsolidationReport` carries per-stage metrics so the
admin UI can render a summary without re-querying.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from arango.database import StandardDatabase

from app.config import settings
from app.db import revision_meta_repo as rev_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services import confidence_decay, ontology_rule_engine, revision_safety

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StaleBelief:
    """One class that hasn't been re-evidenced for ``stale_after_days``."""

    class_key: str
    label: str
    age_days: float
    current_confidence: float | None


@dataclass
class ConsolidationReport:
    """Aggregated output of one consolidation pass.

    Carries enough information to render a meaningful admin UI without
    re-querying. Serializable via :meth:`to_dict`.
    """

    job_key: str
    ontology_id: str
    dry_run: bool
    started_at: float
    finished_at: float = 0.0
    status: str = "running"  # "running" | "completed" | "failed" | "cancelled"

    # Per-stage outputs.
    rules: ontology_rule_engine.RuleEngineReport | None = None
    decay: confidence_decay.DecayReport | None = None
    stale_beliefs: list[StaleBelief] = field(default_factory=list)

    # Counts of revision_meta rows written (zero when dry_run=True).
    revisions_written_rules: int = 0
    revisions_written_stale: int = 0

    # Per-stage timings (ms).
    ms_rules: float = 0.0
    ms_decay: float = 0.0
    ms_stale: float = 0.0

    error: str | None = None

    @property
    def total_planned_actions(self) -> int:
        rules = len(self.rules.violations) if self.rules else 0
        decayed = self.decay.classes_decayed if self.decay else 0
        return rules + decayed + len(self.stale_beliefs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_key": self.job_key,
            "ontology_id": self.ontology_id,
            "dry_run": self.dry_run,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 1)
            if self.finished_at
            else None,
            "rules": self.rules.to_dict() if self.rules else None,
            "decay": self.decay.to_dict() if self.decay else None,
            "stale_beliefs": [
                {
                    "class_key": b.class_key,
                    "label": b.label,
                    "age_days": b.age_days,
                    "current_confidence": b.current_confidence,
                }
                for b in self.stale_beliefs
            ],
            "revisions_written_rules": self.revisions_written_rules,
            "revisions_written_stale": self.revisions_written_stale,
            "total_planned_actions": self.total_planned_actions,
            "ms_rules": self.ms_rules,
            "ms_decay": self.ms_decay,
            "ms_stale": self.ms_stale,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Stale-belief detection
# ---------------------------------------------------------------------------


def _scan_stale_beliefs(
    db: StandardDatabase,
    ontology_id: str,
    *,
    stale_after_days: float,
    now: float,
    limit: int,
) -> list[StaleBelief]:
    """Return live classes older than ``stale_after_days`` since last evidence.

    The age signal is the same as :mod:`confidence_decay`: prefer
    ``last_evidenced_at`` (set by REINFORCE), fall back to ``created``
    (the version's interval start). Classes with no usable timestamp
    are silently ignored (the decay report's ``skipped_no_age`` is
    the place to surface those).

    ``limit`` caps the result so a freshly-deployed ontology with
    thousands of legacy classes doesn't write thousands of inbox rows
    on the first consolidation.
    """
    if not db.has_collection("ontology_classes"):
        return []
    threshold_ts = now - (stale_after_days * 86400.0)
    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND ( c.last_evidenced_at != null AND c.last_evidenced_at < @threshold ) "
            "      OR ( c.last_evidenced_at == null AND c.created != null "
            "           AND c.created < @threshold ) "
            "SORT (c.last_evidenced_at != null ? c.last_evidenced_at : c.created) ASC "
            "LIMIT @limit "
            "RETURN { "
            "  _key: c._key, label: c.label, "
            "  last_evidenced_at: c.last_evidenced_at, "
            "  created: c.created, "
            "  current_confidence: c.current_confidence "
            "}",
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "threshold": threshold_ts,
                "limit": limit,
            },
        )
    )
    out: list[StaleBelief] = []
    for row in rows:
        ts = row.get("last_evidenced_at") or row.get("created")
        if not isinstance(ts, (int, float)) or ts <= 0:
            continue
        age_days = round((now - float(ts)) / 86400.0, 1)
        out.append(
            StaleBelief(
                class_key=str(row.get("_key") or ""),
                label=str(row.get("label") or row.get("_key") or ""),
                age_days=age_days,
                current_confidence=row.get("current_confidence"),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Inbox-row writer (only when not dry-run)
# ---------------------------------------------------------------------------


def _write_inbox_rows_for_violations(
    *,
    ontology_id: str,
    violations: list[ontology_rule_engine.Violation],
    job_key: str,
    db: StandardDatabase,
) -> int:
    """Persist one ``revision_meta`` row per violation, status=pending.

    Returns the number of rows written. Exceptions per row are
    swallowed and logged so a single bad violation doesn't abort the
    whole consolidation pass.
    """
    written = 0
    for v in violations:
        try:
            entity_id = v.entity_ids[0] if v.entity_ids else f"unknown/{job_key}"
            verdict = v.suggested_action or rev_repo.VERDICT_UNCERTAIN
            if verdict not in rev_repo.VERDICTS:
                verdict = rev_repo.VERDICT_UNCERTAIN
            rev_repo.record_revision(
                ontology_id=ontology_id,
                verdict=verdict,
                action=rev_repo.ACTION_FLAG_FOR_CURATION,
                agent_type=rev_repo.AGENT_MECHANICAL,
                agent_version=f"consolidation+{v.rule_id}",
                triggering_doc_id=f"consolidation:{job_key}",
                existing_entity_id=entity_id,
                evidence_quotes=[],
                reasoning=v.description,
                db=db,
            )
            written += 1
        except Exception:
            log.exception(
                "consolidation: failed to write inbox row for rule %s on entity %s",
                v.rule_id,
                v.entity_ids,
            )
    return written


def _write_inbox_rows_for_stale(
    *,
    ontology_id: str,
    stale: list[StaleBelief],
    job_key: str,
    db: StandardDatabase,
) -> int:
    """Persist one ``revision_meta`` row per stale belief, status=pending."""
    written = 0
    for s in stale:
        try:
            rev_repo.record_revision(
                ontology_id=ontology_id,
                verdict=rev_repo.VERDICT_UNCERTAIN,
                action=rev_repo.ACTION_FLAG_FOR_CURATION,
                agent_type=rev_repo.AGENT_MECHANICAL,
                agent_version="consolidation+stale_belief",
                triggering_doc_id=f"consolidation:{job_key}",
                existing_entity_id=f"ontology_classes/{s.class_key}",
                evidence_quotes=[],
                reasoning=(
                    f"Class {s.label!r} has not been re-evidenced for "
                    f"{s.age_days:.1f} days; consider retracting or "
                    f"adding new evidence."
                ),
                db=db,
            )
            written += 1
        except Exception:
            log.exception(
                "consolidation: failed to write inbox row for stale belief %s",
                s.class_key,
            )
    return written


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_consolidation(
    ontology_id: str,
    *,
    dry_run: bool = False,
    job_key: str | None = None,
    stale_after_days: float | None = None,
    stale_inbox_limit: int = 200,
    db: StandardDatabase | None = None,
) -> ConsolidationReport:
    """Run a full consolidation pass on one ontology.

    Parameters
    ----------
    ontology_id:
        Ontology to consolidate.
    dry_run:
        When True, no ``revision_meta`` rows are written and the decay
        function is invoked with ``dry_run=True``. The report still
        carries the planned actions so the admin UI can preview them.
    job_key:
        Optional explicit job key for cursor resumption. When ``None``,
        a fresh ``uuid4`` is generated -- always treated as a new job.
        To resume an existing job, pass the same ``job_key`` again
        (callers obtain it from ``revision_safety.list_recent_jobs``).
    stale_after_days:
        Threshold for the stale-belief stage. When ``None``, falls
        back to ``settings.belief_revision_decay_half_life_days``
        (a class hasn't been re-evidenced for one half-life ⇒ flag).
    stale_inbox_limit:
        Cap on the number of inbox rows written for stale beliefs in
        one pass. Defaults to 200 -- generous for a healthy ontology
        but low enough that a fresh deployment can't flood the inbox.
    db:
        Optional injected database handle (tests).

    Returns
    -------
    ConsolidationReport
        Always returned -- on per-stage failure the report carries
        the partial results and ``status="failed"`` with ``error``
        populated.
    """
    db = db or get_db()
    job_key = job_key or f"consolidation_{uuid.uuid4().hex[:12]}"
    started = time.time()
    cursor = revision_safety.ConsolidationCursor(
        job_key=job_key,
        ontology_id=ontology_id,
        stage="rules",
        started_at=started,
        dry_run=dry_run,
    )
    revision_safety.checkpoint_cursor(cursor, db=db)
    report = ConsolidationReport(
        job_key=job_key,
        ontology_id=ontology_id,
        dry_run=dry_run,
        started_at=started,
    )

    log.info(
        "consolidation started",
        extra={
            "job_key": job_key,
            "ontology_id": ontology_id,
            "dry_run": dry_run,
        },
    )

    # ---- Stage 1: rule engine -----------------------------------------
    try:
        t0 = time.perf_counter()
        report.rules = ontology_rule_engine.evaluate_rules(db, ontology_id)
        report.ms_rules = round((time.perf_counter() - t0) * 1000, 1)
        if not dry_run and report.rules.violations:
            report.revisions_written_rules = _write_inbox_rows_for_violations(
                ontology_id=ontology_id,
                violations=report.rules.violations,
                job_key=job_key,
                db=db,
            )
        cursor.stage = "decay"
        cursor.processed_count = (
            len(report.rules.violations) if report.rules else 0
        )
        revision_safety.checkpoint_cursor(cursor, db=db)
    except Exception as exc:
        log.exception("consolidation: rules stage failed")
        report.status = "failed"
        report.error = f"rules stage: {exc}"
        report.finished_at = time.time()
        cursor.status = "failed"
        revision_safety.checkpoint_cursor(cursor, db=db)
        return report

    # ---- Stage 2: confidence decay ------------------------------------
    try:
        t0 = time.perf_counter()
        report.decay = confidence_decay.apply_confidence_decay(
            db,
            ontology_id,
            dry_run=dry_run,
            # ``force`` lets the dry-run preview decay even when the
            # global feature flag is off, so admins can preview impact
            # before enabling.
            force=dry_run,
        )
        report.ms_decay = round((time.perf_counter() - t0) * 1000, 1)
        cursor.stage = "stale"
        cursor.processed_count += (
            report.decay.classes_decayed if report.decay else 0
        )
        revision_safety.checkpoint_cursor(cursor, db=db)
    except Exception as exc:
        log.exception("consolidation: decay stage failed")
        report.status = "failed"
        report.error = f"decay stage: {exc}"
        report.finished_at = time.time()
        cursor.status = "failed"
        revision_safety.checkpoint_cursor(cursor, db=db)
        return report

    # ---- Stage 3: stale beliefs ---------------------------------------
    try:
        t0 = time.perf_counter()
        threshold_days = (
            stale_after_days
            if stale_after_days is not None
            else float(settings.belief_revision_decay_half_life_days)
        )
        report.stale_beliefs = _scan_stale_beliefs(
            db,
            ontology_id,
            stale_after_days=threshold_days,
            now=time.time(),
            limit=stale_inbox_limit,
        )
        if not dry_run and report.stale_beliefs:
            report.revisions_written_stale = _write_inbox_rows_for_stale(
                ontology_id=ontology_id,
                stale=report.stale_beliefs,
                job_key=job_key,
                db=db,
            )
        report.ms_stale = round((time.perf_counter() - t0) * 1000, 1)
        cursor.stage = "done"
        cursor.processed_count += len(report.stale_beliefs)
        cursor.status = "completed"
        revision_safety.checkpoint_cursor(cursor, db=db)
    except Exception as exc:
        log.exception("consolidation: stale stage failed")
        report.status = "failed"
        report.error = f"stale stage: {exc}"
        report.finished_at = time.time()
        cursor.status = "failed"
        revision_safety.checkpoint_cursor(cursor, db=db)
        return report

    report.status = "completed"
    report.finished_at = time.time()
    log.info(
        "consolidation completed",
        extra={
            "job_key": job_key,
            "ontology_id": ontology_id,
            "dry_run": dry_run,
            "ms_rules": report.ms_rules,
            "ms_decay": report.ms_decay,
            "ms_stale": report.ms_stale,
            "violations": len(report.rules.violations) if report.rules else 0,
            "decayed": report.decay.classes_decayed if report.decay else 0,
            "stale": len(report.stale_beliefs),
            "revisions_written_rules": report.revisions_written_rules,
            "revisions_written_stale": report.revisions_written_stale,
        },
    )
    return report
