r"""Repository for ``revision_meta`` -- the belief revision audit log
(PRD §6.16, FR-16.6, Stream 11 IBR.1).

Document schema
---------------

Every revision (Phase 2 mechanical or Phase 3 LLM) produces one
``revision_meta`` document with these fields:

| Field                | Type             | Notes                                  |
|----------------------|------------------|----------------------------------------|
| ``ontology_id``      | str              | Owning ontology                        |
| ``verdict``          | str              | One of REINFORCED / REFINED /           |
|                      |                  | GAP-FILLING / REDUNDANT /               |
|                      |                  | CONTRADICTED / UNCERTAIN                |
| ``action``           | str              | One of REINFORCE / REVISE / RETRACT /   |
|                      |                  | FLAG_FOR_CURATION / GAP_FILL            |
| ``status``           | str              | ``applied`` (Phase 2 auto-applied),     |
|                      |                  | ``pending`` (FLAG_FOR_CURATION),        |
|                      |                  | ``accepted`` / ``rejected`` /           |
|                      |                  | ``modified`` (curator decision)         |
| ``agent_type``       | str              | ``mechanical`` (Phase 2 rule) or        |
|                      |                  | ``llm`` (Phase 3 agent)                 |
| ``agent_version``    | str              | Rule engine version / LLM model+prompt  |
| ``triggering_doc_id``| str              | The document that triggered this        |
| ``existing_entity_id``| str             | Pre-revision belief ``_id``             |
| ``existing_version`` | str \| None      | Pre-revision version ``_key``           |
| ``new_version``      | str \| None      | Post-revision version ``_key``          |
|                      |                  | (None for REINFORCED / RETRACT)         |
| ``evidence_quotes``  | list[str]        | Verbatim quotes from supporting chunks  |
| ``reasoning``        | str              | LLM justification or rule name          |
| ``confidence_before``| float            | Pre-revision confidence                 |
| ``confidence_after`` | float            | Post-revision confidence                |
| ``created``          | float            | Unix timestamp                          |

Mutability
----------

Documents are *immutable* except ``status`` (and any ``modified`` audit
trail attached to it via :func:`update_status`). Updating ``status`` is
an in-place edit -- no new version of the revision is created -- because
the revision itself is an event record, not a belief.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import doc_get, run_aql

log = logging.getLogger(__name__)

_COLLECTION = "revision_meta"

# Verdicts the Phase 2 mechanical classifier can emit.
VERDICT_REINFORCED = "REINFORCED"
VERDICT_REFINED = "REFINED"
VERDICT_GAP_FILLING = "GAP-FILLING"
VERDICT_REDUNDANT = "REDUNDANT"
VERDICT_CONTRADICTED = "CONTRADICTED"
VERDICT_UNCERTAIN = "UNCERTAIN"

VERDICTS = frozenset(
    {
        VERDICT_REINFORCED,
        VERDICT_REFINED,
        VERDICT_GAP_FILLING,
        VERDICT_REDUNDANT,
        VERDICT_CONTRADICTED,
        VERDICT_UNCERTAIN,
    }
)

# Actions that may be recorded.
ACTION_REINFORCE = "REINFORCE"
ACTION_REVISE = "REVISE"
ACTION_RETRACT = "RETRACT"
ACTION_FLAG_FOR_CURATION = "FLAG_FOR_CURATION"
ACTION_GAP_FILL = "GAP_FILL"

ACTIONS = frozenset(
    {
        ACTION_REINFORCE,
        ACTION_REVISE,
        ACTION_RETRACT,
        ACTION_FLAG_FOR_CURATION,
        ACTION_GAP_FILL,
    }
)

# Status lifecycle.
STATUS_APPLIED = "applied"
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_MODIFIED = "modified"

STATUSES = frozenset(
    {STATUS_APPLIED, STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_MODIFIED}
)

AGENT_MECHANICAL = "mechanical"
AGENT_LLM = "llm"


def _ensure_collection(db: StandardDatabase | None = None) -> StandardDatabase:
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s on demand", _COLLECTION)
    return db


def record_revision(
    *,
    ontology_id: str,
    verdict: str,
    action: str,
    agent_type: str,
    agent_version: str,
    triggering_doc_id: str,
    existing_entity_id: str,
    existing_version: str | None = None,
    new_version: str | None = None,
    evidence_quotes: list[str] | None = None,
    reasoning: str = "",
    confidence_before: float | None = None,
    confidence_after: float | None = None,
    status: str | None = None,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Insert one ``revision_meta`` document and return the persisted form.

    ``status`` defaults to ``"pending"`` for ``FLAG_FOR_CURATION`` actions
    and to ``"applied"`` for everything else, matching the four-phase
    pipeline contract (auto-apply unless flagged).

    Validation is intentionally minimal: ``verdict`` / ``action`` /
    ``status`` / ``agent_type`` are checked against the module-level
    constants. Field types are not coerced -- callers are expected to
    supply the documented types. Wrong values raise ``ValueError`` so
    bugs surface at the call site rather than at read time.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}; expected one of {sorted(VERDICTS)}")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {sorted(ACTIONS)}")
    if agent_type not in (AGENT_MECHANICAL, AGENT_LLM):
        raise ValueError(
            f"unknown agent_type {agent_type!r}; expected one of "
            f"{[AGENT_MECHANICAL, AGENT_LLM]}"
        )
    if status is None:
        status = STATUS_PENDING if action == ACTION_FLAG_FOR_CURATION else STATUS_APPLIED
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {sorted(STATUSES)}")

    db = _ensure_collection(db)
    doc: dict[str, Any] = {
        "ontology_id": ontology_id,
        "verdict": verdict,
        "action": action,
        "status": status,
        "agent_type": agent_type,
        "agent_version": agent_version,
        "triggering_doc_id": triggering_doc_id,
        "existing_entity_id": existing_entity_id,
        "existing_version": existing_version,
        "new_version": new_version,
        "evidence_quotes": list(evidence_quotes or []),
        "reasoning": reasoning,
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
        "created": time.time(),
    }
    result = cast(
        "dict[str, Any]",
        db.collection(_COLLECTION).insert(doc, return_new=True),
    )
    return result["new"]


def get_revision(
    revision_key: str,
    *,
    db: StandardDatabase | None = None,
) -> dict[str, Any] | None:
    """Fetch one ``revision_meta`` document by its ``_key``."""
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return None
    return doc_get(db.collection(_COLLECTION), revision_key)


def list_revisions(
    ontology_id: str,
    *,
    action: str | None = None,
    status: str | None = None,
    since: float | None = None,
    limit: int = 100,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """List revisions for an ontology, newest-first.

    Optional filters mirror the public REST contract
    (``GET /ontology/{id}/revisions``):

    - ``action``  -- one of the ``ACTION_*`` constants
    - ``status``  -- one of the ``STATUS_*`` constants
    - ``since``   -- Unix timestamp lower bound on ``created``

    Returns at most ``limit`` rows.
    """
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return []

    filters = ["r.ontology_id == @oid"]
    bind: dict[str, Any] = {"oid": ontology_id, "limit": limit}
    if action is not None:
        filters.append("r.action == @action")
        bind["action"] = action
    if status is not None:
        filters.append("r.status == @status")
        bind["status"] = status
    if since is not None:
        filters.append("r.created >= @since")
        bind["since"] = since

    aql = (
        f"FOR r IN {_COLLECTION} "
        f"FILTER {' AND '.join(filters)} "
        "SORT r.created DESC "
        "LIMIT @limit "
        "RETURN r"
    )
    return list(run_aql(db, aql, bind_vars=bind))


def list_inbox(
    ontology_id: str,
    *,
    limit: int = 100,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """List pending FLAG_FOR_CURATION revisions for the Revisions Inbox.

    Convenience wrapper around :func:`list_revisions` with the inbox-
    specific filter combination locked in.
    """
    return list_revisions(
        ontology_id,
        action=ACTION_FLAG_FOR_CURATION,
        status=STATUS_PENDING,
        limit=limit,
        db=db,
    )


def list_revisions_for_entity(
    entity_id: str,
    *,
    limit: int = 100,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """List every revision touching a specific class or edge ``_id``.

    Powers the per-class / per-edge revision history endpoints
    (``GET /ontology/class/{key}/revisions`` and the edge equivalent).
    """
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return []
    return list(
        run_aql(
            db,
            f"FOR r IN {_COLLECTION} "
            "FILTER r.existing_entity_id == @eid "
            "SORT r.created DESC "
            "LIMIT @limit "
            "RETURN r",
            bind_vars={"eid": entity_id, "limit": limit},
        )
    )


def update_status(
    revision_key: str,
    *,
    status: str,
    decided_by: str | None = None,
    note: str | None = None,
    db: StandardDatabase | None = None,
) -> dict[str, Any] | None:
    """Update ``status`` on a revision -- the only mutable field.

    ``decided_by`` and ``note`` (when provided) are appended to the
    document's ``decision_log`` list, preserving every status transition
    for audit. Returns the updated document, or ``None`` when the
    revision does not exist.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {sorted(STATUSES)}")
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return None
    col = db.collection(_COLLECTION)
    current = doc_get(col, revision_key)
    if current is None:
        return None

    decision_log = list(current.get("decision_log") or [])
    decision_log.append(
        {
            "from_status": current.get("status"),
            "to_status": status,
            "decided_by": decided_by,
            "note": note,
            "decided_at": time.time(),
        }
    )
    update = {
        "_key": revision_key,
        "status": status,
        "decision_log": decision_log,
    }
    result = cast("dict[str, Any]", col.update(update, return_new=True))
    return result.get("new")
