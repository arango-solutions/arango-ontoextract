"""MCP tools for entity resolution — run ER pipeline, explain matches,
and retrieve entity clusters.

Three tools:
  - run_entity_resolution: triggers the ER pipeline
  - explain_entity_match: field-by-field similarity breakdown
  - get_entity_clusters: returns entity clusters with member details
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_er_tools(mcp: FastMCP) -> None:
    """Register all entity resolution tools on the given MCP server instance."""

    @mcp.tool()
    def run_entity_resolution(
        ontology_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger the entity resolution pipeline for an ontology.

        Runs blocking, scoring, and clustering stages to find duplicate
        ontology classes. Returns run info including candidate and cluster counts.

        Args:
            ontology_id: The ontology to run ER on.
            config: Optional ER config overrides (blocking_strategies, field_configs,
                    similarity_threshold, etc.).
        """
        try:
            from app.services.er import ERPipelineConfig, run_er_pipeline

            er_config = None
            if config:
                er_config = ERPipelineConfig.from_dict(config)

            result = run_er_pipeline(ontology_id=ontology_id, config=er_config)

            return {
                "run_id": result.run_id,
                "status": result.status.value,
                "candidate_count": result.candidate_count,
                "cluster_count": result.cluster_count,
                "duration_seconds": result.duration_seconds,
                "error": result.error,
            }
        except Exception as exc:
            log.exception("run_entity_resolution failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def explain_entity_match(key1: str, key2: str) -> dict[str, Any]:
        """Return a detailed field-by-field similarity explanation for two entities.

        Shows label (Jaro-Winkler), description (token overlap), URI (exact),
        and topological similarity scores with a combined weighted score.

        Args:
            key1: The _key of the first ontology class.
            key2: The _key of the second ontology class.
        """
        try:
            from app.services.er import explain_match

            return explain_match(key1=key1, key2=key2)
        except Exception as exc:
            log.exception("explain_entity_match failed")
            return {"error": str(exc), "key1": key1, "key2": key2}

    @mcp.tool()
    def get_entity_clusters(ontology_id: str) -> list[dict[str, Any]]:
        """Return entity clusters for an ontology with member details.

        Each cluster represents a group of potentially duplicate classes
        identified by WCC (Weakly Connected Components) analysis.

        Args:
            ontology_id: The ontology identifier.
        """
        try:
            from app.services.er import get_clusters

            return get_clusters(ontology_id=ontology_id)
        except Exception as exc:
            log.exception("get_entity_clusters failed")
            return [{"error": str(exc), "ontology_id": ontology_id}]
