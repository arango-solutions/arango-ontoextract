"""Per-ontology named graph management.

Each ontology gets its own named ArangoDB graph so it can be explored
independently in the ArangoDB Graph Visualizer. The graph name follows
the pattern ``ontology_{ontology_id}``.

All per-ontology graphs share the same underlying edge and vertex
collections (ontology_classes, ontology_properties, etc.) — the
separation is purely at the ArangoDB named-graph level for visual
exploration. Data isolation is achieved by filtering on ``ontology_id``.
"""

from __future__ import annotations

import logging
import re

from arango.database import StandardDatabase

from app.db.client import get_db

log = logging.getLogger(__name__)

PER_ONTOLOGY_EDGE_DEFINITIONS = [
    {
        "edge_collection": "subclass_of",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
    {
        "edge_collection": "has_property",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_properties"],
    },
    {
        "edge_collection": "related_to",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
    {
        "edge_collection": "extracted_from",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["documents"],
    },
]


def _safe_graph_name(name: str) -> str:
    """Derive a valid ArangoDB graph name from a human-readable name.

    Lowercases, replaces spaces/special chars with underscores, and
    collapses consecutive underscores.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return f"ontology_{sanitized}"


def _resolve_ontology_name(
    ontology_id: str,
    db: StandardDatabase,
) -> str:
    """Look up the human-readable name from the registry, falling back to the id."""
    if db.has_collection("ontology_registry"):
        col = db.collection("ontology_registry")
        if col.has(ontology_id):
            doc = col.get(ontology_id)
            if doc and doc.get("name"):
                return doc["name"]
    return ontology_id


def ensure_ontology_graph(
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_name: str | None = None,
) -> str:
    """Create (if needed) a per-ontology named graph. Returns the graph name.

    If ``ontology_name`` is not provided, it is looked up from the registry.
    """
    db = db or get_db()
    display_name = ontology_name or _resolve_ontology_name(ontology_id, db)
    graph_name = _safe_graph_name(display_name)

    if db.has_graph(graph_name):
        log.debug("per-ontology graph %s already exists", graph_name)
        return graph_name

    db.create_graph(
        graph_name,
        edge_definitions=PER_ONTOLOGY_EDGE_DEFINITIONS,
    )
    log.info(
        "created per-ontology graph %s for ontology '%s' (%s)",
        graph_name,
        display_name,
        ontology_id,
    )
    return graph_name


def list_ontology_graphs(
    *,
    db: StandardDatabase | None = None,
) -> list[dict]:
    """List all per-ontology named graphs."""
    db = db or get_db()
    graphs = []
    for g in db.graphs():
        name = g["name"]
        if name.startswith("ontology_"):
            ontology_id = name[len("ontology_"):]
            graphs.append({"graph_name": name, "ontology_id": ontology_id})
    return graphs


def delete_ontology_graph(
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_name: str | None = None,
) -> bool:
    """Delete a per-ontology named graph (graph definition only, not data)."""
    db = db or get_db()
    display_name = ontology_name or _resolve_ontology_name(ontology_id, db)
    graph_name = _safe_graph_name(display_name)
    if not db.has_graph(graph_name):
        return False
    db.delete_graph(graph_name, drop_collections=False)
    log.info("deleted per-ontology graph %s", graph_name)
    return True
