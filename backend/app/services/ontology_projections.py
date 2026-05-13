"""Field projections for ontology API responses.

Two projection profiles are supported by the workspace API:

``full``
    The legacy shape: every field on the document is returned. This is what
    detail panels, exporters, and provenance views need because they render
    ``evidence[]`` arrays, full ``description`` text, scoring breakdowns,
    and the ``_rev`` token.

``summary``
    A narrow allow-list of the fields the workspace canvas + asset explorer
    actually consume to paint nodes and edges. Specifically, ``evidence[]``
    and ``parent_evidence[]`` are dropped -- on the WTW Ontology those two
    fields make up **38 %** of the ``/classes`` payload (366 KB of 943 KB)
    and **22 %** of the ``/edges`` payload (133 KB of 581 KB), and neither
    is read by the canvas. ``embedding`` is also dropped as a defensive
    measure in case it is ever materialised onto class/edge documents
    (currently embeddings live on a side collection); a 1536-dim float
    vector serialises to ~12 KB per row.

Why allow-list rather than deny-list
------------------------------------

A deny-list ("everything except these three fields") would silently leak
any new heavy field a future writer adds. The allow-list makes the wire
contract for ``summary`` explicit and stable: when someone adds a new
field to the writer, the API response shape does not change until they
also extend this module. That keeps payload regressions reviewable.

Why project in AQL rather than Python
-------------------------------------

The backend talks to a remote ArangoDB over WAN. Projecting fields in
Python still pulls every byte across the WAN. The ``CLASS_SUMMARY_AQL``
and ``EDGE_SUMMARY_AQL`` projections push the allow-list into the
``RETURN { ... }`` clause so the bytes never leave Arango. Combined
with the in-Python helpers (used by single-item endpoints that already
have the full document in hand), every code path produces the same
shape.
"""

from __future__ import annotations

from typing import Any, Final


# ---------------------------------------------------------------------------
# Allow-list of fields kept in the summary projection.
# ---------------------------------------------------------------------------
#
# Class summary fields, in roughly the order the workspace canvas reads them:
#   * identity:     _key, _id, uri, ontology_id
#   * display:      label, description, rdf_type, tier, status, parent_uri
#   * lenses:       confidence, faithfulness_score, semantic_validity_score
#   * temporal:     created, expired
#   * provenance:   extraction_run_id  (used by run-filter chips)
#
# Dropped: evidence, parent_evidence, embedding, _rev.

CLASS_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "_key",
    "_id",
    "uri",
    "ontology_id",
    "label",
    "description",
    "rdf_type",
    "tier",
    "status",
    "parent_uri",
    "confidence",
    "faithfulness_score",
    "semantic_validity_score",
    "created",
    "expired",
    "extraction_run_id",
)


# Edge summary fields, in roughly the order the workspace canvas reads them:
#   * identity:    _key, _id, _from, _to, ontology_id
#   * display:     edge_type, label, description, status
#   * lenses:      confidence
#   * temporal:    created, expired
#
# Dropped: evidence, embedding, _rev.
#
# Note: the rdfs_range_class enrichment (which lifts label / description /
# confidence from the owning property document) runs BEFORE projection in
# ``list_ontology_edges``, so those merged values are preserved.

EDGE_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "_key",
    "_id",
    "_from",
    "_to",
    "ontology_id",
    "edge_type",
    "label",
    "description",
    "status",
    "confidence",
    "created",
    "expired",
)


# ---------------------------------------------------------------------------
# AQL projection clauses.
# ---------------------------------------------------------------------------
#
# Generated from the Python tuples so the AQL stays in lockstep with the
# in-Python helpers. The variable name in the AQL must match the FOR loop
# variable of the caller -- both endpoints use ``c`` for class loops and
# ``e`` for edge loops.

def _aql_return_clause(var: str, fields: tuple[str, ...]) -> str:
    """Build a ``RETURN { _key: c._key, ... }`` clause for the given fields.

    AQL uses dot-notation for field access on a document variable. Missing
    fields evaluate to ``null`` rather than raising, which matches the
    Python ``.get()`` behaviour on dictionaries -- so optional fields
    (``tier``, ``status``, ``parent_uri``, ...) come back as ``null`` for
    documents that do not have them.
    """
    return "RETURN { " + ", ".join(f"{name}: {var}.{name}" for name in fields) + " }"


CLASS_SUMMARY_RETURN: Final[str] = _aql_return_clause("c", CLASS_SUMMARY_FIELDS)
EDGE_SUMMARY_RETURN: Final[str] = _aql_return_clause("e", EDGE_SUMMARY_FIELDS)


# ---------------------------------------------------------------------------
# In-Python projection helpers.
# ---------------------------------------------------------------------------
#
# Used after the AQL has already returned a full document and we want to
# project it down (e.g. in tests, or in code paths that compute fields in
# Python like ``compute_edge_confidence`` and need the merged-then-projected
# shape). Returns a NEW dict so the caller can mutate the original safely.

def summarize_class(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a ``CLASS_SUMMARY_FIELDS``-only copy of ``doc``.

    Missing fields are returned as ``None`` to match the AQL projection's
    ``null`` semantics for absent attributes -- this keeps the wire shape
    stable regardless of which projection path produced it.
    """
    return {name: doc.get(name) for name in CLASS_SUMMARY_FIELDS}


def summarize_edge(doc: dict[str, Any]) -> dict[str, Any]:
    """Return an ``EDGE_SUMMARY_FIELDS``-only copy of ``doc``.

    See ``summarize_class`` for the rationale around missing-field handling.
    """
    return {name: doc.get(name) for name in EDGE_SUMMARY_FIELDS}


# ---------------------------------------------------------------------------
# Query-parameter parsing.
# ---------------------------------------------------------------------------

#: Valid values for the ``?include=`` query parameter on /classes and /edges.
INCLUDE_FULL: Final[str] = "full"
INCLUDE_SUMMARY: Final[str] = "summary"
VALID_INCLUDE_VALUES: Final[frozenset[str]] = frozenset({INCLUDE_FULL, INCLUDE_SUMMARY})


def normalize_include(value: str | None) -> str:
    """Normalise the ``?include=`` query value to one of the valid profiles.

    Defaults to ``"full"`` for backwards compatibility with existing
    consumers (exports, detail panels, third-party scripts) that depend
    on the legacy field set. Unknown values fall back to ``"full"`` rather
    than raising, because a stricter contract here would break callers
    that send a typo for what they think is a hint.
    """
    if value is None:
        return INCLUDE_FULL
    lowered = value.strip().lower()
    if lowered in VALID_INCLUDE_VALUES:
        return lowered
    return INCLUDE_FULL
