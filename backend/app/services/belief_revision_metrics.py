"""Read-only aggregation helpers for the belief-revision dashboard
(Stream 11 IBR.6 telemetry hooks).

These functions back the ``GET /api/v1/quality/{ontology_id}/revisions``
endpoint specified in PRD §7.7a. They are intentionally read-only and
cheap -- the dashboard polls them frequently, so every helper is
implemented as a single AQL pass with bounded result size.

All functions degrade gracefully when ``revision_meta`` does not yet
exist (e.g. on freshly-migrated ontologies that have not yet had a
revision recorded). They return zero-filled structures rather than
raising, so the dashboard never sees a 5xx because of an empty
collection.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.db.client import get_db
from app.db.revision_meta_repo import (
    ACTIONS,
    STATUSES,
    VERDICTS,
)
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_COLLECTION = "revision_meta"


def _ensure_db(db: Any | None) -> Any:
    return db if db is not None else get_db()


def _empty_counts(buckets: frozenset[str]) -> dict[str, int]:
    """Return a dict pre-filled with zeros for every known bucket key.

    Pre-filling is important: the dashboard renders bars/legends from
    this dict, so callers must always see every category, not just
    those that have non-zero counts.
    """
    return dict.fromkeys(sorted(buckets), 0)


def revisions_summary(
    ontology_id: str,
    *,
    db: Any | None = None,
) -> dict[str, dict[str, int]]:
    """Counts of revisions by verdict / action / status for one ontology.

    Returns
    -------
    dict
        ``{
            "by_verdict": {VERDICT_REINFORCED: int, ...},
            "by_action":  {ACTION_REINFORCE: int, ...},
            "by_status":  {STATUS_APPLIED: int, ...},
            "total":      int,
        }``
        Every known verdict / action / status appears as a key, with
        zero counts when no rows match -- the dashboard renders these
        as bars/badges and benefits from a stable shape.
    """
    db = _ensure_db(db)
    summary = {
        "by_verdict": _empty_counts(VERDICTS),
        "by_action": _empty_counts(ACTIONS),
        "by_status": _empty_counts(STATUSES),
        "total": 0,
    }
    if not db.has_collection(_COLLECTION):
        return summary

    bind = {"oid": ontology_id}
    rows = list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.ontology_id == @oid "
            "COLLECT verdict = r.verdict, action = r.action, status = r.status "
            "WITH COUNT INTO n "
            "RETURN { verdict, action, status, n }",
            bind_vars=bind,
        )
    )
    for row in rows:
        n = int(row.get("n", 0))
        summary["total"] += n
        v = row.get("verdict")
        a = row.get("action")
        s = row.get("status")
        if isinstance(v, str) and v in summary["by_verdict"]:
            summary["by_verdict"][v] += n
        if isinstance(a, str) and a in summary["by_action"]:
            summary["by_action"][a] += n
        if isinstance(s, str) and s in summary["by_status"]:
            summary["by_status"][s] += n
    return summary


def recent_revisions(
    ontology_id: str,
    *,
    limit: int = 20,
    db: Any | None = None,
) -> list[dict[str, Any]]:
    """Most-recent N revisions, newest-first, for the dashboard timeline tile.

    Compact projection: only the fields the timeline tile needs, so
    the response stays under a few KB even at high ``limit``.
    """
    db = _ensure_db(db)
    if not db.has_collection(_COLLECTION):
        return []
    return list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.ontology_id == @oid "
            "SORT r.created DESC "
            "LIMIT @limit "
            "RETURN { "
            "  _key: r._key, verdict: r.verdict, action: r.action, "
            "  status: r.status, agent_type: r.agent_type, "
            "  existing_entity_id: r.existing_entity_id, "
            "  triggering_doc_id: r.triggering_doc_id, "
            "  confidence_before: r.confidence_before, "
            "  confidence_after: r.confidence_after, "
            "  reasoning: r.reasoning, created: r.created "
            "}",
            bind_vars={"oid": ontology_id, "limit": limit},
        )
    )


def decay_status(
    ontology_id: str,
    *,
    db: Any | None = None,
) -> dict[str, Any]:
    """Snapshot of the confidence-decay state for the dashboard.

    Returns
    -------
    dict
        ``{
            "enabled":           bool,   # echoes settings.belief_revision_decay_enabled
            "half_life_days":    float,  # configured decay half-life
            "floor":             float,  # configured decay floor
            "last_decay_run_at": float | None,  # max(confidence_decayed_at) over live classes
            "decayed_classes":   int,    # how many live classes carry a decayed value
        }``

    A ``last_decay_run_at`` of ``None`` means decay has never been
    applied (or was applied before this field existed). The dashboard
    renders this as "Never run" rather than zero-time, so the field
    must remain ``None`` rather than 0 when no run is recorded.
    """
    db = _ensure_db(db)
    snapshot: dict[str, Any] = {
        "enabled": bool(settings.belief_revision_decay_enabled),
        "half_life_days": float(settings.belief_revision_decay_half_life_days),
        "floor": float(settings.belief_revision_decay_floor),
        "last_decay_run_at": None,
        "decayed_classes": 0,
    }
    if not db.has_collection("ontology_classes"):
        return snapshot

    # Single AQL pass: classes with current_confidence + their max
    # confidence_decayed_at. We sentinel ``never`` against the live
    # set so we don't count expired versions.
    from app.db.temporal_constants import NEVER_EXPIRES

    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND c.current_confidence != null "
            "COLLECT AGGREGATE "
            "  count = LENGTH(1), "
            "  last_run = MAX(c.confidence_decayed_at) "
            "RETURN { count, last_run }",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    if rows:
        row = rows[0]
        snapshot["decayed_classes"] = int(row.get("count") or 0)
        last = row.get("last_run")
        if isinstance(last, (int, float)):
            snapshot["last_decay_run_at"] = float(last)
    return snapshot


def inbox_size(
    ontology_id: str,
    *,
    db: Any | None = None,
) -> int:
    """Cheap COUNT-only helper for the navbar Revisions Inbox badge.

    Avoids the full row scan of :func:`list_inbox` -- the navbar
    polls this on every page load and only needs the integer.
    """
    db = _ensure_db(db)
    if not db.has_collection(_COLLECTION):
        return 0
    rows = list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.ontology_id == @oid "
            "  AND r.action == 'FLAG_FOR_CURATION' "
            "  AND r.status == 'pending' "
            "COLLECT WITH COUNT INTO n "
            "RETURN n",
            bind_vars={"oid": ontology_id},
        )
    )
    return int(rows[0]) if rows else 0
