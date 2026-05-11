"""Levi-identity supersede helper for the belief-revision pipeline (Stream 11 IBR.9).

Implements the five-action revision dispatch on top of the existing
edge-interval temporal substrate (:mod:`app.services.temporal`):

* ``REINFORCE`` -- append evidence + bump ``current_confidence`` on
  the existing vertex (in-place; no version bump). Direct field update.
* ``REVISE`` -- expire the existing vertex and create a new version
  with the supplied ``new_vertex_data``, re-creating connected edges
  (Levi expand+contract). Wraps :func:`temporal.update_entity`.
* ``GAP_FILL`` -- insert a new edge (typically ``subclass_of`` or
  ``rdfs_range_class``) between two existing vertices. Plain
  ``db.collection().insert`` with stamped temporal fields.
* ``RETRACT`` -- expire the existing vertex (soft-delete). Wraps
  :func:`temporal.expire_entity`.
* ``FLAG_FOR_CURATION`` -- writes ``revision_meta`` with
  ``status=pending``; no graph change. The curator decides.

In all cases a ``revision_meta`` document is written with the verdict,
action, agent type/version, triggering doc id, before/after refs,
evidence quotes, reasoning and confidences (PRD §6.16, FR-16.6).

Idempotency contract
--------------------

If a revision with the same ``(triggering_doc_id, existing_entity_id,
action)`` already exists in ``revision_meta`` with ``status`` in
``{applied, pending}``, :func:`supersede` returns the prior result
without re-applying. This is what lets the LangGraph node (IBR.10)
safely retry a partially-completed pipeline run -- the supersede pass
is replay-safe.

Set ``skip_idempotency=True`` to force re-application (e.g. when the
caller has already verified the prior state is gone). Logged at WARNING
because legitimate use is rare.

Safety contract
---------------

* No Arango stream transactions are required: the operations are
  forward-only soft-deletes that are individually idempotent. A failure
  partway through leaves the graph in a recoverable state (the next
  retry's idempotency check picks up where the previous one left off).
* Published items are NOT protected here -- IBR.18's safety guards
  enforce the "FLAG_FOR_CURATION-only on approved entities" rule before
  ever calling :func:`supersede`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_GAP_FILL,
    ACTION_REINFORCE,
    ACTION_RETRACT,
    ACTION_REVISE,
    AGENT_LLM,
    AGENT_MECHANICAL,
    STATUS_APPLIED,
    STATUS_PENDING,
    record_revision,
)
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services import temporal

log = logging.getLogger(__name__)

_REVISION_META = "revision_meta"


@dataclass(frozen=True)
class SupersedeResult:
    """Outcome of one :func:`supersede` call.

    Always returned -- never raises on idempotency hit. Always carries
    ``revision_meta_key`` (either the new audit doc or the prior one
    the idempotency check matched).
    """

    revision_meta_key: str
    action: str
    status: str
    new_version_key: str | None = None
    expired_version_key: str | None = None
    new_edge_key: str | None = None
    skipped: bool = False
    skipped_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_meta_key": self.revision_meta_key,
            "action": self.action,
            "status": self.status,
            "new_version_key": self.new_version_key,
            "expired_version_key": self.expired_version_key,
            "new_edge_key": self.new_edge_key,
            "skipped": self.skipped,
            "skipped_reason": self.skipped_reason,
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def _find_existing_revision(
    db: StandardDatabase,
    *,
    triggering_doc_id: str,
    existing_entity_id: str,
    action: str,
) -> dict[str, Any] | None:
    """Return the most-recent applied/pending revision for the triple, if any.

    Used as the idempotency guard: a re-run of the same logical revision
    finds this and returns without doing anything.
    """
    if not db.has_collection(_REVISION_META):
        return None
    rows = list(
        run_aql(
            db,
            f"FOR r IN {_REVISION_META} "
            "FILTER r.triggering_doc_id == @doc_id "
            "  AND r.existing_entity_id == @eid "
            "  AND r.action == @action "
            "  AND r.status IN [@applied, @pending] "
            "SORT r.created DESC "
            "LIMIT 1 "
            "RETURN r",
            bind_vars={
                "doc_id": triggering_doc_id,
                "eid": existing_entity_id,
                "action": action,
                "applied": STATUS_APPLIED,
                "pending": STATUS_PENDING,
            },
        )
    )
    return rows[0] if rows else None


def _split_id(entity_id: str) -> tuple[str, str]:
    """Parse an Arango ``_id`` into ``(collection, key)``.

    Raises :class:`ValueError` on a non-conforming id so callers fail
    fast rather than silently no-oping.
    """
    if not entity_id or "/" not in entity_id:
        raise ValueError(f"invalid entity _id: {entity_id!r}")
    collection, key = entity_id.split("/", 1)
    if not collection or not key:
        raise ValueError(f"invalid entity _id: {entity_id!r}")
    return collection, key


# ---------------------------------------------------------------------------
# Action handlers (one per action; pure-ish wrappers around temporal helpers)
# ---------------------------------------------------------------------------


def _apply_reinforce(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
    evidence_quotes: list[str],
    confidence_after: float | None,
) -> dict[str, Any]:
    """REINFORCE: append evidence + bump current_confidence in place.

    No version bump -- reinforcement is not a structural change. Edits
    only ``evidence`` (appended) and ``current_confidence`` (replaced).
    Returns the updated document.

    The reason we mutate in place rather than supersede: a REINFORCE
    represents the SAME belief gaining additional support from new
    evidence. Creating a new version would imply the belief itself
    changed, polluting the version history with no-op revisions.
    """
    current = temporal.get_current(db, collection=collection, key=key)
    if current is None:
        raise ValueError(f"no current version for {collection}/{key}")
    existing_evidence = list(current.get("evidence") or [])
    existing_evidence.extend(evidence_quotes)
    update: dict[str, Any] = {
        "_key": key,
        "evidence": existing_evidence,
        "evidence_count": len(existing_evidence),
        "last_evidenced_at": time.time(),
    }
    if confidence_after is not None:
        update["current_confidence"] = float(confidence_after)
    return cast(
        "dict[str, Any]",
        db.collection(collection).update(update, return_new=True),
    )["new"]


def _apply_revise(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
    new_vertex_data: dict[str, Any],
    edge_collections: list[str] | None,
    created_by: str,
    change_summary: str,
) -> dict[str, Any]:
    """REVISE: expire the old version and create a new one (Levi expand+contract).

    Wraps :func:`app.services.temporal.update_entity` so all the
    edge re-creation logic is reused. Returns the new vertex doc.
    """
    return temporal.update_entity(
        db,
        collection=collection,
        key=key,
        new_data=new_vertex_data,
        created_by=created_by,
        change_type="belief_revision",
        change_summary=change_summary,
        edge_collections=edge_collections,
    )


def _apply_gap_fill(
    db: StandardDatabase,
    *,
    edge_collection: str,
    new_edge: dict[str, Any],
) -> dict[str, Any]:
    """GAP_FILL: insert a new edge with stamped temporal fields.

    Caller supplies ``new_edge`` with at minimum ``_from``, ``_to``,
    and ``ontology_id``. We set ``created=now``, ``expired=NEVER_EXPIRES``,
    and ``ttlExpireAt=None``.
    """
    if not db.has_collection(edge_collection):
        raise ValueError(f"edge collection not found: {edge_collection}")
    if not new_edge.get("_from") or not new_edge.get("_to"):
        raise ValueError("new_edge requires _from and _to")
    now = time.time()
    payload = {**new_edge}
    payload.setdefault("ontology_id", new_edge.get("ontology_id"))
    payload["created"] = now
    payload["expired"] = NEVER_EXPIRES
    payload["ttlExpireAt"] = None
    return cast(
        "dict[str, Any]",
        db.collection(edge_collection).insert(payload, return_new=True),
    )["new"]


def _apply_retract(
    db: StandardDatabase,
    *,
    collection: str,
    key: str,
) -> dict[str, Any] | None:
    """RETRACT: expire the current version (soft-delete)."""
    return temporal.expire_entity(db, collection=collection, key=key)


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def supersede(
    *,
    ontology_id: str,
    existing_entity_id: str,
    verdict: str,
    action: str,
    agent_type: str,
    agent_version: str,
    triggering_doc_id: str,
    evidence_quotes: list[str] | None = None,
    reasoning: str = "",
    confidence_before: float | None = None,
    confidence_after: float | None = None,
    new_vertex_data: dict[str, Any] | None = None,
    edge_collections: list[str] | None = None,
    new_edge: dict[str, Any] | None = None,
    new_edge_collection: str | None = None,
    created_by: str = "belief_revision_agent",
    change_summary: str = "",
    skip_idempotency: bool = False,
    db: StandardDatabase | None = None,
) -> SupersedeResult:
    """Apply one revision atomically and write the audit record.

    Dispatches on ``action`` to the matching handler, then writes the
    ``revision_meta`` document. Returns a :class:`SupersedeResult`.

    Parameters
    ----------
    ontology_id, existing_entity_id, triggering_doc_id:
        Required identifiers. ``existing_entity_id`` must be a full
        Arango ``_id`` (``collection/key``).
    verdict, action:
        The output of IBR.7 (mechanical) or IBR.8 (LLM agent). Validated
        against the constants in :mod:`app.db.revision_meta_repo`.
    agent_type, agent_version:
        ``mechanical`` (rule engine version) or ``llm`` (model + prompt
        version).
    evidence_quotes, reasoning:
        Persisted to ``revision_meta`` and -- for REINFORCE -- appended
        to the existing vertex's ``evidence`` field.
    confidence_before, confidence_after:
        Persisted to ``revision_meta``. ``confidence_after`` is also
        written to the vertex's ``current_confidence`` for REINFORCE.
    new_vertex_data:
        Required for REVISE; otherwise ignored.
    edge_collections:
        For REVISE: the list of edge collections whose endpoints
        reference the soon-to-be-expired version. Defaults to None
        (no re-creation), but in practice the IBR.10 node passes the
        full set so subclass / domain / range edges follow the new
        version.
    new_edge, new_edge_collection:
        Required for GAP_FILL.
    skip_idempotency:
        Force re-application even if a prior matching revision exists.
        Logged WARN; legitimate use is rare.
    db:
        Optional injected handle (tests use a mock).

    Returns
    -------
    SupersedeResult
        Always returned. ``skipped=True`` indicates idempotency hit.
    """
    db = db or get_db()

    # ---- Idempotency check ------------------------------------------
    if not skip_idempotency:
        prior = _find_existing_revision(
            db,
            triggering_doc_id=triggering_doc_id,
            existing_entity_id=existing_entity_id,
            action=action,
        )
        if prior is not None:
            log.info(
                "supersede idempotency hit",
                extra={
                    "triggering_doc_id": triggering_doc_id,
                    "existing_entity_id": existing_entity_id,
                    "action": action,
                    "prior_revision_key": prior.get("_key"),
                    "prior_status": prior.get("status"),
                },
            )
            return SupersedeResult(
                revision_meta_key=str(prior.get("_key", "")),
                action=action,
                status=str(prior.get("status", "")),
                new_version_key=prior.get("new_version"),
                expired_version_key=prior.get("existing_version"),
                skipped=True,
                skipped_reason=(
                    "prior revision with same "
                    "(triggering_doc_id, entity_id, action) exists"
                ),
            )
    else:
        log.warning(
            "supersede skip_idempotency=True",
            extra={
                "triggering_doc_id": triggering_doc_id,
                "existing_entity_id": existing_entity_id,
                "action": action,
            },
        )

    # ---- Parse the existing entity id (needed for non-edge actions) -
    if action != ACTION_GAP_FILL:
        try:
            existing_collection, existing_key = _split_id(existing_entity_id)
        except ValueError:
            raise
    else:
        existing_collection, existing_key = "", ""

    # ---- Dispatch ----------------------------------------------------
    quotes = list(evidence_quotes or [])
    new_version_key: str | None = None
    expired_version_key: str | None = None
    new_edge_key: str | None = None
    extra: dict[str, Any] = {}

    if action == ACTION_REINFORCE:
        result_doc = _apply_reinforce(
            db,
            collection=existing_collection,
            key=existing_key,
            evidence_quotes=quotes,
            confidence_after=confidence_after,
        )
        new_version_key = result_doc.get("_key")  # same key (in-place update)
        extra = {
            "evidence_count_after": result_doc.get("evidence_count"),
            "current_confidence_after": result_doc.get("current_confidence"),
        }

    elif action == ACTION_REVISE:
        if not new_vertex_data:
            raise ValueError("REVISE requires new_vertex_data")
        new_doc = _apply_revise(
            db,
            collection=existing_collection,
            key=existing_key,
            new_vertex_data=new_vertex_data,
            edge_collections=edge_collections,
            created_by=created_by,
            change_summary=change_summary,
        )
        expired_version_key = existing_key
        new_version_key = new_doc.get("_key")
        extra = {"new_version_id": new_doc.get("_id")}

    elif action == ACTION_GAP_FILL:
        if not new_edge or not new_edge_collection:
            raise ValueError("GAP_FILL requires new_edge and new_edge_collection")
        edge_doc = _apply_gap_fill(
            db, edge_collection=new_edge_collection, new_edge=new_edge
        )
        new_edge_key = edge_doc.get("_key")
        extra = {
            "new_edge_id": edge_doc.get("_id"),
            "from": edge_doc.get("_from"),
            "to": edge_doc.get("_to"),
        }

    elif action == ACTION_RETRACT:
        retracted = _apply_retract(
            db, collection=existing_collection, key=existing_key
        )
        if retracted is None:
            log.warning(
                "supersede RETRACT no-op",
                extra={"existing_entity_id": existing_entity_id},
            )
        expired_version_key = existing_key

    elif action == ACTION_FLAG_FOR_CURATION:
        # No graph change. Audit record is the entire deliverable.
        pass

    else:
        raise ValueError(f"unsupported action {action!r}")

    # ---- Audit record -----------------------------------------------
    revision_doc = record_revision(
        ontology_id=ontology_id,
        verdict=verdict,
        action=action,
        agent_type=agent_type,
        agent_version=agent_version,
        triggering_doc_id=triggering_doc_id,
        existing_entity_id=existing_entity_id,
        existing_version=expired_version_key,
        new_version=new_version_key or new_edge_key,
        evidence_quotes=quotes,
        reasoning=reasoning,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        db=db,
    )
    revision_key = str(revision_doc.get("_key", ""))
    status = str(revision_doc.get("status", ""))

    log.info(
        "supersede applied",
        extra={
            "ontology_id": ontology_id,
            "existing_entity_id": existing_entity_id,
            "action": action,
            "verdict": verdict,
            "agent_type": agent_type,
            "revision_meta_key": revision_key,
        },
    )
    return SupersedeResult(
        revision_meta_key=revision_key,
        action=action,
        status=status,
        new_version_key=new_version_key,
        expired_version_key=expired_version_key,
        new_edge_key=new_edge_key,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Convenience helpers for IBR.10
# ---------------------------------------------------------------------------


def supersede_from_mechanical_revision(
    revision: Any,
    *,
    ontology_id: str,
    triggering_doc_id: str,
    agent_version: str,
    new_vertex_data: dict[str, Any] | None = None,
    new_edge: dict[str, Any] | None = None,
    new_edge_collection: str | None = None,
    edge_collections: list[str] | None = None,
    db: StandardDatabase | None = None,
) -> SupersedeResult:
    """Apply a :class:`~app.services.revision_verdict.MechanicalRevision`.

    Convenience adapter: extracts the touchpoint's existing entity id,
    the verdict, action, rule_id (used as agent_version suffix),
    confidence and reasoning, then forwards to :func:`supersede`.
    """
    return supersede(
        ontology_id=ontology_id,
        existing_entity_id=revision.touchpoint.existing_class_id,
        verdict=revision.verdict,
        action=revision.action,
        agent_type=AGENT_MECHANICAL,
        agent_version=f"{agent_version}+{revision.rule_id}",
        triggering_doc_id=triggering_doc_id,
        reasoning=revision.reasoning,
        confidence_before=None,
        confidence_after=revision.confidence,
        new_vertex_data=new_vertex_data,
        new_edge=new_edge,
        new_edge_collection=new_edge_collection,
        edge_collections=edge_collections,
        db=db,
    )


def supersede_from_llm_proposal(
    proposal: Any,
    *,
    ontology_id: str,
    existing_entity_id: str,
    verdict: str,
    triggering_doc_id: str,
    agent_version: str,
    new_vertex_data: dict[str, Any] | None = None,
    new_edge: dict[str, Any] | None = None,
    new_edge_collection: str | None = None,
    edge_collections: list[str] | None = None,
    db: StandardDatabase | None = None,
) -> SupersedeResult:
    """Apply a :class:`~app.services.revision_agent.LLMRevisionProposal`.

    The LLM proposal does not carry the existing entity id (it is
    assembled from the touchpoint by the caller), so the caller passes
    it in explicitly. The proposal supplies action / evidence /
    reasoning / confidence.
    """
    return supersede(
        ontology_id=ontology_id,
        existing_entity_id=existing_entity_id,
        verdict=verdict,
        action=proposal.action,
        agent_type=AGENT_LLM,
        agent_version=agent_version,
        triggering_doc_id=triggering_doc_id,
        evidence_quotes=list(proposal.evidence_quotes),
        reasoning=proposal.reasoning,
        confidence_after=proposal.confidence,
        new_vertex_data=new_vertex_data,
        new_edge=new_edge,
        new_edge_collection=new_edge_collection,
        edge_collections=edge_collections,
        db=db,
    )
