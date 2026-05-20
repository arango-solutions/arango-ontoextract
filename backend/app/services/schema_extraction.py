"""Schema extraction from external ArangoDB databases (graph schema → ontology).

Two paths, picked automatically:

1. **Direct (built-in, default)** — connect to the target ArangoDB, walk its
   named graphs + loose collections, and emit OWL/Turtle directly:
     * Document collection           → ``owl:Class``
     * Edge collection (in a graph)  → ``owl:ObjectProperty`` with
       ``rdfs:domain`` / ``rdfs:range`` resolved from the graph's edge
       definition (``from`` / ``to`` vertex collections).
     * Loose edge collection         → ``owl:ObjectProperty`` without
       domain / range (no graph context to resolve them).
     * Sampled scalar fields         → ``owl:DatatypeProperty`` with
       ``rdfs:domain`` set to the collection's class and ``rdfs:range``
       inferred from the sampled value's XSD type.
     * Selected existing ontologies  → ``owl:imports`` triples on the
       generated ontology resource (PR 1 S.10 — wires to AOE's
       ``imports`` edges via the standard post-import sync).
     * Per-class provenance          → after the OWL is imported, every
       generated class is stamped with ``source_db`` + ``source_collection``
       so curators can trace back to the originating ArangoDB collection.

2. **schema_analyzer-driven (optional enhancement)** — when the optional
   ``arangodb-schema-analyzer`` library is installed, ``_run_schema_mapper_extract``
   delegates extraction + OWL export to it. This path is preserved for
   backward compatibility but is **no longer the primary mode** — the
   library was person-record-focused historically and the direct path
   now provides richer ontology-class semantics (named-graph awareness,
   provenance, auto-imports).

This module is **graph-schema extraction**, distinct from the
document → chunk → LangGraph pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
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
    # Stream 5 PR 1 S.7 + S.8: named-graph-aware direct extraction. When
    # ``graph_names`` is None we walk *every* named graph plus loose
    # collections; when set, only the listed graphs are extracted (loose
    # collections still emit as classless objects unless ``include_loose``
    # is also False).
    graph_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of named graphs to extract. When None, all named graphs are walked. "
            "Loose collections (not in any graph) are included by default; set "
            "``include_loose=False`` to skip them."
        ),
    )
    include_loose: bool = Field(
        default=True,
        description=(
            "When False, loose collections (not in any named graph) are skipped. "
            "Has no effect on the schema_analyzer path."
        ),
    )
    # Stream 5 PR 1 S.8: scalar field sampling. The direct path samples
    # ``field_sample_limit`` documents per collection, infers an XSD
    # type from the value, and emits an ``owl:DatatypeProperty``. Set
    # ``sample_fields=False`` for a pure topology-only extraction.
    sample_fields: bool = Field(
        default=True,
        description="When False, do not sample documents for datatype properties.",
    )
    field_sample_limit: int = Field(
        default=10,
        ge=0,
        le=1000,
        description="Documents to sample per collection when inferring field XSD types.",
    )
    # Stream 5 PR 1 S.10: auto-imports. Each entry is the ``ontology_id``
    # (registry ``_key``) of an existing AOE ontology to import. The
    # generated TTL embeds ``owl:imports <ontology_uri>`` triples and the
    # standard ``sync_owl_imports_edges`` pass wires the actual edges
    # post-import.
    imports: list[str] = Field(
        default_factory=list,
        description=(
            "List of existing AOE ontology IDs to import. Each becomes an "
            "``owl:imports`` triple on the generated ontology resource; the standard "
            "post-import sync wires the ``imports`` edges to the registry."
        ),
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


_SchemaAnalyzerComponents = tuple[
    Any,
    Callable[..., Any],
    Callable[..., Any],
    Callable[..., Any],
]


# ---------------------------------------------------------------------------
# schema_analyzer integration (optional dependency)
# ---------------------------------------------------------------------------


def _try_import_schema_mapper() -> _SchemaAnalyzerComponents | None:
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
    mapper: _SchemaAnalyzerComponents,
) -> tuple[str, dict[str, Any]]:
    analyzer_cls, export_owl, fingerprint_fn, snapshot_fn = mapper
    from arango.client import ArangoClient

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


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Named-graph discovery (S.6)
# ---------------------------------------------------------------------------


def _connect_target(config: SchemaExtractionConfig) -> tuple[Any, Any]:
    """Open a python-arango client + db handle for the target instance.

    Returns ``(client, db)``. The caller is responsible for calling
    ``client.close()`` -- usually via a try/finally. Kept private because
    the connection lifecycle is interleaved with extraction state.
    """
    from arango.client import ArangoClient

    client = ArangoClient(hosts=config.target_host, verify_override=config.verify_tls)
    connect_kwargs: dict[str, Any] = {"username": config.target_user}
    if config.target_password:
        connect_kwargs["password"] = config.target_password
    db = client.db(config.target_db, **connect_kwargs)
    return client, db


def list_named_graphs(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Discover named graphs + loose collections on the target ArangoDB.

    Returns the shape the schema-extraction UI binds to (Stream 5 S.11):

    ::

        {
          "target_host": "http://host:8529",
          "target_db": "social",
          "graphs": [
            {
              "name": "social_graph",
              "edge_definitions": [
                {"edge_collection": "follows",
                 "from_vertex_collections": ["users"],
                 "to_vertex_collections": ["users"]}
              ],
              "vertex_collections": ["users", "posts"],
              "orphan_collections": []
            },
            ...
          ],
          "loose_collections": [
            {"name": "logs", "type": "document", "count": 12345}
          ]
        }

    "Loose" = collection that is not part of any named graph. They are
    surfaced separately so the UI can show "extract this graph, plus
    these standalone collections" -- a strict-graph-only fetch would
    hide e.g. an audit log collection the user actually wants in the
    ontology.

    Raises whatever the underlying python-arango call raises (network,
    auth) -- API layer maps these to 4xx/5xx.
    """
    client, db = _connect_target(config)
    try:
        # ``db.graphs()`` returns a list[dict] like
        #   [{"name": "...", "edge_definitions": [...], "orphan_collections": [...]}, ...]
        # The edge-definition shape uses the same `from_vertex_collections`
        # / `to_vertex_collections` keys we already use elsewhere.
        graphs_raw = cast("list[dict[str, Any]]", db.graphs())
        graphs: list[dict[str, Any]] = []
        in_graph: set[str] = set()
        for g in graphs_raw:
            edge_defs = list(g.get("edge_definitions") or [])
            vertex_cols: set[str] = set()
            for ed in edge_defs:
                vertex_cols.update(ed.get("from_vertex_collections") or [])
                vertex_cols.update(ed.get("to_vertex_collections") or [])
                edge_col = ed.get("edge_collection")
                if edge_col:
                    in_graph.add(edge_col)
            orphans = list(g.get("orphan_collections") or [])
            vertex_cols.update(orphans)
            in_graph.update(vertex_cols)
            graphs.append(
                {
                    "name": g.get("name"),
                    "edge_definitions": edge_defs,
                    "vertex_collections": sorted(vertex_cols),
                    "orphan_collections": sorted(orphans),
                }
            )

        # Anything not covered by a named graph is "loose". Type 2 = document,
        # type 3 = edge. We surface count too because the UI uses it to dim
        # collections that are likely test/log scratch (count == 0 or very
        # large) so the curator can choose to skip them.
        all_cols = cast("list[dict[str, Any]]", db.collections())
        loose: list[dict[str, Any]] = []
        for c in all_cols:
            if c.get("system"):
                continue
            name = c["name"]
            if name in in_graph:
                continue
            try:
                count_val = db.collection(name).count()
            except Exception:
                # A count() failure (eg permissions on a single collection)
                # should not abort discovery. Surface as None so the UI can
                # show "unknown" rather than crash the page.
                count_val = None
            loose.append(
                {
                    "name": name,
                    "type": "edge" if c.get("type") == 3 else "document",
                    "count": count_val,
                }
            )
        loose.sort(key=lambda x: x["name"])

        return {
            "target_host": config.target_host,
            "target_db": config.target_db,
            "graphs": graphs,
            "loose_collections": loose,
        }
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Direct extraction (S.7 + S.8) with provenance + auto-imports
# ---------------------------------------------------------------------------


