"""Schema extraction from external ArangoDB databases.

Wraps ``arango-schema-mapper`` (``arangodb-schema-analyzer``) to introspect a live
ArangoDB instance, extract a conceptual schema, convert it to OWL, and import
into AOE via the standard import pipeline.

If ``arango-schema-mapper`` is not installed, a stub implementation provides
a minimal deterministic schema based on collection introspection.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.db.client import get_db

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SchemaExtractionConfig(BaseModel):
    """Connection and options for schema extraction from an external ArangoDB."""

    target_host: str = Field(..., description="ArangoDB host URL (e.g. http://host:8530)")
    target_db: str = Field(..., description="Database name to introspect")
    target_user: str = Field(default="root", description="ArangoDB username")
    target_password: str = Field(default="", description="ArangoDB password")
    use_llm_inference: bool = Field(
        default=False,
        description="Use LLM for semantic entity naming and relationship labeling",
    )
    ontology_id: str | None = Field(
        default=None,
        description="Ontology ID for the imported result; auto-generated if omitted",
    )
    ontology_label: str | None = Field(
        default=None,
        description="Human-readable label for the extracted ontology",
    )


# ---------------------------------------------------------------------------
# Run tracking
# ---------------------------------------------------------------------------


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class _ExtractionRun:
    run_id: str
    config: SchemaExtractionConfig
    status: ExtractionStatus = ExtractionStatus.PENDING
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


_runs: dict[str, _ExtractionRun] = {}


# ---------------------------------------------------------------------------
# arango-schema-mapper integration (optional dependency)
# ---------------------------------------------------------------------------


def _try_import_schema_mapper():
    """Attempt to import arango-schema-mapper components.

    Returns a tuple of (snapshot_fn, owl_export_fn) or None if unavailable.
    """
    try:
        from arangodb_schema_analyzer.schema_analyzer.owl_export import (
            export_conceptual_model_as_owl_turtle,
        )
        from arangodb_schema_analyzer.schema_analyzer.snapshot import (
            snapshot_physical_schema,
        )

        return snapshot_physical_schema, export_conceptual_model_as_owl_turtle
    except ImportError:
        log.warning(
            "arango-schema-mapper not installed; "
            "schema extraction will use stub implementation"
        )
        return None


def _stub_extract_schema(config: SchemaExtractionConfig) -> str:
    """Minimal deterministic schema extraction without arango-schema-mapper.

    Connects to the target ArangoDB, lists collections and edges,
    and produces a basic OWL Turtle representation.
    """
    from arango import ArangoClient
    from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef

    client = ArangoClient(hosts=config.target_host)
    connect_kwargs: dict[str, Any] = {"username": config.target_user}
    if config.target_password:
        connect_kwargs["password"] = config.target_password
    target_db = client.db(config.target_db, **connect_kwargs)

    ns_str = f"http://aoe.example.org/schema/{config.target_db}#"
    ns = Namespace(ns_str)
    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("schema", ns)

    ont_uri = URIRef(ns_str.rstrip("#"))
    g.add((ont_uri, RDF.type, OWL.Ontology))
    g.add((ont_uri, RDFS.label, Literal(f"Schema of {config.target_db}")))

    collections = target_db.collections()
    for col_info in collections:
        if col_info["system"]:
            continue
        col_name = col_info["name"]
        col_uri = ns[col_name]

        if col_info.get("type") == 3:
            g.add((col_uri, RDF.type, OWL.ObjectProperty))
            g.add((col_uri, RDFS.label, Literal(col_name)))
            g.add((col_uri, RDFS.comment, Literal(f"Edge collection: {col_name}")))
        else:
            g.add((col_uri, RDF.type, OWL.Class))
            g.add((col_uri, RDFS.label, Literal(col_name)))
            g.add((col_uri, RDFS.comment, Literal(f"Document collection: {col_name}")))

    client.close()

    ttl = g.serialize(format="turtle")
    log.info(
        "stub schema extraction complete",
        extra={"target_db": config.target_db, "triples": len(g)},
    )
    return ttl


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_schema(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Extract schema from an external ArangoDB and import as an ontology.

    Creates a run, connects to the target DB, extracts schema, converts to OWL,
    and imports via the standard ArangoRDF pipeline.

    Returns:
        Dict with ``run_id``, status, and import stats.
    """
    run_id = uuid.uuid4().hex[:12]
    ontology_id = config.ontology_id or f"schema_{config.target_db}_{run_id}"
    run = _ExtractionRun(run_id=run_id, config=config)
    _runs[run_id] = run

    run.status = ExtractionStatus.RUNNING
    run.started_at = time.time()

    try:
        mapper = _try_import_schema_mapper()
        if mapper is not None:
            snapshot_fn, owl_export_fn = mapper
            snapshot = snapshot_fn(
                host=config.target_host,
                database=config.target_db,
                username=config.target_user,
                password=config.target_password,
            )
            ttl_content = owl_export_fn(snapshot)
        else:
            ttl_content = _stub_extract_schema(config)

        from app.services.arangordf_bridge import import_from_file

        db = get_db()
        import_result = import_from_file(
            file_content=ttl_content.encode("utf-8"),
            filename=f"{config.target_db}_schema.ttl",
            ontology_id=ontology_id,
            db=db,
            ontology_label=config.ontology_label or f"Schema: {config.target_db}",
        )

        run.status = ExtractionStatus.COMPLETED
        run.completed_at = time.time()
        run.result = import_result

        log.info(
            "schema extraction completed",
            extra={
                "run_id": run_id,
                "ontology_id": ontology_id,
                "target_db": config.target_db,
            },
        )

        return {
            "run_id": run_id,
            "status": run.status.value,
            "ontology_id": ontology_id,
            "import_stats": import_result,
        }

    except Exception as exc:
        run.status = ExtractionStatus.FAILED
        run.completed_at = time.time()
        run.error = str(exc)
        log.exception(
            "schema extraction failed",
            extra={"run_id": run_id, "target_db": config.target_db},
        )
        raise


def get_extraction_status(run_id: str) -> dict[str, Any]:
    """Get the status of an async schema extraction run.

    Returns:
        Dict with run_id, status, timing, and result (if completed).

    Raises:
        ValueError: If the run_id is not found.
    """
    run = _runs.get(run_id)
    if run is None:
        raise ValueError(f"Schema extraction run '{run_id}' not found")

    result: dict[str, Any] = {
        "run_id": run.run_id,
        "status": run.status.value,
        "target_db": run.config.target_db,
        "target_host": run.config.target_host,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }

    if run.status == ExtractionStatus.COMPLETED:
        result["import_stats"] = run.result
    if run.error:
        result["error"] = run.error

    return result
