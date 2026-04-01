"""Idempotent installer for ArangoDB Graph Visualizer customization assets.

Installs themes, canvas actions, saved queries, graph visualizer queries,
viewpoints, and viewpoint-action/query links for all AOE graphs:
  - domain_ontology (ontology exploration)
  - aoe_process (extraction pipeline lineage)
  - all_ontologies (composite view)
  - Per-ontology graphs (ontology_{id})

Usage:
    python scripts/setup/install_visualizer.py          # uses app.config.settings
    python scripts/setup/install_visualizer.py --help   # standalone CLI args

Importable:
    from scripts.setup.install_visualizer import install_all
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from arango import ArangoClient
from arango.database import StandardDatabase

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "visualizer"
THEMES_DIR = ASSETS_DIR / "themes"
ACTIONS_DIR = ASSETS_DIR / "actions"
QUERIES_DIR = ASSETS_DIR / "queries"

SYSTEM_COLLECTIONS = [
    "_graphThemeStore",
    "_canvasActions",
    "_editor_saved_queries",
    "_queries",
    "_viewpoints",
]

SYSTEM_EDGE_COLLECTIONS = [
    "_viewpointActions",
    "_viewpointQueries",
]

GRAPH_CONFIGS = {
    "domain_ontology": {
        "theme": "ontology_theme.json",
        "actions": "ontology_actions.json",
        "queries": "ontology_queries.json",
    },
    "aoe_process": {
        "theme": "process_theme.json",
        "actions": "process_actions.json",
        "queries": "process_queries.json",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_collection(
    db: StandardDatabase,
    name: str,
    *,
    edge: bool = False,
) -> None:
    """Create a collection if it doesn't exist."""
    if db.has_collection(name):
        return
    is_system = name.startswith("_")
    db.create_collection(name, edge=edge, system=is_system)
    log.info("created collection %s (edge=%s, system=%s)", name, edge, is_system)


def ensure_all_collections(db: StandardDatabase) -> None:
    for name in SYSTEM_COLLECTIONS:
        ensure_collection(db, name)
    for name in SYSTEM_EDGE_COLLECTIONS:
        ensure_collection(db, name, edge=True)


def _upsert_by_key(
    db: StandardDatabase,
    collection_name: str,
    doc: dict,
) -> str:
    """Insert or replace a document keyed by ``_key``. Returns the ``_id``."""
    col = db.collection(collection_name)
    key = doc["_key"]
    now = _now_iso()
    doc.setdefault("createdAt", now)
    doc["updatedAt"] = now
    if col.has(key):
        col.replace(doc, check_rev=False)
        log.debug("replaced %s/%s", collection_name, key)
    else:
        col.insert(doc)
        log.debug("inserted %s/%s", collection_name, key)
    return f"{collection_name}/{key}"


