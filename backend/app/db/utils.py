"""Shared database utilities used across repository modules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def existing_collection_names(db: StandardDatabase) -> set[str] | None:
    """Snapshot the database's collection names in ONE round-trip.

    python-arango's ``has_collection`` issues a full HTTP request per probe;
    code paths that probe many collections against a remote (cloud/WAN)
    ArangoDB pay ~0.2s per probe. Fetching ``db.collections()`` once and
    membership-testing the returned set replaces N round-trips with one.

    Returns ``None`` when the snapshot cannot be taken or comes back empty
    (mocked connections in unit tests iterate as empty, and a real database
    always exposes at least its system collections) so callers can fall back
    to per-call ``has_collection`` probes.
    """
    try:
        names = {c["name"] for c in db.collections()}  # type: ignore[union-attr]
    except Exception:
        return None
    return names or None


def run_aql(
    db: StandardDatabase,
    query: str,
    bind_vars: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Cursor:
    """Execute an AQL query and return a Cursor.

    python-arango types ``aql.execute`` as returning
    ``Cursor | AsyncJob | BatchJob | None`` but in synchronous mode
    it always returns ``Cursor``.  This wrapper narrows the type so
    callers don't need ``cast()`` at every call-site.
    """
    result = db.aql.execute(query, bind_vars=bind_vars, **kwargs)
    return cast(Cursor, result)


def doc_get(collection: Any, key: str) -> dict[str, Any] | None:
    """Get a document by key, returning a typed dict or None.

    python-arango types ``collection.get`` as returning
    ``dict | AsyncJob | BatchJob | None``.  In synchronous mode it
    always returns ``dict | None``.
    """
    result = collection.get(key)
    return cast("dict[str, Any] | None", result)


def insert_temporal_edge_if_absent(
    db: StandardDatabase,
    collection: Any,
    *,
    from_id: str,
    to_id: str,
    ontology_id: str,
    now: float,
    extra_fields: dict[str, Any] | None = None,
) -> bool:
    """Insert a temporal edge iff no live edge with the same endpoint
    triple ``(_from, _to, ontology_id)`` already exists.

    Why this exists
    ---------------
    Several extraction-pipeline writers (``rdfs_domain``,
    ``rdfs_range_class``, ``subclass_of``) historically issued bare
    ``collection.insert()`` calls without checking whether an
    existing live edge already represented the same logical
    relationship. Re-extracting the same class from a second
    document then duplicated the edge, leaving N>1 live rows where
    exactly one was expected. This broke downstream readers that
    assume "one edge per logical relationship" -- the workspace
    ``FloatingDetailPanel`` was the first to surface the symptom
    (React duplicate-key warning on the relationships list).

    The dedup-on-read pattern in
    :func:`app.api.ontology.get_class_detail` hides the symptom on
    the read side; this helper closes the bug on the write side so
    new extractions don't keep accumulating duplicate edges.

    Behaviour
    ---------
    Returns ``True`` if a new edge was inserted, ``False`` if an
    existing live edge was kept and no insert happened. Idempotent:
    safe to call from every extraction pass without coordinating
    between them.

    Notes
    -----
    This does NOT supersede an existing live edge. The contract for
    these structural edges is that the relationship carries no
    per-version state of its own (label / confidence / evidence
    live on the connected property document), so the original
    ``created`` timestamp is preserved -- the resulting provenance
    reads "this relationship has held since X" rather than "since
    the most recent re-extraction", which is more useful.

    For edges that DO carry per-version state (confidence, evidence,
    weight) use :func:`app.services.temporal.update_entity` instead;
    that path supersedes the prior version (expires it, inserts a
    new one) so the new payload becomes the live row.
    """
    cname = collection.name
    cursor = run_aql(
        db,
        f"FOR e IN {cname} "
        "FILTER e._from == @f AND e._to == @t "
        "  AND e.ontology_id == @oid AND e.expired == @never "
        "LIMIT 1 RETURN 1",
        bind_vars={
            "f": from_id,
            "t": to_id,
            "oid": ontology_id,
            "never": NEVER_EXPIRES,
        },
    )
    if next(cursor, None) is not None:
        return False

    # Canonical fields are written last so they win over any same-keyed
    # entry in ``extra_fields``. This is intentional defence-in-depth:
    # the helper's idempotency contract depends on every inserted edge
    # carrying ``expired == NEVER_EXPIRES`` (the probe filters on it),
    # and a caller that mistakenly passes ``extra_fields={"expired":
    # something_else}`` would otherwise silently break the contract for
    # that edge -- subsequent calls would re-insert a duplicate.
    doc: dict[str, Any] = dict(extra_fields or {})
    doc.update(
        {
            "_from": from_id,
            "_to": to_id,
            "ontology_id": ontology_id,
            "created": now,
            "expired": NEVER_EXPIRES,
        }
    )
    collection.insert(doc)
    return True
