"""Integration tests for the ArangoDB Graph Visualizer install script.

Requires a running ArangoDB instance. Uses the ``test_db`` fixture from conftest
which auto-creates an ephemeral database and drops it after the session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from arango.database import StandardDatabase

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT.parent))

from scripts.setup.install_visualizer import (  # noqa: E402
    ensure_all_collections,
    ensure_default_viewpoint,
    install_all,
    install_canvas_actions,
    install_pruned_theme,
    install_saved_queries,
    install_themes,
    prune_theme,
)

TEST_GRAPH = "test_ontology_graph"


@pytest.fixture(autouse=True)
def _create_test_graph(test_db: StandardDatabase):
    """Create a minimal named graph so graph-aware operations work."""
    vertex_colls = ["ontology_classes", "ontology_properties"]
    edge_colls = ["subclass_of", "has_property"]

    for name in vertex_colls:
        if not test_db.has_collection(name):
            test_db.create_collection(name)
    for name in edge_colls:
        if not test_db.has_collection(name):
            test_db.create_collection(name, edge=True)

    if not test_db.has_graph(TEST_GRAPH):
        test_db.create_graph(
            TEST_GRAPH,
            edge_definitions=[
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
            ],
        )


class TestInstallCreatesTheme:
    def test_install_creates_theme(self, test_db: StandardDatabase):
        install_themes(test_db, TEST_GRAPH)

        col = test_db.collection("_graphThemeStore")
        themes = list(col.find({"graphId": TEST_GRAPH}))
        assert len(themes) >= 2, "Expected at least ontology theme + default theme"

        ontology_theme = next(
            (t for t in themes if t["name"] != "Default"),
            None,
        )
        assert ontology_theme is not None
        assert ontology_theme["isDefault"] is True
        assert "nodeConfigMap" in ontology_theme
        assert "edgeConfigMap" in ontology_theme
        assert len(ontology_theme["nodeConfigMap"]) >= 3
        assert len(ontology_theme["edgeConfigMap"]) >= 3

        default_theme = next(
            (t for t in themes if t["name"] == "Default"),
            None,
        )
        assert default_theme is not None
        assert default_theme["isDefault"] is False


class TestInstallCreatesCanvasActions:
    def test_install_creates_canvas_actions(self, test_db: StandardDatabase):
        ensure_all_collections(test_db)
        action_ids = install_canvas_actions(test_db, TEST_GRAPH)

        assert len(action_ids) >= 7, f"Expected 7+ actions, got {len(action_ids)}"

        col = test_db.collection("_canvasActions")
        for action_id in action_ids:
            key = action_id.split("/")[1]
            doc = col.get(key)
            assert doc is not None, f"Missing action {key}"
            assert "queryText" in doc, f"Action {key} missing queryText"
            assert "name" in doc, f"Action {key} missing name"
            assert doc["graphId"] == TEST_GRAPH

    def test_temporal_filtering_in_actions(self, test_db: StandardDatabase):
        """Canvas actions that traverse edges must filter by expired == NEVER_EXPIRES."""
        ensure_all_collections(test_db)
        install_canvas_actions(test_db, TEST_GRAPH)

        col = test_db.collection("_canvasActions")
        temporal_actions = [
            "show_subclasses",
            "show_superclasses",
            "show_properties",
            "show_full_hierarchy",
            "show_related_classes",
            "show_cross_tier_links",
            "full_neighborhood",
        ]
        for key in temporal_actions:
            doc = col.get(key)
            assert doc is not None, f"Missing action {key}"
            assert "9223372036854775807" in doc["queryText"], (
                f"Action {key} does not filter by NEVER_EXPIRES"
            )


class TestInstallCreatesSavedQueries:
    def test_install_creates_saved_queries(self, test_db: StandardDatabase):
        ensure_all_collections(test_db)
        query_ids = install_saved_queries(test_db, TEST_GRAPH)

        assert len(query_ids) >= 10, f"Expected 10+ queries, got {len(query_ids)}"

        editor_col = test_db.collection("_editor_saved_queries")
        for qid in query_ids:
            key = qid.split("/")[1]
            doc = editor_col.get(key)
            assert doc is not None, f"Missing query {key}"
            assert doc.get("content"), f"Query {key} missing content"
            assert doc.get("value"), f"Query {key} missing value"
            assert doc["content"] == doc["value"], f"Query {key} content != value"

    def test_queries_also_in_visualizer_collection(self, test_db: StandardDatabase):
        """Saved queries must also be in _queries for the Graph Visualizer panel."""
        ensure_all_collections(test_db)
        install_saved_queries(test_db, TEST_GRAPH)

        viz_col = test_db.collection("_queries")
        count = viz_col.count()
        assert count >= 10, f"Expected 10+ docs in _queries, got {count}"

        doc = viz_col.get("class_hierarchy_full")
        assert doc is not None
        assert doc.get("queryText")
        assert doc["graphId"] == TEST_GRAPH


class TestInstallIsIdempotent:
    def test_install_is_idempotent(self, test_db: StandardDatabase):
        summary1 = install_all(test_db, graph_name=TEST_GRAPH)
        summary2 = install_all(test_db, graph_name=TEST_GRAPH)

        assert summary1["canvas_actions"] == summary2["canvas_actions"]
        assert summary1["saved_queries"] == summary2["saved_queries"]
        assert summary1["theme_node_types"] == summary2["theme_node_types"]

        theme_count = test_db.collection("_graphThemeStore").count()
        action_count = test_db.collection("_canvasActions").count()
        query_count = test_db.collection("_editor_saved_queries").count()

        install_all(test_db, graph_name=TEST_GRAPH)

        assert test_db.collection("_graphThemeStore").count() == theme_count
        assert test_db.collection("_canvasActions").count() == action_count
        assert test_db.collection("_editor_saved_queries").count() == query_count


class TestPruneTheme:
    def test_prune_theme_removes_unused_types(self, test_db: StandardDatabase):
        ensure_all_collections(test_db)
        pruned = install_pruned_theme(test_db, TEST_GRAPH)

        node_keys = set(pruned["nodeConfigMap"].keys())
        edge_keys = set(pruned["edgeConfigMap"].keys())

        assert "ontology_classes" in node_keys
        assert "ontology_properties" in node_keys
        assert "subclass_of" in edge_keys
        assert "has_property" in edge_keys

        assert "documents" not in node_keys, "documents is not in test graph"
        assert "chunks" not in node_keys, "chunks is not in test graph"
        assert "extracted_from" not in edge_keys, "extracted_from is not in test graph"

    def test_prune_theme_pure_function(self):
        """prune_theme() as a pure function removes non-matching collections."""
        raw = {
            "nodeConfigMap": {
                "ontology_classes": {"background": {}},
                "documents": {"background": {}},
                "chunks": {"background": {}},
            },
            "edgeConfigMap": {
                "subclass_of": {"lineStyle": {}},
                "extracted_from": {"lineStyle": {}},
            },
        }
        result = prune_theme(
            raw,
            vertex_colls={"ontology_classes"},
            edge_colls={"subclass_of"},
        )
        assert set(result["nodeConfigMap"].keys()) == {"ontology_classes"}
        assert set(result["edgeConfigMap"].keys()) == {"subclass_of"}
        assert "documents" in raw["nodeConfigMap"], "original not mutated"


class TestViewpointCreation:
    def test_ensure_default_viewpoint(self, test_db: StandardDatabase):
        ensure_all_collections(test_db)
        vp_id = ensure_default_viewpoint(test_db, TEST_GRAPH)
        assert vp_id.startswith("_viewpoints/")

        vp_id_2 = ensure_default_viewpoint(test_db, TEST_GRAPH)
        assert vp_id == vp_id_2, "Should return existing viewpoint, not create a new one"

    def test_viewpoint_action_links(self, test_db: StandardDatabase):
        summary = install_all(test_db, graph_name=TEST_GRAPH)
        vp_id = summary["viewpoint_id"]

        edge_col = test_db.collection("_viewpointActions")
        edges = list(edge_col.find({"_from": vp_id}))
        assert len(edges) >= 7, f"Expected 7+ viewpoint-action edges, got {len(edges)}"

    def test_viewpoint_query_links(self, test_db: StandardDatabase):
        summary = install_all(test_db, graph_name=TEST_GRAPH)
        vp_id = summary["viewpoint_id"]

        edge_col = test_db.collection("_viewpointQueries")
        edges = list(edge_col.find({"_from": vp_id}))
        assert len(edges) >= 10, f"Expected 10+ viewpoint-query edges, got {len(edges)}"
