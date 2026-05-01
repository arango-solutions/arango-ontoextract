"""MCP tools for ontology querying — domain summaries, class hierarchy,
class properties, and BM25 search.

Four tools:
  - query_domain_ontology: summary stats for an ontology
  - get_class_hierarchy: subClassOf tree as nested dict
  - get_class_properties: properties via PGT (rdfs_domain) and/or legacy has_property
  - search_similar_classes: BM25 search on class labels/descriptions
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db
from app.db.utils import doc_get, run_aql

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize

_PROPERTY_VERTEX_COLLECTIONS = (
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
)


def _count_ontology_property_vertices(db: Any, ontology_id: str) -> int:
    """Count current property vertices across legacy + PGT collections (ADR-006)."""
    total = 0
    for col in _PROPERTY_VERTEX_COLLECTIONS:
        if not db.has_collection(col):
            continue
        rows = list(
            run_aql(
                db,
                f"FOR p IN {col} "
                "FILTER p.ontology_id == @oid AND p.expired == @never "
                "COLLECT WITH COUNT INTO c RETURN c",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )
        total += int(rows[0]) if rows else 0
    return total


def _load_class_property_rows(
    db: Any,
    *,
    class_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (datatype_props, object_props_merged, legacy_props) like REST get_class_detail."""
    attributes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    legacy_properties: list[dict[str, Any]] = []

    if db.has_collection("rdfs_domain") and db.has_collection("ontology_datatype_properties"):
        attributes = list(
            run_aql(
                db,
                "FOR e IN rdfs_domain "
                "FILTER e._to == @cid AND e.expired == @never "
                "FOR p IN ontology_datatype_properties "
                "FILTER p._id == e._from AND p.expired == @never "
                "RETURN p",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

    if db.has_collection("rdfs_domain") and db.has_collection("ontology_object_properties"):
        range_sub = "RETURN p"
        if db.has_collection("rdfs_range_class"):
            range_sub = (
                "LET target = FIRST("
                "  FOR re IN rdfs_range_class "
                "  FILTER re._from == p._id AND re.expired == @never "
                "  LET t = DOCUMENT(re._to) "
                "  RETURN {_key: t._key, label: t.label, uri: t.uri, _id: t._id}"
                ") "
                "RETURN MERGE(p, {target_class: target})"
            )
        relationships = list(
            run_aql(
                db,
                "FOR e IN rdfs_domain "
                "FILTER e._to == @cid AND e.expired == @never "
                "FOR p IN ontology_object_properties "
                f"FILTER p._id == e._from AND p.expired == @never "
                f"{range_sub}",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

    if (
        not attributes
        and not relationships
        and db.has_collection("has_property")
        and db.has_collection("ontology_properties")
    ):
        legacy_properties = list(
            run_aql(
                db,
                "FOR e IN has_property "
                "FILTER e._from == @cid AND e.expired == @never "
                "LET prop = DOCUMENT(e._to) "
                "FILTER prop != null AND prop.expired == @never "
                "RETURN prop",
                bind_vars={"cid": class_id, "never": NEVER_EXPIRES},
            )
        )

    return attributes, relationships, legacy_properties


def _flatten_properties_for_mcp(
    attributes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    legacy_properties: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Single list shape expected by older MCP clients."""
    flat: list[dict[str, Any]] = []
    for p in attributes:
        flat.append(
            {
                "key": p.get("_key"),
                "uri": p.get("uri"),
                "label": p.get("label"),
                "description": p.get("description"),
                "property_type": "datatype",
                "range": p.get("range_datatype", "xsd:string"),
                "domain_class": None,
            }
        )
    for p in relationships:
        tgt = p.get("target_class") or {}
        range_uri = tgt.get("uri") or ""
        flat.append(
            {
                "key": p.get("_key"),
                "uri": p.get("uri"),
                "label": p.get("label"),
                "description": p.get("description"),
                "property_type": "object",
                "range": range_uri,
                "domain_class": None,
            }
        )
    if not flat:
        for p in legacy_properties:
            flat.append(
                {
                    "key": p.get("_key"),
                    "uri": p.get("uri"),
                    "label": p.get("label"),
                    "description": p.get("description"),
                    "property_type": p.get("property_type", "datatype"),
                    "range": p.get("range", "xsd:string"),
                    "domain_class": p.get("domain_class"),
                }
            )
    return flat


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
                class_count_result = list(
                    run_aql(
                        db,
                        """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  COLLECT WITH COUNT INTO cnt
  RETURN cnt""",
                        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                    )
                )
                class_count = class_count_result[0] if class_count_result else 0

                recent_changes = list(
                    run_aql(
                        db,
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
                    )
                )

            prop_count = _count_ontology_property_vertices(db, ontology_id)

            max_depth = _compute_hierarchy_depth(db, ontology_id)

            registry_info = None
            if db.has_collection("ontology_registry"):
                doc = doc_get(db.collection("ontology_registry"), ontology_id)
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

            classes = list(
                run_aql(
                    db,
                    """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN {key: cls._key, id: cls._id, label: cls.label, uri: cls.uri,
          description: cls.description}""",
                    bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                )
            )

            edges: list[dict[str, Any]] = []
            if db.has_collection("subclass_of"):
                class_ids = {c["id"] for c in classes}
                all_edges = list(
                    run_aql(
                        db,
                        """\
FOR e IN subclass_of
  FILTER e.expired == @never
  RETURN {from_id: e._from, to_id: e._to}""",
                        bind_vars={"never": NEVER_EXPIRES},
                    )
                )
                edges = [
                    e for e in all_edges if e["from_id"] in class_ids and e["to_id"] in class_ids
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
        """Return properties for a class (PGT rdfs_domain + legacy has_property).

        ``properties`` is a flattened list with ``property_type`` ``datatype`` or
        ``object`` and a string ``range`` (XSD type or target class URI).

        Args:
            class_key: The _key of the ontology class.
        """
        try:
            db = get_db()
            if not db.has_collection("ontology_classes"):
                return {"error": "ontology_classes collection not found"}

            cls_results = list(
                run_aql(
                    db,
                    """\
FOR cls IN ontology_classes
  FILTER cls._key == @key
  FILTER cls.expired == @never
  LIMIT 1
  RETURN cls""",
                    bind_vars={"key": class_key, "never": NEVER_EXPIRES},
                )
            )
            if not cls_results:
                return {"error": f"Class '{class_key}' not found or expired"}

            cls = cls_results[0]
            attrs, rels, legacy = _load_class_property_rows(db, class_id=cls["_id"])
            properties = _flatten_properties_for_mcp(attrs, rels, legacy)

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
        result = list(
            run_aql(
                db,
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
            )
        )
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

    return list(
        run_aql(
            db,
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
        )
    )


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

    return list(
        run_aql(
            db,
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
        )
    )
