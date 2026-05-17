"""Unit tests for migration 025 (ontology_imports named graph -- Stream 1 H.2).

The real graph-creation path is covered by the integration test
``test_ontology_imports_named_graph`` in ``tests/integration/test_migrations.py``
which runs against a fresh ArangoDB. These unit tests cover the defensive
code paths that do *not* require a live database:

* the migration skips when ``ontology_registry`` is missing
* the migration skips when ``imports`` is missing
* the migration is a no-op when the graph already exists
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def mod025():
    return importlib.import_module("migrations.025_ontology_imports_graph")


def test_constants_match_named_graph_contract(mod025) -> None:
    """The exported edge definition must match the graph wiring spec.

    The visualizer queries (H.9) and the imports-graph endpoint (H.3)
    both depend on ``ontology_imports`` being declared as exactly one
    edge definition over ``ontology_registry`` <-> ``ontology_registry``
    via the ``imports`` edge collection. Drift here would silently
    break those callers.
    """
    assert mod025.GRAPH_NAME == "ontology_imports"
    assert len(mod025.ONTOLOGY_IMPORTS_EDGE_DEFINITIONS) == 1
    ed = mod025.ONTOLOGY_IMPORTS_EDGE_DEFINITIONS[0]
    assert ed["edge_collection"] == "imports"
    assert ed["from_vertex_collections"] == ["ontology_registry"]
    assert ed["to_vertex_collections"] == ["ontology_registry"]


def test_skips_when_ontology_registry_missing(mod025) -> None:
    db = MagicMock()
    db.has_collection.side_effect = lambda name: False  # registry missing
    db.has_graph.return_value = False

    mod025.up(db)

    db.create_graph.assert_not_called()


def test_skips_when_imports_collection_missing(mod025) -> None:
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name != "imports"
    db.has_graph.return_value = False

    mod025.up(db)

    db.create_graph.assert_not_called()


def test_creates_graph_when_collections_present_and_graph_missing(mod025) -> None:
    db = MagicMock()
    db.has_collection.return_value = True
    db.has_graph.return_value = False

    mod025.up(db)

    db.create_graph.assert_called_once_with(
        "ontology_imports",
        edge_definitions=mod025.ONTOLOGY_IMPORTS_EDGE_DEFINITIONS,
    )


def test_is_idempotent_when_graph_already_exists(mod025) -> None:
    db = MagicMock()
    db.has_collection.return_value = True
    db.has_graph.return_value = True

    mod025.up(db)

    db.create_graph.assert_not_called()
