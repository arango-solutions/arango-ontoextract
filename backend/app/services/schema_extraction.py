"""Schema extraction from external ArangoDB databases (graph schema → ontology).

Uses ``schema_analyzer`` (``arangodb-schema-analyzer``) to snapshot a live ArangoDB
database, infer a conceptual model (+ mapping), export OWL Turtle, and import into
AOE via the standard pipeline.

This path is **ontology extraction from graph schema** (collections, edges, type
discriminators) — distinct from the document → chunk → LangGraph pipeline.

If ``schema_analyzer`` is not installed, a minimal stub lists collections and emits
basic OWL without semantic inference.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services.arangordf_bridge import import_from_file

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
    verify_tls: bool = Field(
        default=True,
        description="Verify TLS certificates when using HTTPS (python-arango verify_override).",
    )
    extraction_source: Literal["arango_graph_schema"] = Field(
        default="arango_graph_schema",
        description=(
            "Reverse-engineer from live graph schema; document-based extraction uses other APIs."
        ),
    )
    sample_limit_per_collection: int = Field(
        default=5,
        ge=0,
        description="Documents/edges to sample per collection for schema_analyzer snapshot.",
    )
    use_llm_inference: bool = Field(
        default=False,
        description="Use LLM for semantic enrichment (requires provider SDK + API key in env).",
    )
    llm_provider: str | None = Field(
        default=None,
        description="When use_llm_inference: provider id, e.g. openai, anthropic, openrouter.",
    )
    llm_model: str | None = Field(
        default=None,
        description="Optional model name; default is provider default in schema_analyzer.",
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
# schema_analyzer integration (optional dependency)
# ---------------------------------------------------------------------------


def _try_import_schema_mapper():
    """Return (AgenticSchemaAnalyzer, export_owl, fingerprint_fn, snapshot_fn) or None."""
    try:
        from schema_analyzer import AgenticSchemaAnalyzer
        from schema_analyzer.owl_export import export_conceptual_model_as_owl_turtle
        from schema_analyzer.snapshot import fingerprint_physical_schema, snapshot_physical_schema

        return (
            AgenticSchemaAnalyzer,
            export_conceptual_model_as_owl_turtle,
            fingerprint_physical_schema,
            snapshot_physical_schema,
        )
    except ImportError:
        log.warning(
            "schema_analyzer (arangodb-schema-analyzer) not installed; "
            "schema extraction will use stub implementation"
        )
        return None


def _run_schema_mapper_extract(
    config: SchemaExtractionConfig,
    mapper: tuple[Any, ...],
) -> tuple[str, dict[str, Any]]:
    analyzer_cls, export_owl, fingerprint_fn, snapshot_fn = mapper
    from arango import ArangoClient

    client = ArangoClient(hosts=config.target_host, verify_override=config.verify_tls)
    try:
        db = client.db(
            config.target_db,
            username=config.target_user,
            password=config.target_password,
        )
        snap = snapshot_fn(
            db,
            sample_limit_per_collection=config.sample_limit_per_collection,
            include_samples_in_snapshot=False,
        )
        phys_fp = fingerprint_fn(snap, include_samples=False)

        if config.use_llm_inference and config.llm_provider:
            analyzer = analyzer_cls(llm_provider=config.llm_provider, model=config.llm_model)
        elif config.use_llm_inference:
            analyzer = analyzer_cls(llm_provider="openai", model=config.llm_model)
        else:
            analyzer = analyzer_cls(llm_provider=None, api_key=None)

        analysis = analyzer.analyze_physical_schema(
            db,
            sample_limit_per_collection=config.sample_limit_per_collection,
            include_samples_in_snapshot=False,
            _snapshot=snap,
        )
        ttl = export_owl(analysis)
        meta = analysis.metadata.model_dump(by_alias=True)
        provenance: dict[str, Any] = {
            "physical_schema_fingerprint": phys_fp,
            "extraction_source": config.extraction_source,
            "schema_analyzer_metadata": meta,
        }
        return ttl, provenance
    finally:
        client.close()


def _stub_extract_schema(config: SchemaExtractionConfig) -> str:
    """Minimal deterministic schema extraction without schema_analyzer.

    Connects to the target ArangoDB, lists collections and edges,
    and produces a basic OWL Turtle representation.
    """
    from arango import ArangoClient
    from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef

    client = ArangoClient(hosts=config.target_host, verify_override=config.verify_tls)
    try:
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

        collections = cast("list[dict[str, Any]]", target_db.collections())
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

        ttl = g.serialize(format="turtle")
        log.info(
            "stub schema extraction complete",
            extra={"target_db": config.target_db, "triples": len(g)},
        )
        return ttl
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_schema(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Extract schema from an external ArangoDB and import as an ontology.

    Creates a run, connects to the target DB, extracts schema, converts to OWL,
    and imports via the standard ArangoRDF pipeline.

    Returns:
        Dict with ``run_id``, status, import stats, and optional ``provenance``.
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
            ttl_content, provenance = _run_schema_mapper_extract(config, mapper)
        else:
            ttl_content = _stub_extract_schema(config)
            provenance = {"mode": "stub", "extraction_source": config.extraction_source}

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
                "extraction_source": config.extraction_source,
            },
        )

        return {
            "run_id": run_id,
            "status": run.status.value,
            "ontology_id": ontology_id,
            "import_stats": import_result,
            "provenance": provenance,
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
        "extraction_source": run.config.extraction_source,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }

    if run.status == ExtractionStatus.COMPLETED:
        result["import_stats"] = run.result
    if run.error:
        result["error"] = run.error

    return result
