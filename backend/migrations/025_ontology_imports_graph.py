"""025 — Create the ``ontology_imports`` named graph (Stream 1 H.2).

Per PRD Section 6.15 / FR-15.1, the registry-level dependency DAG between
ontologies (``A owl:imports B``) lives on the existing ``imports`` edge
collection (created in migration 003) with ``ontology_registry`` documents
as both endpoints. Until now that DAG existed only at the collection
level; this migration registers it as a named graph so:

* The ArangoDB Visualizer (FR-6.x) can render and traverse it without
  callers having to re-declare the edge definition each time.
* Saved AQL queries (Stream 1 H.9: "Ontology Dependencies", "Upstream
  Ontologies", "Downstream Dependents") can be parameterised by graph
  name rather than by collection list.
* Future GraphQL/Graph API consumers (e.g. the workspace
  ``ImportsDependencyOverlay`` from H.7) can use ``GRAPH 'ontology_imports'``
  in AQL traversals, picking up new edge collections automatically if
  the dependency model grows beyond ``imports`` alone.

Graph composition
-----------------

* Vertex collection: ``ontology_registry`` (one document per ontology)
* Edge collection:   ``imports`` (one document per live import edge)

Both endpoints are ``ontology_registry`` because imports are
ontology-to-ontology; this matches the edge shape created by
``sync_owl_imports_edges`` and ``add_ontology_import``.

Idempotency
-----------

The migration is a no-op if the graph already exists with the expected
edge definition. If the graph exists but its edge definition has
drifted (e.g. an additional edge collection was registered out of
band), we leave it alone -- ``replace_edge_definition`` is destructive
and a future migration should make any structural change explicit.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

GRAPH_NAME = "ontology_imports"

ONTOLOGY_IMPORTS_EDGE_DEFINITIONS = [
    {
        "edge_collection": "imports",
        "from_vertex_collections": ["ontology_registry"],
        "to_vertex_collections": ["ontology_registry"],
    },
]


def up(db: StandardDatabase) -> None:
    # Both halves of the edge definition must already exist; migrations
    # 001 (ontology_registry) and 003 (imports) ship the underlying
    # collections. Defensive checks keep this migration runnable on
    # partially-applied databases.
    if not db.has_collection("ontology_registry"):
        log.warning(
            "skipping %s: ontology_registry collection missing (migration 001 not applied?)",
            GRAPH_NAME,
        )
        return
    if not db.has_collection("imports"):
        log.warning(
            "skipping %s: imports edge collection missing (migration 003 not applied?)",
            GRAPH_NAME,
        )
        return

    if not db.has_graph(GRAPH_NAME):
        db.create_graph(
            GRAPH_NAME,
            edge_definitions=ONTOLOGY_IMPORTS_EDGE_DEFINITIONS,
        )
        log.info("created named graph %s", GRAPH_NAME)
    else:
        log.debug("named graph %s already exists -- skipping", GRAPH_NAME)
