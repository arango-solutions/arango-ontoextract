"""MCP tools for provenance tracing and ontology export.

Two tools:
  - get_provenance: trace an entity back to its source extraction run and chunks
  - export_ontology: export an ontology as OWL Turtle or JSON-LD string
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.db.client import get_db
from app.db.utils import doc_get, run_aql

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize

_PROPERTY_VERTEX_COLLECTIONS = (
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
)


def _load_export_property_vertices(db: Any, ontology_id: str) -> list[dict[str, Any]]:
    """Load current property vertices from legacy + PGT collections (ADR-006)."""
    rows: list[dict[str, Any]] = []
    for col in _PROPERTY_VERTEX_COLLECTIONS:
        if not db.has_collection(col):
            continue
        part = list(
            run_aql(
                db,
                f"FOR p IN {col} FILTER p.ontology_id == @oid AND p.expired == @never RETURN p",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )
        rows.extend(part)
    return rows


def _object_property_range_uris(db: Any, ontology_id: str) -> dict[str, str]:
    """Map property document _id -> range class URI from rdfs_range_class edges."""
    if not db.has_collection("rdfs_range_class"):
        return {}
    out: dict[str, str] = {}
    for row in run_aql(
        db,
        """\
FOR e IN rdfs_range_class
  FILTER e.ontology_id == @oid AND e.expired == @never
  LET t = DOCUMENT(e._to)
  FILTER t != null
  RETURN {from_id: e._from, uri: t.uri}""",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ):
        fid = row.get("from_id")
        if fid:
            out[str(fid)] = str(row.get("uri") or "")
    return out


def _rdfs_domain_edges(db: Any, ontology_id: str) -> list[dict[str, str]]:
    if not db.has_collection("rdfs_domain"):
        return []
    return list(
        run_aql(
            db,
            """\
FOR e IN rdfs_domain
  FILTER e.ontology_id == @oid AND e.expired == @never
  RETURN {from_id: e._from, to_id: e._to}""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _property_vertex_kind(prop: dict[str, Any]) -> str:
    """Infer owl:ObjectProperty vs DatatypeProperty from source collection / fields."""
    explicit = prop.get("property_type")
    if explicit in ("object", "datatype"):
        return explicit
    pid = prop.get("_id", "")
    if isinstance(pid, str) and "ontology_object_properties" in pid:
        return "object"
    if isinstance(pid, str) and "ontology_datatype_properties" in pid:
        return "datatype"
    return "datatype"


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

        Queries all current classes and properties for the ontology, builds
        an rdflib Graph, and serializes to the requested format.

        Args:
            ontology_id: The ontology identifier.
            format: Export format — "turtle" (default) or "json-ld".
        """
        try:
            from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef

            db = get_db()

            fmt = format.lower().strip()
            if fmt not in ("turtle", "json-ld", "jsonld"):
                return f"Unsupported format '{format}'. Use 'turtle' or 'json-ld'."

            rdflib_format = "turtle" if fmt == "turtle" else "json-ld"

            from rdflib.namespace import XSD

            classes: list[dict[str, Any]] = []
            if db.has_collection("ontology_classes"):
                classes = list(
                    run_aql(
                        db,
                        """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN cls""",
                        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
                    )
                )

            properties = _load_export_property_vertices(db, ontology_id)
            range_by_prop = _object_property_range_uris(db, ontology_id)
            domain_edges = _rdfs_domain_edges(db, ontology_id)

            if not classes and not properties:
                return f"No entities found for ontology '{ontology_id}'."

            ns = Namespace("http://example.org/ontology#")
            g = Graph()
            g.bind("owl", OWL)
            g.bind("rdfs", RDFS)
            g.bind("rdf", RDF)
            g.bind("xsd", XSD)
            g.bind("ont", ns)

            ont_node = URIRef(f"http://example.org/ontology/{ontology_id}")
            g.add((ont_node, RDF.type, OWL.Ontology))
            g.add((ont_node, RDFS.label, Literal(ontology_id)))

            subclass_edges: list[dict[str, Any]] = []
            if db.has_collection("subclass_of"):
                subclass_edges = list(
                    run_aql(
                        db,
                        """\
FOR e IN subclass_of
  FILTER e.expired == @never
  RETURN {from_id: e._from, to_id: e._to}""",
                        bind_vars={"never": NEVER_EXPIRES},
                    )
                )

            class_id_to_uri = {}
            for cls in classes:
                cls_uri = URIRef(cls.get("uri", f"http://example.org/ontology#{cls['_key']}"))
                class_id_to_uri[cls["_id"]] = cls_uri
                g.add((cls_uri, RDF.type, OWL.Class))
                if cls.get("label"):
                    g.add((cls_uri, RDFS.label, Literal(cls["label"])))
                if cls.get("description"):
                    g.add((cls_uri, RDFS.comment, Literal(cls["description"])))

            for edge in subclass_edges:
                child_uri = class_id_to_uri.get(edge["from_id"])
                parent_uri = class_id_to_uri.get(edge["to_id"])
                if child_uri and parent_uri:
                    g.add((child_uri, RDFS.subClassOf, parent_uri))

            prop_id_to_uri: dict[str, URIRef] = {}
            for prop in properties:
                prop_uri = URIRef(prop.get("uri", f"http://example.org/ontology#{prop['_key']}"))
                prop_id_to_uri[prop["_id"]] = prop_uri
                kind = _property_vertex_kind(prop)
                if kind == "object":
                    g.add((prop_uri, RDF.type, OWL.ObjectProperty))
                else:
                    g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
                if prop.get("label"):
                    g.add((prop_uri, RDFS.label, Literal(prop["label"])))
                if prop.get("description"):
                    g.add((prop_uri, RDFS.comment, Literal(prop["description"])))
                range_uri = range_by_prop.get(prop["_id"], "").strip()
                if kind == "object" and range_uri:
                    g.add((prop_uri, RDFS.range, URIRef(range_uri)))
                elif kind == "datatype":
                    dt = (prop.get("range_datatype") or prop.get("range") or "xsd:string").strip()
                    if dt.startswith("http://") or dt.startswith("https://"):
                        g.add((prop_uri, RDFS.range, URIRef(dt)))
                    elif dt.lower().startswith("xsd:"):
                        local = dt.split(":", 1)[-1]
                        xsd_term = getattr(XSD, local, XSD.string)
                        g.add((prop_uri, RDFS.range, xsd_term))
                    else:
                        g.add((prop_uri, RDFS.range, XSD.string))

            for edge in domain_edges:
                pu = prop_id_to_uri.get(edge["from_id"])
                du = class_id_to_uri.get(edge["to_id"])
                if pu and du:
                    g.add((pu, RDFS.domain, du))

            serialized: str = g.serialize(format=rdflib_format)
            log.info(
                "ontology exported",
                extra={
                    "ontology_id": ontology_id,
                    "format": rdflib_format,
                    "classes": len(classes),
                    "properties": len(properties),
                    "triples": len(g),
                },
            )
            return serialized
        except Exception as exc:
            log.exception("export_ontology failed")
            return f"Export failed: {exc}"


def _find_entity(db: Any, key: str) -> dict[str, Any] | None:
    """Find an entity by key in class and property vertex collections."""
    for collection in (
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
    ):
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
            return results[0]
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
