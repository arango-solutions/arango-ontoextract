"""Schema extraction from external relational databases (SQL schema -> ontology).

The relational analogue of :mod:`app.services.schema_extraction`'s **direct** path.
It consumes a typed ``PhysicalSchema`` from the optional ``relational-schema-analyzer``
library (a mapping-agnostic, read-only SQL introspector across PostgreSQL / MySQL /
SQL Server / Snowflake / DuckDB / Databricks / CSV) and -- exactly like
``_direct_extract_schema`` owns the ArangoDB->OWL mapping -- AOE owns the SQL->OWL/SHACL
mapping here:

    * Table (or view)          -> ``owl:Class``
    * Column                   -> ``owl:DatatypeProperty`` with ``rdfs:domain`` =
      the table's class and ``rdfs:range`` an XSD type from the column's normalized
      type category. Primary-key / unique columns are also marked
      ``owl:FunctionalProperty`` + ``owl:InverseFunctionalProperty``.
    * Foreign key              -> ``owl:ObjectProperty`` with ``rdfs:domain`` /
      ``rdfs:range`` resolved from the FK's local / referenced table. A FK whose
      columns are unique (1:1) is marked functional + inverse-functional.
    * NOT NULL / UNIQUE / CHECK -> SHACL ``sh:NodeShape`` + ``sh:PropertyShape``
      (``sh:minCount`` / ``sh:maxCount`` / ``sh:datatype`` / ``sh:in`` from a
      recognized ``col IN (...)`` CHECK), picked up by AOE's standard SHACL importer.
    * Per-class provenance      -> ``source_db`` + ``source_collection`` (= table)
      stamped post-import, reusing :func:`_stamp_per_class_provenance`.

The OWL vocabulary, namespaces, and provenance annotations mirror the ArangoDB direct
path so the generated TTL flows through the same ``import_from_file`` pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services.arangordf_bridge import import_from_file
from app.services.schema_extraction import _stamp_per_class_provenance

log = logging.getLogger(__name__)

# Normalized type category (relational-schema-analyzer) -> XSD local name.
_CATEGORY_TO_XSD = {
    "integer": "integer",
    "decimal": "decimal",
    "boolean": "boolean",
    "string": "string",
    "temporal": "dateTime",
    "binary": "base64Binary",
    "uuid": "string",
    "json": "string",
    "array": "string",
}


class RelationalSchemaExtractionConfig(BaseModel):
    """Connection and options for schema extraction from a relational source."""

    source_type: str = Field(
        ..., description="postgresql | mysql | sqlserver | snowflake | duckdb | databricks | csv"
    )
    url: str = Field(..., description="Connection string / DSN / path (CSV directory)")
    schema_name: str = Field(default="public", description="Source schema / namespace")
    source_params: dict[str, Any] | None = Field(
        default=None, description="Type-specific options (e.g. CSV delimiter/has_header)."
    )
    db_label: str | None = Field(
        default=None,
        description="Logical DB name for the ontology namespace + provenance; "
        "defaults to the source's reported database or the schema name.",
    )
    source_host: str = Field(default="", description="Host recorded in provenance.")
    extract_constraints: bool = Field(
        default=True,
        description="Emit SHACL from NOT NULL / UNIQUE / CHECK-enum constraints.",
    )
    imports: list[str] = Field(default_factory=list, description="AOE ontology IDs to import.")
    ontology_id: str | None = Field(default=None)
    ontology_label: str | None = Field(default=None)


def _try_import_relational_analyzer() -> Any | None:
    """Return ``create_connector`` or None when the optional library is absent."""
    try:
        from relational_schema_analyzer import create_connector

        return create_connector
    except ImportError:
        log.warning(
            "relational-schema-analyzer not installed; relational schema extraction "
            "unavailable. Install with: pip install relational-schema-analyzer"
        )
        return None


def build_relational_owl(
    physical: Any,
    *,
    db_label: str,
    source_host: str = "",
    imports: list[str] | None = None,
    extract_constraints: bool = True,
) -> tuple[str, dict[str, str]]:
    """Map a ``PhysicalSchema`` to OWL Turtle + a URI -> table map (for provenance).

    Pure function: no database access. ``physical`` is a
    ``relational_schema_analyzer.PhysicalSchema`` (or anything with the same
    ``.tables`` / ``.source`` shape).
    """
    from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
    from rdflib.collection import Collection

    imports = imports or []
    ns_str = f"http://aoe.example.org/schema/{db_label}#"
    ns = Namespace(ns_str)
    aoe_ns = Namespace("http://aoe.example.org/vocab#")
    sh_ns = Namespace("http://www.w3.org/ns/shacl#")

    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("xsd", XSD)
    g.bind("schema", ns)
    g.bind("aoe", aoe_ns)
    g.bind("sh", sh_ns)

    ont_uri = URIRef(ns_str.rstrip("#"))
    g.add((ont_uri, RDF.type, OWL.Ontology))
    g.add((ont_uri, RDFS.label, Literal(f"Schema of {db_label}")))
    for imported_id in imports:
        g.add((ont_uri, OWL.imports, URIRef(f"http://example.org/ontology/{imported_id}")))

    uri_to_table: dict[str, str] = {}
    tables = physical.tables

    def _xsd(category: str | None) -> URIRef:
        return XSD[_CATEGORY_TO_XSD.get(category or "", "string")]

    def _class_for(table_name: str) -> URIRef:
        uri = ns[table_name]
        uri_to_table[str(uri)] = table_name
        return uri

    # --- Classes + datatype properties -------------------------------------
    for table_name in sorted(tables):
        table = tables[table_name]
        cls_uri = _class_for(table_name)
        g.add((cls_uri, RDF.type, OWL.Class))
        g.add((cls_uri, RDFS.label, Literal(table_name)))
        kind = "View" if getattr(table, "is_view", False) else "Table"
        table_comment = getattr(table, "comment", None) or f"{kind}: {table_name}"
        g.add((cls_uri, RDFS.comment, Literal(table_comment)))
        g.add((cls_uri, aoe_ns.sourceDb, Literal(db_label)))
        g.add((cls_uri, aoe_ns.sourceCollection, Literal(table_name)))

        for col in table.columns:
            prop_uri = ns[f"{table_name}.{col.name}"]
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            g.add((prop_uri, RDFS.label, Literal(col.name)))
            g.add((prop_uri, RDFS.domain, cls_uri))
            g.add((prop_uri, RDFS.range, _xsd(getattr(col, "type_category", None))))
            if getattr(col, "comment", None):
                g.add((prop_uri, RDFS.comment, Literal(col.comment)))
            if getattr(col, "is_unique", False):
                g.add((prop_uri, RDF.type, OWL.FunctionalProperty))
                g.add((prop_uri, RDF.type, OWL.InverseFunctionalProperty))
            g.add((prop_uri, aoe_ns.sourceDb, Literal(db_label)))
            g.add((prop_uri, aoe_ns.sourceCollection, Literal(table_name)))
            g.add((prop_uri, aoe_ns.sourceField, Literal(col.name)))

    # --- Object properties from foreign keys -------------------------------
    used_fk_names: set[str] = set()
    for table_name in sorted(tables):
        table = tables[table_name]
        for fk in table.foreign_keys:
            base = fk.constraint_name or f"{table_name}_{'_'.join(fk.columns)}_fk"
            name = base
            suffix = 2
            while name in used_fk_names:
                name = f"{base}_{suffix}"
                suffix += 1
            used_fk_names.add(name)

            obj_uri = ns[name]
            uri_to_table[str(obj_uri)] = table_name
            g.add((obj_uri, RDF.type, OWL.ObjectProperty))
            g.add((obj_uri, RDFS.label, Literal(name)))
            g.add(
                (
                    obj_uri,
                    RDFS.comment,
                    Literal(
                        f"Foreign key {table_name}({', '.join(fk.columns)}) -> "
                        f"{fk.foreign_table}({', '.join(fk.foreign_columns)})"
                    ),
                )
            )
            g.add((obj_uri, RDFS.domain, ns[table_name]))
            if fk.foreign_table in tables:
                g.add((obj_uri, RDFS.range, ns[fk.foreign_table]))
            if getattr(fk, "is_unique", False):
                g.add((obj_uri, RDF.type, OWL.FunctionalProperty))
                g.add((obj_uri, RDF.type, OWL.InverseFunctionalProperty))
            g.add((obj_uri, aoe_ns.sourceDb, Literal(db_label)))
            g.add((obj_uri, aoe_ns.sourceCollection, Literal(table_name)))

    # --- SHACL constraints -------------------------------------------------
    if extract_constraints:
        for table_name in sorted(tables):
            table = tables[table_name]
            enum_by_col: dict[str, list[str]] = {}
            for chk in getattr(table, "check_constraints", []) or []:
                cols = getattr(chk, "columns", []) or []
                if getattr(chk, "enum_values", None) and len(cols) == 1:
                    enum_by_col[chk.columns[0]] = list(chk.enum_values)

            shape_uri = ns[f"{table_name}Shape"]
            emitted = False
            for col in table.columns:
                prop_uri = ns[f"{table_name}.{col.name}"]
                pnode = BNode()
                triples: list[tuple[Any, Any, Any]] = [
                    (pnode, sh_ns.path, prop_uri),
                    (pnode, sh_ns.datatype, _xsd(getattr(col, "type_category", None))),
                ]
                if not col.is_nullable:
                    triples.append((pnode, sh_ns.minCount, Literal(1)))
                if getattr(col, "is_unique", False):
                    triples.append((pnode, sh_ns.maxCount, Literal(1)))
                enum = enum_by_col.get(col.name)
                has_shape = len(triples) > 2 or enum is not None
                if not has_shape:
                    continue
                if not emitted:
                    g.add((shape_uri, RDF.type, sh_ns.NodeShape))
                    g.add((shape_uri, sh_ns.targetClass, ns[table_name]))
                    emitted = True
                g.add((shape_uri, sh_ns.property, pnode))
                for t in triples:
                    g.add(t)
                if enum is not None:
                    list_node = BNode()
                    Collection(g, list_node, [Literal(v) for v in enum])
                    g.add((pnode, sh_ns["in"], list_node))

    ttl = g.serialize(format="turtle")
    log.info(
        "relational schema extraction complete",
        extra={
            "db_label": db_label,
            "triples": len(g),
            "classes": sum(1 for _ in g.subjects(RDF.type, OWL.Class)),
            "object_properties": sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)),
            "datatype_properties": sum(1 for _ in g.subjects(RDF.type, OWL.DatatypeProperty)),
        },
    )
    return ttl, uri_to_table


def _introspect(config: RelationalSchemaExtractionConfig) -> tuple[Any, Any, str]:
    """Connect to the relational source and return ``(physical, source, db_label)``.

    Shared by :func:`list_relational_tables` (preview) and
    :func:`extract_relational_schema` (commit). Raises ``RuntimeError`` when the
    optional ``relational-schema-analyzer`` library is not installed so both
    callers surface the same actionable message.
    """
    create_connector = _try_import_relational_analyzer()
    if create_connector is None:
        raise RuntimeError(
            "relational-schema-analyzer is not installed; "
            "install it to extract from relational sources"
        )

    physical = create_connector(
        config.source_type,
        config.url,
        schema_name=config.schema_name,
        source_params=config.source_params,
    ).get_schema()

    source = getattr(physical, "source", None)
    db_label = (
        config.db_label
        or (getattr(source, "database", None) if source else None)
        or config.schema_name
        or "relational"
    )
    return physical, source, db_label


def list_relational_tables(config: RelationalSchemaExtractionConfig) -> dict[str, Any]:
    """Preview a relational source's topology **without** importing anything.

    The relational analogue of :func:`app.services.schema_extraction.list_named_graphs`:
    the workspace "connect" step binds to this to show the curator which tables,
    columns, and foreign keys *will* become classes / datatype properties / object
    properties before committing the extract.

    Read-only: introspects the source and returns table / column / FK summaries plus
    the counts the UI's commit gate needs. Credentials are consumed from ``config``
    and never echoed back in the response.

    Raises:
        RuntimeError: when ``relational-schema-analyzer`` is not installed.
        Exception: connection / auth failures propagate (mapped to 502 at the API).
    """
    physical, source, db_label = _introspect(config)
    tables = physical.tables

    table_summaries: list[dict[str, Any]] = []
    for table_name in sorted(tables):
        table = tables[table_name]
        columns = [
            {
                "name": col.name,
                "data_type": col.data_type,
                "type_category": getattr(col, "type_category", None),
                "nullable": bool(getattr(col, "is_nullable", True)),
                "primary_key": bool(getattr(col, "is_primary_key", False)),
                "unique": bool(getattr(col, "is_unique", False)),
            }
            for col in table.columns
        ]
        foreign_keys = [
            {
                "columns": list(fk.columns),
                "foreign_table": fk.foreign_table,
                "foreign_columns": list(fk.foreign_columns),
            }
            for fk in table.foreign_keys
        ]
        table_summaries.append(
            {
                "name": table_name,
                "is_view": bool(getattr(table, "is_view", False)),
                "comment": getattr(table, "comment", None),
                "column_count": len(columns),
                "primary_key": list(getattr(table, "primary_key", []) or []),
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
        )

    return {
        "source_type": config.source_type,
        "schema_name": config.schema_name,
        "db_label": db_label,
        "server_version": getattr(source, "server_version", None) if source else None,
        "dialect": getattr(source, "dialect", None) if source else None,
        "tables": table_summaries,
        "table_count": len(table_summaries),
        "view_count": sum(1 for t in table_summaries if t["is_view"]),
        "foreign_key_count": sum(len(t["foreign_keys"]) for t in table_summaries),
    }


def extract_relational_schema(config: RelationalSchemaExtractionConfig) -> dict[str, Any]:
    """Introspect a relational source and import the derived ontology into AOE.

    Mirrors :func:`app.services.schema_extraction.extract_schema` for the relational
    path: introspect -> OWL/SHACL -> ``import_from_file`` -> per-class provenance.
    """
    run_id = uuid.uuid4().hex[:12]
    started = time.time()

    physical, source, db_label = _introspect(config)
    ontology_id = config.ontology_id or f"relschema_{db_label}_{run_id}"

    ttl_content, uri_to_table = build_relational_owl(
        physical,
        db_label=db_label,
        source_host=config.source_host,
        imports=config.imports,
        extract_constraints=config.extract_constraints,
    )

    db = get_db()
    import_result = import_from_file(
        file_content=ttl_content.encode("utf-8"),
        filename=f"{db_label}_relschema.ttl",
        ontology_id=ontology_id,
        db=db,
        ontology_label=config.ontology_label or f"Schema: {db_label}",
    )

    provenance_stamped = _stamp_per_class_provenance(
        db,
        ontology_id=ontology_id,
        source_db=db_label,
        source_host=config.source_host or config.source_type,
        uri_to_collection=uri_to_table,
    )

    log.info(
        "relational schema extraction imported",
        extra={"run_id": run_id, "ontology_id": ontology_id, "source_type": config.source_type},
    )
    return {
        "run_id": run_id,
        "status": "completed",
        "ontology_id": ontology_id,
        "import_stats": import_result,
        "provenance": {
            "mode": "relational",
            "source_type": config.source_type,
            "db_label": db_label,
            "server_version": getattr(source, "server_version", None) if source else None,
            "auto_imports": list(config.imports),
        },
        "provenance_stamped": provenance_stamped,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
