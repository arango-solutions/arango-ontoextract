"""Belief-revision safety guards (Stream 11 IBR.18).

Four orthogonal guards layered on top of :mod:`temporal_revisions_repo`
and :mod:`revision_actions`:

1. **Published-item protection** -- :func:`should_flag_for_curation`
   downgrades any *structural* revision (REVISE / RETRACT / GAP_FILL)
   on an ``status: approved`` vertex to FLAG_FOR_CURATION, regardless
   of agent confidence. Curators must always look at structural
   changes to vetted content.
2. **Circuit breaker** -- :class:`RevisionRateLimiter` is a fixed-
   window in-memory counter that halts the LLM revision agent when
   too many revisions are produced too quickly. Default 50 / minute.
   When tripped, the agent must stop and the breaker logs an
   alertable warning.
3. **Dry-run mode** -- :func:`apply_dry_run` returns a list of
   proposed actions WITHOUT calling supersede. Used by the admin
   consolidation endpoint (IBR.17) so operators can preview impact.
4. **Cursor resumption** -- :class:`ConsolidationCursor` is a tiny
   ``consolidation_jobs`` collection adapter with ``checkpoint`` /
   ``resume`` so that consolidation jobs can be interrupted and
   continued without losing progress.

These guards are intentionally additive: each one is opt-in at the
caller site, and each one is independently testable. The
consolidation job (IBR.17) composes all four; the per-document
LangGraph node (IBR.10, already shipped) only needs guard #1 and
guard #2.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from arango.database import StandardDatabase

from app.config import settings
from app.db import revision_meta_repo as rev_repo
from app.db.client import get_db
from app.db.utils import doc_get, run_aql

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guard #1 -- Published-item protection
# ---------------------------------------------------------------------------


# Actions that materially change the graph (vs REINFORCE which just
# adds evidence). These are the ones that must be downgraded to
# FLAG_FOR_CURATION when the underlying entity has ``status: approved``.
_STRUCTURAL_ACTIONS = frozenset(
    {
        rev_repo.ACTION_REVISE,
        rev_repo.ACTION_RETRACT,
        rev_repo.ACTION_GAP_FILL,
    }
)


def is_published(
    entity: dict[str, Any] | None,
) -> bool:
    """Return True iff ``entity`` represents a curated/approved row.

    The convention is ``status == "approved"`` (set by the promotion
    service, see ``app.services.promotion``). This helper exists so
    we have one place to evolve the rule (e.g. when adding ``"published"``
    or ``"locked"`` states later).

    ``None`` returns ``False`` -- a missing entity cannot be published.
    """
    if not entity:
        return False
    return str(entity.get("status") or "") == "approved"


def should_flag_for_curation(
    *,
    entity: dict[str, Any] | None,
    proposed_action: str,
) -> bool:
    """Return True iff the proposed action must be downgraded to FLAG_FOR_CURATION.

    Structural revisions (REVISE / RETRACT / GAP_FILL) on an approved
    entity always require human review -- the LLM agent's confidence
    score is irrelevant here. REINFORCE on an approved entity is fine
    (it just adds evidence; no structural change).

    GAP_FILL is special: the existing entity is one *side* of the
    proposed edge. We treat the protection as "if the from-side is
    approved, flag." Callers that want both-side protection should
    call this twice with different ``entity`` arguments.
    """
    if proposed_action not in _STRUCTURAL_ACTIONS:
        return False
    return is_published(entity)


def downgrade_action_for_published(
    *,
    entity: dict[str, Any] | None,
    proposed_action: str,
) -> str:
    """Return the action to actually use after applying guard #1.

    Convenience wrapper around :func:`should_flag_for_curation`:
    returns ``ACTION_FLAG_FOR_CURATION`` when downgrade is required,
    otherwise echoes ``proposed_action`` unchanged.
    """
    if should_flag_for_curation(entity=entity, proposed_action=proposed_action):
        log.info(
            "revision downgraded to FLAG_FOR_CURATION (published entity)",
            extra={
                "entity_key": entity.get("_key") if entity else None,
                "entity_status": entity.get("status") if entity else None,
                "proposed_action": proposed_action,
            },
        )
        return rev_repo.ACTION_FLAG_FOR_CURATION
    return proposed_action


# ---------------------------------------------------------------------------
# Guard #2 -- Circuit breaker (rate limiter)
# ---------------------------------------------------------------------------


class RevisionRateLimiter:
    """Fixed-window in-memory rate limiter for the LLM revision agent.

    Thread-safe (uses a single lock per instance). Exposes two
    primitives:

    * :meth:`check_and_increment` -- atomically check the current
      window's count, return False (and log a warning) if the cap
      would be exceeded, otherwise increment and return True.
    * :meth:`current_rate` -- read-only inspector for the dashboard.

    The window is a fixed wall-clock interval (default 60 seconds);
    the count resets at the next boundary. This is intentionally
    simpler than a sliding window because we only need to *halt*
    runaway behavior, not smoothly throttle to a target rate.

    Defaults are pulled from ``settings`` so operators can tune
    without a code change. A limit of 0 disables the breaker.
    """

    def __init__(
        self,
        *,
        max_per_window: int | None = None,
        window_seconds: float | None = None,
    ) -> None:
        self._max = (
            max_per_window
            if max_per_window is not None
            else int(getattr(settings, "belief_revision_circuit_max_per_minute", 50))
        )
        self._window = (
            window_seconds
            if window_seconds is not None
            else float(
                getattr(settings, "belief_revision_circuit_window_seconds", 60.0)
            )
        )
        self._lock = threading.Lock()
        self._window_start: float = time.time()
        self._count: int = 0
        self._tripped_at: float | None = None

    def _maybe_rotate(self, now: float) -> None:
        """Reset the window if we've crossed the boundary.

        Called under the lock by every public method.
        """
        if now - self._window_start >= self._window:
            self._window_start = now
            self._count = 0
            self._tripped_at = None

    def check_and_increment(self) -> bool:
        """Atomically test + increment.

        Returns True if under the cap (and the increment took effect),
        False if the increment would exceed the cap (and the breaker
        is now tripped). A tripped breaker stays tripped for the rest
        of the current window; the next window auto-resets it.
        """
        if self._max <= 0:
            return True  # Disabled
        now = time.time()
        with self._lock:
            self._maybe_rotate(now)
            if self._count >= self._max:
                if self._tripped_at is None:
                    self._tripped_at = now
                    log.warning(
                        "belief-revision circuit breaker tripped",
                        extra={
                            "max_per_window": self._max,
                            "window_seconds": self._window,
                            "count": self._count,
                            "tripped_at": self._tripped_at,
                        },
                    )
                return False
            self._count += 1
            return True

    def current_rate(self) -> dict[str, Any]:
        """Snapshot of the breaker state for the dashboard."""
        now = time.time()
        with self._lock:
            self._maybe_rotate(now)
            return {
                "max_per_window": self._max,
                "window_seconds": self._window,
                "current_count": self._count,
                "window_remaining_seconds": max(
                    0.0, self._window - (now - self._window_start)
                ),
                "tripped": self._tripped_at is not None,
                "tripped_at": self._tripped_at,
            }

    def reset(self) -> None:
        """Force-clear the breaker (admin action; not used by the agent)."""
        with self._lock:
            self._window_start = time.time()
            self._count = 0
            self._tripped_at = None
            log.info("belief-revision circuit breaker manually reset")


# Module-level shared instance -- the LLM revision agent and the
# admin endpoint must see the same counters.
_default_limiter: RevisionRateLimiter | None = None


def get_default_limiter() -> RevisionRateLimiter:
    """Lazily-constructed shared :class:`RevisionRateLimiter`.

    Lazy because reading ``settings`` at module import time would
    couple this module to import order. Callers that want their own
    limiter (tests, separate workers) should instantiate the class
    directly.
    """
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RevisionRateLimiter()
    return _default_limiter


def reset_default_limiter() -> None:
    """Reset the module-level limiter -- test-only."""
    global _default_limiter
    _default_limiter = None


# ---------------------------------------------------------------------------
# Guard #3 -- Dry-run plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedAction:
    """One proposed revision in a dry-run plan.

    Carries enough information to render in the admin UI: the
    affected entity, the original verdict + agent, the original
    action, and (after applying guard #1) the action that would
    actually have been used.
    """

    entity_id: str
    verdict: str
    agent_type: str
    proposed_action: str
    effective_action: str
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "verdict": self.verdict,
            "agent_type": self.agent_type,
            "proposed_action": self.proposed_action,
            "effective_action": self.effective_action,
            "reason": self.reason,
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# Guard #4 -- Cursor resumption
# ---------------------------------------------------------------------------


_CURSOR_COLLECTION = "consolidation_jobs"


@dataclass
class ConsolidationCursor:
    """Persistent cursor for consolidation jobs (IBR.17).

    ``job_key`` is the document ``_key``. The same job_key resumes
    the same job: the cursor's stored ``last_processed_id`` and
    ``stage`` survive process restarts because they are written to
    Arango after every batch.

    Mutability contract
    -------------------

    The cursor document is mutated in place -- there is no temporal
    versioning. A consolidation job is an *event*, not a belief, and
    we want the latest checkpoint, not its history. The ``status``
    transitions (``running`` → ``completed`` / ``failed`` /
    ``cancelled``) are recorded as monotonic state, not as new docs.
    """

    job_key: str
    ontology_id: str
    stage: str = "rules"  # "rules" | "decay" | "stale" | "done"
    last_processed_id: str | None = None
    processed_count: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "running"  # "running" | "completed" | "failed" | "cancelled"
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_doc(self) -> dict[str, Any]:
        return {
            "_key": self.job_key,
            "ontology_id": self.ontology_id,
            "stage": self.stage,
            "last_processed_id": self.last_processed_id,
            "processed_count": self.processed_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "dry_run": self.dry_run,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "ConsolidationCursor":
        return cls(
            job_key=str(doc.get("_key") or ""),
            ontology_id=str(doc.get("ontology_id") or ""),
            stage=str(doc.get("stage") or "rules"),
            last_processed_id=doc.get("last_processed_id"),
            processed_count=int(doc.get("processed_count") or 0),
            started_at=float(doc.get("started_at") or time.time()),
            updated_at=float(doc.get("updated_at") or time.time()),
            status=str(doc.get("status") or "running"),
            dry_run=bool(doc.get("dry_run") or False),
            extra=dict(doc.get("extra") or {}),
        )


def _ensure_cursor_collection(db: StandardDatabase) -> StandardDatabase:
    if not db.has_collection(_CURSOR_COLLECTION):
        db.create_collection(_CURSOR_COLLECTION)
        log.info("created collection %s on demand", _CURSOR_COLLECTION)
    return db


def checkpoint_cursor(
    cursor: ConsolidationCursor,
    *,
    db: StandardDatabase | None = None,
) -> None:
    """Write the cursor's current state to Arango.

    Called after every batch by the consolidation job. The collection
    is created on demand so a freshly-migrated database doesn't fail
    on the first checkpoint.

    Idempotency: uses ``insert_overwrite`` semantics. The document
    ``_key`` is ``cursor.job_key``, so the same job always writes to
    the same row.
    """
    db = db or get_db()
    db = _ensure_cursor_collection(db)
    cursor.updated_at = time.time()
    col = db.collection(_CURSOR_COLLECTION)
    if doc_get(col, cursor.job_key) is None:
        col.insert(cursor.to_doc())
    else:
        col.update(cursor.to_doc())


def load_cursor(
    job_key: str,
    *,
    db: StandardDatabase | None = None,
) -> ConsolidationCursor | None:
    """Resume a checkpointed cursor by ``job_key``.

    Returns ``None`` if the cursor does not exist (i.e. this is a
    fresh job, not a resume).
    """
    db = db or get_db()
    if not db.has_collection(_CURSOR_COLLECTION):
        return None
    doc = doc_get(db.collection(_CURSOR_COLLECTION), job_key)
    if doc is None:
        return None
    return ConsolidationCursor.from_doc(doc)


def list_recent_jobs(
    *,
    ontology_id: str | None = None,
    limit: int = 25,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """List the most-recent consolidation jobs, newest-first.

    Powers the admin dashboard's "recent runs" panel. Filterable by
    ``ontology_id``; if ``None``, returns global recent runs.
    """
    db = db or get_db()
    if not db.has_collection(_CURSOR_COLLECTION):
        return []
    if ontology_id:
        aql = (
            f"FOR j IN {_CURSOR_COLLECTION} "
            "FILTER j.ontology_id == @oid "
            "SORT j.started_at DESC LIMIT @limit RETURN j"
        )
        bind = {"oid": ontology_id, "limit": limit}
    else:
        aql = (
            f"FOR j IN {_CURSOR_COLLECTION} "
            "SORT j.started_at DESC LIMIT @limit RETURN j"
        )
        bind = {"limit": limit}
    return list(run_aql(db, aql, bind_vars=bind))
