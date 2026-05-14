"""Revisions API -- inbox + accept / reject / modify (Stream 11 IBR.16).

This is the curator-facing surface for the belief-revision pipeline.
The Phase 2 LangGraph node writes ``revision_meta`` rows with
``status=pending`` for FLAG_FOR_CURATION verdicts; this router lets a
curator (or the Revisions Inbox UI) act on them.

Endpoints
---------

* ``GET  /api/v1/revisions/inbox?ontology_id=...&limit=...``
    List pending FLAG_FOR_CURATION rows for one ontology, newest-first.
    Powers the workspace inbox overlay.
* ``GET  /api/v1/revisions?ontology_id=...&action=...&status=...&limit=...``
    Generic revision list, filterable, newest-first.
* ``GET  /api/v1/revisions/{key}``
    Fetch a single revision by ``_key``.
* ``GET  /api/v1/revisions/entity/{entity_id}``
    All revisions touching one entity ``_id`` (path-segment-encoded).
* ``POST /api/v1/revisions/{key}/accept``
    Apply the proposed action and flip status to ``accepted``.
* ``POST /api/v1/revisions/{key}/reject``
    Mark the revision ``rejected``; no graph change.
* ``POST /api/v1/revisions/{key}/modify``
    Apply an override (different action, modified vertex/edge payload)
    and flag the row ``modified``.

All POST handlers are *idempotent*: re-calling on a row that has
already been decided returns the existing decision rather than
applying a second time.

Error envelope follows :mod:`app.api.errors`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from app.api.errors import NotFoundError, ValidationError
from app.db import revision_meta_repo as rev_repo
from app.db.client import get_db
from app.services import revision_actions

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/revisions", tags=["revisions"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AcceptRevisionRequest(BaseModel):
    """Body for ``POST /revisions/{key}/accept``.

    ``decided_by`` is required so the audit trail captures the human
    or service that approved the change. ``note`` is free-form and
    appended to ``decision_log``. The ``new_*`` fields plumb through
    to :func:`supersede` for REVISE / GAP_FILL revisions; REINFORCE
    and RETRACT do not need them.
    """

    decided_by: str = Field(..., min_length=1, max_length=200)
    note: str | None = None
    new_vertex_data: dict[str, Any] | None = None
    new_edge: dict[str, Any] | None = None
    new_edge_collection: str | None = None
    edge_collections: list[str] | None = None


class RejectRevisionRequest(BaseModel):
    """Body for ``POST /revisions/{key}/reject``."""

    decided_by: str = Field(..., min_length=1, max_length=200)
    note: str | None = None


class ModifyRevisionRequest(BaseModel):
    """Body for ``POST /revisions/{key}/modify``.

    At least one of ``override_action`` / ``new_vertex_data`` /
    ``new_edge`` must be present -- otherwise the request is a no-op
    and the service raises ``ValidationError``.
    """

    decided_by: str = Field(..., min_length=1, max_length=200)
    note: str | None = None
    override_action: str | None = None
    new_vertex_data: dict[str, Any] | None = None
    new_edge: dict[str, Any] | None = None
    new_edge_collection: str | None = None
    edge_collections: list[str] | None = None


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


@router.get("/inbox")
async def get_inbox(
    ontology_id: str = Query(..., description="Ontology to fetch the inbox for"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Pending FLAG_FOR_CURATION revisions for one ontology, newest-first."""
    db = get_db()
    rows = rev_repo.list_inbox(ontology_id, limit=limit, db=db)
    return {"data": rows, "ontology_id": ontology_id, "count": len(rows)}


