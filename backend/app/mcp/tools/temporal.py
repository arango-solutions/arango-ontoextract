"""MCP tools for temporal graph operations — snapshots, version history, diffs.

Three tools:
  - get_ontology_snapshot: full graph state at a timestamp
  - get_class_history: all versions of a class
  - get_ontology_diff: added/removed/changed entities between two timestamps
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def register_temporal_tools(mcp: FastMCP) -> None:
    """Register all temporal tools on the given MCP server instance."""

    @mcp.tool()
    def get_ontology_snapshot(
        ontology_id: str,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Return the full graph state at a given timestamp (or current state if None).

        Returns class count, property count, edge count, and a sample of classes.

        Args:
            ontology_id: The ontology identifier.
            timestamp: Unix timestamp for point-in-time query. Defaults to now.
        """
        try:
            from app.services.temporal import get_snapshot

            ts = timestamp if timestamp is not None else time.time()
            snapshot = get_snapshot(ontology_id=ontology_id, timestamp=ts)

            classes = snapshot.get("classes", [])
            properties = snapshot.get("properties", [])
            edges = snapshot.get("edges", [])

            sample_classes = [
                {
                    "key": c.get("_key"),
                    "label": c.get("label"),
                    "uri": c.get("uri"),
                    "version": c.get("version"),
                }
                for c in classes[:10]
            ]

            return {
                "ontology_id": ontology_id,
                "timestamp": ts,
                "class_count": len(classes),
                "property_count": len(properties),
                "edge_count": len(edges),
                "sample_classes": sample_classes,
            }
        except Exception as exc:
            log.exception("get_ontology_snapshot failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def get_class_history(class_key: str) -> list[dict[str, Any]]:
        """Return all versions of a class sorted by created timestamp descending.

        Looks up the class by _key, finds its URI, then returns all versions
        sharing that URI across the ontology_classes collection.

        Args:
            class_key: The _key of the ontology class.
        """
        try:
            from app.services.temporal import get_entity_history

            versions = get_entity_history(
                collection="ontology_classes",
                key=class_key,
            )

            return [
                {
                    "key": v.get("_key"),
                    "label": v.get("label"),
                    "uri": v.get("uri"),
                    "version": v.get("version"),
                    "created": v.get("created"),
                    "expired": v.get("expired"),
                    "is_current": v.get("expired") == NEVER_EXPIRES,
                    "change_type": v.get("change_type"),
                    "change_summary": v.get("change_summary"),
                    "created_by": v.get("created_by"),
                }
                for v in versions
            ]
        except Exception as exc:
            log.exception("get_class_history failed")
            return [{"error": str(exc), "class_key": class_key}]

    @mcp.tool()
    def get_ontology_diff(
        ontology_id: str,
        t1: float,
        t2: float,
    ) -> dict[str, Any]:
        """Return the temporal diff between two timestamps: added, removed, and
        changed entities.

        Args:
            ontology_id: The ontology identifier.
            t1: Start timestamp (earlier).
            t2: End timestamp (later).
        """
        try:
            from app.services.temporal import get_diff

            diff = get_diff(ontology_id=ontology_id, t1=t1, t2=t2)

            added = diff.get("added", [])
            removed = diff.get("removed", [])
            changed = diff.get("changed", [])

            return {
                "ontology_id": ontology_id,
                "t1": t1,
                "t2": t2,
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
                "added": [
                    {"key": e.get("_key"), "label": e.get("label"), "uri": e.get("uri")}
                    for e in added
                ],
                "removed": [
                    {"key": e.get("_key"), "label": e.get("label"), "uri": e.get("uri")}
                    for e in removed
                ],
                "changed": [
                    {
                        "key": c["after"].get("_key"),
                        "label": c["after"].get("label"),
                        "collection": c.get("collection"),
                        "before_version": c["before"].get("version"),
                        "after_version": c["after"].get("version"),
                    }
                    for c in changed
                ],
            }
        except Exception as exc:
            log.exception("get_ontology_diff failed")
            return {"error": str(exc), "ontology_id": ontology_id}
