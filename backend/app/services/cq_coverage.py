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

from app.db import requirements_repo
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
        if ev["answerable"]:
            bucket["answerable"] += 1

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
        "gaps": [
            {"text": r["text"], "use_case": r["use_case"], "status": r["status"]}
            for r in results
            if not r["answerable"]
        ],
    }
