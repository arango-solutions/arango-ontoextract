"""Standard ontology catalog (Stream 1 H.5).

The catalog is the curated list of well-known ontologies a user can
one-click-import into AOE (FIBO modules, Schema.org, Dublin Core, FOAF,
PROV-O, SKOS, OWL-Time). Catalog metadata lives in
``backend/app/data/standard_ontology_catalog.json``; bundled ontology
files (when present) live under ``backend/app/data/ontologies/``.

Why a service module instead of inline AQL in the route:

* The catalog import path delegates to the existing
  ``import_from_file`` / ``import_from_url`` helpers in
  ``arangordf_bridge``. Keeping the resolver here means the route
  stays a thin HTTP wrapper, the resolver is unit-testable without a
  TestClient, and the (already-real) catalog JSON shape is owned by
  one place.
* Frontend H.6 reads the same catalog (via ``GET /ontology/catalog``)
  to render the browser; pinning the response model here means UI
  drift is caught by the unit suite, not by manual QA.
"""

from __future__ import annotations

import importlib.resources as _resources
import json
import logging
from typing import Any

from arango.database import StandardDatabase

from app.db import registry_repo
from app.services.arangordf_bridge import import_from_file, import_from_url

log = logging.getLogger(__name__)

# Module names where bundled assets live. ``importlib.resources`` resolves
# these to actual file paths inside the installed package, so the catalog
# works equally well from a source checkout, a wheel, or a Docker image.
_DATA_PACKAGE = "app.data"
_ONTOLOGIES_PACKAGE = "app.data.ontologies"
_CATALOG_FILENAME = "standard_ontology_catalog.json"


# --- Loader -----------------------------------------------------------------


def load_catalog() -> list[dict[str, Any]]:
    """Return the catalog entries as a list of dicts.

    The JSON file is parsed on every call (it is small -- well under
    8 KB -- and read-only on disk); caching would add a footgun if a
    deployment hot-swaps the file. Tests can monkey-patch this
    function to inject fixtures.

    Raises
    ------
    RuntimeError
        If the bundled catalog JSON is malformed or missing the
        ``ontologies`` array. Production never sees this; the file
        ships in the package.
    """
    try:
        raw = (
            _resources.files(_DATA_PACKAGE).joinpath(_CATALOG_FILENAME).read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Standard ontology catalog file '{_CATALOG_FILENAME}' missing from {_DATA_PACKAGE}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Standard ontology catalog JSON is invalid: {exc}") from exc

    entries = data.get("ontologies")
    if not isinstance(entries, list):
        got = type(entries).__name__
        raise RuntimeError(f"Standard ontology catalog JSON has no 'ontologies' array (got {got})")

    return entries


def get_catalog_entry(catalog_id: str) -> dict[str, Any] | None:
    """Return one catalog entry by ``id``, or ``None`` if absent."""
    for entry in load_catalog():
        if entry.get("id") == catalog_id:
            return entry
    return None


# --- Import dispatch --------------------------------------------------------


def import_catalog_entry(
    catalog_id: str,
    *,
    db: StandardDatabase,
    ontology_id: str | None = None,
) -> dict[str, Any]:
    """One-click import a catalog entry into AOE.

    Resolves the entry's ``source`` (bundled file or remote URL),
    delegates the heavy lifting to the existing import helpers, and
    tags the result with ``source = "catalog_import"`` plus the catalog
    id so downstream UI can render a "Imported from FOAF (catalog)"
    badge.

    Parameters
    ----------
    catalog_id:
        Catalog entry ``id`` (e.g. ``"foaf"``).
    db:
        ArangoDB handle. Required (no implicit ``get_db``) so callers
        can inject a test DB.
    ontology_id:
        Optional override for the new registry ``_key``. Defaults to
        the catalog id (with characters that ArangoDB rejects sanitized
        out by ``arangordf_bridge``).

    Raises
    ------
    LookupError
        Unknown catalog id (callers map to ``404``).
    ConflictError
        Registry entry with the same id already exists. The catalog
        importer refuses to overwrite an existing ontology -- callers
        must pass a different ``ontology_id`` or delete the existing
        one first.
    RuntimeError
        Bundled file referenced by the catalog entry is missing from
        the package; signals a packaging bug.
    """
    from app.api.errors import ConflictError  # local import to avoid api->services->api cycle

    entry = get_catalog_entry(catalog_id)
    if entry is None:
        raise LookupError(f"Unknown catalog entry '{catalog_id}'")

    final_ontology_id = ontology_id or entry["id"]

    if registry_repo.get_registry_entry(final_ontology_id, db=db) is not None:
        raise ConflictError(
            f"An ontology with id '{final_ontology_id}' already exists. "
            "Delete it first or import the catalog entry under a different id."
        )

    source = entry.get("source") or {}
    kind = source.get("kind")
    ontology_label = entry.get("name") or entry.get("id")

    log.info(
        "catalog import starting",
        extra={
            "catalog_id": catalog_id,
            "ontology_id": final_ontology_id,
            "source_kind": kind,
        },
    )

    if kind == "bundled":
        result = _import_bundled(
            entry=entry,
            ontology_id=final_ontology_id,
            ontology_label=ontology_label,
            db=db,
        )
    elif kind == "url":
        url = source.get("url")
        if not url:
            raise RuntimeError(
                f"Catalog entry '{catalog_id}' has source.kind='url' but no source.url"
            )
        result = import_from_url(
            url=url,
            ontology_id=final_ontology_id,
            db=db,
            ontology_label=ontology_label,
        )
    else:
        raise RuntimeError(f"Catalog entry '{catalog_id}' has unsupported source.kind={kind!r}")

    result["source"] = "catalog_import"
    result["catalog_id"] = catalog_id
    result["catalog_name"] = entry.get("name")
    return result


def _import_bundled(
    *,
    entry: dict[str, Any],
    ontology_id: str,
    ontology_label: str | None,
    db: StandardDatabase,
) -> dict[str, Any]:
    """Read a packaged file out of ``app.data.ontologies`` and import it.

    Uses ``importlib.resources`` so the same code works from a source
    checkout, an installed wheel, and a Docker image without any
    path-twiddling.
    """
    source = entry["source"]
    bundled_path = source.get("path")
    if not bundled_path:
        raise RuntimeError(
            f"Catalog entry '{entry.get('id')}' has source.kind='bundled' but no source.path"
        )

    try:
        file_bytes = _resources.files(_ONTOLOGIES_PACKAGE).joinpath(bundled_path).read_bytes()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Bundled ontology file '{bundled_path}' missing from {_ONTOLOGIES_PACKAGE}"
        ) from exc

    return import_from_file(
        file_content=file_bytes,
        filename=bundled_path,
        ontology_id=ontology_id,
        db=db,
        ontology_label=ontology_label,
    )
