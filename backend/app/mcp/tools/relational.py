"""MCP tools for relational (SQL) schema extraction.

Two tools that let an AI agent create ontologies from relational databases via
the optional ``relational-schema-analyzer`` library:

  - preview_relational_schema:  read-only topology preview (tables / columns / FKs)
  - extract_relational_schema:  introspect -> OWL/SHACL -> import as a new ontology

Both delegate to :mod:`app.services.relational_schema_extraction` (the single
source of truth for the SQL->OWL mapping). Errors are returned as ``{"error": ...}``
payloads so an agent never sees an unhandled exception, matching the other tool
modules' contract.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_relational_tools(mcp: FastMCP) -> None:
    """Register relational schema-extraction tools on the given MCP server."""

    @mcp.tool()
    def preview_relational_schema(
        source_type: str,
        url: str,
        schema_name: str = "public",
        source_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Preview a relational database's tables, columns, and foreign keys.

        Read-only: nothing is written to AOE. Use this before
        ``extract_relational_schema`` to confirm the source, schema, and
        credentials are correct and to see what will become classes /
        datatype properties / object properties.

        Args:
            source_type: One of postgresql | mysql | sqlserver | snowflake |
                duckdb | databricks | csv.
            url: Connection string / DSN, or a directory path for csv.
            schema_name: Source schema / namespace (default "public").
            source_params: Type-specific options (e.g. CSV delimiter/has_header).
        """
        try:
            from app.services.relational_schema_extraction import (
                RelationalSchemaExtractionConfig,
                list_relational_tables,
            )

            config = RelationalSchemaExtractionConfig(
                source_type=source_type,
                url=url,
                schema_name=schema_name,
                source_params=source_params,
            )
            return list_relational_tables(config)
        except Exception as exc:
            log.exception("preview_relational_schema failed")
            return {"error": str(exc), "source_type": source_type}

    @mcp.tool()
    def extract_relational_schema(
        source_type: str,
        url: str,
        schema_name: str = "public",
        db_label: str | None = None,
        ontology_label: str | None = None,
        ontology_id: str | None = None,
        imports: list[str] | None = None,
        extract_constraints: bool = True,
        source_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract an ontology from a relational database and import it into AOE.

        Introspects the source, maps tables/columns/foreign-keys/constraints to
        OWL classes / datatype properties / object properties / SHACL shapes,
        and imports the result as a new AOE ontology. Returns the run summary
        (``run_id``, ``ontology_id``, ``import_stats``, ``provenance``).

        Args:
            source_type: One of postgresql | mysql | sqlserver | snowflake |
                duckdb | databricks | csv.
            url: Connection string / DSN, or a directory path for csv.
            schema_name: Source schema / namespace (default "public").
            db_label: Logical DB name for the ontology namespace + provenance.
            ontology_label: Human-readable name for the new ontology.
            ontology_id: Explicit registry ID (auto-generated when omitted).
            imports: AOE ontology IDs to wire as ``owl:imports``.
            extract_constraints: Emit SHACL from NOT NULL / UNIQUE / CHECK-enum
                constraints (default True).
            source_params: Type-specific options (e.g. CSV delimiter/has_header).
        """
        try:
            from app.services.relational_schema_extraction import (
                RelationalSchemaExtractionConfig,
            )
            from app.services.relational_schema_extraction import (
                extract_relational_schema as _extract,
            )

            config = RelationalSchemaExtractionConfig(
                source_type=source_type,
                url=url,
                schema_name=schema_name,
                db_label=db_label,
                ontology_label=ontology_label,
                ontology_id=ontology_id,
                imports=imports or [],
                extract_constraints=extract_constraints,
                source_params=source_params,
            )
            return _extract(config)
        except Exception as exc:
            log.exception("extract_relational_schema failed")
            return {"error": str(exc), "source_type": source_type}
