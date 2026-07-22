"""MCP tools for multi-source ontology alignment (Stream 20 / AL-PR6, PRD §6.17).

Exposes the P1 alignment flow to agents — the same primitives as the REST API
(:mod:`app.api.alignment`), wrapped as MCP tools with error envelopes:

  - align_ontologies       : create a session over N>=2 sources + generate candidates
  - adjudicate_alignment   : selective-LLM adjudication (auto-accept high, LLM the rest)
  - list_correspondences   : list a session's candidate correspondences
  - accept_correspondence  : confirm a candidate (bounded human confirmation)
  - reject_correspondence  : reject a candidate
  - materialize_master     : write the reconciled master from accepted pairs

Full P1 loop: align_ontologies -> (adjudicate_alignment | list_correspondences +
accept/reject_correspondence) -> materialize_master (FR-17.12, FR-17.13).
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_alignment_tools(mcp: FastMCP) -> None:
    """Register all alignment tools on the given MCP server instance."""

    @mcp.tool()
    def align_ontologies(
        source_ontology_ids: list[str],
        min_score: float = 0.5,
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Create an alignment session over >=2 ontologies and generate candidates.

        Embedding-retrieval + multi-signal scoring produce candidate correspondences
        (no LLM yet). Returns the session doc with ``candidate_count``.

        Args:
            source_ontology_ids: >=2 distinct source ontology ids to align.
            min_score: Minimum combined score for a candidate to be kept.
            weights: Optional per-signal weight overrides (label/description/embedding).
        """
        try:
            from app.services.alignment import create_alignment_session

            return create_alignment_session(
                source_ontology_ids=source_ontology_ids,
                min_score=min_score,
                weights=weights,
            )
        except ValueError as exc:
            return {"error": "validation_error", "message": str(exc)}
        except Exception as exc:
            log.exception("align_ontologies failed")
            return {"error": str(exc), "source_ontology_ids": source_ontology_ids}

    @mcp.tool()
    async def adjudicate_alignment(
        session_id: str,
        auto_accept_band: float | None = None,
    ) -> dict[str, Any]:
        """Adjudicate a session's candidates: auto-accept high-confidence, LLM the rest.

        Correspondences at/above the auto-accept band are accepted by score alone;
        the borderline middle gets a selective LLM equivalence/subsumption verdict.
        The curation ``status`` is left for a human to confirm. Returns counts.

        Args:
            session_id: The alignment session key.
            auto_accept_band: Override the configured auto-accept confidence band.
        """
        try:
            from app.services.alignment import adjudicate_session

            return await adjudicate_session(
                session_id=session_id, auto_accept_band=auto_accept_band
            )
        except Exception as exc:
            log.exception("adjudicate_alignment failed")
            return {"error": str(exc), "session_id": session_id}

    @mcp.tool()
    def list_correspondences(
        session_id: str,
        status: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List a session's candidate correspondences, optionally filtered.

        Args:
            session_id: The alignment session key.
            status: Filter to 'candidate' | 'accepted' | 'rejected' (None = all).
            min_confidence: Only correspondences at/above this confidence.
            limit: Max rows to return.
            offset: Pagination offset.
        """
        try:
            from app.services.alignment import list_session_candidates

            if status is not None and status not in ("candidate", "accepted", "rejected"):
                return {
                    "error": "validation_error",
                    "message": f"invalid status: {status}",
                    "valid_statuses": ["candidate", "accepted", "rejected"],
                }
            rows = list_session_candidates(
                None,
                session_id,
                status=status,
                min_confidence=min_confidence,
                limit=limit,
                offset=offset,
            )
            return {"session_id": session_id, "correspondences": rows, "count": len(rows)}
        except Exception as exc:
            log.exception("list_correspondences failed")
            return {"error": str(exc), "session_id": session_id}

    @mcp.tool()
    def accept_correspondence(correspondence_key: str) -> dict[str, Any]:
        """Accept (confirm) a candidate correspondence.

        Args:
            correspondence_key: The correspondence _key to accept.
        """
        return _set_status(correspondence_key, "accepted")

    @mcp.tool()
    def reject_correspondence(correspondence_key: str) -> dict[str, Any]:
        """Reject a candidate correspondence.

        Args:
            correspondence_key: The correspondence _key to reject.
        """
        return _set_status(correspondence_key, "rejected")

    @mcp.tool()
    def materialize_master(session_id: str, name: str | None = None) -> dict[str, Any]:
        """Materialize a reconciled master ontology from the session's accepted pairs.

        Transitively clusters accepted correspondences into master classes with
        provenance + owl:equivalentClass edges. Returns the master summary.

        Args:
            session_id: The alignment session key.
            name: Optional name for the master ontology.
        """
        try:
            from app.services.alignment import materialize_master as _materialize

            return _materialize(session_id=session_id, name=name)
        except ValueError as exc:
            return {"error": "not_found", "message": str(exc), "session_id": session_id}
        except Exception as exc:
            log.exception("materialize_master failed")
            return {"error": str(exc), "session_id": session_id}


def _set_status(correspondence_key: str, status: str) -> dict[str, Any]:
    """Shared accept/reject helper -> updated doc or a not_found envelope."""
    try:
        from app.services.alignment import set_candidate_status

        updated = set_candidate_status(None, correspondence_key, status)
        if updated is None:
            return {"error": "not_found", "correspondence_key": correspondence_key}
        return updated
    except Exception as exc:
        log.exception("set correspondence status failed")
        return {"error": str(exc), "correspondence_key": correspondence_key}
