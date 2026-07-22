"""Competency-question coverage validation (Stream 22 / CQ-PR4+5, PRD §6.19).

Runs each competency question's query against the ontology (+ A-box) and reports
which CQs the ontology can answer and which are gaps (FR-19.5). The coverage
percentage is the metric that both drives extraction scope (CQ-PR6 feeds gaps
back) and gates releases (Stream 19).

Safety: CQ queries are human-authored/verified (CQ-PR3), but we still refuse to
execute anything that isn't read-only — a query containing a write operation is
classified ``error`` (never run), so coverage validation cannot mutate data.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from arango.database import StandardDatabase

from app.db import cq_gap_repo, requirements_repo
from app.db.client import get_db
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_WRITE_KEYWORDS = re.compile(r"\b(INSERT|UPDATE|REPLACE|REMOVE|UPSERT)\b", re.IGNORECASE)


def _is_read_only(query: str) -> bool:
    return not _WRITE_KEYWORDS.search(query or "")


def _evaluate_cq(db: StandardDatabase, cq: dict[str, Any], ontology_id: str) -> dict[str, Any]:
    """Classify a single CQ: answerable / unanswerable / unformalized / error."""
    query = str(cq.get("query") or "").strip()
    if not query:
        return {"status": "unformalized", "answerable": False}
    if not _is_read_only(query):
        return {"status": "error", "answerable": False, "detail": "query is not read-only"}
    try:
        bind = {"ontology_id": ontology_id} if "@ontology_id" in query else None
        cursor = run_aql(db, query, bind_vars=bind)
        first = next(iter(cursor), None)
        answerable = first is not None
        return {"status": "answerable" if answerable else "unanswerable", "answerable": answerable}
    except Exception as exc:
        log.info("CQ query failed for ontology %s: %s", ontology_id, type(exc).__name__)
        return {"status": "error", "answerable": False, "detail": type(exc).__name__}


def run_coverage(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> dict[str, Any]:
    """Evaluate every competency question in the ontology's spec.

    Returns a coverage report: totals per status, ``coverage_pct`` (answerable /
    total), a per-use-case breakdown, and the ``gaps`` (every non-answerable CQ).
    Raises ``ValueError`` if the ontology has no requirements spec.
    """
    if db is None:
        db = get_db()
    spec = requirements_repo.get_requirements(db, ontology_id)
    if spec is None:
        raise ValueError(f"no requirements spec for ontology '{ontology_id}'")

    cqs = requirements_repo.iter_competency_questions(spec)
    results: list[dict[str, Any]] = []
    by_use_case: dict[str, dict[str, int]] = {}
    by_priority: dict[str, dict[str, int]] = {}
    for cq in cqs:
        ev = _evaluate_cq(db, cq, ontology_id)
        results.append(
            {
                "text": cq.get("text"),
                "use_case": cq.get("use_case"),
                "priority": cq.get("priority"),
                **ev,
            }
        )
        uc = cq.get("use_case") or "(unassigned)"
        bucket = by_use_case.setdefault(uc, {"total": 0, "answerable": 0})
        bucket["total"] += 1
        prio = str(cq.get("priority") or "(unset)")
        pbucket = by_priority.setdefault(prio, {"total": 0, "answerable": 0})
        pbucket["total"] += 1
        if ev["answerable"]:
            bucket["answerable"] += 1
            pbucket["answerable"] += 1

    total = len(results)
    answerable = sum(1 for r in results if r["answerable"])

    def _count(status: str) -> int:
        return sum(1 for r in results if r["status"] == status)

    return {
        "ontology_id": ontology_id,
        "total": total,
        "answerable": answerable,
        "unanswerable": _count("unanswerable"),
        "unformalized": _count("unformalized"),
        "error": _count("error"),
        "coverage_pct": round(answerable / total * 100, 1) if total else 0.0,
        "by_use_case": by_use_case,
        "by_priority": by_priority,
        "gaps": [
            {
                "text": r["text"],
                "use_case": r["use_case"],
                "priority": r["priority"],
                "status": r["status"],
            }
            for r in results
            if not r["answerable"]
        ],
    }


def route_gaps_to_backlog(
    db: StandardDatabase | None,
    *,
    ontology_id: str,
    report: dict[str, Any],
) -> dict[str, int]:
    """Persist a coverage report's gaps as trackable backlog items (FR-19.6).

    Opens (or re-opens) a backlog item per gap and resolves any previously-open
    gap that is no longer present (the CQ became answerable). Idempotent — safe to
    call on every coverage run. Returns ``{opened, resolved, open_total}``.
    """
    if db is None:
        db = get_db()
    gaps = report.get("gaps") or []
    active_keys: set[str] = set()
    opened = 0
    for g in gaps:
        text = str(g.get("text") or "").strip()
        if not text:
            continue
        active_keys.add(cq_gap_repo.gap_key(ontology_id, text))
        if cq_gap_repo.upsert_gap(
            db,
            ontology_id=ontology_id,
            cq_text=text,
            use_case=g.get("use_case"),
            priority=g.get("priority"),
            gap_kind=str(g.get("status") or "unanswerable"),
        ):
            opened += 1
    resolved = cq_gap_repo.resolve_gaps_not_in(db, ontology_id, active_keys)
    open_total = len(cq_gap_repo.list_gaps(db, ontology_id, status=cq_gap_repo.STATUS_OPEN))
    return {"opened": opened, "resolved": resolved, "open_total": open_total}


def evaluate_release_gate(
    report: dict[str, Any],
    *,
    min_priority_pct: float,
    gate_priorities: tuple[str, ...] = ("high",),
) -> dict[str, Any]:
    """Evaluate CQ coverage as a release-readiness signal (FR-19.8).

    A release can require >= ``min_priority_pct`` of the *priority* competency
    questions to be answerable. Only CQs whose priority is in ``gate_priorities``
    count. When there are no priority CQs the gate passes vacuously. Returns the
    pass/fail signal plus the blocking gaps (priority CQs still unanswered) so the
    Release Readiness Review (Stream 19) can surface them.
    """
    by_priority = report.get("by_priority") or {}
    considered = sum(b.get("total", 0) for p, b in by_priority.items() if p in gate_priorities)
    answerable = sum(b.get("answerable", 0) for p, b in by_priority.items() if p in gate_priorities)
    actual_pct = round(answerable / considered * 100, 1) if considered else 100.0
    passed = actual_pct >= min_priority_pct
    blocking = [g for g in (report.get("gaps") or []) if g.get("priority") in gate_priorities]
    return {
        "passed": passed,
        "required_pct": min_priority_pct,
        "actual_pct": actual_pct,
        "priorities": list(gate_priorities),
        "considered": considered,
        "answerable": answerable,
        "blocking_gaps": blocking,
    }
