"""OntologyService — staging graph management, promotion, and ontology CRUD coordination."""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.models.ontology import ExtractionResult
from app.services.arangordf_bridge import import_owl_to_graph
from app.services.owl_serializer import extraction_to_owl

log = logging.getLogger(__name__)


def create_staging_graph(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    extraction_result: ExtractionResult,
    ontology_uri: str | None = None,
) -> dict[str, Any]:
    """Create a staging graph from extraction results.

    Serializes ExtractionResult to OWL TTL, then imports via ArangoRDF bridge
    into a ``staging_{run_id}`` named graph.
    """
    if db is None:
        db = get_db()

    ttl_content = extraction_to_owl(
        extraction_result,
        ontology_uri=ontology_uri,
    )

    graph_name = f"staging_{run_id}"
    ontology_id = f"extraction_{run_id}"

    stats = import_owl_to_graph(
        db,
        ttl_content=ttl_content,
        graph_name=graph_name,
        ontology_id=ontology_id,
    )

    log.info(
        "staging graph created",
        extra={"run_id": run_id, "graph_name": graph_name, **stats},
    )

    return {
        "staging_graph_id": graph_name,
        "ontology_id": ontology_id,
        **stats,
    }


def get_staging_graph(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Retrieve staging graph contents for a given run."""
    if db is None:
        db = get_db()

    ontology_id = f"extraction_{run_id}"
    classes: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if db.has_collection("ontology_classes"):
        classes = list(
            run_aql(db,
                "FOR c IN ontology_classes FILTER c.ontology_id == @oid RETURN c",
                bind_vars={"oid": ontology_id},
            )
        )

    for prop_col in (
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
    ):
        if db.has_collection(prop_col):
            properties.extend(
                list(
                    run_aql(
                        db,
                        f"FOR p IN {prop_col} FILTER p.ontology_id == @oid RETURN p",
                        bind_vars={"oid": ontology_id},
                    )
                )
            )

    edge_collections = [
        "subclass_of",
        "has_property",
        "equivalent_class",
        "related_to",
        "rdfs_domain",
        "rdfs_range_class",
        "extracted_from",
    ]
    for edge_col in edge_collections:
        if db.has_collection(edge_col):
            col_edges = list(
                run_aql(db,
                    f"FOR e IN {edge_col} RETURN e",
                )
            )
            edges.extend(col_edges)

    return {
        "run_id": run_id,
        "ontology_id": ontology_id,
        "classes": classes,
        "properties": properties,
        "edges": edges,
    }


def promote_staging(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Promote approved staging entities to production.

    Stub for Phase 3 — will move approved entities from staging graph to
    production graph using temporal versioning.
    """
    if db is None:
        db = get_db()

    log.info("promote_staging called (Phase 3 stub)", extra={"run_id": run_id})

    return {
        "run_id": run_id,
        "promoted": 0,
        "status": "not_implemented",
        "message": "Promotion logic will be implemented in Phase 3 (curation workflow).",
    }
