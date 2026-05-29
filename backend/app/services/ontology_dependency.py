"""Ontology deletion-impact analysis (Stream 1 H.4).

Before an ontology is deprecated or hard-deleted, callers MUST present the
user with a complete picture of what the cascade will affect. The previous
implementation -- inline AQL inside ``DELETE /ontology/library/{id}`` --
only reported direct (1-hop) ``imports`` dependents. Indirect dependents
(``A -> B -> C``: deleting ``C`` breaks ``A`` even though ``A`` does not
directly import ``C``), cross-ontology ``extends_domain`` edges,
extraction runs targeting the ontology, and released versions were all
invisible.

This module centralises the analysis so:

* The dry-run path of ``DELETE /library/{id}`` and a new dedicated
  ``GET /library/{id}/deletion-impact`` endpoint return the same payload
  shape, eliminating drift.
* The frontend ``OntologyDeleteDialog`` has one canonical contract to
  render against.
* Tests can exercise the analysis logic without reaching for the HTTP
  layer.

All AQL queries gate on ``db.has_collection(...)`` so the analysis still
runs (with zero counts) on freshly migrated databases that lack optional
collections.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.ontology_collections import PROPERTY_VERTEX_COLLECTIONS
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


# --- Collection groups -----------------------------------------------------
#
# Mirrors the cascade implemented in ``app.api.ontology.delete_ontology``.
# Keep these in sync if the cascade list ever grows; otherwise the impact
# preview will under-report what the user is about to expire.

# Versioned vertex collections that hold ontology content. Counted when
# computing how many entities would be soft-expired.
_VERTEX_COLLECTIONS: tuple[str, ...] = (
    "ontology_classes",
    *PROPERTY_VERTEX_COLLECTIONS,
    "ontology_constraints",
)

# Edge collections that hold ontology-internal relationships. Counted when
# computing how many edges would be soft-expired.
_EDGE_COLLECTIONS: tuple[str, ...] = (
    "subclass_of",
    "has_property",
    "has_constraint",
    "related_to",
    "equivalent_class",
    "extracted_from",
    "extends_domain",
    "has_chunk",
    "produced_by",
    "rdfs_domain",
    "rdfs_range_class",
)

# Maximum depth for the transitive ``imports`` traversal. Picked to mirror
# the cycle-detection bound in ``add_ontology_import`` (10 hops). In
# practice imports DAGs are shallow; this is a safety stop, not a feature.
_MAX_IMPORTS_DEPTH = 10


def analyze_deletion_impact(
    db: StandardDatabase,
    ontology_id: str,
    *,
    max_depth: int = _MAX_IMPORTS_DEPTH,
) -> dict[str, Any]:
    """Compute the cascade-on-delete dependency report for an ontology.

    Parameters
    ----------
    db:
        ArangoDB handle. Must already be initialised; this function does
        not call ``get_db`` so callers can inject mocks in tests.
    ontology_id:
        Registry ``_key`` of the ontology under consideration.
    max_depth:
        Maximum number of ``imports`` hops to traverse when building the
        transitive dependents list. Defaults to ten.

    Returns
    -------
    dict
        Structured payload (see module docstring). The shape is part of
        the public API contract of ``GET /library/{id}/deletion-impact``
        and the dry-run branch of ``DELETE /library/{id}``.

    Raises
    ------
    ValueError
        If ``ontology_id`` is not present in ``ontology_registry``.
        Callers translate this to ``404 NOT_FOUND``.
    """
    if not db.has_collection("ontology_registry"):
        raise ValueError("ontology_registry collection is not available")

    entry = _get_registry_entry(db, ontology_id)
    if entry is None:
        raise ValueError(f"Ontology '{ontology_id}' not found")

    target_id = f"ontology_registry/{ontology_id}"

    direct_dependents = _list_direct_dependents(db, target_id)
    transitive_dependents = _list_transitive_dependents(db, target_id, max_depth=max_depth)
    imports_outgoing = _list_imports_outgoing(db, target_id)
    expire_counts = _count_expirable_entities(db, ontology_id)
    extraction_runs = _summarise_extraction_runs(db, ontology_id)
    cross_extends = _count_cross_ontology_extends_edges(db, ontology_id)
    quality_history_count = _count_quality_history(db, ontology_id)
    released_versions = _count_released_versions(db, ontology_id)
    revision_count = _count_open_revisions(db, ontology_id)

    warnings: list[str] = []
    if transitive_dependents:
        warnings.append(
            f"{len(transitive_dependents)} ontology(ies) depend on this one via imports; "
            "they will keep their import edges expired but lose live access to imported axioms."
        )
    if cross_extends > 0:
        warnings.append(
            f"{cross_extends} cross-ontology extends_domain edge(s) point into this ontology's "
            "classes; they will be expired so dependent extractions lose their domain anchors."
        )
    if released_versions > 0:
        warnings.append(
            f"{released_versions} released version(s) exist for this ontology; "
            "deletion forfeits the published artifact."
        )
    if revision_count > 0:
        warnings.append(
            f"{revision_count} pending belief-revision(s) reference this ontology; "
            "they will become unreviewable."
        )

    has_dependents = bool(transitive_dependents)
    has_cross_refs = cross_extends > 0
    has_published = released_versions > 0

    return {
        "ontology_id": ontology_id,
        "ontology_name": entry.get("name") or ontology_id,
        "status": entry.get("status"),
        "direct_dependents": direct_dependents,
        "transitive_dependents": transitive_dependents,
        "imports_outgoing": imports_outgoing,
        "cross_ontology_extends_edges": cross_extends,
        "expire_counts": expire_counts,
        "extraction_runs": extraction_runs,
        "quality_history_snapshots": quality_history_count,
        "released_versions": released_versions,
        "open_revisions": revision_count,
        "has_dependents": has_dependents,
        "safe_to_delete": not (has_dependents or has_cross_refs or has_published),
        "warnings": warnings,
    }


# --- Helpers ---------------------------------------------------------------


def _get_registry_entry(db: StandardDatabase, ontology_id: str) -> dict[str, Any] | None:
    try:
        doc = db.collection("ontology_registry").get(ontology_id)
    except Exception:
        return None
    return cast("dict[str, Any] | None", doc)


def _list_direct_dependents(db: StandardDatabase, target_id: str) -> list[dict[str, Any]]:
    """Ontologies that have a *live* import edge pointing at the target."""
    if not db.has_collection("imports"):
        return []
    rows = list(
        run_aql(
            db,
            """
            FOR e IN imports
              FILTER e._to == @target AND e.expired == @never
              LET src = DOCUMENT(e._from)
              RETURN {
                _key: PARSE_IDENTIFIER(e._from).key,
                name: src.name || src.label || PARSE_IDENTIFIER(e._from).key,
                status: src.status
              }
            """,
            bind_vars={"target": target_id, "never": NEVER_EXPIRES},
        )
    )
    # Deduplicate by _key in case multiple imports edges exist (one live edge
    # is the norm but defensive coding here costs nothing).
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("_key") or "")
        if key and key not in seen:
            seen[key] = row
    return list(seen.values())


def _list_transitive_dependents(
    db: StandardDatabase, target_id: str, *, max_depth: int
) -> list[dict[str, Any]]:
    """Full upstream closure of ``imports`` -- direct + indirect.

    Uses BFS with ``uniqueVertices: 'global'`` so each ontology appears at
    most once with its shortest-path depth. The traversal walks INBOUND
    because dependents *import* the target, so the edge direction is
    target <- dependent.
    """
    if not db.has_collection("imports"):
        return []
    rows = list(
        run_aql(
            db,
            """
            FOR v, e, p IN 1..@max_depth INBOUND @target imports
              OPTIONS { uniqueVertices: 'global', bfs: true }
              FILTER e.expired == @never
              RETURN {
                _key: v._key,
                name: v.name || v.label || v._key,
                status: v.status,
                depth: LENGTH(p.edges)
              }
            """,
            bind_vars={
                "target": target_id,
                "never": NEVER_EXPIRES,
                "max_depth": max_depth,
            },
        )
    )
    # Stable order: shallowest depth first, then alphabetical by name -- the
    # frontend renders this verbatim, so an unstable traversal order would
    # cause the dialog to flicker on re-fetch.
    rows.sort(key=lambda r: (int(r.get("depth", 0)), str(r.get("name", "")).lower()))
    return rows


def _list_imports_outgoing(db: StandardDatabase, target_id: str) -> list[dict[str, Any]]:
    """Ontologies the target itself imports (informational; not affected)."""
    if not db.has_collection("imports"):
        return []
    rows = list(
        run_aql(
            db,
            """
            FOR e IN imports
              FILTER e._from == @target AND e.expired == @never
              LET dst = DOCUMENT(e._to)
              RETURN {
                _key: PARSE_IDENTIFIER(e._to).key,
                name: dst.name || dst.label || PARSE_IDENTIFIER(e._to).key,
                status: dst.status
              }
            """,
            bind_vars={"target": target_id, "never": NEVER_EXPIRES},
        )
    )
    return rows


def _count_expirable_entities(db: StandardDatabase, ontology_id: str) -> dict[str, int]:
    """Count, per collection, the live entities that would be soft-expired.

    The map mirrors the collections enumerated in ``delete_ontology`` so
    the user sees the same scope the cascade will actually apply to.
    Empty/missing collections are reported as zero (rather than omitted)
    so the frontend can render a stable table.
    """
    counts: dict[str, int] = {}
    for col in _VERTEX_COLLECTIONS:
        counts[col] = _count_live(db, col, "ontology_id", ontology_id)
    for col in _EDGE_COLLECTIONS:
        counts[col] = _count_live(db, col, "ontology_id", ontology_id)
    return counts


def _count_live(db: StandardDatabase, collection: str, field: str, value: str) -> int:
    """Count live (``expired == NEVER_EXPIRES``) docs in ``collection``
    whose ``field`` equals ``value``. Returns 0 if collection is missing.
    """
    if not db.has_collection(collection):
        return 0
    query = (
        f"RETURN LENGTH(FOR d IN {collection} "
        f"FILTER d.@field == @value AND d.expired == @never RETURN 1)"
    )
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"field": field, "value": value, "never": NEVER_EXPIRES},
        )
    )
    if not rows:
        return 0
    val = rows[0]
    if isinstance(val, int):
        return val
    if isinstance(val, dict) and "count" in val:
        return int(val["count"])
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _summarise_extraction_runs(db: StandardDatabase, ontology_id: str) -> dict[str, int]:
    """Count extraction runs touching this ontology.

    A run "touches" an ontology if either
    * ``target_ontology_id == ontology_id`` (the ontology being populated), or
    * ``ontology_id`` appears in ``domain_ontology_ids`` (used as
      tier-2 domain context).

    These run records survive deletion (they are append-only history) but
    their stored references will dangle, so the user should know.
    """
    if not db.has_collection("extraction_runs"):
        return {"as_target": 0, "as_domain": 0, "total": 0}

    target_rows = list(
        run_aql(
            db,
            "RETURN LENGTH(FOR r IN extraction_runs FILTER r.target_ontology_id == @oid RETURN 1)",
            bind_vars={"oid": ontology_id},
        )
    )
    domain_rows = list(
        run_aql(
            db,
            "RETURN LENGTH(FOR r IN extraction_runs "
            "FILTER @oid IN (r.domain_ontology_ids || []) RETURN 1)",
            bind_vars={"oid": ontology_id},
        )
    )
    as_target = int(target_rows[0]) if target_rows else 0
    as_domain = int(domain_rows[0]) if domain_rows else 0
    return {
        "as_target": as_target,
        "as_domain": as_domain,
        # Conservative upper bound; some runs may appear in both so we
        # surface both numbers separately AND a (deduped) total.
        "total": _count_distinct_runs(db, ontology_id),
    }


def _count_distinct_runs(db: StandardDatabase, ontology_id: str) -> int:
    if not db.has_collection("extraction_runs"):
        return 0
    rows = list(
        run_aql(
            db,
            """
            RETURN LENGTH(
              UNIQUE(
                FOR r IN extraction_runs
                  FILTER r.target_ontology_id == @oid
                      OR @oid IN (r.domain_ontology_ids || [])
                  RETURN r._key
              )
            )
            """,
            bind_vars={"oid": ontology_id},
        )
    )
    return int(rows[0]) if rows else 0


def _count_cross_ontology_extends_edges(db: StandardDatabase, ontology_id: str) -> int:
    """Count live ``extends_domain`` edges from another ontology's classes
    into this ontology's classes.

    These edges are how tier-2 EXTENSION classes anchor themselves into
    tier-1 (or other) library ontologies; deleting this ontology breaks
    them.
    """
    if not db.has_collection("extends_domain") or not db.has_collection("ontology_classes"):
        return 0
    rows = list(
        run_aql(
            db,
            """
            LET target_class_ids = (
              FOR c IN ontology_classes
                FILTER c.ontology_id == @oid AND c.expired == @never
                RETURN c._id
            )
            RETURN LENGTH(
              FOR e IN extends_domain
                FILTER e._to IN target_class_ids
                FILTER e.expired == @never
                LET src = DOCUMENT(e._from)
                FILTER src != null AND src.ontology_id != @oid
                RETURN 1
            )
            """,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    return int(rows[0]) if rows else 0


def _count_quality_history(db: StandardDatabase, ontology_id: str) -> int:
    if not db.has_collection("quality_history"):
        return 0
    rows = list(
        run_aql(
            db,
            "RETURN LENGTH(FOR q IN quality_history FILTER q.ontology_id == @oid RETURN 1)",
            bind_vars={"oid": ontology_id},
        )
    )
    return int(rows[0]) if rows else 0


def _count_released_versions(db: StandardDatabase, ontology_id: str) -> int:
    if not db.has_collection("ontology_releases"):
        return 0
    rows = list(
        run_aql(
            db,
            "RETURN LENGTH(FOR r IN ontology_releases FILTER r.ontology_id == @oid RETURN 1)",
            bind_vars={"oid": ontology_id},
        )
    )
    return int(rows[0]) if rows else 0


def _count_open_revisions(db: StandardDatabase, ontology_id: str) -> int:
    """Count ``revision_meta`` documents in ``proposed`` status for this
    ontology. Closed (accepted/rejected/applied) revisions are immutable
    audit records and are not flagged as a deletion blocker.
    """
    if not db.has_collection("revision_meta"):
        return 0
    rows = list(
        run_aql(
            db,
            """
            RETURN LENGTH(
              FOR rm IN revision_meta
                FILTER rm.ontology_id == @oid
                FILTER rm.status == 'proposed'
                RETURN 1
            )
            """,
            bind_vars={"oid": ontology_id},
        )
    )
    return int(rows[0]) if rows else 0
