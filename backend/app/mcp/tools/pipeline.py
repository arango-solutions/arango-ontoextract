"""MCP tools for extraction pipeline operations — trigger extraction,
check status, and retrieve merge candidates.

Three tools:
  - trigger_extraction: starts an extraction run
  - get_extraction_status: returns run status and progress
  - get_merge_candidates: returns ER merge candidates above a score threshold
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_pipeline_tools(mcp: FastMCP) -> None:
    """Register all pipeline tools on the given MCP server instance."""

    @mcp.tool()
    def trigger_extraction(
        document_id: str,
        ontology_id: str | None = None,
    ) -> dict[str, Any]:
        """Start an extraction run on a document. Returns the run_id and initial status.

        If ontology_id is provided, uses Tier 2 extraction with domain context
        (the domain ontology is injected into the LLM prompt for context-aware
        extraction).

        Args:
            document_id: The document to extract from (doc_id or _key).
            ontology_id: Optional domain ontology ID for Tier 2 context-aware extraction.
        """
        try:
            from app.services.extraction import start_run

            config_overrides = None
            if ontology_id:
                config_overrides = {
                    "domain_ontology_id": ontology_id,
                    "tier": "local",
                    "prompt_version": "tier2_domain_context",
                }

            loop = _get_or_create_event_loop()
            run = loop.run_until_complete(
                start_run(
                    document_id=document_id,
                    config_overrides=config_overrides,
                )
            )

            return {
                "run_id": run.get("_key", ""),
                "document_id": document_id,
                "status": run.get("status", "unknown"),
                "started_at": run.get("started_at"),
                "ontology_id": ontology_id,
            }
        except Exception as exc:
            log.exception("trigger_extraction failed")
            return {
                "error": str(exc),
                "document_id": document_id,
                "ontology_id": ontology_id,
            }

    @mcp.tool()
    def get_extraction_status(run_id: str) -> dict[str, Any]:
        """Return extraction run status, current step, elapsed time, and token usage.

        Args:
            run_id: The extraction run identifier.
        """
        try:
            from app.services.extraction import get_run

            run = get_run(run_id=run_id)
            stats = run.get("stats", {})

            elapsed = None
            if run.get("started_at"):
                end = run.get("completed_at") or time.time()
                elapsed = round(end - run["started_at"], 2)

            return {
                "run_id": run_id,
                "status": run.get("status", "unknown"),
                "document_id": run.get("doc_id"),
                "model": run.get("model"),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "elapsed_seconds": elapsed,
                "token_usage": stats.get("token_usage", {}),
                "classes_extracted": stats.get("classes_extracted", 0),
                "errors": stats.get("errors", []),
                "step_count": len(stats.get("step_logs", [])),
            }
        except Exception as exc:
            log.exception("get_extraction_status failed")
            return {"error": str(exc), "run_id": run_id}

    @mcp.tool()
    def get_merge_candidates(
        ontology_id: str,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Return entity resolution merge candidates above a score threshold.

        Queries the similarTo edge collection for candidate pairs with
        combined_score >= min_score.

        Args:
            ontology_id: The ontology to get candidates for.
            min_score: Minimum combined similarity score (default 0.5).
        """
        try:
            from app.services.er import get_candidates

            return get_candidates(
                ontology_id=ontology_id,
                min_score=min_score,
                limit=50,
            )
        except Exception as exc:
            log.exception("get_merge_candidates failed")
            return [{"error": str(exc), "ontology_id": ontology_id}]


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get the running event loop or create a new one for sync contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop
