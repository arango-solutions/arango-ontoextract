"""MCP tools for the belief-revision pipeline (Stream 11 IBR.20).

Six tools that mirror the REST endpoints from IBR.16 + IBR.17 so
external agents can drive the inbox / consolidation flow without HTTP:

* ``list_revisions_inbox(ontology_id)`` -- pending FLAG_FOR_CURATION rows.
* ``list_recent_revisions(ontology_id, limit, action, status)`` -- audit trail.
* ``get_revision(revision_key)`` -- one row by ``_key``.
* ``decide_revision(revision_key, decision, decided_by, ...)`` -- accept /
  reject / modify in one tool.
* ``run_consolidation(ontology_id, dry_run, ...)`` -- trigger an
  ontology-wide consolidation pass.
* ``get_circuit_breaker_state()`` -- snapshot the LLM-revision-agent
  rate-limiter state.

Each tool wraps the same service-layer functions used by the REST
routes, so behavior (idempotency, dry-run, safety guards, error
codes) is identical regardless of transport.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_belief_revision_tools(mcp: FastMCP) -> None:
    """Register every belief-revision tool on the given MCP server."""

    @mcp.tool()
    def list_revisions_inbox(
        ontology_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List pending FLAG_FOR_CURATION revisions for an ontology.

        Backs the workspace Revisions Inbox UI; safe to poll. Returns
        the same shape as ``GET /api/v1/revisions/inbox``.

        Args:
            ontology_id: The ontology identifier.
            limit: Maximum number of rows (1-500). Defaults to 100.
        """
        try:
            from app.db import revision_meta_repo as rev_repo
            from app.db.client import get_db

            db = get_db()
            rows = rev_repo.list_inbox(ontology_id, limit=limit, db=db)
            return {
                "data": rows,
                "ontology_id": ontology_id,
                "count": len(rows),
            }
        except Exception as exc:
            log.exception("list_revisions_inbox failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def list_recent_revisions(
        ontology_id: str,
        limit: int = 100,
        action: str | None = None,
        status: str | None = None,
        since: float | None = None,
    ) -> dict[str, Any]:
        """List revisions for an ontology with optional filters, newest-first.

        Mirrors ``GET /api/v1/revisions``. Use this for ad-hoc audit
        queries -- e.g. "all REINFORCED revisions in the last 24h".

        Args:
            ontology_id: The ontology identifier.
            limit: Maximum number of rows (1-500).
            action: Optional action filter (REINFORCE / REVISE / ...).
            status: Optional status filter (applied / pending / accepted / ...).
            since: Optional Unix-timestamp lower bound on ``created``.
        """
        try:
            from app.db import revision_meta_repo as rev_repo
            from app.db.client import get_db

            db = get_db()
            if action is not None and action not in rev_repo.ACTIONS:
                return {
                    "error": f"invalid action: {action!r}",
                    "valid_actions": sorted(rev_repo.ACTIONS),
                }
            if status is not None and status not in rev_repo.STATUSES:
                return {
                    "error": f"invalid status: {status!r}",
                    "valid_statuses": sorted(rev_repo.STATUSES),
                }
            rows = rev_repo.list_revisions(
                ontology_id,
                action=action,
                status=status,
                since=since,
                limit=limit,
                db=db,
            )
            return {
                "data": rows,
                "ontology_id": ontology_id,
                "count": len(rows),
            }
        except Exception as exc:
            log.exception("list_recent_revisions failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def get_revision(revision_key: str) -> dict[str, Any]:
        """Fetch one ``revision_meta`` row by ``_key``.

        Args:
            revision_key: The revision document's ``_key``.
        """
        try:
            from app.db import revision_meta_repo as rev_repo
            from app.db.client import get_db

            row = rev_repo.get_revision(revision_key, db=get_db())
            if row is None:
                return {"error": "not_found", "revision_key": revision_key}
            return row
        except Exception as exc:
            log.exception("get_revision failed")
            return {"error": str(exc), "revision_key": revision_key}

    @mcp.tool()
    def decide_revision(
        revision_key: str,
        decision: str,
        decided_by: str,
        note: str | None = None,
        override_action: str | None = None,
        new_vertex_data: dict[str, Any] | None = None,
        new_edge: dict[str, Any] | None = None,
        new_edge_collection: str | None = None,
        edge_collections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Accept / reject / modify a pending revision.

        Single tool that dispatches on ``decision`` -- mirrors the three
        ``POST /api/v1/revisions/{key}/{accept|reject|modify}`` routes.
        Idempotent: re-calling on an already-decided row returns
        ``already_decided=True``.

        Args:
            revision_key: The revision document's ``_key``.
            decision: One of "accept", "reject", "modify".
            decided_by: Curator or service identifier (required for audit).
            note: Optional free-form note appended to ``decision_log``.
            override_action: For "modify" only -- override the proposed
                action (e.g. RETRACT instead of REVISE).
            new_vertex_data: For accept/modify of REVISE -- the new
                vertex payload.
            new_edge: For accept/modify of GAP_FILL -- the new edge
                payload (must include ``_from`` / ``_to``).
            new_edge_collection: For accept/modify of GAP_FILL -- the
                edge collection name.
            edge_collections: For REVISE -- list of edge collections
                whose endpoints reference the soon-to-be-expired
                version (so they're recreated against the new one).
        """
        try:
            from app.services import revision_actions

            decision = decision.lower()
            if decision == "accept":
                result = revision_actions.accept_revision(
                    revision_key,
                    decided_by=decided_by,
                    note=note,
                    new_vertex_data=new_vertex_data,
                    new_edge=new_edge,
                    new_edge_collection=new_edge_collection,
                    edge_collections=edge_collections,
                )
            elif decision == "reject":
                result = revision_actions.reject_revision(
                    revision_key,
                    decided_by=decided_by,
                    note=note,
                )
            elif decision == "modify":
                result = revision_actions.modify_revision(
                    revision_key,
                    decided_by=decided_by,
                    note=note,
                    override_action=override_action,
                    new_vertex_data=new_vertex_data,
                    new_edge=new_edge,
                    new_edge_collection=new_edge_collection,
                    edge_collections=edge_collections,
                )
            else:
                return {
                    "error": "invalid decision",
                    "valid": ["accept", "reject", "modify"],
                }
            return result.to_dict()
        except Exception as exc:
            from app.services.revision_actions import (
                RevisionActionError,
                RevisionNotFoundError,
            )

            if isinstance(exc, RevisionNotFoundError):
                return {"error": "not_found", "revision_key": revision_key}
            if isinstance(exc, RevisionActionError):
                return {
                    "error": "validation_error",
                    "message": str(exc),
                    "revision_key": revision_key,
                }
            log.exception("decide_revision failed")
            return {"error": str(exc), "revision_key": revision_key}

    @mcp.tool()
    def run_consolidation(
        ontology_id: str,
        dry_run: bool = True,
        job_key: str | None = None,
        stale_after_days: float | None = None,
        stale_inbox_limit: int = 200,
    ) -> dict[str, Any]:
        """Trigger an ontology-wide consolidation pass.

        Default is ``dry_run=True`` so the agent gets a preview by
        default and must opt in to mutations. Mirrors
        ``POST /api/v1/admin/ontology/{id}/consolidate``.

        Args:
            ontology_id: The ontology identifier.
            dry_run: When True (default), no revision_meta rows are
                written and decay is computed without applying.
            job_key: Optional explicit job key for cursor resumption.
            stale_after_days: Stale-belief threshold (defaults to
                configured decay half-life).
            stale_inbox_limit: Cap on stale-belief inbox rows per pass.
        """
        try:
            from app.services.consolidation import run_consolidation as _run

            report = _run(
                ontology_id,
                dry_run=dry_run,
                job_key=job_key,
                stale_after_days=stale_after_days,
                stale_inbox_limit=stale_inbox_limit,
            )
            return report.to_dict()
        except Exception as exc:
            log.exception("run_consolidation MCP tool failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def get_circuit_breaker_state() -> dict[str, Any]:
        """Snapshot the LLM-revision-agent circuit-breaker state.

        Returns the current window count, window remaining time, and
        whether the breaker is currently tripped. Safe to poll.
        """
        try:
            from app.services.revision_safety import get_default_limiter

            return get_default_limiter().current_rate()
        except Exception as exc:
            log.exception("get_circuit_breaker_state failed")
            return {"error": str(exc)}
