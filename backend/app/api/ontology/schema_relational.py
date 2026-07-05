"""Relational (SQL) schema extraction endpoints.

The relational analogue of the ArangoDB schema-extraction endpoints in
:mod:`app.api.ontology.schema_temporal`. Two endpoints, both POST (never GET)
because the request body carries a connection string / DSN that may embed
credentials -- we never want those in query strings (URL logs, browser
history, referrer leaks):

    POST /schema/relational/tables    -> read-only topology preview
    POST /schema/relational/extract   -> commit (introspect -> OWL/SHACL -> import)

The optional ``relational-schema-analyzer`` library backs both. When it is not
installed the service raises ``RuntimeError``; we map that to 501 (Not
Implemented) with an actionable install hint rather than a generic 500.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.relational_schema_extraction import (
    RelationalSchemaExtractionConfig,
    extract_relational_schema,
    list_relational_tables,
)

log = logging.getLogger(__name__)
router = APIRouter()

_NOT_INSTALLED_HINT = (
    "relational-schema-analyzer is not installed on the server. "
    "Install it (pip install relational-schema-analyzer) to extract "
    "ontologies from relational databases."
)


@router.post("/schema/relational/tables")
async def preview_relational_tables(
    config: RelationalSchemaExtractionConfig,
) -> dict[str, Any]:
    """Preview a relational source's tables / columns / foreign keys.

    Read-only introspection: nothing is written to the AOE registry. The
    workspace "connect" step binds to this so the curator sees what will
    become classes / datatype properties / object properties before
    committing. Credentials in the request body are never echoed back.

    Errors mapped:
      - library not installed -> 501 (actionable install hint)
      - ``ValueError`` (bad config) -> 400
      - connection / auth failures -> 502 (upstream DB unreachable)
    """
    try:
        return list_relational_tables(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=_NOT_INSTALLED_HINT) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Surface the upstream driver message: the curator needs to know
        # whether the host, credentials, or schema name was wrong.
        log.exception("Relational schema preview failed")
        raise HTTPException(status_code=502, detail=f"Relational source error: {exc}") from exc


@router.post("/schema/relational/extract")
async def trigger_relational_extraction(
    config: RelationalSchemaExtractionConfig,
) -> dict[str, Any]:
    """Extract an ontology from a relational database and import it into AOE.

    Introspect -> SQL->OWL/SHACL mapping -> standard ``import_from_file``
    pipeline -> per-class provenance stamping. Returns the run summary
    (``run_id``, ``ontology_id``, ``import_stats``, ``provenance``,
    ``provenance_stamped``) so the UI can switch to the new ontology.

    Errors mapped:
      - library not installed -> 501 (actionable install hint)
      - ``ValueError`` (bad config) -> 400
      - connection / driver failures -> 502 (upstream DB unreachable)
    """
    try:
        return extract_relational_schema(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=_NOT_INSTALLED_HINT) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Relational schema extraction failed")
        raise HTTPException(status_code=502, detail=f"Relational source error: {exc}") from exc
