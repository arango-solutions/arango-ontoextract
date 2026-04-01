"""Dev-time MCP introspection tools for querying ArangoDB state.

Three tools:
  - query_collections: list all collections with doc counts and types
  - run_aql: execute read-only AQL queries (limit 100 results)
  - sample_collection: return N sample documents from a collection
"""

from __future__ import annotations

import logging
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db
from app.db.utils import run_aql as _run_aql

log = logging.getLogger(__name__)


def register_introspection_tools(mcp: FastMCP) -> None:
    """Register all introspection tools on the given MCP server instance."""

    @mcp.tool()
    def query_collections() -> list[dict[str, Any]]:
        """List all ArangoDB collections with their document counts and types.

        Returns a list of objects with fields:
          - name: collection name
          - count: number of documents
          - type: "document" or "edge"
        System collections (prefixed with '_') are excluded.
        """
        try:
            db = get_db()
            results: list[dict[str, Any]] = []
            for col in cast("list[dict[str, Any]]", db.collections()):
                if col["system"]:
                    continue
                info = db.collection(col["name"])
                results.append(
                    {
                        "name": col["name"],
                        "count": info.count(),
                        "type": "edge" if col["type"] == 3 else "document",
                    }
                )
            return results
        except Exception as exc:
            log.exception("query_collections failed")
            return [{"error": str(exc)}]

    @mcp.tool()
    def run_aql(query: str, bind_vars: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only AQL query against the database.

        The query is wrapped in a read transaction for safety.
        Results are capped at 100 documents.

        Args:
            query: The AQL query string to execute.
            bind_vars: Optional dictionary of bind variables for the query.
        """
        try:
            db = get_db()
            cursor = _run_aql(
                db,
                query,
                bind_vars=bind_vars or {},
                count=True,
                batch_size=100,
            )
            results = []
            for doc in cursor:
                results.append(doc)
                if len(results) >= 100:
                    break
            return results
        except Exception as exc:
            log.exception("run_aql failed")
            return [{"error": str(exc), "query": query}]

    @mcp.tool()
    def sample_collection(collection_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return N sample documents from a named collection.

        Useful for understanding the schema/shape of documents in a collection.

        Args:
            collection_name: Name of the ArangoDB collection to sample.
            limit: Number of sample documents to return (default 5, max 20).
        """
        try:
            limit = min(max(1, limit), 20)
            db = get_db()
            if not db.has_collection(collection_name):
                return [{"error": f"Collection '{collection_name}' does not exist"}]
            cursor = _run_aql(
                db,
                "FOR doc IN @@col LIMIT @lim RETURN doc",
                bind_vars={"@col": collection_name, "lim": limit},
            )
            return list(cursor)
        except Exception as exc:
            log.exception("sample_collection failed")
            return [{"error": str(exc), "collection": collection_name}]
