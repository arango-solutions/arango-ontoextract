"""Ontology imports dependency DAG (Stream 1 H.3).

The H.4 ``ontology_dependency`` module computes the cascade-on-delete
report for a single ontology. This module computes the orthogonal view:
the *whole* registry's ``owl:imports`` DAG, optionally restricted to the
subgraph reachable from a single root.

It is the data source for:

* ``GET /api/v1/ontology/imports-graph`` (H.3) -- the workspace
  ``ImportsDependencyOverlay`` (H.7) consumes this verbatim.
* The standard ontology catalog UI (H.6) when previewing the dependency
  fan-out of a candidate import.
* The ArangoDB Visualizer saved queries (H.9) which traverse the new
  ``ontology_imports`` named graph (migration 025) for the same data.

Both edges and vertices come from one AQL pass each so the call cost is
constant regardless of ontology count. Output shape is stable and is
considered part of the public contract; H.7 unit tests pin it.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# Mirrors ``add_ontology_import``'s cycle-check depth (10 hops). Imports
# DAGs are almost always shallow; this is a guardrail, not a feature.
DEFAULT_MAX_DEPTH = 10

Direction = Literal["outbound", "inbound", "both"]


def build_imports_dag(
    db: StandardDatabase,
    *,
    root: str | None = None,
    direction: Direction = "both",
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    """Return the live ``owl:imports`` dependency graph.

    Parameters
    ----------
    db:
        ArangoDB handle. Not closed by this function.
    root:
        Registry ``_key`` to anchor the traversal on. If ``None`` (the
        default), the entire registry's imports DAG is returned -- every
        live import edge plus every registry entry that participates as
        either endpoint.
    direction:
        Only consulted when ``root`` is set:

        * ``"outbound"`` -- ancestors (what this ontology imports,
          transitively).
        * ``"inbound"`` -- descendants (who imports this ontology,
          transitively).
        * ``"both"`` -- the union (default), so a node can see its full
          context regardless of which side of the DAG it sits on.
    max_depth:
        Traversal depth cap. Defaults to :data:`DEFAULT_MAX_DEPTH`.
        Values < 1 are clamped to 1; values > 50 are clamped to 50 to
        keep one bad query from running away.

    Returns
    -------
    dict
        ``{"nodes": [...], "edges": [...], "root": root|None,
        "direction": direction|None, "truncated": bool}``. ``nodes`` and
        ``edges`` are de-duplicated and sorted (nodes by name then key,
        edges by ``(from_key, to_key, edge_key)``) so the frontend's
        ``ImportsDependencyOverlay`` does not flicker on refresh.
    """
    safe_depth = max(1, min(int(max_depth), 50))

    if not db.has_collection("imports") or not db.has_collection("ontology_registry"):
        return {
            "nodes": [],
            "edges": [],
            "root": root,
            "direction": direction if root else None,
            "truncated": False,
        }

    if root is None:
        nodes, edges = _build_full_dag(db)
        chosen_direction: Direction | None = None
    else:
        target_id = f"ontology_registry/{root}"
        if not _registry_exists(db, root):
            raise ValueError(f"Ontology '{root}' not found")
        nodes, edges = _build_rooted_dag(
            db,
            target_id=target_id,
            direction=direction,
            max_depth=safe_depth,
        )
        chosen_direction = direction

    nodes_sorted = sorted(nodes, key=lambda n: (str(n.get("name") or n["_key"]).lower(), n["_key"]))
    edges_sorted = sorted(
        edges,
        key=lambda e: (e["from_key"], e["to_key"], str(e.get("edge_key") or "")),
    )

    return {
        "nodes": nodes_sorted,
        "edges": edges_sorted,
        "root": root,
        "direction": chosen_direction,
        "truncated": False,
    }


# --- internals --------------------------------------------------------------


def _registry_exists(db: StandardDatabase, ontology_id: str) -> bool:
    try:
        return bool(db.collection("ontology_registry").get(ontology_id))
    except Exception:
        return False


def _build_full_dag(db: StandardDatabase) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Whole-registry pass: every live import edge + the registry rows it touches."""
    edge_rows = list(
        run_aql(
            db,
            """
            FOR e IN imports
              FILTER e.expired == @never
              LET src = DOCUMENT(e._from)
              LET dst = DOCUMENT(e._to)
              RETURN {
                edge_key: e._key,
                from_key: PARSE_IDENTIFIER(e._from).key,
                to_key: PARSE_IDENTIFIER(e._to).key,
                import_iri: e.import_iri,
                created: e.created,
                from_name: src.name || src.label,
                from_status: src.status,
                from_tier: src.tier,
                to_name: dst.name || dst.label,
                to_status: dst.status,
                to_tier: dst.tier
              }
            """,
            bind_vars={"never": NEVER_EXPIRES},
        )
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for row in edge_rows:
        from_key = str(row["from_key"])
        to_key = str(row["to_key"])

        _upsert_node(
            nodes,
            from_key,
            row.get("from_name"),
            row.get("from_status"),
            row.get("from_tier"),
        )
        _upsert_node(
            nodes,
            to_key,
            row.get("to_name"),
            row.get("to_status"),
            row.get("to_tier"),
        )

        edges.append(
            {
                "edge_key": row.get("edge_key"),
                "from_key": from_key,
                "to_key": to_key,
                "import_iri": row.get("import_iri"),
                "created": row.get("created"),
            }
        )

    return list(nodes.values()), edges


def _build_rooted_dag(
    db: StandardDatabase,
    *,
    target_id: str,
    direction: Direction,
    max_depth: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sub-DAG reachable from a single root.

    For ``direction="both"`` we run two traversals and union them so the
    user sees the full neighbourhood (what this ontology imports AND who
    depends on it). Duplicate edges/nodes are collapsed via the node
    map and ``edge_key`` dedupe set.
    """
    arango_direction = {
        "outbound": "OUTBOUND",
        "inbound": "INBOUND",
        "both": "ANY",
    }[direction]

    rows = list(
        run_aql(
            db,
            f"""
            FOR v, e, p IN 1..@max_depth {arango_direction} @target imports
              OPTIONS {{ uniqueEdges: 'global', bfs: true }}
              FILTER e == null OR e.expired == @never
              LET src = DOCUMENT(e._from)
              LET dst = DOCUMENT(e._to)
              RETURN {{
                edge_key: e._key,
                from_key: PARSE_IDENTIFIER(e._from).key,
                to_key: PARSE_IDENTIFIER(e._to).key,
                import_iri: e.import_iri,
                created: e.created,
                from_name: src.name || src.label,
                from_status: src.status,
                from_tier: src.tier,
                to_name: dst.name || dst.label,
                to_status: dst.status,
                to_tier: dst.tier,
                visited_key: v._key,
                visited_name: v.name || v.label,
                visited_status: v.status,
                visited_tier: v.tier
              }}
            """,
            bind_vars={
                "target": target_id,
                "never": NEVER_EXPIRES,
                "max_depth": max_depth,
            },
        )
    )

    # Always include the root, even if it has no imports edges (so the
    # overlay can render a single isolated node rather than an empty
    # graph and confuse the user about whether the ontology exists).
    nodes: dict[str, dict[str, Any]] = {}
    root_key = target_id.split("/", 1)[1]
    root_entry = cast(
        "dict[str, Any] | None",
        db.collection("ontology_registry").get(root_key),
    )
    if root_entry is not None:
        _upsert_node(
            nodes,
            str(root_entry["_key"]),
            root_entry.get("name") or root_entry.get("label"),
            root_entry.get("status"),
            root_entry.get("tier"),
        )

    seen_edge_keys: set[str] = set()
    edges: list[dict[str, Any]] = []
    for row in rows:
        edge_key = str(row.get("edge_key") or "")
        if not edge_key or edge_key in seen_edge_keys:
            continue
        seen_edge_keys.add(edge_key)

        from_key = str(row["from_key"])
        to_key = str(row["to_key"])
        _upsert_node(
            nodes,
            from_key,
            row.get("from_name"),
            row.get("from_status"),
            row.get("from_tier"),
        )
        _upsert_node(
            nodes,
            to_key,
            row.get("to_name"),
            row.get("to_status"),
            row.get("to_tier"),
        )
        _upsert_node(
            nodes,
            str(row.get("visited_key")),
            row.get("visited_name"),
            row.get("visited_status"),
            row.get("visited_tier"),
        )

        edges.append(
            {
                "edge_key": edge_key,
                "from_key": from_key,
                "to_key": to_key,
                "import_iri": row.get("import_iri"),
                "created": row.get("created"),
            }
        )

    return list(nodes.values()), edges


def _upsert_node(
    nodes: dict[str, dict[str, Any]],
    key: str,
    name: Any,
    status: Any,
    tier: Any,
) -> None:
    """Insert or refine a node entry.

    Refinement is important because the registry row may appear under
    different traversal rows with partial fields populated (e.g. a row
    where the node is only the ``_from`` side has populated source
    fields but a different ``visited_*`` set). We never overwrite a
    non-empty field with a None.
    """
    if not key:
        return
    existing = nodes.get(key)
    if existing is None:
        nodes[key] = {
            "_key": key,
            "name": _coerce_str(name) or key,
            "status": _coerce_str(status),
            "tier": _coerce_str(tier),
        }
        return
    if not existing.get("name") or existing.get("name") == key:
        existing["name"] = _coerce_str(name) or existing.get("name") or key
    if existing.get("status") is None and status is not None:
        existing["status"] = _coerce_str(status)
    if existing.get("tier") is None and tier is not None:
        existing["tier"] = _coerce_str(tier)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
