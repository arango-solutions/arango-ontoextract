"""MCP tools for provenance tracing and ontology export.

Two tools:
  - get_provenance: trace an entity back to its source extraction run and chunks
  - export_ontology: export an ontology as OWL Turtle or JSON-LD string
"""

from __future__ import annotations

import logging
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db
from app.db.ontology_collections import PROPERTY_VERTEX_COLLECTIONS
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get, run_aql
from app.services import export as export_svc

log = logging.getLogger(__name__)


def register_export_tools(mcp: FastMCP) -> None:
    """Register all export/provenance tools on the given MCP server instance."""

    @mcp.tool()
    def get_provenance(entity_key: str) -> dict[str, Any]:
        """Return the provenance chain for an ontology entity.

        Traces back to: the extraction run that created it, the source document,
        the source chunks, and any curator decisions made on it.

        Args:
            entity_key: The _key of the ontology class or property.
        """
        try:
            db = get_db()

            entity = _find_entity(db, entity_key)
            if not entity:
                return {"error": f"Entity '{entity_key}' not found", "entity_key": entity_key}

            ontology_id = entity.get("ontology_id", "")

            extraction_run = None
            if ontology_id.startswith("extraction_"):
                run_id = ontology_id.replace("extraction_", "")
                extraction_run = _get_extraction_run(db, run_id)

            source_document = None
            source_chunks: list[dict[str, Any]] = []
            if extraction_run:
                doc_id = extraction_run.get("doc_id")
                if doc_id:
                    source_document = _get_document_info(db, doc_id)
                    source_chunks = _get_related_chunks(db, doc_id, entity.get("label", ""))

            curation_decisions = _get_curation_decisions(db, entity_key)

            return {
                "entity_key": entity_key,
                "entity_label": entity.get("label"),
                "entity_uri": entity.get("uri"),
                "ontology_id": ontology_id,
                "extraction_run": extraction_run,
                "source_document": source_document,
                "source_chunks": source_chunks,
                "curation_decisions": curation_decisions,
                "created": entity.get("created"),
                "created_by": entity.get("created_by"),
                "version": entity.get("version"),
            }
        except Exception as exc:
            log.exception("get_provenance failed")
            return {"error": str(exc), "entity_key": entity_key}

    @mcp.tool()
    def export_ontology(
        ontology_id: str,
        format: str = "turtle",
    ) -> str:
        """Export an ontology as an OWL Turtle or JSON-LD string.

        Delegates to :func:`app.services.export.export_ontology`, the single
        source of truth for OWL/RDF graph building. That service is
        registry-URI aware and emits ``owl:imports`` and ``owl:Restriction``
        triples that this tool previously omitted, so MCP consumers now get
        the same, more complete output as the HTTP export endpoint.

        Args:
            ontology_id: The ontology identifier.
            format: Export format — "turtle" (default) or "json-ld".
        """
        fmt = format.lower().strip()
        if fmt not in ("turtle", "json-ld", "jsonld"):
            return f"Unsupported format '{format}'. Use 'turtle' or 'json-ld'."

        rdflib_format = "turtle" if fmt == "turtle" else "json-ld"
        try:
            return export_svc.export_ontology(ontology_id, fmt=rdflib_format)
        except Exception as exc:
            log.exception("export_ontology failed")
            return f"Export failed: {exc}"


def _find_entity(db: Any, key: str) -> dict[str, Any] | None:
    """Find an entity by key in class and property vertex collections."""
    for collection in ("ontology_classes", *PROPERTY_VERTEX_COLLECTIONS):
        if not db.has_collection(collection):
            continue
        results = list(
            run_aql(
                db,
                """\
FOR doc IN @@col
  FILTER doc._key == @key
  FILTER doc.expired == @never
  LIMIT 1
  RETURN doc""",
                bind_vars={"@col": collection, "key": key, "never": NEVER_EXPIRES},
            )
        )
        if results:
            return cast(dict[str, Any], results[0])
    return None


def _get_extraction_run(db: Any, run_id: str) -> dict[str, Any] | None:
    """Get extraction run summary."""
    if not db.has_collection("extraction_runs"):
        return None
    doc = doc_get(db.collection("extraction_runs"), run_id)
    if not doc:
        return None
    return {
        "run_id": run_id,
        "doc_id": doc.get("doc_id"),
        "model": doc.get("model"),
        "status": doc.get("status"),
        "started_at": doc.get("started_at"),
        "completed_at": doc.get("completed_at"),
    }


def _get_document_info(db: Any, doc_id: str) -> dict[str, Any] | None:
    """Get source document metadata."""
    if not db.has_collection("documents"):
        return None
    doc = doc_get(db.collection("documents"), doc_id)
    if not doc:
        return None
    return {
        "doc_id": doc_id,
        "filename": doc.get("filename"),
        "content_type": doc.get("content_type"),
        "uploaded_at": doc.get("uploaded_at"),
    }


def _get_related_chunks(db: Any, doc_id: str, entity_label: str) -> list[dict[str, Any]]:
    """Find chunks from the source document that mention the entity label."""
    if not db.has_collection("chunks") or not entity_label:
        return []
    try:
        return list(
            run_aql(
                db,
                """\
FOR chunk IN chunks
  FILTER chunk.doc_id == @doc_id
  FILTER CONTAINS(LOWER(chunk.text), LOWER(@label))
  LIMIT 5
  RETURN {
    chunk_index: chunk.chunk_index,
    text_preview: SUBSTRING(chunk.text, 0, 200)
  }""",
                bind_vars={"doc_id": doc_id, "label": entity_label},
            )
        )
    except Exception:
        return []


def _get_curation_decisions(db: Any, entity_key: str) -> list[dict[str, Any]]:
    """Get curation decisions related to an entity."""
    if not db.has_collection("curation_decisions"):
        return []
    try:
        return list(
            run_aql(
                db,
                """\
FOR d IN curation_decisions
  FILTER d.entity_key == @key
  SORT d.decided_at DESC
  LIMIT 10
  RETURN {
    decision: d.decision,
    decided_at: d.decided_at,
    decided_by: d.decided_by,
    notes: d.notes
  }""",
                bind_vars={"key": entity_key},
            )
        )
    except Exception:
        return []
