"""MCP resources — read-only data endpoints for external agents.

Four resources:
  - aoe://ontology/domain/summary — summary of all domain ontologies
  - aoe://extraction/runs/recent — last 10 extraction runs with status
  - aoe://system/health — system health including ArangoDB connection status
  - aoe://ontology/{ontology_id}/stats — detailed stats for a specific ontology
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db
from app.db.utils import doc_get, run_aql

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def register_ontology_resources(mcp: FastMCP) -> None:
    """Register all MCP resources on the given server instance."""

    @mcp.resource("aoe://ontology/domain/summary")
    def ontology_domain_summary() -> str:
        """Summary of all domain ontologies — count, names, sizes."""
        try:
            db = get_db()
            entries: list[dict[str, Any]] = []

            if db.has_collection("ontology_registry"):
                entries = list(run_aql(
                    db,
                    """\
FOR entry IN ontology_registry
  FILTER entry.status != "deprecated"
  SORT entry.created_at DESC
  RETURN {
    ontology_id: entry._key,
    name: entry.name,
    tier: entry.tier,
    status: entry.status,
    created_at: entry.created_at
  }"""
                ))

            ontology_sizes: list[dict[str, Any]] = []
            for entry in entries:
                oid = entry["ontology_id"]
                class_count = 0
                if db.has_collection("ontology_classes"):
                    cnt = list(run_aql(
                        db,
                        """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                        bind_vars={"oid": oid, "never": NEVER_EXPIRES},
                    ))
                    class_count = cnt[0] if cnt else 0

                ontology_sizes.append({
                    **entry,
                    "class_count": class_count,
                })

            import json
            return json.dumps({
                "total_ontologies": len(entries),
                "ontologies": ontology_sizes,
                "generated_at": time.time(),
            }, indent=2, default=str)
        except Exception as exc:
            log.exception("ontology_domain_summary resource failed")
            import json
            return json.dumps({"error": str(exc)})

    @mcp.resource("aoe://extraction/runs/recent")
    def extraction_runs_recent() -> str:
        """Last 10 extraction runs with status."""
        try:
            db = get_db()
            runs: list[dict[str, Any]] = []

            if db.has_collection("extraction_runs"):
                runs = list(run_aql(
                    db,
                    """\
FOR run IN extraction_runs
  FILTER HAS(run, "status")
  FILTER run._key NOT LIKE "results_%"
  SORT run.started_at DESC
  LIMIT 10
  RETURN {
    run_id: run._key,
    doc_id: run.doc_id,
    model: run.model,
    status: run.status,
    started_at: run.started_at,
    completed_at: run.completed_at,
    classes_extracted: run.stats.classes_extracted
  }"""
                ))

            import json
            return json.dumps({
                "recent_runs": runs,
                "count": len(runs),
                "generated_at": time.time(),
            }, indent=2, default=str)
        except Exception as exc:
            log.exception("extraction_runs_recent resource failed")
            import json
            return json.dumps({"error": str(exc)})

    @mcp.resource("aoe://system/health")
    def system_health() -> str:
        """System health including ArangoDB connection and collection counts."""
        try:
            db = get_db()
            collections_info: list[dict[str, Any]] = []
            db_connected = True

            try:
                for col in cast("list[dict[str, Any]]", db.collections()):
                    if col["system"]:
                        continue
                    info = db.collection(col["name"])
                    collections_info.append({
                        "name": col["name"],
                        "count": info.count(),
                        "type": "edge" if col["type"] == 3 else "document",
                    })
            except Exception as db_exc:
                db_connected = False
                log.warning("health check: ArangoDB query failed", exc_info=db_exc)

            import json
            return json.dumps({
                "status": "healthy" if db_connected else "degraded",
                "arango_connected": db_connected,
                "collection_count": len(collections_info),
                "collections": collections_info,
                "generated_at": time.time(),
            }, indent=2, default=str)
        except Exception as exc:
            log.exception("system_health resource failed")
            import json
            return json.dumps({"error": str(exc), "status": "unhealthy"})

    @mcp.resource("aoe://ontology/{ontology_id}/stats")
    def ontology_stats(ontology_id: str) -> str:
        """Detailed stats for a specific ontology."""
        try:
            db = get_db()

            class_count = 0
            prop_count = 0

            if db.has_collection("ontology_classes"):
                cnt = list(run_aql(
                    db,
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                ))
                class_count = cnt[0] if cnt else 0

            if db.has_collection("ontology_properties"):
                cnt = list(run_aql(
                    db,
                    """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                ))
                prop_count = cnt[0] if cnt else 0

            edge_counts: dict[str, int] = {}
            edge_collections = [
                "subclass_of", "has_property", "equivalent_class",
                "extends_domain", "related_to",
            ]
            class_ids: set[str] = set()
            if class_count > 0 and db.has_collection("ontology_classes"):
                class_ids = set(run_aql(
                    db,
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN cls._id""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                ))

            for edge_col in edge_collections:
                if not db.has_collection(edge_col):
                    edge_counts[edge_col] = 0
                    continue
                edges = list(run_aql(
                    db,
                    """\
FOR e IN @@col
  FILTER e.expired == @never
  RETURN {f: e._from, t: e._to}""",
                    bind_vars={"@col": edge_col, "never": NEVER_EXPIRES},
                ))
                count = sum(
                    1 for e in edges
                    if e["f"] in class_ids or e["t"] in class_ids
                )
                edge_counts[edge_col] = count

            total_versions = 0
            if db.has_collection("ontology_classes"):
                cnt = list(run_aql(
                    db,
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                    bind_vars={"oid": ontology_id},
                ))
                total_versions = cnt[0] if cnt else 0

            registry_info = None
            if db.has_collection("ontology_registry"):
                doc = doc_get(db.collection("ontology_registry"), ontology_id)
                if doc:
                    registry_info = {
                        "name": doc.get("name", ontology_id),
                        "status": doc.get("status"),
                        "tier": doc.get("tier"),
                    }

            import json
            return json.dumps({
                "ontology_id": ontology_id,
                "class_count": class_count,
                "property_count": prop_count,
                "edge_counts": edge_counts,
                "total_edge_count": sum(edge_counts.values()),
                "total_versions": total_versions,
                "historical_versions": total_versions - class_count,
                "registry": registry_info,
                "generated_at": time.time(),
            }, indent=2, default=str)
        except Exception as exc:
            log.exception("ontology_stats resource failed")
            import json
            return json.dumps({"error": str(exc), "ontology_id": ontology_id})
