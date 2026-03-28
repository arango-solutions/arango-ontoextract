"""ArangoRDF bridge — wraps arango_rdf for PGT import with post-processing.

Handles OWL/TTL import into ArangoDB, post-import ontology_id tagging, and
per-ontology named graph creation.
"""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db

log = logging.getLogger(__name__)

_URI_MAP_COLLECTION = "aoe_uri_map"


def _ensure_arango_rdf():
    """Import arango_rdf lazily to avoid hard dependency at module load."""
    try:
        from arango_rdf import ArangoRDF

        return ArangoRDF
    except ImportError as exc:
        raise ImportError(
            "arango_rdf is required for OWL import. "
            "Install it with: pip install arango-rdf"
        ) from exc


def import_owl_to_graph(
    db: StandardDatabase | None = None,
    *,
    ttl_content: str,
    graph_name: str,
    ontology_id: str,
    ontology_uri_prefix: str | None = None,
) -> dict[str, Any]:
    """Import OWL/TTL content into ArangoDB via PGT transformation.

    Steps:
    1. Parse TTL into rdflib graph
    2. Import via ArangoRDF PGT
    3. Tag all created documents with ``ontology_id``
    4. Create per-ontology named graph if not exists

    Returns dict with import stats.
    """
    if db is None:
        db = get_db()

    arango_rdf_cls = _ensure_arango_rdf()

    from rdflib import Graph as RDFGraph

    rdf_graph = RDFGraph()
    rdf_graph.parse(data=ttl_content, format="turtle")

    triple_count = len(rdf_graph)
    log.info(
        "importing OWL via PGT",
        extra={
            "graph_name": graph_name,
            "ontology_id": ontology_id,
            "triple_count": triple_count,
        },
    )

    adb_rdf = arango_rdf_cls(db)

    adb_rdf.init_rdf_collections(
        bnode_collection=f"{graph_name}_bnodes",
    )

    adb_rdf.rdf_to_arangodb_by_pgt(
        name=graph_name,
        rdf_graph=rdf_graph,
        overwrite=False,
    )

    _tag_documents_with_ontology_id(
        db,
        ontology_id=ontology_id,
        ontology_uri_prefix=ontology_uri_prefix,
        graph_name=graph_name,
    )

    _ensure_named_graph(db, graph_name=graph_name)

    stats = {
        "graph_name": graph_name,
        "ontology_id": ontology_id,
        "triple_count": triple_count,
        "imported": True,
    }

    log.info("OWL import completed", extra=stats)
    return stats


def _tag_documents_with_ontology_id(
    db: StandardDatabase,
    *,
    ontology_id: str,
    ontology_uri_prefix: str | None,
    graph_name: str,
) -> int:
    """Tag all imported documents with ``ontology_id`` field.

    Queries documents that lack an ontology_id and match the graph's collections.
    """
    tagged = 0
    vertex_collections = ["ontology_classes", "ontology_properties", "ontology_constraints"]

    for col_name in vertex_collections:
        if not db.has_collection(col_name):
            continue

        bind_vars: dict[str, Any] = {"@col": col_name, "oid": ontology_id}
        filter_clause = "FILTER doc.ontology_id == null OR doc.ontology_id == ''"

        if ontology_uri_prefix:
            filter_clause += " FILTER STARTS_WITH(doc.uri, @prefix)"
            bind_vars["prefix"] = ontology_uri_prefix

        query = f"""\
FOR doc IN @@col
  {filter_clause}
  UPDATE doc WITH {{ ontology_id: @oid }} IN @@col
  RETURN 1"""

        result = list(db.aql.execute(query, bind_vars=bind_vars))
        tagged += len(result)

    log.info(
        "tagged documents with ontology_id",
        extra={"ontology_id": ontology_id, "tagged_count": tagged},
    )
    return tagged


def _ensure_named_graph(db: StandardDatabase, *, graph_name: str) -> None:
    """Create a per-ontology named graph if it doesn't exist."""
    full_name = f"ontology_{graph_name}" if not graph_name.startswith("ontology_") else graph_name

    if db.has_graph(full_name):
        return

    vertex_cols = ["ontology_classes", "ontology_properties", "ontology_constraints"]
    edge_definitions = [
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
            "edge_collection": "equivalent_class",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "related_to",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
    ]

    existing_cols = {c["name"] for c in db.collections() if not c["system"]}
    edge_defs_to_use = [
        ed for ed in edge_definitions if ed["edge_collection"] in existing_cols
    ]
    orphan_cols = [vc for vc in vertex_cols if vc in existing_cols]

    try:
        db.create_graph(
            full_name,
            edge_definitions=edge_defs_to_use,
            orphan_collections=orphan_cols,
        )
        log.info("named graph created", extra={"graph_name": full_name})
    except Exception:
        log.warning(
            "could not create named graph (may already exist)",
            extra={"graph_name": full_name},
            exc_info=True,
        )