@router.get("")
async def list_revisions(
    ontology_id: str = Query(..., description="Ontology to fetch revisions for"),
    action: str | None = Query(None, description="Filter by action"),
    status: str | None = Query(None, description="Filter by status"),
    since: float | None = Query(None, description="Lower bound on created (Unix ts)"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Generic, filterable revision list. Newest-first."""
    if action is not None and action not in rev_repo.ACTIONS:
        raise ValidationError(
            f"invalid action {action!r}; expected one of {sorted(rev_repo.ACTIONS)}",
            details={"action": action},
        )
    if status is not None and status not in rev_repo.STATUSES:
        raise ValidationError(
            f"invalid status {status!r}; expected one of {sorted(rev_repo.STATUSES)}",
            details={"status": status},
        )
    db = get_db()
    rows = rev_repo.list_revisions(
        ontology_id,
        action=action,
        status=status,
        since=since,
        limit=limit,
        db=db,
    )
    return {"data": rows, "ontology_id": ontology_id, "count": len(rows)}


@router.get("/entity/{entity_id:path}")
async def list_revisions_for_entity(
    entity_id: str = Path(..., description="Full Arango _id (collection/key)"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Every revision touching one entity ``_id``.

    The ``:path`` converter is required because ``_id`` contains a
    forward slash (``ontology_classes/abc123``) that FastAPI would
    otherwise treat as the next path segment.
    """
    if "/" not in entity_id:
        raise ValidationError(
            f"entity_id must be a full Arango _id (got {entity_id!r})",
            details={"entity_id": entity_id},
        )
    db = get_db()
    rows = rev_repo.list_revisions_for_entity(entity_id, limit=limit, db=db)
    return {"data": rows, "entity_id": entity_id, "count": len(rows)}


@router.get("/{revision_key}")
async def get_revision(revision_key: str) -> dict[str, Any]:
    """Fetch one ``revision_meta`` row by ``_key``."""
    db = get_db()
    row = rev_repo.get_revision(revision_key, db=db)
    if row is None:
        raise NotFoundError(
            f"Revision '{revision_key}' not found",
            details={"revision_key": revision_key},
        )
    return row


# ---------------------------------------------------------------------------
# POST endpoints
# ---------------------------------------------------------------------------


def _handle_decision_errors(err: Exception, *, revision_key: str) -> None:
    """Translate service-layer errors into route-layer HTTP errors.

    Centralized so all three POST handlers map errors uniformly.
    """
    if isinstance(err, revision_actions.RevisionNotFoundError):
        raise NotFoundError(
            f"Revision '{revision_key}' not found",
            details={"revision_key": revision_key},
        ) from err
    if isinstance(err, revision_actions.RevisionActionError):
        raise ValidationError(str(err), details={"revision_key": revision_key}) from err


@router.post("/{revision_key}/accept")
async def accept_revision(
    body: AcceptRevisionRequest,
    revision_key: str,
) -> dict[str, Any]:
    """Apply the pending revision and flip status to ``accepted``.

    Returns 200 with ``already_decided=true`` if the row has already
    been decided -- callers can treat this as success without special-
    casing the rare "double-click in the inbox" path.
    """
    try:
        result = revision_actions.accept_revision(
            revision_key,
            decided_by=body.decided_by,
            note=body.note,
            new_vertex_data=body.new_vertex_data,
            new_edge=body.new_edge,
            new_edge_collection=body.new_edge_collection,
            edge_collections=body.edge_collections,
        )
    except (
        revision_actions.RevisionNotFoundError,
        revision_actions.RevisionActionError,
    ) as exc:
        _handle_decision_errors(exc, revision_key=revision_key)
        raise  # unreachable; appeases mypy
    return result.to_dict()


@router.post("/{revision_key}/reject")
async def reject_revision(
    body: RejectRevisionRequest,
    revision_key: str,
) -> dict[str, Any]:
    """Mark the pending revision ``rejected``; no graph change."""
    try:
        result = revision_actions.reject_revision(
            revision_key,
            decided_by=body.decided_by,
            note=body.note,
        )
    except revision_actions.RevisionNotFoundError as exc:
        _handle_decision_errors(exc, revision_key=revision_key)
        raise
    return result.to_dict()


@router.post("/{revision_key}/modify")
async def modify_revision(
    body: ModifyRevisionRequest,
    revision_key: str,
) -> dict[str, Any]:
    """Apply a curator-modified version of the pending revision.

    The override may change the action and/or replace the vertex /
    edge payload. The audit trail records both the original proposal
    and the curator's modifications.
    """
    try:
        result = revision_actions.modify_revision(
            revision_key,
            decided_by=body.decided_by,
            note=body.note,
            override_action=body.override_action,
            new_vertex_data=body.new_vertex_data,
            new_edge=body.new_edge,
            new_edge_collection=body.new_edge_collection,
            edge_collections=body.edge_collections,
        )
    except (
        revision_actions.RevisionNotFoundError,
        revision_actions.RevisionActionError,
    ) as exc:
        _handle_decision_errors(exc, revision_key=revision_key)
        raise
    return result.to_dict()
