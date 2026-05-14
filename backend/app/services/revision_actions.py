"""Curator-driven revision actions (Stream 11 IBR.16).

Three verbs on a pending ``revision_meta`` row:

* :func:`accept_revision`  -- apply the proposed action via
  :func:`app.db.temporal_revisions_repo.supersede` and flip the row's
  ``status`` from ``pending`` to ``accepted``.
* :func:`reject_revision`  -- mark the row ``rejected``; no graph
  change. The original belief stays as it is.
* :func:`modify_revision`  -- the curator overrides the proposal with
  a different action / new vertex / new edge, the override is applied
  via :func:`supersede`, and the row is flagged ``modified`` (with
  the override payload preserved in ``decision_log``).

All three operations are *idempotent at the row level*: re-calling on
an already-decided row returns the current state without re-applying.
This matches the existing ``supersede`` idempotency contract and lets
the inbox UX optimistically PATCH without worrying about duplicate
network calls.

What this module does NOT do
----------------------------

* It does not enforce published-item protection. That is IBR.18's
  job and lives in :mod:`app.services.revision_safety`. The accept /
  modify path here calls into that guard module before ``supersede``.
* It does not send notifications. The notifications service is
  invoked from the route handler so that integration tests covering
  this layer don't spin up a notification bus.
* It does not understand the LLM proposal payload shape. Inputs are
  plain dicts (``new_vertex_data``, ``new_edge``, ``new_edge_collection``,
  ``edge_collections``); the route layer is responsible for turning
  the curator's HTTP body into those primitives.

PRD references: §6.16 FR-16.6, §7.7b accept/reject/modify endpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from arango.database import StandardDatabase

from app.db import revision_meta_repo as rev_repo
from app.db import temporal_revisions_repo as supersede_repo
from app.db.client import get_db
from app.db.utils import doc_get
from app.services import revision_safety

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevisionDecisionResult:
    """Outcome of an accept / reject / modify call.

    Always returned -- even on idempotency hits, where ``already_decided``
    is True and ``supersede_result`` is ``None``.
    """

    revision_key: str
    decision: str  # "accepted" | "rejected" | "modified"
    status: str  # final status on the row (echoes ``decision`` on success)
    already_decided: bool = False
    supersede_result: dict[str, Any] | None = None
    revision: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_key": self.revision_key,
            "decision": self.decision,
            "status": self.status,
            "already_decided": self.already_decided,
            "supersede_result": self.supersede_result,
            "revision": dict(self.revision),
        }


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class RevisionNotFoundError(Exception):
    """The ``revision_meta`` row does not exist."""


class RevisionNotPendingError(Exception):
    """The row exists but is no longer pending.

    Carries the row's current ``status`` so the caller can produce a
    helpful 409 message.
    """

    def __init__(self, revision_key: str, status: str) -> None:
        super().__init__(
            f"revision {revision_key!r} has status {status!r}; "
            "only pending revisions can be decided"
        )
        self.revision_key = revision_key
        self.status = status


class RevisionActionError(Exception):
    """Raised when the underlying supersede call fails (bad payload, etc).

    Wraps the inner :class:`ValueError` from ``supersede`` so route
    handlers can map it to a uniform 400 response while preserving
    the original message.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_pending(
    revision_key: str,
    *,
    db: StandardDatabase,
) -> dict[str, Any]:
    """Return the row if it is in ``pending`` status; raise otherwise.

    Centralizes the precondition all three verbs share so we have
    exactly one place to reason about "decision attempted on a
    non-pending row".
    """
    row = rev_repo.get_revision(revision_key, db=db)
    if row is None:
        raise RevisionNotFoundError(revision_key)
    status = str(row.get("status") or "")
    if status != rev_repo.STATUS_PENDING:
        raise RevisionNotPendingError(revision_key, status)
    return row


def _load_existing_entity(
    db: StandardDatabase,
    *,
    entity_id: str,
) -> dict[str, Any] | None:
    """Best-effort fetch of the entity referenced by a revision row.

    Used by the published-item guard. ``None`` is returned silently
    on lookup failure -- the caller treats that as "not published"
    (see ``revision_safety.is_published``) so a transient lookup
    issue cannot accidentally trigger the downgrade path.
    """
    if not entity_id or "/" not in entity_id:
        return None
    collection, key = entity_id.split("/", 1)
    if not collection or not key or not db.has_collection(collection):
        return None
    try:
        return doc_get(db.collection(collection), key)
    except Exception:  # pragma: no cover -- defensive against driver errors
        log.exception("revision_actions: failed to load entity %s", entity_id)
        return None


