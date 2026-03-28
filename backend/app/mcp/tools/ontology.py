"""MCP tools for ontology querying — domain summaries, class hierarchy,
class properties, and BM25 search.

Four tools:
  - query_domain_ontology: summary stats for an ontology
  - get_class_hierarchy: subClassOf tree as nested dict
  - get_class_properties: properties attached to a class via has_property edges
  - search_similar_classes: BM25 search on class labels/descriptions
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def register_ontology_tools(mcp: FastMCP) -> None:
    """Register all ontology query tools on the given MCP server instance."""

    @mcp.tool()
    def query_domain_ontology(ontology_id: str) -> dict[str, Any]:
        """Return a summary of a domain ontology: class count, property count,
        hierarchy depth, and recent changes.

        Args:
            ontology_id: The ontology identifier (registry key).
        """
        try:
            db = get_db()

            class_count = 0
            prop_count = 0
            recent_changes: list[dict[str, Any]] = []

            if db.has_collection("ontology_classes"):
                class_count_result = list(db.aql.execute(
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                ))
                class_count = class_count_result[0] if class_count_result else 0

                recent_changes = list(db.aql.execute(
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  SORT cls.created DESC
  LIMIT 5
  RETURN {
    key: cls._key,
    label: cls.label,
    change_type: cls.change_type,
    created: cls.created,
    version: cls.version
  }""",
                    bind_vars={"oid": ontology_id},
                ))

            if db.has_collection("ontology_properties"):
                prop_count_result = list(db.aql.execute(
                    """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                ))
                prop_count = prop_count_result[0] if prop_count_result else 0

            max_depth = _compute_hierarchy_depth(db, ontology_id)

            registry_info = None
            if db.has_collection("ontology_registry"):
                doc = db.collection("ontology_registry").get(ontology_id)
                if doc:
                    registry_info = {
                        "name": doc.get("name", ontology_id),
                        "status": doc.get("status"),
                        "tier": doc.get("tier"),
                        "created_at": doc.get("created_at"),
                    }

            return {
                "ontology_id": ontology_id,
                "class_count": class_count,
                "property_count": prop_count,
                "hierarchy_depth": max_depth,
                "recent_changes": recent_changes,
                "registry": registry_info,
            }
        except Exception as exc:
            log.exception("query_domain_ontology failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def get_class_hierarchy(
        ontology_id: str,
        root_class_key: str | None = None,
    ) -> dict[str, Any]:
        """Return the class hierarchy as a nested dict tree.

        If root_class_key is specified, returns the subtree rooted at that class.
        Only includes current (non-expired) classes and subclass_of edges.

        Args:
            ontology_id: The ontology identifier.
            root_class_key: Optional root class _key to start the subtree from.
        """
        try:
            db = get_db()

            if not db.has_collection("ontology_classes"):
                return {"error": "ontology_classes collection not found"}

            classes = list(db.aql.execute(
                """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN {key: cls._key, id: cls._id, label: cls.label, uri: cls.uri,
          description: cls.description}""",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            ))

            edges: list[dict[str, Any]] = []
            if db.has_collection("subclass_of"):
                class_ids = {c["id"] for c in classes}
                all_edges = list(db.aql.execute(
                    """\
FOR e IN subclass_of
  FILTER e.expired == @never
  RETURN {from_id: e._from, to_id: e._to}""",
                    bind_vars={"never": NEVER_EXPIRES},
                ))
                edges = [
                    e for e in all_edges
                    if e["from_id"] in class_ids and e["to_id"] in class_ids
                ]

            class_by_id = {c["id"]: c for c in classes}
            children_map: dict[str, list[str]] = {}
            child_ids: set[str] = set()

            for e in edges:
                parent_id = e["to_id"]
                child_id = e["from_id"]
                children_map.setdefault(parent_id, []).append(child_id)
                child_ids.add(child_id)

            def _build_tree(node_id: str) -> dict[str, Any]:
                node = class_by_id[node_id]
                child_nodes = children_map.get(node_id, [])
                return {
                    "key": node["key"],
                    "label": node["label"],
                    "uri": node["uri"],
                    "children": [_build_tree(cid) for cid in child_nodes if cid in class_by_id],
                }

            if root_class_key:
                root_id = f"ontology_classes/{root_class_key}"
                if root_id not in class_by_id:
                    return {"error": f"Class '{root_class_key}' not found in ontology"}
                return _build_tree(root_id)

            root_ids = [c["id"] for c in classes if c["id"] not in child_ids]
            if not root_ids:
                root_ids = [classes[0]["id"]] if classes else []

            return {
                "ontology_id": ontology_id,
                "roots": [_build_tree(rid) for rid in root_ids if rid in class_by_id],
            }
        except Exception as exc:
            log.exception("get_class_hierarchy failed")
            return {"error": str(exc), "ontology_id": ontology_id}

    @mcp.tool()
    def get_class_properties(class_key: str) -> dict[str, Any]:
        """Return all properties for a class (via has_property edges, current versions).

        Args:
            class_key: The _key of the ontology class.
        """
        try:
            db = get_db()
            if not db.has_collection("ontology_classes"):
                return {"error": "ontology_classes collection not found"}

            cls_results = list(db.aql.execute(
                """\
FOR cls IN ontology_classes
  FILTER cls._key == @key
  FILTER cls.expired == @never
  LIMIT 1
  RETURN cls""",
                bind_vars={"key": class_key, "never": NEVER_EXPIRES},
            ))
            if not cls_results:
                return {"error": f"Class '{class_key}' not found or expired"}

            cls = cls_results[0]

            properties: list[dict[str, Any]] = []
            if db.has_collection("has_property") and db.has_collection("ontology_properties"):
                properties = list(db.aql.execute(
                    """\
FOR e IN has_property
  FILTER e._from == @cls_id
  FILTER e.expired == @never
  LET prop = DOCUMENT(e._to)
  FILTER prop != null
  FILTER prop.expired == @never
  RETURN {
    key: prop._key,
    uri: prop.uri,
    label: prop.label,
    description: prop.description,
    property_type: prop.property_type,
    range: prop.range,
    domain_class: prop.domain_class
  }""",
                    bind_vars={"cls_id": cls["_id"], "never": NEVER_EXPIRES},
                ))

            return {
                "class_key": class_key,
                "class_label": cls.get("label"),
                "class_uri": cls.get("uri"),
                "property_count": len(properties),
                "properties": properties,
            }
        except Exception as exc:
            log.exception("get_class_properties failed")
            return {"error": str(exc), "class_key": class_key}

    @mcp.tool()
    def search_similar_classes(
        query: str,
        ontology_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """BM25 search on class labels and descriptions via ArangoSearch view.

        Falls back to LIKE-based search if the ArangoSearch view is not available.

        Args:
            query: The search query string.
            ontology_id: Optional ontology to scope the search to.
            limit: Maximum number of results (default 10, max 50).
        """
        try:
            db = get_db()
            limit = min(max(1, limit), 50)

            if not db.has_collection("ontology_classes"):
                return [{"error": "ontology_classes collection not found"}]

            has_view = _has_search_view(db, "ontology_classes_search")

            if has_view:
                return _bm25_search(db, query, ontology_id, limit)

            return _fallback_search(db, query, ontology_id, limit)
        except Exception as exc:
            log.exception("search_similar_classes failed")
            return [{"error": str(exc), "query": query}]


def _compute_hierarchy_depth(db: Any, ontology_id: str) -> int:
    """Compute the maximum depth of the subClassOf hierarchy."""
    if not db.has_collection("ontology_classes") or not db.has_collection("subclass_of"):
        return 0

    try:
        result = list(db.aql.execute(
            """\
LET roots = (
  FOR cls IN ontology_classes
    FILTER cls.ontology_id == @oid
    FILTER cls.expired == @never
    LET is_child = (
      FOR e IN subclass_of
        FILTER e._from == cls._id
        FILTER e.expired == @never
        LIMIT 1
        RETURN 1
    )
    FILTER LENGTH(is_child) == 0
    RETURN cls._id
)
FOR root IN roots
  LET depth = LENGTH(
    FOR v IN 1..100 OUTBOUND root subclass_of
      OPTIONS {order: "bfs", uniqueVertices: "global"}
      FILTER v.expired == @never
      RETURN 1
  )
  RETURN depth""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        return max(result) if result else 0
    except Exception:
        return 0


def _has_search_view(db: Any, view_name: str) -> bool:
    """Check if an ArangoSearch view exists."""
    try:
        views = db.views()
        return any(v["name"] == view_name for v in views)
    except Exception:
        return False


def _bm25_search(
    db: Any,
    query: str,
    ontology_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """BM25 search using ArangoSearch view."""
    oid_filter = "FILTER doc.ontology_id == @oid" if ontology_id else ""
    bind_vars: dict[str, Any] = {
        "query": query,
        "never": NEVER_EXPIRES,
        "lim": limit,
    }
    if ontology_id:
        bind_vars["oid"] = ontology_id

    return list(db.aql.execute(
        f"""\
FOR doc IN ontology_classes_search
  SEARCH ANALYZER(
    BOOST(BM25(doc.label, @query), 2) > 0
    OR BM25(doc.description, @query) > 0,
    "text_en"
  )
  FILTER doc.expired == @never
  {oid_filter}
  SORT BM25(doc) DESC
  LIMIT @lim
  RETURN {{
    key: doc._key,
    label: doc.label,
    uri: doc.uri,
    description: doc.description,
    ontology_id: doc.ontology_id,
    score: BM25(doc)
  }}""",
        bind_vars=bind_vars,
    ))


def _fallback_search(
    db: Any,
    query: str,
    ontology_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Fallback LIKE-based search when ArangoSearch is not available."""
    oid_filter = "FILTER cls.ontology_id == @oid" if ontology_id else ""
    bind_vars: dict[str, Any] = {
        "pattern": f"%{query}%",
        "never": NEVER_EXPIRES,
        "lim": limit,
    }
    if ontology_id:
        bind_vars["oid"] = ontology_id

    return list(db.aql.execute(
        f"""\
FOR cls IN ontology_classes
  FILTER cls.expired == @never
  {oid_filter}
  FILTER LIKE(cls.label, @pattern, true) OR LIKE(cls.description, @pattern, true)
  LIMIT @lim
  RETURN {{
    key: cls._key,
    label: cls.label,
    uri: cls.uri,
    description: cls.description,
    ontology_id: cls.ontology_id
  }}""",
        bind_vars=bind_vars,
    ))