# Order matters: bool is a subclass of int in Python, so check it first.
def _infer_xsd_type(value: Any) -> str | None:
    """Map a sampled Python value to an XSD type IRI.

    Returns ``None`` for nulls, lists, dicts, or anything we can't
    confidently classify. Callers should skip emitting a datatype
    property when the inference is None (silent uncertainty is better
    than a wrong-typed ontology assertion).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "http://www.w3.org/2001/XMLSchema#boolean"
    if isinstance(value, int):
        return "http://www.w3.org/2001/XMLSchema#integer"
    if isinstance(value, float):
        return "http://www.w3.org/2001/XMLSchema#decimal"
    if isinstance(value, str):
        # Heuristic: an ISO-8601 date/datetime string maps to xsd:date
        # (no time component) or xsd:dateTime (has a "T" separator).
        # Anything else stays a string. We deliberately do NOT call
        # dateutil/parser here -- a permissive parser misclassifies
        # things like "1.0" or "Jan" as dates. Strict ISO 8601 only.
        #
        # CRITICAL ORDER: on Python 3.11+, ``datetime.fromisoformat``
        # ALSO accepts a bare date string ("2026-05-19") and returns
        # midnight. We don't want that -- a bare date is xsd:date,
        # not xsd:dateTime. So we check for the "T" separator first
        # and only attempt the dateTime parse when one is present.
        if "T" in value:
            try:
                datetime.fromisoformat(value)
                return "http://www.w3.org/2001/XMLSchema#dateTime"
            except ValueError:
                pass
        try:
            date.fromisoformat(value)
            return "http://www.w3.org/2001/XMLSchema#date"
        except ValueError:
            pass
        return "http://www.w3.org/2001/XMLSchema#string"
    # Lists / dicts: too ambiguous for a single XSD type. A future PR can
    # emit rdf:List for arrays of scalars and recurse for nested objects.
    return None


def _sample_collection_fields(
    db: Any,
    collection: str,
    sample_limit: int,
) -> dict[str, str]:
    """Sample ``sample_limit`` documents and infer ``{field: xsd_type}``.

    Reserved meta-fields (``_key``, ``_id``, ``_rev``, ``_from``, ``_to``)
    are skipped -- they are ArangoDB plumbing, not user data, and an
    ontology that asserts ``owl:DatatypeProperty :_key`` would be
    misleading.

    When multiple sampled values yield different inferred types for the
    same field (eg one doc has ``count: 3``, another has ``count: "n/a"``)
    we fall back to ``xsd:string`` -- the safest superset.
    """
    if sample_limit <= 0:
        return {}

    # AQL is cheaper + bypasses the python-arango cursor batching quirks
    # that show up with very small LIMITs on a server-side sample. The
    # ``KEEP`` strips meta-fields server-side instead of post-filtering
    # in Python.
    docs = list(
        run_aql(
            db,
            "FOR doc IN @@col LIMIT @lim RETURN UNSET(doc, '_key', '_id', '_rev', '_from', '_to')",
            bind_vars={"@col": collection, "lim": sample_limit},
        )
    )

    field_types: dict[str, str] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            xsd = _infer_xsd_type(v)
            if xsd is None:
                continue
            prior = field_types.get(k)
            if prior is None:
                field_types[k] = xsd
            elif prior != xsd:
                # Mixed types -> fall back to string. This is conservative
                # but truthful: the curator will see "this field has
                # heterogeneous types" and can refine in the UI.
                field_types[k] = "http://www.w3.org/2001/XMLSchema#string"
    return field_types


def _direct_extract_schema(
    config: SchemaExtractionConfig,
    db: Any | None = None,
) -> tuple[str, dict[str, str]]:
    """Named-graph-aware direct extraction without ``schema_analyzer``.

    Returns ``(ttl_content, uri_to_collection)`` -- the second value is
    the URI → source collection map used downstream to stamp per-class
    provenance (S.4). Kept as a pair so the caller does not have to
    re-parse the TTL to recover the mapping.

    When ``db`` is provided (tests), uses it directly; otherwise opens
    + closes its own connection via :func:`_connect_target`.
    """
    from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

    own_connection = db is None
    client = None
    if own_connection:
        client, db = _connect_target(config)
    # After this point ``db`` is guaranteed non-None, but mypy cannot
    # narrow ``Any | None`` across the conditional assignment. The
    # assert is purely a type-narrowing hint -- the runtime check is
    # also a useful belt-and-braces in case a future caller passes
    # ``None`` and skips the connect branch by accident.
    assert db is not None

    try:
        ns_str = f"http://aoe.example.org/schema/{config.target_db}#"
        ns = Namespace(ns_str)
        aoe_ns = Namespace("http://aoe.example.org/vocab#")
        g = Graph()
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)
        g.bind("rdf", RDF)
        g.bind("xsd", XSD)
        g.bind("schema", ns)
        g.bind("aoe", aoe_ns)

        # Ontology resource + auto-imports (S.10). Each `imports` entry is
        # an existing AOE ontology_id; we expand it to the standard AOE
        # ontology URI scheme so `sync_owl_imports_edges` can resolve it
        # against the registry post-import.
        ont_uri = URIRef(ns_str.rstrip("#"))
        g.add((ont_uri, RDF.type, OWL.Ontology))
        g.add((ont_uri, RDFS.label, Literal(f"Schema of {config.target_db}")))
        for imported_id in config.imports:
            imported_uri = URIRef(f"http://example.org/ontology/{imported_id}")
            g.add((ont_uri, OWL.imports, imported_uri))

        # We re-walk the topology inline (rather than calling
        # list_named_graphs) because that function opens its own
        # connection -- here we already hold one via _connect_target.
        # The walk logic mirrors list_named_graphs so the UI preview
        # and the actual extraction agree on what they will produce.
        graphs_raw = cast("list[dict[str, Any]]", db.graphs())
        all_cols = cast("list[dict[str, Any]]", db.collections())
        col_types: dict[str, int] = {c["name"]: c.get("type", 2) for c in all_cols}

        # Filter graphs if config.graph_names was set.
        if config.graph_names is not None:
            wanted = set(config.graph_names)
            graphs_to_walk = [g_def for g_def in graphs_raw if g_def.get("name") in wanted]
        else:
            graphs_to_walk = list(graphs_raw)

        in_graph_cols: set[str] = set()
        in_graph_edges: set[str] = set()
        uri_to_collection: dict[str, str] = {}

        def _class_for(col: str) -> URIRef:
            uri = ns[col]
            uri_to_collection[str(uri)] = col
            if (uri, RDF.type, OWL.Class) not in g:
                g.add((uri, RDF.type, OWL.Class))
                g.add((uri, RDFS.label, Literal(col)))
                g.add((uri, RDFS.comment, Literal(f"Document collection: {col}")))
                # Provenance annotations (S.4) -- redundant with the
                # post-import stamping (which is the source of truth on
                # the AOE side), but embedding them in the TTL means
                # exported / re-imported ontologies keep provenance.
                g.add((uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((uri, aoe_ns.sourceCollection, Literal(col)))
            return uri

        # Walk each (selected) named graph.
        for g_def in graphs_to_walk:
            for ed in g_def.get("edge_definitions") or []:
                edge_col = ed.get("edge_collection")
                if not edge_col:
                    continue
                in_graph_edges.add(edge_col)
                from_cols = list(ed.get("from_vertex_collections") or [])
                to_cols = list(ed.get("to_vertex_collections") or [])
                for c in from_cols + to_cols:
                    in_graph_cols.add(c)
                    _class_for(c)

                obj_uri = ns[edge_col]
                uri_to_collection[str(obj_uri)] = edge_col
                g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                g.add((obj_uri, RDFS.label, Literal(edge_col)))
                g.add(
                    (
                        obj_uri,
                        RDFS.comment,
                        Literal(f"Edge collection from graph '{g_def.get('name')}': {edge_col}"),
                    )
                )
                # Multi-from / multi-to edge definitions: emit one
                # rdfs:domain / rdfs:range triple per vertex collection.
                # Owl semantics treat multiple rdfs:domain as the
                # intersection in some readings, but the more common
                # interpretation in tooling is the union, which is what
                # the user expects from a graph schema.
                for fc in from_cols:
                    g.add((obj_uri, RDFS.domain, _class_for(fc)))
                for tc in to_cols:
                    g.add((obj_uri, RDFS.range, _class_for(tc)))
                g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((obj_uri, aoe_ns.sourceCollection, Literal(edge_col)))

            for orphan in g_def.get("orphan_collections") or []:
                in_graph_cols.add(orphan)
                _class_for(orphan)

        # Loose collections (not in any walked graph). Document collections
        # become classes; edge collections become object properties with no
        # domain/range (we don't have one to assert).
        if config.include_loose:
            for c in all_cols:
                if c.get("system"):
                    continue
                name = c["name"]
                if name in in_graph_cols or name in in_graph_edges:
                    continue
                if col_types.get(name) == 3:
                    obj_uri = ns[name]
                    uri_to_collection[str(obj_uri)] = name
                    g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                    g.add((obj_uri, RDFS.label, Literal(name)))
                    g.add(
                        (
                            obj_uri,
                            RDFS.comment,
                            Literal(f"Loose edge collection (no graph context): {name}"),
                        )
                    )
                    g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                    g.add((obj_uri, aoe_ns.sourceCollection, Literal(name)))
                else:
                    _class_for(name)

        # Datatype properties from sampled fields (S.8). One pass per
        # document collection that ended up emitted as a class.
        if config.sample_fields:
            class_uris = list(g.subjects(RDF.type, OWL.Class))
            for cls_uri in class_uris:
                col_name = uri_to_collection.get(str(cls_uri))
                if not col_name:
                    continue
                if col_types.get(col_name) != 2:
                    continue
                try:
                    fields = _sample_collection_fields(db, col_name, config.field_sample_limit)
                except Exception:
                    log.warning(
                        "field sampling failed; skipping datatype properties",
                        extra={"collection": col_name},
                        exc_info=True,
                    )
                    continue
                for fname, xsd_iri in fields.items():
                    # Field URI: scope to the source collection so two
                    # collections with a `name` field do not collide on a
                    # single :name property. The local name becomes
                    # `<Collection>.<field>` which round-trips cleanly
                    # through rdflib's Turtle serializer.
                    prop_uri = ns[f"{col_name}.{fname}"]
                    g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
                    g.add((prop_uri, RDFS.label, Literal(fname)))
                    g.add((prop_uri, RDFS.domain, cls_uri))
                    g.add((prop_uri, RDFS.range, URIRef(xsd_iri)))
                    g.add((prop_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                    g.add((prop_uri, aoe_ns.sourceCollection, Literal(col_name)))
                    g.add((prop_uri, aoe_ns.sourceField, Literal(fname)))

        ttl = g.serialize(format="turtle")
        log.info(
            "direct schema extraction complete",
            extra={
                "target_db": config.target_db,
                "triples": len(g),
                "graphs_walked": len(graphs_to_walk),
                "classes": sum(1 for _ in g.subjects(RDF.type, OWL.Class)),
                "object_properties": sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)),
                "datatype_properties": sum(1 for _ in g.subjects(RDF.type, OWL.DatatypeProperty)),
            },
        )
        return ttl, uri_to_collection
    finally:
        if own_connection and client is not None:
            client.close()


def _stub_extract_schema(config: SchemaExtractionConfig) -> str:
    """Back-compat alias retained for callers/tests that don't need the
    URI → collection map. Equivalent to ``_direct_extract_schema(config)[0]``.

    Internally the new path is named-graph-aware; the function name is
    kept so existing imports + tests continue to work unchanged.
    """
    ttl, _ = _direct_extract_schema(config)
    return ttl


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Per-class provenance stamping (S.4)
# ---------------------------------------------------------------------------


def _stamp_per_class_provenance(
    db: Any,
    *,
    ontology_id: str,
    source_db: str,
    source_host: str,
    uri_to_collection: dict[str, str],
) -> int:
    """Stamp ``source_db`` / ``source_collection`` / ``source_host`` on every
    class created by this import.

    The stamping is **best-effort**: any class created by this import
    (matched by ``ontology_id``) that has a URI in ``uri_to_collection``
    gets the provenance fields. Classes without a URI in the map (e.g.
    from imported ontologies pulled in transitively) are left alone.

    Returns the number of classes stamped. Failures are logged but
    swallowed -- a provenance bug must never break the extraction write
    path.
    """
    if not db.has_collection("ontology_classes"):
        return 0

    stamped = 0
    try:
        # One bulk AQL pass so we avoid the N+1 pattern of per-class UPDATE.
        # The ``uri_to_collection`` map is materialised as bind data so the
        # server can look up each match without round-tripping.
        result = list(
            run_aql(
                db,
                """
                FOR cls IN ontology_classes
                  FILTER cls.ontology_id == @oid
                  FILTER cls.expired == @never
                  LET sc = @uri_map[cls.uri]
                  FILTER sc != null
                  UPDATE cls WITH {
                    source_db: @sdb,
                    source_collection: sc,
                    source_host: @shost
                  } IN ontology_classes
                  RETURN 1
                """,
                bind_vars={
                    "oid": ontology_id,
                    "uri_map": uri_to_collection,
                    "sdb": source_db,
                    "shost": source_host,
                    "never": NEVER_EXPIRES,
                },
            )
        )
        stamped = len(result)
        log.info(
            "stamped per-class provenance",
            extra={
                "ontology_id": ontology_id,
                "source_db": source_db,
                "stamped_count": stamped,
            },
        )
    except Exception:
        log.warning(
            "per-class provenance stamping failed; classes will lack source metadata",
            extra={"ontology_id": ontology_id, "source_db": source_db},
            exc_info=True,
        )
    return stamped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_schema(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Extract schema from an external ArangoDB and import as an ontology.

    Pipeline:

    1. Create a run record (in-memory, lost on process restart -- OK for
       MVP; an async refactor will move this to ``schema_extraction_runs``
       or similar).
    2. Connect to the target DB.
    3. Extract OWL/TTL:
         - If ``schema_analyzer`` is installed → use its analyzer.
         - Else → direct named-graph-aware extraction (default path
           since PR 1; covers S.7 + S.8 + S.10).
    4. Import via the standard AOE pipeline (``import_from_file``).
       The ``owl:imports`` triples embedded in step 3 are wired to AOE
       ``imports`` edges by ``sync_owl_imports_edges``.
    5. Post-import: stamp per-class provenance (``source_db``,
       ``source_collection``, ``source_host``) from the URI → collection
       map built in step 3.
    6. Return the run summary.

    Returns:
        Dict with ``run_id``, status, import stats, ``provenance``
        (run-level), and ``provenance_stamped`` (per-class count).
    """
    run_id = uuid.uuid4().hex[:12]
    ontology_id = config.ontology_id or f"schema_{config.target_db}_{run_id}"
    run = _ExtractionRun(run_id=run_id, config=config)
    _runs[run_id] = run

    run.status = ExtractionStatus.RUNNING
    run.started_at = time.time()

    try:
        mapper = _try_import_schema_mapper()
        uri_to_collection: dict[str, str] = {}
        if mapper is not None:
            ttl_content, provenance = _run_schema_mapper_extract(config, mapper)
            # schema_analyzer doesn't currently surface a URI → collection
            # map, so per-class provenance stamping is a no-op on this path.
            # When the analyzer is bypassed (the default), the direct path
            # below populates the map.
        else:
            ttl_content, uri_to_collection = _direct_extract_schema(config)
            provenance = {
                "mode": "direct",
                "extraction_source": config.extraction_source,
                "graphs_filter": list(config.graph_names) if config.graph_names else None,
                "include_loose": config.include_loose,
                "auto_imports": list(config.imports),
                "field_sampling": config.sample_fields,
            }

        db = get_db()
        import_result = import_from_file(
            file_content=ttl_content.encode("utf-8"),
            filename=f"{config.target_db}_schema.ttl",
            ontology_id=ontology_id,
            db=db,
            ontology_label=config.ontology_label or f"Schema: {config.target_db}",
        )

        # S.4: per-class provenance stamping. Only fires for the direct
        # path (uri_to_collection populated). Failures are swallowed so a
        # provenance bug cannot break the extraction write path.
        provenance_stamped = 0
        if uri_to_collection:
            provenance_stamped = _stamp_per_class_provenance(
                db,
                ontology_id=ontology_id,
                source_db=config.target_db,
                source_host=config.target_host,
                uri_to_collection=uri_to_collection,
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
                "provenance_stamped": provenance_stamped,
            },
        )

        return {
            "run_id": run_id,
            "status": run.status.value,
            "ontology_id": ontology_id,
            "import_stats": import_result,
            "provenance": provenance,
            "provenance_stamped": provenance_stamped,
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