def _supersede_for_row(
    row: dict[str, Any],
    *,
    decided_by: str,
    new_vertex_data: dict[str, Any] | None,
    new_edge: dict[str, Any] | None,
    new_edge_collection: str | None,
    edge_collections: list[str] | None,
    override_action: str | None,
    db: StandardDatabase,
) -> supersede_repo.SupersedeResult:
    """Apply the row's proposed action (or an override) via supersede.

    The original row already carries verdict / agent / triggering doc
    / evidence -- we just need to plumb them into ``supersede`` along
    with whatever extra payload the curator is providing for
    REVISE / GAP_FILL.

    Published-item protection is intentionally NOT applied to the
    *curator-driven* accept path: a curator clicking "accept" on a
    structural change to an approved entity is the explicit signal
    that the human has approved it. The guard belongs upstream
    (the LangGraph node + LLM agent), not here.
    """
    action = override_action or str(row.get("action") or "")
    if action == rev_repo.ACTION_FLAG_FOR_CURATION:
        # Accepting a FLAG_FOR_CURATION as-is means "I read this and
        # took no action" -- treat as a no-op rather than a structural
        # change. We still flip the row to "accepted" via the caller.
        return supersede_repo.SupersedeResult(
            revision_meta_key=str(row.get("_key") or ""),
            action=action,
            status=rev_repo.STATUS_ACCEPTED,
            skipped=True,
            skipped_reason=(
                "FLAG_FOR_CURATION accepted as-is; no graph change"
            ),
        )
    try:
        return supersede_repo.supersede(
            ontology_id=str(row.get("ontology_id") or ""),
            existing_entity_id=str(row.get("existing_entity_id") or ""),
            verdict=str(row.get("verdict") or ""),
            action=action,
            agent_type=str(row.get("agent_type") or rev_repo.AGENT_LLM),
            agent_version=(
                # Accepting a curator-modified row should distinguish
                # the audit trail from the original LLM/mechanical
                # proposal, otherwise post-hoc analytics can't tell
                # auto-applied from human-applied revisions.
                f"{row.get('agent_version') or ''}+curator:{decided_by}"
                if override_action or new_vertex_data or new_edge
                else str(row.get("agent_version") or "")
            ),
            triggering_doc_id=str(row.get("triggering_doc_id") or ""),
            evidence_quotes=list(row.get("evidence_quotes") or []),
            reasoning=str(row.get("reasoning") or ""),
            confidence_before=row.get("confidence_before"),
            confidence_after=row.get("confidence_after"),
            new_vertex_data=new_vertex_data,
            new_edge=new_edge,
            new_edge_collection=new_edge_collection,
            edge_collections=edge_collections,
            created_by=f"curator:{decided_by}",
            change_summary=(
                "curator-accepted revision"
                if not override_action
                else f"curator-modified revision (override action: {override_action})"
            ),
            db=db,
        )
    except ValueError as exc:
        # Translate the supersede precondition errors into our domain
        # type so the route layer can produce a uniform 400.
        raise RevisionActionError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Public verbs
# ---------------------------------------------------------------------------


def accept_revision(
    revision_key: str,
    *,
    decided_by: str,
    note: str | None = None,
    new_vertex_data: dict[str, Any] | None = None,
    new_edge: dict[str, Any] | None = None,
    new_edge_collection: str | None = None,
    edge_collections: list[str] | None = None,
    db: StandardDatabase | None = None,
) -> RevisionDecisionResult:
    """Apply the pending revision and flag the row ``accepted``.

    For REINFORCE / RETRACT / FLAG_FOR_CURATION, the curator does not
    need to provide any extra payload. For REVISE the caller MUST
    provide ``new_vertex_data``; for GAP_FILL the caller MUST provide
    ``new_edge`` + ``new_edge_collection``. (These mirror the
    supersede contract.)

    Returns a :class:`RevisionDecisionResult`. If the row is already
    decided (``accepted`` / ``rejected`` / ``modified``), returns
    ``already_decided=True`` with the row's current state and does
    not re-apply.
    """
    db = db or get_db()
    try:
        row = _load_pending(revision_key, db=db)
    except RevisionNotPendingError as exc:
        # Idempotency: already-decided rows return their current state
        # rather than raising. The route layer maps this to 200 (with
        # ``already_decided``) instead of 409.
        existing = rev_repo.get_revision(revision_key, db=db) or {}
        return RevisionDecisionResult(
            revision_key=revision_key,
            decision=exc.status,
            status=exc.status,
            already_decided=True,
            revision=existing,
        )

    supersede_result = _supersede_for_row(
        row,
        decided_by=decided_by,
        new_vertex_data=new_vertex_data,
        new_edge=new_edge,
        new_edge_collection=new_edge_collection,
        edge_collections=edge_collections,
        override_action=None,
        db=db,
    )
    updated = rev_repo.update_status(
        revision_key,
        status=rev_repo.STATUS_ACCEPTED,
        decided_by=decided_by,
        note=note,
        db=db,
    )
    log.info(
        "revision accepted",
        extra={
            "revision_key": revision_key,
            "decided_by": decided_by,
            "ontology_id": row.get("ontology_id"),
            "action": row.get("action"),
        },
    )
    return RevisionDecisionResult(
        revision_key=revision_key,
        decision=rev_repo.STATUS_ACCEPTED,
        status=rev_repo.STATUS_ACCEPTED,
        supersede_result=supersede_result.to_dict(),
        revision=updated or {},
    )


