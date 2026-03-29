"""010 — Create the ``aoe_process`` named graph and update ``domain_ontology``.

``aoe_process`` visualizes the full extraction pipeline:
  documents → chunks (via has_chunk)
  ontology_classes → documents (via extracted_from)
  ontology_classes → ontology_properties (via has_property)
  ontology_classes → ontology_classes (via subclass_of)
  ontology_registry → extraction_runs (via produced_by)

Also adds ``extracted_from`` and ``documents`` to ``domain_ontology``
so ontology provenance is visible in the ontology graph.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

AOE_PROCESS_EDGE_DEFINITIONS = [
    {
        "edge_collection": "has_chunk",
        "from_vertex_collections": ["documents"],
        "to_vertex_collections": ["chunks"],
    },
    {
        "edge_collection": "extracted_from",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["documents"],
    },
    {
        "edge_collection": "has_property",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_properties"],
    },
    {
        "edge_collection": "subclass_of",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
    {
        "edge_collection": "produced_by",
        "from_vertex_collections": ["ontology_registry"],
        "to_vertex_collections": ["extraction_runs"],
    },
]


def _ensure_edge_collections(db: StandardDatabase) -> None:
    for name in ("has_chunk", "produced_by"):
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            log.info("created edge collection %s", name)


def up(db: StandardDatabase) -> None:
    _ensure_edge_collections(db)

    graph_name = "aoe_process"
    if not db.has_graph(graph_name):
        db.create_graph(
            graph_name,
            edge_definitions=AOE_PROCESS_EDGE_DEFINITIONS,
        )
        log.info("created named graph %s", graph_name)
    else:
        log.debug("named graph %s already exists", graph_name)

    if db.has_graph("domain_ontology"):
        graph = db.graph("domain_ontology")
        existing_edge_colls = {
            edef["edge_collection"] for edef in graph.edge_definitions()
        }
        if "extracted_from" not in existing_edge_colls:
            graph.create_edge_definition(
                edge_collection="extracted_from",
                from_vertex_collections=["ontology_classes"],
                to_vertex_collections=["documents"],
            )
            log.info("added extracted_from edge to domain_ontology graph")
