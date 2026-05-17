"""Unit tests for the ``ontology_imports`` Graph Visualizer assets (H.9).

These test the SHAPE of the JSON files that
``scripts/setup/install_visualizer.py`` reads. The full install path
that actually upserts the assets into ArangoDB is covered by
``tests/integration/test_visualizer_install.py``; here we lock down the
file format invariants so a bad edit fails fast without standing up
Docker.

Why this matters: the visualizer installer assumes saved queries have
matching ``content`` and ``value`` fields (see
``test_install_creates_saved_queries::test_install_creates_saved_queries``
which checks ``doc["content"] == doc["value"]``) and that canvas
actions carry a ``graphId`` pointing at the named graph. A JSON typo
here would break the install at runtime, not at lint time, so we
verify here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VIZ_DIR = PROJECT_ROOT / "docs" / "visualizer"


def _load_json(rel_path: str) -> object:
    return json.loads((VIZ_DIR / rel_path).read_text(encoding="utf-8"))


# --- Theme -----------------------------------------------------------------


class TestImportsTheme:
    def test_theme_targets_ontology_imports_graph(self) -> None:
        theme = _load_json("themes/ontology_imports_theme.json")
        assert isinstance(theme, dict)
        assert theme["graphId"] == "ontology_imports"
        assert theme["isDefault"] is True

    def test_theme_styles_registry_vertex_and_imports_edge(self) -> None:
        theme = _load_json("themes/ontology_imports_theme.json")
        assert "ontology_registry" in theme["nodeConfigMap"], (
            "imports DAG must style its only vertex collection"
        )
        assert "imports" in theme["edgeConfigMap"], (
            "imports DAG must style its only edge collection"
        )

    def test_registry_node_has_tier_and_status_rules(self) -> None:
        theme = _load_json("themes/ontology_imports_theme.json")
        rules = theme["nodeConfigMap"]["ontology_registry"]["rules"]
        rule_names = {r["name"] for r in rules}
        # Without these conditional rules, every registry node would look
        # identical -- the H.9 visualizer overview would be useless.
        assert "Released" in rule_names
        assert "Core (W3C / standard)" in rule_names
        assert "Deprecated" in rule_names


# --- Canvas actions --------------------------------------------------------


class TestImportsActions:
    def test_three_actions_for_directional_exploration(self) -> None:
        actions = _load_json("actions/ontology_imports_actions.json")
        assert isinstance(actions, list)
        keys = {a["_key"] for a in actions}
        assert keys == {
            "imp_show_direct_dependencies",
            "imp_show_direct_dependents",
            "imp_show_full_dependency_tree",
        }

    def test_all_actions_target_imports_graph(self) -> None:
        actions = _load_json("actions/ontology_imports_actions.json")
        for action in actions:
            assert action["graphId"] == "ontology_imports", (
                f"action {action['_key']} has wrong graphId={action['graphId']!r}"
            )
            assert action.get("queryText"), f"action {action['_key']} missing queryText"
            assert "@nodes" in action["queryText"], (
                f"action {action['_key']} must accept selected nodes via @nodes binding"
            )
            assert "bindVariables" in action and "nodes" in action["bindVariables"]

    def test_traversals_filter_by_temporal_expiry(self) -> None:
        actions = _load_json("actions/ontology_imports_actions.json")
        for action in actions:
            assert "9223372036854775807" in action["queryText"], (
                f"action {action['_key']} must filter by NEVER_EXPIRES "
                "(soft-deleted imports edges would otherwise appear)"
            )


# --- Saved queries ---------------------------------------------------------


class TestImportsSavedQueries:
    def test_three_queries_matching_h9_spec(self) -> None:
        """Exactly the three queries the plan calls for, no more no less."""
        queries = _load_json("queries/ontology_imports_queries.json")
        assert isinstance(queries, list)
        keys = {q["_key"] for q in queries}
        assert keys == {
            "ontology_dependencies",
            "upstream_ontologies",
            "downstream_dependents",
        }

    def test_content_and_value_match(self) -> None:
        """The installer mirrors `content` into the `_queries` collection
        as `queryText` and into `_editor_saved_queries` keeping `content`
        and `value` -- the integration suite asserts they match. Anything
        else would mean the editor and the visualizer panel showed
        different AQL for the same name, which is a UX trap."""
        queries = _load_json("queries/ontology_imports_queries.json")
        for q in queries:
            assert q["content"] == q["value"], f"query {q['_key']!r}: content != value"

    def test_root_anchored_queries_take_ontology_id_binding(self) -> None:
        queries = _load_json("queries/ontology_imports_queries.json")
        for q in queries:
            if q["_key"] in ("upstream_ontologies", "downstream_dependents"):
                assert "ontology_id" in q["bindVariables"], (
                    f"query {q['_key']!r} must expose an ontology_id binding"
                )
                assert "@ontology_id" in q["content"], (
                    f"query {q['_key']!r} must reference @ontology_id"
                )

    def test_traversals_use_named_graph(self) -> None:
        """The rooted queries traverse via ``GRAPH 'ontology_imports'``
        so they pick up any future edge definitions added to the named
        graph without a query rewrite."""
        queries = _load_json("queries/ontology_imports_queries.json")
        for q in queries:
            if q["_key"] in ("upstream_ontologies", "downstream_dependents"):
                assert "GRAPH 'ontology_imports'" in q["content"], (
                    f"query {q['_key']!r} must traverse the ontology_imports named graph"
                )

    def test_all_queries_filter_by_temporal_expiry(self) -> None:
        queries = _load_json("queries/ontology_imports_queries.json")
        for q in queries:
            assert "9223372036854775807" in q["content"], (
                f"query {q['_key']!r} must filter expired edges"
            )


# --- Installer wiring ------------------------------------------------------


@pytest.fixture(scope="module")
def install_visualizer_module():
    # The installer lives under `scripts/setup/` which isn't on the
    # default sys.path; the integration test already does this dance,
    # we mirror it so the unit test can import it without that setup.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return __import__("scripts.setup.install_visualizer", fromlist=["GRAPH_CONFIGS"])


def test_graph_configs_includes_ontology_imports(install_visualizer_module) -> None:
    """The installer's GRAPH_CONFIGS map must include the new graph.

    Without this entry ``install_all`` wouldn't apply theme / actions /
    queries for ``ontology_imports`` even though the JSON files exist.
    """
    cfgs = install_visualizer_module.GRAPH_CONFIGS
    assert "ontology_imports" in cfgs
    cfg = cfgs["ontology_imports"]
    assert cfg == {
        "theme": "ontology_imports_theme.json",
        "actions": "ontology_imports_actions.json",
        "queries": "ontology_imports_queries.json",
    }


def test_referenced_asset_files_exist(install_visualizer_module) -> None:
    """Every file in GRAPH_CONFIGS[ontology_imports] must actually exist
    on disk so install_all doesn't FileNotFoundError at runtime.
    """
    cfg = install_visualizer_module.GRAPH_CONFIGS["ontology_imports"]
    assert (VIZ_DIR / "themes" / cfg["theme"]).exists()
    assert (VIZ_DIR / "actions" / cfg["actions"]).exists()
    assert (VIZ_DIR / "queries" / cfg["queries"]).exists()
