"""Cross-ontology schema diff service.

Stream 5 PR 3 sub-B -- S.5. Given two ``ontology_id``s (typically two
re-extractions of the same target ArangoDB at different points in
time), compute the schema-level diff: added / removed / changed
classes, properties, and constraints.

This is the cross-ontology counterpart to ``temporal.get_diff`` (which
diffs two timestamps on ONE ontology). The diff key for classes and
properties is ``uri`` (mirrors the temporal semantics); the diff key
for constraints is the composite ``(class_uri, property_uri,
restriction_type)`` tuple because constraints don't carry URIs of
their own. The constraint walker resolves ``class_id`` /
``property_id`` to URIs server-side via an AQL join so two ontologies
with disjoint Arango ``_key`` namespaces can still be diffed.

Provenance compatibility (whether both ontologies came from the same
``source_db`` / ``source_host``) is surfaced as a **warning**, not a
refusal -- the diff is still meaningful between arbitrary ontologies,
it's just not "schema evolution".

Edge collections (subclass_of, has_property, rdfs_domain,
rdfs_range_class, etc.) are intentionally OUT of scope for v1 -- their
changes are nearly always implicit consequences of class / property
adds / removes that this diff already surfaces, and diffing them
independently would mostly duplicate information.
"""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.ontology_collections import PROPERTY_VERTEX_COLLECTIONS
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# PGT-aligned (ADR-006): properties live in three collections depending
# on whether they're un-typed, owl:ObjectProperty, or owl:DatatypeProperty.
# Diff walks all three so a datatype-property added in run B that didn't
# exist in run A still shows up as ``added``.
_PROPERTY_COLLECTIONS = list(PROPERTY_VERTEX_COLLECTIONS)

# Fields we deliberately ignore when deciding whether two rows differ.
# ``_key`` / ``_id`` / ``_rev`` are Arango plumbing. The temporal fields
# (``created`` / ``expired`` / ``version`` / ``ttlExpireAt``) change on
# every write even if semantics are identical. ``ontology_id`` is by
# definition different across the two ontologies. ``source_run_id``
# carries the run uuid which differs per extraction even when the
# resulting schema is identical.
_SCHEMA_METADATA_FIELDS: frozenset[str] = frozenset(
    {
        "_key",
        "_id",
        "_rev",
        "created",
        "expired",
        "version",
        "ttlExpireAt",
        "ontology_id",
        "source_run_id",
    }
)


# ---------------------------------------------------------------------------
# Pure helpers (DB-free, unit-testable in isolation)
# ---------------------------------------------------------------------------


