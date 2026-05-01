"""ArangoRDF bridge — wraps arango_rdf for PGT import with post-processing.

Handles OWL/TTL import into ArangoDB, post-import ontology_id tagging,
per-ontology named graph creation, and file/URL-based import with format
detection.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from arango.database import StandardDatabase
from rdflib import OWL, RDF, RDFS, URIRef
from rdflib import Graph as RDFGraph

from app.db.client import get_db
from app.db.ontology_repo import create_class, create_edge, create_property
from app.db.registry_repo import create_registry_entry
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)

_URI_MAP_COLLECTION = "aoe_uri_map"


def _ensure_arango_rdf():
    """Import arango_rdf lazily to avoid hard dependency at module load."""
    try:
        from arango_rdf import ArangoRDF

        return ArangoRDF
    except ImportError as exc:
        raise ImportError(
            "arango_rdf is required for OWL import. Install it with: pip install arango-rdf"
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

    try:
        arango_rdf_cls = _ensure_arango_rdf()
    except ImportError:
        log.warning("arango_rdf unavailable; using rdflib fallback importer")
        _import_with_rdflib_fallback(
            db,
            rdf_graph=rdf_graph,
            ontology_id=ontology_id,
        )
    else:
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


def _find_registry_key_for_import_iri(
    db: StandardDatabase,
    imported_iri: str,
) -> str | None:
    """Resolve an ``owl:imports`` target IRI to an ``ontology_registry`` ``_key``."""
    if not db.has_collection("ontology_registry"):
        return None
    rows = list(
        run_aql(
            db,
            """
            FOR o IN ontology_registry
              FILTER o.uri != null AND o.uri != ""
              FILTER o.status == null OR o.status != "deprecated"
              LET u = o.uri
              FILTER u == @iri OR STARTS_WITH(@iri, u) OR STARTS_WITH(u, @iri)
              SORT LENGTH(u) DESC
              LIMIT 1
              RETURN o._key
            """,
            bind_vars={"iri": imported_iri},
        )
    )
    if not rows:
        return None
    key = rows[0]
    return str(key) if key is not None else None


def sync_owl_imports_edges(
    db: StandardDatabase,
    rdf_graph: RDFGraph,
    importer_registry_key: str,
) -> dict[str, Any]:
    """Wire ``owl:imports`` IRIs to ``imports`` edges between registry documents.

    Edges run ``ontology_registry/{importer}`` → ``ontology_registry/{imported}`` when the
    imported IRI matches another registry document's ``uri`` (exact or prefix). Targets not
    in the library are logged as warnings (PGT.7 / PRD imports graph).
    """
    if not db.has_collection("imports"):
        return {"created": 0, "skipped": 0, "warnings": []}

    from_id = f"ontology_registry/{importer_registry_key}"
    imported_iris: set[str] = set()
    for _subj, obj in rdf_graph.subject_objects(OWL.imports):
        o_str = str(obj)
        if o_str:
            imported_iris.add(o_str)

    warnings: list[str] = []
    created = 0
    skipped = 0

    for iri in sorted(imported_iris):
        target_key = _find_registry_key_for_import_iri(db, iri)
        if target_key is None:
            warnings.append(f"No registry entry for owl:imports target {iri!r}")
            continue
        if target_key == importer_registry_key:
            skipped += 1
            continue
        to_id = f"ontology_registry/{target_key}"
        dup = list(
            run_aql(
                db,
                """
                FOR e IN imports
                  FILTER e._from == @fr AND e._to == @to AND e.expired == @never
                  LIMIT 1
                  RETURN 1
                """,
                bind_vars={
                    "fr": from_id,
                    "to": to_id,
                    "never": NEVER_EXPIRES,
                },
            )
        )
        if dup:
            skipped += 1
            continue
        create_edge(
            db,
            edge_collection="imports",
            from_id=from_id,
            to_id=to_id,
            data={"import_iri": iri},
        )
        created += 1

    if warnings:
        log.warning(
            "owl:imports targets missing from ontology_registry",
            extra={"importer": importer_registry_key, "warnings": warnings},
        )

    return {
        "created": created,
        "skipped": skipped,
        "warnings": warnings,
    }


def _ensure_import_collections(db: StandardDatabase) -> None:
    for name, edge in (
        ("ontology_classes", False),
        ("ontology_properties", False),
        ("ontology_object_properties", False),
        ("ontology_datatype_properties", False),
        ("ontology_constraints", False),
        ("subclass_of", True),
        ("has_property", True),
        ("equivalent_class", True),
        ("related_to", True),
        ("rdfs_domain", True),
        ("rdfs_range_class", True),
    ):
        if not db.has_collection(name):
            db.create_collection(name, edge=edge)


def _label_for(graph: RDFGraph, subject: URIRef) -> str:
    label = graph.value(subject, RDFS.label)
    if label:
        return str(label)
    return subject.split("#")[-1].split("/")[-1]


def _comment_for(graph: RDFGraph, subject: URIRef) -> str:
    comment = graph.value(subject, RDFS.comment)
    return str(comment) if comment else ""


def _import_with_rdflib_fallback(
    db: StandardDatabase,
    *,
    rdf_graph: RDFGraph,
    ontology_id: str,
) -> None:
    """Minimal OWL importer used when ``arango_rdf`` is unavailable.

    Writes ``owl:ObjectProperty`` instances to ``ontology_object_properties``
    and ``owl:DatatypeProperty`` instances to ``ontology_datatype_properties``.
    Creates ``rdfs_domain`` edges (property → domain class) and
    ``rdfs_range_class`` edges (object property → range class) per ADR-006.
    """
    _ensure_import_collections(db)

    class_ids: dict[str, str] = {}

    for class_uri in sorted({str(s) for s in rdf_graph.subjects(RDF.type, OWL.Class)}):
        doc = create_class(
            db,
            ontology_id=ontology_id,
            data={
                "uri": class_uri,
                "label": _label_for(rdf_graph, URIRef(class_uri)),
                "description": _comment_for(rdf_graph, URIRef(class_uri)),
                "status": "approved",
                "tier": "domain",
                "rdf_type": "owl:Class",
            },
            created_by="import",
        )
        class_ids[class_uri] = doc["_id"]

    prop_type_map: dict[str, tuple[str, str]] = {
        "object": ("ontology_object_properties", "owl:ObjectProperty"),
        "datatype": ("ontology_datatype_properties", "owl:DatatypeProperty"),
    }

    property_ids: dict[str, str] = {}
    property_meta: list[dict[str, Any]] = []

    for rdf_type, property_kind in (
        (OWL.ObjectProperty, "object"),
        (OWL.DatatypeProperty, "datatype"),
    ):
        target_col, rdf_type_label = prop_type_map[property_kind]
        for prop_uri in sorted({str(s) for s in rdf_graph.subjects(RDF.type, rdf_type)}):
            domain = rdf_graph.value(URIRef(prop_uri), RDFS.domain)
            range_value = rdf_graph.value(URIRef(prop_uri), RDFS.range)

            prop_data: dict[str, Any] = {
                "uri": prop_uri,
                "label": _label_for(rdf_graph, URIRef(prop_uri)),
                "description": _comment_for(rdf_graph, URIRef(prop_uri)),
                "property_type": property_kind,
                "rdf_type": rdf_type_label,
                "status": "approved",
            }
            if property_kind == "datatype" and range_value:
                prop_data["range_datatype"] = str(range_value)
            if range_value:
                prop_data["range"] = str(range_value)

            doc = create_property(
                db,
                ontology_id=ontology_id,
                data=prop_data,
                created_by="import",
                collection=target_col,
            )
            property_ids[prop_uri] = doc["_id"]
            property_meta.append(
                {
                    "uri": prop_uri,
                    "kind": property_kind,
                    "domain": str(domain) if domain else None,
                    "range": str(range_value) if range_value else None,
                }
            )

    for child, parent in rdf_graph.subject_objects(RDFS.subClassOf):
        child_id = class_ids.get(str(child))
        parent_id = class_ids.get(str(parent))
        if child_id and parent_id:
            create_edge(
                db,
                edge_collection="subclass_of",
                from_id=child_id,
                to_id=parent_id,
                data={"ontology_id": ontology_id},
            )

    for meta in property_meta:
        prop_id = property_ids.get(meta["uri"])
        domain_id = class_ids.get(meta["domain"] or "")
        if prop_id and domain_id:
            create_edge(
                db,
                edge_collection="rdfs_domain",
                from_id=prop_id,
                to_id=domain_id,
                data={"ontology_id": ontology_id},
            )
        if meta["kind"] == "object" and prop_id:
            range_id = class_ids.get(meta["range"] or "")
            if range_id:
                create_edge(
                    db,
                    edge_collection="rdfs_range_class",
                    from_id=prop_id,
                    to_id=range_id,
                    data={"ontology_id": ontology_id},
                )


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
    vertex_collections = [
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_constraints",
    ]

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

        result = list(run_aql(db, query, bind_vars=bind_vars))
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

    vertex_cols = [
        "ontology_classes",
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
        "ontology_constraints",
    ]
    edge_definitions = [
        {
            "edge_collection": "subclass_of",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "rdfs_domain",
            "from_vertex_collections": [
                "ontology_object_properties",
                "ontology_datatype_properties",
            ],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "rdfs_range_class",
            "from_vertex_collections": ["ontology_object_properties"],
            "to_vertex_collections": ["ontology_classes"],
        },
        {
            "edge_collection": "equivalent_class",
            "from_vertex_collections": ["ontology_classes"],
            "to_vertex_collections": ["ontology_classes"],
        },
        # Backward compat: include legacy edges if they exist
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
    ]

    cols = cast("list[dict[str, Any]]", db.collections())
    existing_cols = {c["name"] for c in cols if not c["system"]}
    edge_defs_to_use = [ed for ed in edge_definitions if ed["edge_collection"] in existing_cols]
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


# ---------------------------------------------------------------------------
# Format detection helpers
# ---------------------------------------------------------------------------

_FORMAT_BY_EXTENSION: dict[str, str] = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".rdf": "xml",
    ".xml": "xml",
    ".owl": "xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
    ".n3": "n3",
    ".nt": "nt",
}


def _detect_format(filename: str) -> str:
    """Detect RDF serialization format from file extension."""
    suffix = PurePosixPath(filename).suffix.lower()
    fmt = _FORMAT_BY_EXTENSION.get(suffix)
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension '{suffix}'. "
            f"Supported: {', '.join(sorted(_FORMAT_BY_EXTENSION))}"
        )
    return fmt


def _human_title_from_filename(filename: str) -> str:
    stem = PurePosixPath(filename).stem
    if not stem:
        return ""
    return stem.replace("-", " ").replace("_", " ").strip().title()


def _owl_ontology_label_from_graph(g: RDFGraph) -> str | None:
    """First non-empty ``rdfs:label`` on any ``owl:Ontology`` resource, if present."""
    try:
        for _ont in g.subjects(RDF.type, OWL.Ontology):
            for label in g.objects(_ont, RDFS.label):
                s = str(label).strip()
                if s:
                    return s
    except Exception:
        log.debug("owl ontology label extraction failed", exc_info=True)
    return None


def _registry_display_name_for_file_import(
    *,
    filename: str,
    ontology_id: str,
    ontology_label: str | None,
    rdf_graph: RDFGraph,
) -> str:
    """Resolve a human-readable ontology name for the registry (matches extraction-style naming)."""
    if ontology_label and str(ontology_label).strip():
        return str(ontology_label).strip()
    from_graph = _owl_ontology_label_from_graph(rdf_graph)
    if from_graph:
        return from_graph
    titled = _human_title_from_filename(filename)
    if titled:
        return titled
    return ontology_id


# ---------------------------------------------------------------------------
# File / URL import (Week 20)
# ---------------------------------------------------------------------------


def import_from_file(
    file_content: bytes,
    filename: str,
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_label: str | None = None,
    ontology_uri_prefix: str | None = None,
) -> dict[str, Any]:
    """Import an OWL/TTL/RDF-XML/JSON-LD file into ArangoDB.

    1. Detect format from file extension
    2. Parse with rdflib to validate
    3. Import via PGT (``import_owl_to_graph``)
    4. Create an ``ontology_registry`` entry

    Returns:
        Dict with import stats and registry entry key.
    """
    if db is None:
        db = get_db()

    fmt = _detect_format(filename)
    text = file_content.decode("utf-8")

    rdf_graph = RDFGraph()
    rdf_graph.parse(data=text, format=fmt)
    triple_count = len(rdf_graph)
    if triple_count == 0:
        raise ValueError("Parsed file contains no RDF triples")

    ttl_content = rdf_graph.serialize(format="turtle")

    graph_name = ontology_id.replace("-", "_").replace(" ", "_")

    stats = import_owl_to_graph(
        db,
        ttl_content=ttl_content,
        graph_name=graph_name,
        ontology_id=ontology_id,
        ontology_uri_prefix=ontology_uri_prefix,
    )

    display_name = _registry_display_name_for_file_import(
        filename=filename,
        ontology_id=ontology_id,
        ontology_label=ontology_label,
        rdf_graph=rdf_graph,
    )

    registry_entry = create_registry_entry(
        {
            "_key": ontology_id,
            "name": display_name,
            "label": display_name,
            "description": f"Imported from {filename}",
            "tier": "local",
            "source": "file_import",
            "source_filename": filename,
            "format": fmt,
            "triple_count": triple_count,
            "graph_name": f"ontology_{graph_name}",
            "uri": ontology_uri_prefix or f"http://example.org/ontology/{ontology_id}",
        },
        db=db,
    )

    imports_sync = sync_owl_imports_edges(db, rdf_graph, ontology_id)

    log.info(
        "file import completed",
        extra={
            "ontology_id": ontology_id,
            "source_filename": filename,
            "format": fmt,
            "triple_count": triple_count,
            "registry_key": registry_entry["_key"],
            "imports_edges_created": imports_sync.get("created", 0),
        },
    )

    return {
        **stats,
        "source": "file_import",
        "filename": filename,
        "format": fmt,
        "registry_key": registry_entry["_key"],
        "imports_sync": imports_sync,
    }


def import_from_url(
    url: str,
    ontology_id: str,
    *,
    db: StandardDatabase | None = None,
    ontology_label: str | None = None,
) -> dict[str, Any]:
    """Fetch an OWL/RDF file from a URL and import it.

    Determines format from the URL path extension, downloads the content,
    and delegates to ``import_from_file``.

    Returns:
        Dict with import stats and registry entry key.
    """
    if db is None:
        db = get_db()

    filename = PurePosixPath(urlparse(url).path).name
    if not filename:
        filename = "ontology.ttl"

    log.info("downloading ontology from URL", extra={"url": url, "ontology_id": ontology_id})

    response = httpx.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()

    result = import_from_file(
        file_content=response.content,
        filename=filename,
        ontology_id=ontology_id,
        db=db,
        ontology_label=ontology_label,
    )
    result["source"] = "url_import"
    result["source_url"] = url
    return result