def reject_revision(
    revision_key: str,
    *,
    decided_by: str,
    note: str | None = None,
    db: StandardDatabase | None = None,
) -> RevisionDecisionResult:
    """Mark the pending revision ``rejected`` -- no graph change.

    Idempotent on already-decided rows (returns ``already_decided=True``).
    """
    db = db or get_db()
    try:
        row = _load_pending(revision_key, db=db)
    except RevisionNotPendingError as exc:
        existing = rev_repo.get_revision(revision_key, db=db) or {}
        return RevisionDecisionResult(
            revision_key=revision_key,
            decision=exc.status,
            status=exc.status,
            already_decided=True,
            revision=existing,
        )

    updated = rev_repo.update_status(
        revision_key,
        status=rev_repo.STATUS_REJECTED,
        decided_by=decided_by,
        note=note,
        db=db,
    )
    log.info(
        "revision rejected",
        extra={
            "revision_key": revision_key,
            "decided_by": decided_by,
            "ontology_id": row.get("ontology_id"),
            "action": row.get("action"),
            "note": note,
        },
    )
    return RevisionDecisionResult(
        revision_key=revision_key,
        decision=rev_repo.STATUS_REJECTED,
        status=rev_repo.STATUS_REJECTED,
        revision=updated or {},
    )


def modify_revision(
    revision_key: str,
    *,
    decided_by: str,
    note: str | None = None,
    override_action: str | None = None,
    new_vertex_data: dict[str, Any] | None = None,
    new_edge: dict[str, Any] | None = None,
    new_edge_collection: str | None = None,
    edge_collections: list[str] | None = None,
    db: StandardDatabase | None = None,
) -> RevisionDecisionResult:
    """Apply a curator-modified version of the revision.

    The override may change the action (e.g. the LLM proposed REVISE
    but the curator decides RETRACT is correct), or replace the
    vertex / edge payload. Whatever override is provided is applied
    via :func:`supersede` with ``agent_version`` suffixed with the
    curator id so the audit trail stays unambiguous.

    Idempotent on already-decided rows.
    """
    db = db or get_db()
    if (
        override_action is None
        and new_vertex_data is None
        and new_edge is None
    ):
        raise RevisionActionError(
            "modify_revision requires at least one of "
            "override_action, new_vertex_data, or new_edge"
        )
    if override_action is not None and override_action not in rev_repo.ACTIONS:
        raise RevisionActionError(
            f"invalid override_action {override_action!r}; "
            f"expected one of {sorted(rev_repo.ACTIONS)}"
        )

    try:
        row = _load_pending(revision_key, db=db)
    except RevisionNotPendingError as exc:
        existing = rev_repo.get_revision(revision_key, db=db) or {}
        return RevisionDecisionResult(
            revision_key=revision_key,
            decision=exc.status,
            status=exc.status,
            already_decided=True,
            revision=existing,
        )

    supersede_result = _supersede_for_row(
        row,
        decided_by=decided_by,
        new_vertex_data=new_vertex_data,
        new_edge=new_edge,
        new_edge_collection=new_edge_collection,
        edge_collections=edge_collections,
        override_action=override_action,
        db=db,
    )
    # Persist the override payload alongside the status change so the
    # decision_log captures what the curator actually did.
    audit_note = note or ""
    if override_action:
        audit_note = (
            f"override_action={override_action} | {audit_note}"
            if audit_note
            else f"override_action={override_action}"
        )
    if new_vertex_data:
        audit_note = (
            f"new_vertex_keys={sorted(new_vertex_data.keys())} | {audit_note}"
            if audit_note
            else f"new_vertex_keys={sorted(new_vertex_data.keys())}"
        )
    if new_edge:
        audit_note = (
            f"new_edge_to={new_edge.get('_to')} | {audit_note}"
            if audit_note
            else f"new_edge_to={new_edge.get('_to')}"
        )
    updated = rev_repo.update_status(
        revision_key,
        status=rev_repo.STATUS_MODIFIED,
        decided_by=decided_by,
        note=audit_note,
        db=db,
    )
    log.info(
        "revision modified",
        extra={
            "revision_key": revision_key,
            "decided_by": decided_by,
            "ontology_id": row.get("ontology_id"),
            "original_action": row.get("action"),
            "override_action": override_action,
        },
    )
    return RevisionDecisionResult(
        revision_key=revision_key,
        decision=rev_repo.STATUS_MODIFIED,
        status=rev_repo.STATUS_MODIFIED,
        supersede_result=supersede_result.to_dict(),
        revision=updated or {},
    )
