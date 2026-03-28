"""
ArangoDB collection and graph schema initialization.

Idempotent — safe to run on every startup.
"""

from arango.database import StandardDatabase

DOCUMENT_COLLECTIONS = [
    "documents",
    "chunks",
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "extraction_runs",
    "curation_decisions",
]

EDGE_COLLECTIONS = [
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
]

GRAPHS = {
    "domain_ontology": {
        "edge_definitions": [
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
        ],
    },
}


def ensure_collections(db: StandardDatabase) -> None:
    for name in DOCUMENT_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)

    for name in EDGE_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=True)


def ensure_graphs(db: StandardDatabase) -> None:
    for graph_name, definition in GRAPHS.items():
        if not db.has_graph(graph_name):
            db.create_graph(graph_name, edge_definitions=definition["edge_definitions"])


def init_schema(db: StandardDatabase) -> None:
    ensure_collections(db)
    ensure_graphs(db)
