"""Unit tests for ``app.services.ontology_imports_graph`` (Stream 1 H.3).

The service produces the data structure the workspace
``ImportsDependencyOverlay`` (H.7) and the catalog browser preview
(H.6) render directly. The shape is part of the public API contract;
these tests pin it.

DB calls are mocked at the AQL dispatcher level, mirroring the H.4
test pattern (see ``test_ontology_dependency.py``).
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.ontology_imports_graph import (
    DEFAULT_MAX_DEPTH,
    build_imports_dag,
)

NEVER = sys.maxsize


def _make_db(
    *,
    aql_responses: dict[str, list[Any]] | None = None,
    missing_collections: tuple[str, ...] = (),
    registry_entries: dict[str, dict[str, Any]] | None = None,
) -> MagicMock:
    db = MagicMock()

    def _has_collection(name: str) -> bool:
        return name not in missing_collections

    db.has_collection.side_effect = _has_collection

    registry_entries = registry_entries or {}
    registry_collection = MagicMock()

    def _registry_get(key: str) -> dict[str, Any] | None:
        return registry_entries.get(key)

    registry_collection.get.side_effect = _registry_get
    db.collection.return_value = registry_collection

    aql_responses = aql_responses or {}

    def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        for needle, rows in aql_responses.items():
            if needle in query:
                return iter(list(rows))
        return iter([])

    db.aql.execute = MagicMock(side_effect=_execute)
    return db


# --- Empty / missing collection paths --------------------------------------


class TestMissingCollections:
    def test_returns_empty_when_imports_collection_missing(self) -> None:
        db = _make_db(missing_collections=("imports",))

        result = build_imports_dag(db)

        assert result == {
            "nodes": [],
            "edges": [],
            "root": None,
            "direction": None,
            "truncated": False,
        }

    def test_returns_empty_when_registry_missing(self) -> None:
        db = _make_db(missing_collections=("ontology_registry",))

        result = build_imports_dag(db, root="anything")

        # No traversal attempted because the substrate is gone.
        assert result["nodes"] == []
        assert result["edges"] == []


# --- Full-DAG mode ---------------------------------------------------------


class TestFullDag:
    def test_full_dag_returns_every_live_edge(self) -> None:
        db = _make_db(
            aql_responses={
                "FOR e IN imports": [
                    {
                        "edge_key": "e1",
                        "from_key": "A",
                        "to_key": "B",
                        "import_iri": "http://example.org/B",
                        "created": 100.0,
                        "from_name": "Alpha",
                        "from_status": "active",
                        "from_tier": "domain",
                        "to_name": "Bravo",
                        "to_status": "approved",
                        "to_tier": "domain",
                    },
                    {
                        "edge_key": "e2",
                        "from_key": "B",
                        "to_key": "C",
                        "import_iri": "http://example.org/C",
                        "created": 101.0,
                        "from_name": "Bravo",
                        "from_status": "approved",
                        "from_tier": "domain",
                        "to_name": "Charlie",
                        "to_status": "released",
                        "to_tier": "core",
                    },
                ],
            },
        )

        result = build_imports_dag(db)

        # Three distinct nodes.
        keys = {n["_key"] for n in result["nodes"]}
        assert keys == {"A", "B", "C"}

        # Two edges, preserved end-to-end.
        edges_by_key = {e["edge_key"]: e for e in result["edges"]}
        assert edges_by_key["e1"]["from_key"] == "A"
        assert edges_by_key["e1"]["to_key"] == "B"
        assert edges_by_key["e1"]["import_iri"] == "http://example.org/B"
        assert edges_by_key["e2"]["from_key"] == "B"

        assert result["root"] is None
        assert result["direction"] is None
        assert result["truncated"] is False

    def test_full_dag_sorts_nodes_by_name_then_key(self) -> None:
        db = _make_db(
            aql_responses={
                "FOR e IN imports": [
                    {
                        "edge_key": "e1",
                        "from_key": "Z",
                        "to_key": "Y",
                        "from_name": "alpha",  # lowercase
                        "to_name": "beta",
                        "from_status": None,
                        "to_status": None,
                        "from_tier": None,
                        "to_tier": None,
                        "created": 0,
                        "import_iri": None,
                    },
                ],
            },
        )

        result = build_imports_dag(db)
        names = [n["name"] for n in result["nodes"]]
        # Stable order means the overlay does not flicker on refresh.
        assert names == ["alpha", "beta"]

    def test_full_dag_handles_node_with_missing_name(self) -> None:
        db = _make_db(
            aql_responses={
                "FOR e IN imports": [
                    {
                        "edge_key": "e1",
                        "from_key": "lonely",
                        "to_key": "target",
                        "from_name": None,
                        "to_name": "Target",
                        "from_status": None,
                        "to_status": "active",
                        "from_tier": None,
                        "to_tier": None,
                        "created": 0,
                        "import_iri": None,
                    },
                ],
            },
        )

        result = build_imports_dag(db)
        by_key = {n["_key"]: n for n in result["nodes"]}
        # Falls back to _key when name is missing -- not a crash.
        assert by_key["lonely"]["name"] == "lonely"
        assert by_key["target"]["name"] == "Target"


# --- Rooted mode -----------------------------------------------------------


class TestRootedDag:
    def test_raises_when_root_ontology_missing(self) -> None:
        db = _make_db(registry_entries={})

        with pytest.raises(ValueError, match="ont-missing"):
            build_imports_dag(db, root="ont-missing")

    def test_rooted_dag_isolated_root_returns_single_node(self) -> None:
        db = _make_db(
            registry_entries={
                "root": {
                    "_key": "root",
                    "name": "Root Ontology",
                    "status": "active",
                    "tier": "domain",
                }
            },
            # No traversal rows -- root has no imports either direction.
            aql_responses={},
        )

        result = build_imports_dag(db, root="root")

        assert len(result["nodes"]) == 1
        node = result["nodes"][0]
        assert node["_key"] == "root"
        assert node["name"] == "Root Ontology"
        assert node["status"] == "active"
        assert node["tier"] == "domain"
        assert result["edges"] == []
        assert result["root"] == "root"
        assert result["direction"] == "both"

    @pytest.mark.parametrize(
        "direction,expected_arango",
        [
            ("outbound", "OUTBOUND"),
            ("inbound", "INBOUND"),
            ("both", "ANY"),
        ],
    )
    def test_rooted_dag_uses_correct_traversal_direction(
        self, direction: str, expected_arango: str
    ) -> None:
        captured: list[str] = []

        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
        )

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append(query)
            return iter([])

        db.aql.execute = MagicMock(side_effect=_execute)

        build_imports_dag(db, root="root", direction=direction)  # type: ignore[arg-type]

        assert any(expected_arango in q for q in captured), (
            f"expected {expected_arango} traversal, queries were: {captured}"
        )

    def test_rooted_traversal_uses_supported_unique_edges_option(self) -> None:
        """Regression: ArangoDB rejects ``uniqueEdges: 'global'`` with
        ``[HTTP 400][ERR 10] ... Use 'path' or 'none' instead``. Every
        rooted dependency-graph query 500'd until this was switched to a
        supported value. Mocked AQL can't surface the 400, so we pin the
        emitted option string instead (the Python layer already de-dupes
        edges, so ``'path'`` is sufficient)."""
        captured: list[str] = []

        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
        )

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append(query)
            return iter([])

        db.aql.execute = MagicMock(side_effect=_execute)

        build_imports_dag(db, root="root", direction="both")

        traversal = next((q for q in captured if "@target imports" in q), None)
        assert traversal is not None, f"no traversal query issued, got: {captured}"
        assert "uniqueEdges: 'global'" not in traversal
        assert "uniqueEdges: 'path'" in traversal

    def test_rooted_dag_dedupes_edges(self) -> None:
        # Edge "e1" appears twice in the traversal (different paths can
        # revisit the same edge with ANY direction); the result must
        # contain it once.
        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
            aql_responses={
                "INBOUND @target imports": [
                    {
                        "edge_key": "e1",
                        "from_key": "dep",
                        "to_key": "root",
                        "from_name": "Dep",
                        "from_status": "active",
                        "from_tier": "domain",
                        "to_name": "Root",
                        "to_status": "active",
                        "to_tier": "domain",
                        "visited_key": "dep",
                        "visited_name": "Dep",
                        "visited_status": "active",
                        "visited_tier": "domain",
                        "import_iri": None,
                        "created": 0,
                    },
                    {  # duplicate -- same edge_key, different traversal path
                        "edge_key": "e1",
                        "from_key": "dep",
                        "to_key": "root",
                        "from_name": "Dep",
                        "from_status": "active",
                        "from_tier": "domain",
                        "to_name": "Root",
                        "to_status": "active",
                        "to_tier": "domain",
                        "visited_key": "dep",
                        "visited_name": "Dep",
                        "visited_status": "active",
                        "visited_tier": "domain",
                        "import_iri": None,
                        "created": 0,
                    },
                ],
            },
        )

        result = build_imports_dag(db, root="root", direction="inbound")

        assert len(result["edges"]) == 1
        assert result["edges"][0]["edge_key"] == "e1"


# --- Depth clamping --------------------------------------------------------


class TestDepthClamping:
    def test_depth_below_one_is_clamped_to_one(self) -> None:
        captured: list[dict[str, Any]] = []

        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
        )

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append(dict(bind_vars or {}))
            return iter([])

        db.aql.execute = MagicMock(side_effect=_execute)

        build_imports_dag(db, root="root", max_depth=0)

        assert any(c.get("max_depth") == 1 for c in captured)

    def test_depth_above_fifty_is_clamped_to_fifty(self) -> None:
        captured: list[dict[str, Any]] = []

        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
        )

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append(dict(bind_vars or {}))
            return iter([])

        db.aql.execute = MagicMock(side_effect=_execute)

        build_imports_dag(db, root="root", max_depth=10_000)

        assert any(c.get("max_depth") == 50 for c in captured)

    def test_default_depth_is_used_when_not_specified(self) -> None:
        captured: list[dict[str, Any]] = []

        db = _make_db(
            registry_entries={
                "root": {"_key": "root", "name": "Root", "status": "active", "tier": "domain"}
            },
        )

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            captured.append(dict(bind_vars or {}))
            return iter([])

        db.aql.execute = MagicMock(side_effect=_execute)

        build_imports_dag(db, root="root")

        assert any(c.get("max_depth") == DEFAULT_MAX_DEPTH for c in captured)