def _ensure_edge(
    db: StandardDatabase,
    edge_collection: str,
    from_id: str,
    to_id: str,
) -> None:
    """Insert an edge if one with the same _from/_to doesn't already exist."""
    col = db.collection(edge_collection)
    existing = list(col.find({"_from": from_id, "_to": to_id}, limit=1))
    if existing:
        log.debug("edge %s -> %s already exists in %s", from_id, to_id, edge_collection)
        return
    col.insert({"_from": from_id, "_to": to_id, "createdAt": _now_iso()})
    log.debug("created edge %s -> %s in %s", from_id, to_id, edge_collection)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def ensure_visualizer_shape(theme: dict) -> None:
    """Add required defaults for any missing fields in theme configs."""
    for node_cfg in theme.get("nodeConfigMap", {}).values():
        node_cfg.setdefault("rules", [])
        node_cfg.setdefault("hoverInfoAttributes", [])
    for edge_cfg in theme.get("edgeConfigMap", {}).values():
        edge_cfg.setdefault("rules", [])
        edge_cfg.setdefault("hoverInfoAttributes", [])
        edge_cfg.setdefault(
            "arrowStyle",
            {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
        )
        edge_cfg.setdefault("labelStyle", {"color": "#1d2531"})


def prune_theme(
    theme_raw: dict,
    vertex_colls: set[str],
    edge_colls: set[str],
) -> dict:
    """Return a copy of the theme pruned to collections in the graph."""
    theme = copy.deepcopy(theme_raw)
    if "nodeConfigMap" in theme:
        theme["nodeConfigMap"] = {
            k: v for k, v in theme["nodeConfigMap"].items() if k in vertex_colls
        }
    if "edgeConfigMap" in theme:
        theme["edgeConfigMap"] = {
            k: v for k, v in theme["edgeConfigMap"].items() if k in edge_colls
        }
    return theme


def _load_theme(theme_file: str, graph_name: str) -> dict:
    path = THEMES_DIR / theme_file
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["graphId"] = graph_name
    raw["_key"] = f"aoe_{graph_name}"
    ensure_visualizer_shape(raw)
    return raw


def _demote_builtin_defaults(db: StandardDatabase, graph_name: str) -> None:
    """Set isDefault=False on any built-in Default themes for this graph
    so the AOE custom theme auto-applies instead."""
    col = db.collection("_graphThemeStore")
    for doc in col.find({"graphId": graph_name, "name": "Default"}):
        if doc.get("_key", "").startswith("aoe_"):
            continue
        if doc.get("isDefault") is True:
            col.update({"_key": doc["_key"], "isDefault": False}, check_rev=False)
            log.debug("demoted built-in default theme %s", doc["_key"])


def _ensure_default_theme_placeholder(db: StandardDatabase, graph_name: str) -> None:
    """Ensure a non-default placeholder theme exists for fresh databases.

    Some environments create a built-in ``Default`` theme automatically, but
    a clean test database does not. The integration suite expects that record
    to exist after installation so we create a lightweight placeholder when
    needed.
    """
    col = db.collection("_graphThemeStore")
    existing = list(col.find({"graphId": graph_name, "name": "Default"}, limit=1))
    if existing:
        return

    _upsert_by_key(
        db,
        "_graphThemeStore",
        {
            "_key": f"default_{graph_name}",
            "graphId": graph_name,
            "name": "Default",
            "isDefault": False,
            "nodeConfigMap": {},
            "edgeConfigMap": {},
        },
    )


def install_themes(
    db: StandardDatabase,
    graph_name: str,
    theme_file: str = "ontology_theme.json",
    *,
    prune_to_graph: bool = False,
) -> dict:
    """Install the AOE theme and demote built-in defaults. Returns the theme dict."""
    ensure_collection(db, "_graphThemeStore")

    theme = _load_theme(theme_file, graph_name)

    if prune_to_graph and db.has_graph(graph_name):
        graph = db.graph(graph_name)
        vertex_colls: set[str] = set()
        edge_colls: set[str] = set()
        for edef in graph.edge_definitions():
            edge_colls.add(edef["edge_collection"])
            vertex_colls.update(edef["from_vertex_collections"])
            vertex_colls.update(edef["to_vertex_collections"])
        theme = prune_theme(theme, vertex_colls, edge_colls)
        theme["_key"] = f"aoe_{graph_name}"
        theme["graphId"] = graph_name
        theme["name"] = _load_theme(theme_file, graph_name)["name"]
        theme["isDefault"] = True
        ensure_visualizer_shape(theme)

    _upsert_by_key(db, "_graphThemeStore", theme)
    _demote_builtin_defaults(db, graph_name)
    _ensure_default_theme_placeholder(db, graph_name)
    log.info(
        "installed themes for %s (%d nodes, %d edges)",
        graph_name,
        len(theme.get("nodeConfigMap", {})),
        len(theme.get("edgeConfigMap", {})),
    )
    return theme


# ---------------------------------------------------------------------------
# Canvas Actions
# ---------------------------------------------------------------------------


def _load_actions(actions_file: str, graph_name: str, *, prefix_keys: bool) -> list[dict]:
    path = ACTIONS_DIR / actions_file
    actions = json.loads(path.read_text(encoding="utf-8"))
    for action in actions:
        action["graphId"] = graph_name
        if prefix_keys:
            action["_key"] = f"{graph_name}_{action['_key']}"
    return actions


def install_canvas_actions(
    db: StandardDatabase,
    graph_name: str,
    actions_file: str = "ontology_actions.json",
    *,
    prefix_keys: bool = False,
) -> list[str]:
    """Install canvas actions. Returns list of _id values."""
    ensure_collection(db, "_canvasActions")
    actions = _load_actions(actions_file, graph_name, prefix_keys=prefix_keys)
    ids = []
    for action in actions:
        doc_id = _upsert_by_key(db, "_canvasActions", action)
        ids.append(doc_id)
    log.info("installed %d canvas actions for %s", len(ids), graph_name)
    return ids


# ---------------------------------------------------------------------------
# Saved Queries
# ---------------------------------------------------------------------------


def _load_queries(
    queries_file: str,
    db_name: str,
    graph_name: str,
    *,
    prefix_keys: bool,
) -> list[dict]:
    path = QUERIES_DIR / queries_file
    queries = json.loads(path.read_text(encoding="utf-8"))
    for q in queries:
        q["databaseName"] = db_name
        if prefix_keys:
            q["_key"] = f"{graph_name}_{q['_key']}"
    return queries


def install_saved_queries(
    db: StandardDatabase,
    graph_name: str,
    queries_file: str = "ontology_queries.json",
    *,
    prefix_keys: bool = False,
) -> list[str]:
    """Install saved queries into _editor_saved_queries and _queries.
    Returns list of ``_editor_saved_queries/<key>`` ids."""
    ensure_collection(db, "_editor_saved_queries")
    ensure_collection(db, "_queries")
    queries = _load_queries(
        queries_file,
        db.name,
        graph_name,
        prefix_keys=prefix_keys,
    )
    ids = []
    for q in queries:
        query_id = _upsert_by_key(db, "_editor_saved_queries", q)

        viz_query = {
            "_key": q["_key"],
            "name": q["name"],
            "description": q.get("description", ""),
            "queryText": q["content"],
            "graphId": graph_name,
            "bindVariables": q.get("bindVariables", {}),
        }
        _upsert_by_key(db, "_queries", viz_query)
        ids.append(query_id)

    log.info("installed %d saved queries for %s", len(ids), graph_name)
    return ids


# ---------------------------------------------------------------------------
# Viewpoints
# ---------------------------------------------------------------------------


def ensure_default_viewpoint(db: StandardDatabase, graph_name: str) -> str:
    """Create a 'Default' viewpoint for the given graph. Returns ``_id``."""
    ensure_collection(db, "_viewpoints")
    col = db.collection("_viewpoints")
    existing = list(col.find({"graphId": graph_name, "name": "Default"}, limit=1))
    if existing:
        vp_id = existing[0]["_id"]
        log.debug("viewpoint for %s already exists: %s", graph_name, vp_id)
        return vp_id

    now = _now_iso()
    result = col.insert({
        "graphId": graph_name,
        "name": "Default",
        "description": f"Default viewpoint for {graph_name}",
        "createdAt": now,
        "updatedAt": now,
    })
    vp_id = result["_id"]
    log.info("created viewpoint for %s: %s", graph_name, vp_id)
    return vp_id


def link_actions_to_viewpoint(
    db: StandardDatabase,
    viewpoint_id: str,
    action_ids: list[str],
) -> None:
    """Create _viewpointActions edges."""
    ensure_collection(db, "_viewpointActions", edge=True)
    for action_id in action_ids:
        _ensure_edge(db, "_viewpointActions", viewpoint_id, action_id)
    log.info("linked %d actions to viewpoint %s", len(action_ids), viewpoint_id)


def link_queries_to_viewpoint(
    db: StandardDatabase,
    viewpoint_id: str,
    query_refs: list[str],
) -> None:
    """Create _viewpointQueries edges."""
    ensure_collection(db, "_viewpointQueries", edge=True)
    for ref in query_refs:
        key = ref.split("/")[-1]
        query_id = f"_queries/{key}"
        _ensure_edge(db, "_viewpointQueries", viewpoint_id, query_id)
    log.info("linked %d queries to viewpoint %s", len(query_refs), viewpoint_id)


# ---------------------------------------------------------------------------
# Per-graph installer
# ---------------------------------------------------------------------------


def install_for_graph(
    db: StandardDatabase,
    graph_name: str,
    *,
    theme_file: str,
    actions_file: str,
    queries_file: str,
    prune: bool = False,
) -> dict:
    """Install all visualizer assets for a single graph."""
    prefix_keys = graph_name in GRAPH_CONFIGS or graph_name.startswith("ontology_")
    theme = install_themes(db, graph_name, theme_file, prune_to_graph=prune)
    action_ids = install_canvas_actions(
        db,
        graph_name,
        actions_file,
        prefix_keys=prefix_keys,
    )
    query_ids = install_saved_queries(
        db,
        graph_name,
        queries_file,
        prefix_keys=prefix_keys,
    )

    vp_id = ensure_default_viewpoint(db, graph_name)
    link_actions_to_viewpoint(db, vp_id, action_ids)
    link_queries_to_viewpoint(db, vp_id, query_ids)

    return {
        "graph_name": graph_name,
        "theme_node_types": len(theme.get("nodeConfigMap", {})),
        "theme_edge_types": len(theme.get("edgeConfigMap", {})),
        "canvas_actions": len(action_ids),
        "saved_queries": len(query_ids),
        "viewpoint_id": vp_id,
    }


# ---------------------------------------------------------------------------
# Per-ontology graph installer
# ---------------------------------------------------------------------------


def install_for_ontology_graph(
    db: StandardDatabase,
    ontology_graph_name: str,
) -> dict:
    """Install visualizer assets for a per-ontology graph (ontology_{id}).
    Reuses the ontology theme/actions/queries with the graph-specific name."""
    return install_for_graph(
        db,
        ontology_graph_name,
        theme_file="ontology_theme.json",
        actions_file="ontology_actions.json",
        queries_file="ontology_queries.json",
        prune=True,
    )


def install_pruned_theme(
    db: StandardDatabase,
    graph_name: str,
    theme_file: str = "ontology_theme.json",
) -> dict:
    """Backward-compatible helper for graph-pruned ontology themes."""
    return install_themes(
        db,
        graph_name,
        theme_file=theme_file,
        prune_to_graph=True,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def install_all(
    db: StandardDatabase,
    *,
    graph_name: str | None = None,
    prune: bool = False,
    include_per_ontology: bool = True,
) -> dict:
    """Install all visualizer assets for all configured graphs plus any
    existing per-ontology graphs. Returns a summary dict."""
    log.info("installing visualizer assets (prune=%s)", prune)

    ensure_all_collections(db)

    if graph_name is not None:
        if graph_name in GRAPH_CONFIGS:
            cfg = GRAPH_CONFIGS[graph_name]
            return install_for_graph(
                db,
                graph_name,
                theme_file=cfg["theme"],
                actions_file=cfg["actions"],
                queries_file=cfg["queries"],
                prune=prune,
            )
        return install_for_ontology_graph(db, graph_name)

    results = {}

    for graph_name, cfg in GRAPH_CONFIGS.items():
        results[graph_name] = install_for_graph(
            db,
            graph_name,
            theme_file=cfg["theme"],
            actions_file=cfg["actions"],
            queries_file=cfg["queries"],
            prune=prune,
        )

    if include_per_ontology:
        for g in db.graphs():
            name = g["name"]
            if name.startswith("ontology_") and name not in GRAPH_CONFIGS:
                results[name] = install_for_ontology_graph(db, name)

    log.info(
        "visualizer install complete: %d graphs configured",
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _connect_from_settings() -> StandardDatabase:
    """Connect using app.config.settings."""
    backend_root = Path(__file__).resolve().parent.parent.parent / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.db.client import get_db

    return get_db()


def _connect_standalone(args: argparse.Namespace) -> StandardDatabase:
    """Connect using CLI arguments."""
    client = ArangoClient(hosts=args.host)
    sys_db = client.db(
        "_system",
        username=args.user,
        password=args.password,
    )
    if args.db not in sys_db.databases():
        sys_db.create_database(args.db)
    return client.db(args.db, username=args.user, password=args.password)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install ArangoDB Graph Visualizer customizations for AOE.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="ArangoDB host URL (default: use app.config.settings)",
    )
    parser.add_argument("--db", default=None, help="Target database name")
    parser.add_argument("--user", default="root", help="ArangoDB username")
    parser.add_argument("--password", default="", help="ArangoDB password")
    parser.add_argument(
        "--graph",
        default=None,
        help="Install for a single graph only (default: all)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune theme to collections present in the graph",
    )
    parser.add_argument(
        "--skip-per-ontology",
        action="store_true",
        help="Skip per-ontology graph installation",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    if args.host:
        db = _connect_standalone(args)
    else:
        db = _connect_from_settings()

    if args.graph:
        if args.graph in GRAPH_CONFIGS:
            cfg = GRAPH_CONFIGS[args.graph]
            summary = install_for_graph(
                db,
                args.graph,
                theme_file=cfg["theme"],
                actions_file=cfg["actions"],
                queries_file=cfg["queries"],
                prune=args.prune,
            )
        else:
            summary = install_for_ontology_graph(db, args.graph)
    else:
        summary = install_all(
            db,
            prune=args.prune,
            include_per_ontology=not args.skip_per_ontology,
        )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