def _by_uri(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index rows by their ``uri`` field. Rows without a ``uri`` are
    skipped (a class or property without a URI is malformed and the
    diff would have no key to join on)."""
    return {r["uri"]: r for r in rows if isinstance(r.get("uri"), str) and r["uri"]}


def _schema_data_changed(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff any non-metadata field differs between two rows.

    We deliberately INCLUDE ``source_db`` / ``source_collection`` /
    ``source_host`` / ``source_field`` in the comparison because a
    re-extraction repointed at a different source DB is exactly the
    kind of schema-evolution event a curator should see flagged.
    """
    keys = (set(a.keys()) | set(b.keys())) - _SCHEMA_METADATA_FIELDS
    return any(a.get(k) != b.get(k) for k in keys)


def _diff_by_uri(
    a_rows: list[dict[str, Any]],
    b_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Three-way diff keyed on ``uri``. Returns ``{added, removed, changed}``.

    ``changed`` rows are wrapped as ``{"uri", "before", "after"}`` so
    the caller can render side-by-side without re-joining.
    """
    a_map = _by_uri(a_rows)
    b_map = _by_uri(b_rows)

    added = [b_map[u] for u in b_map if u not in a_map]
    removed = [a_map[u] for u in a_map if u not in b_map]
    changed: list[dict[str, Any]] = []
    for u in sorted(a_map.keys() & b_map.keys()):
        a_doc = a_map[u]
        b_doc = b_map[u]
        if _schema_data_changed(a_doc, b_doc):
            changed.append({"uri": u, "before": a_doc, "after": b_doc})

    # Stable ordering by URI so test assertions and human review are
    # deterministic. Added/removed didn't go through the sorted() above
    # because dict iteration order is insertion order; sort now.
    added.sort(key=lambda r: r["uri"])
    removed.sort(key=lambda r: r["uri"])
    return {"added": added, "removed": removed, "changed": changed}


def _constraint_join_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    """Composite key for joining a constraint row across ontologies.

    Constraints don't carry their own URI -- they're identified by the
    ``(class_uri, property_uri, restriction_type)`` tuple. A row missing
    any of those three pieces returns ``None`` so the caller can skip
    it (eg a class-level constraint with no property path -- diffing
    those needs a different key shape and is deferred).
    """
    cls = row.get("class_uri")
    prop = row.get("property_uri")
    rtype = row.get("restriction_type")
    if not isinstance(cls, str) or not cls:
        return None
    if not isinstance(prop, str) or not prop:
        return None
    if not isinstance(rtype, str) or not rtype:
        return None
    return (cls, prop, rtype)


def _diff_constraints(
    a_rows: list[dict[str, Any]],
    b_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Three-way diff over constraint rows, keyed by
    ``(class_uri, property_uri, restriction_type)``. A constraint
    counts as ``changed`` if the ``restriction_value`` differs between
    the two rows for the same key. Severity / message drift is NOT
    flagged as a value change in v1 -- those are curator metadata, not
    schema semantics; surface them later if needed.
    """
    a_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in a_rows:
        key = _constraint_join_key(r)
        if key is not None:
            a_map[key] = r

    b_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in b_rows:
        key = _constraint_join_key(r)
        if key is not None:
            b_map[key] = r

    added = [b_map[k] for k in b_map if k not in a_map]
    removed = [a_map[k] for k in a_map if k not in b_map]
    changed: list[dict[str, Any]] = []
    for k in sorted(a_map.keys() & b_map.keys()):
        a_row = a_map[k]
        b_row = b_map[k]
        if a_row.get("restriction_value") != b_row.get("restriction_value"):
            changed.append(
                {
                    "class_uri": k[0],
                    "property_uri": k[1],
                    "restriction_type": k[2],
                    "before": a_row,
                    "after": b_row,
                }
            )

    added.sort(key=lambda r: _constraint_join_key(r) or ("", "", ""))
    removed.sort(key=lambda r: _constraint_join_key(r) or ("", "", ""))
    return {"added": added, "removed": removed, "changed": changed}


def _evaluate_provenance(
    prov_a: dict[str, Any],
    prov_b: dict[str, Any],
) -> tuple[bool, str | None]:
    """Decide whether the two ontologies' source-DB provenance matches.

    Returns ``(compatible, warning)``. ``compatible`` is True ONLY when
    both ontologies carry non-empty source_db + source_host AND those
    values are equal. Empty provenance on either side downgrades the
    result to ``compatible=False`` with an explanatory warning -- the
    caller should still serve the diff (refusing would be more annoying
    than helpful), the warning just signals "this isn't schema
    evolution, it's a generic ontology compare".
    """
    a_db = prov_a.get("source_db")
    a_host = prov_a.get("source_host")
    b_db = prov_b.get("source_db")
    b_host = prov_b.get("source_host")

    if not (a_db and a_host) or not (b_db and b_host):
        return False, (
            "One or both ontologies were not created via schema extraction "
            "(no source_db / source_host on classes); diff is between "
            "arbitrary ontologies, not schema evolution."
        )

    if a_db == b_db and a_host == b_host:
        return True, None

    return False, (
        f"Ontologies target different source databases "
        f"({a_db}@{a_host} vs {b_db}@{b_host}); "
        "diff is between unrelated schemas."
    )


# ---------------------------------------------------------------------------
# DB-touching helpers
# ---------------------------------------------------------------------------


def _fetch_current_classes(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_classes"):
        return []
    return list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "  FILTER c.ontology_id == @oid "
            "  FILTER c.expired == @never "
            "  RETURN c",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _fetch_current_properties(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    """Fetch from every PGT property collection (object + datatype + legacy
    catch-all). The diff treats them as one flat set keyed by URI -- if
    a property moved between collections (eg legacy -> object) it'll
    appear as ``changed`` with the new collection in ``_id``, which is
    fine because ``_id`` is in the metadata-skip set."""
    out: list[dict[str, Any]] = []
    for col in _PROPERTY_COLLECTIONS:
        if not db.has_collection(col):
            continue
        out.extend(
            run_aql(
                db,
                "FOR p IN @@col "
                "  FILTER p.ontology_id == @oid "
                "  FILTER p.expired == @never "
                "  RETURN p",
                bind_vars={"@col": col, "oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )
    return out


def _fetch_current_constraints_with_uris(
    db: StandardDatabase,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """Constraints enriched with ``class_uri`` + ``property_uri``.

    The join is server-side via AQL because constraints store class +
    property as Arango ``_key`` references, but ``_key`` values are
    disjoint across ontologies -- to diff across two ontologies we
    have to resolve to a join-able URI per row.

    ``property_id`` may live in any of three PGT property collections
    (object / datatype / legacy). The AQL walks all three and returns
    the first match -- properties' ``_key`` is globally unique per
    ontology, so at most one collection will resolve any given
    ``property_id``.
    """
    if not db.has_collection("ontology_constraints"):
        return []

    return list(
        run_aql(
            db,
            """
            FOR k IN ontology_constraints
              FILTER k.ontology_id == @oid
              FILTER k.expired == @never
              LET cls = (
                FOR c IN ontology_classes
                  FILTER c._key == k.class_id
                  FILTER c.expired == @never
                  LIMIT 1
                  RETURN c.uri
              )
              LET prop_uri = FIRST(
                FOR col IN @prop_cols
                  FOR p IN COLLECTION(col)
                    FILTER p._key == k.property_id
                    FILTER p.expired == @never
                    LIMIT 1
                    RETURN p.uri
              )
              RETURN MERGE(k, {
                class_uri: LENGTH(cls) > 0 ? cls[0] : null,
                property_uri: prop_uri
              })
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "prop_cols": _PROPERTY_COLLECTIONS,
            },
        )
    )


def _fetch_ontology_provenance(
    db: StandardDatabase,
    ontology_id: str,
) -> dict[str, Any]:
    """Pull ``source_db`` / ``source_host`` off any one class in the
    ontology. Every schema-extracted class carries these (stamped by
    ``_stamp_per_class_provenance`` in PR 1); if no class has them,
    the ontology wasn't created via schema extraction and we return
    ``{}``. The caller uses ``{}`` as the signal for
    "not-schema-evolution" and downgrades the diff accordingly."""
    if not db.has_collection("ontology_classes"):
        return {}

    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "  FILTER c.ontology_id == @oid "
            "  FILTER c.expired == @never "
            "  FILTER c.source_db != null "
            "  LIMIT 1 "
            "  RETURN { source_db: c.source_db, source_host: c.source_host }",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    return rows[0] if rows else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_ontologies(
    db: StandardDatabase | None = None,
    *,
    ontology_a: str,
    ontology_b: str,
) -> dict[str, Any]:
    """Cross-ontology schema diff.

    Computes ``{added, removed, changed}`` for classes, properties,
    and constraints between two ontologies and surfaces provenance
    compatibility as a warning (not an error).

    Args:
        db: ArangoDB handle; opens a default one if omitted.
        ontology_a: The 'before' ontology_id (typically the earlier
            extraction).
        ontology_b: The 'after' ontology_id (typically the later
            extraction).

    Returns:
        Dict with keys:
        * ``ontology_a`` / ``ontology_b`` -- the inputs (echoed for
          response self-description).
        * ``classes`` / ``properties`` / ``constraints`` -- each a
          ``{added, removed, changed}`` bundle.
        * ``summary`` -- nine integers (added / removed / changed per
          category). Useful for "X classes added, Y removed" banners.
        * ``provenance`` -- ``{a, b, compatible, warning}``. Truthy
          ``warning`` means the curator is comparing two ontologies
          that probably weren't intended to be compared as schema
          evolution.

    Raises:
        ValueError: When ``ontology_a == ontology_b``. Self-diffing
            would produce an empty result that misleads callers into
            thinking nothing changed when in fact they passed the
            same ID by accident.
    """
    if db is None:
        db = get_db()

    if ontology_a == ontology_b:
        raise ValueError("Cannot diff an ontology against itself; pass two distinct ontology_ids")

    a_classes = _fetch_current_classes(db, ontology_a)
    b_classes = _fetch_current_classes(db, ontology_b)
    a_props = _fetch_current_properties(db, ontology_a)
    b_props = _fetch_current_properties(db, ontology_b)
    a_constraints = _fetch_current_constraints_with_uris(db, ontology_a)
    b_constraints = _fetch_current_constraints_with_uris(db, ontology_b)

    classes_diff = _diff_by_uri(a_classes, b_classes)
    properties_diff = _diff_by_uri(a_props, b_props)
    constraints_diff = _diff_constraints(a_constraints, b_constraints)

    prov_a = _fetch_ontology_provenance(db, ontology_a)
    prov_b = _fetch_ontology_provenance(db, ontology_b)
    compatible, warning = _evaluate_provenance(prov_a, prov_b)

    summary = {
        "classes_added": len(classes_diff["added"]),
        "classes_removed": len(classes_diff["removed"]),
        "classes_changed": len(classes_diff["changed"]),
        "properties_added": len(properties_diff["added"]),
        "properties_removed": len(properties_diff["removed"]),
        "properties_changed": len(properties_diff["changed"]),
        "constraints_added": len(constraints_diff["added"]),
        "constraints_removed": len(constraints_diff["removed"]),
        "constraints_changed": len(constraints_diff["changed"]),
    }

    log.info(
        "computed schema diff",
        extra={
            "ontology_a": ontology_a,
            "ontology_b": ontology_b,
            "summary": summary,
            "compatible": compatible,
        },
    )

    return {
        "ontology_a": ontology_a,
        "ontology_b": ontology_b,
        "classes": classes_diff,
        "properties": properties_diff,
        "constraints": constraints_diff,
        "summary": summary,
        "provenance": {
            "a": prov_a,
            "b": prov_b,
            "compatible": compatible,
            "warning": warning,
        },
    }
