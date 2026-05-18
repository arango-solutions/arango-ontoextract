"""Effective ontology computation (Stream 1 H.12 + H.13).

When an ontology imports others via ``owl:imports``, the *effective*
ontology is the union of:

* The ontology's own classes / edges / properties.
* The classes / edges / properties of every ontology in its transitive
  ``imports`` closure (ancestors, OUTBOUND from self).

This module produces a single payload combining all of the above, with
each entity annotated by ``source_ontology_id`` so the workspace canvas
(Stream 1 H.15) can render imported entities with distinct styling and
the import-aware extraction prompts (H.17) can tell the LLM which
concepts to reuse versus extend.

It is the data source for:

* ``GET /api/v1/ontology/{id}/effective`` (H.12) -- the workspace canvas
  consumes this when the target ontology has at least one live imports
  edge.
* ``serialize_effective_context`` (H.17) -- the extraction service
  flattens this into the LLM prompt so the model is told which classes
  already exist (and where they came from) before it proposes new ones.

Conflict detection (H.13) runs inline so the consumer never has to make a
second call to learn whether the merge produced ambiguous labels or
duplicate URIs.

Shape of the response:

.. code-block:: python

    {
        "ontology_id": "...",
        "ontology_name": "...",
        "include": "summary" | "full",
        "sources": [
            {"_key": "...", "name": "...", "tier": "...", "is_self": bool, "depth": int}
        ],
        "classes":    [ {... + source_ontology_id, source_ontology_name, is_imported} ],
        "edges":      [ {... + source_ontology_id, source_ontology_name, is_imported} ],
        "properties": [ {... + source_ontology_id, source_ontology_name, is_imported} ],
        "conflicts": [
            {"kind": "duplicate_uri" | "duplicate_label" | "subclass_cycle_via_import",
             "key": "...", "sources": [{"ontology_id", "ontology_name", "entity_key"}, ...],
             "message": "..."},
        ],
        "etag": "<sha256>",
        "truncated": bool,
    }

All AQL gates on ``db.has_collection(...)`` so the service runs cleanly
on freshly migrated databases that lack optional collections.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.ontology_projections import (
    INCLUDE_FULL,
    INCLUDE_SUMMARY,
    LIVE_EDGE_COLLECTIONS,
    LIVE_PROP_COLLECTIONS,
    normalize_include,
    summarize_class,
    summarize_edge,
)

log = logging.getLogger(__name__)


# Maximum depth for the transitive ``imports`` traversal. Mirrors the
# guardrail in ``ontology_imports_graph`` and ``ontology_dependency`` so
# all three services share the same notion of "too deep to be real".
DEFAULT_MAX_DEPTH = 10


def compute_effective_ontology(
    db: StandardDatabase,
    *,
    ontology_id: str,
    include: str = INCLUDE_SUMMARY,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    """Compute the effective (self + imported) ontology view.

    Parameters
    ----------
    db:
        ArangoDB handle. Caller's responsibility to close. We do not call
        ``get_db()`` so the function is trivially mockable in tests.
    ontology_id:
        Registry ``_key`` of the *target* ontology -- the one being
        viewed / edited / extracted into.
    include:
        Field-projection profile, same vocabulary as
        ``GET /{id}/classes?include=...``. Defaults to ``"summary"`` --
        the canvas consumer -- to keep the wire payload small. ``"full"``
        is supported for detail / export consumers but pulls every field
        (including ``evidence[]``), so callers should be deliberate.
    max_depth:
        Maximum number of ``imports`` hops to traverse when computing the
        closure. Defaults to :data:`DEFAULT_MAX_DEPTH`. Values < 1 are
        clamped to 1; values > 50 are clamped to 50.

    Returns
    -------
    dict
        Effective ontology payload. See module docstring for the shape.

    Raises
    ------
    ValueError
        If ``ontology_id`` is not present in ``ontology_registry``.
    """
    if not db.has_collection("ontology_registry"):
        raise ValueError("ontology_registry collection is not available")

    profile = normalize_include(include)
    safe_depth = max(1, min(int(max_depth), 50))

    self_entry = _get_registry_entry(db, ontology_id)
    if self_entry is None:
        raise ValueError(f"Ontology '{ontology_id}' not found")

    sources = _compute_source_closure(
        db,
        self_entry=self_entry,
        max_depth=safe_depth,
    )

    self_oid = ontology_id
    source_keys = [s["_key"] for s in sources]
    source_name_by_key = {s["_key"]: s.get("name") or s["_key"] for s in sources}

    classes_raw, edges_raw, props_raw = _fetch_entities_for_ontologies(db, source_keys)

    classes = _annotate_and_project(
        classes_raw,
        self_oid=self_oid,
        source_name_by_key=source_name_by_key,
        projector=summarize_class if profile == INCLUDE_SUMMARY else None,
    )
    edges = _annotate_and_project(
        edges_raw,
        self_oid=self_oid,
        source_name_by_key=source_name_by_key,
        projector=summarize_edge if profile == INCLUDE_SUMMARY else None,
    )
    properties = _annotate_and_project(
        props_raw,
        self_oid=self_oid,
        source_name_by_key=source_name_by_key,
        projector=None,
    )

    conflicts = _detect_conflicts(
        classes=classes,
        edges=edges,
        source_name_by_key=source_name_by_key,
        self_oid=self_oid,
    )

    etag = _compute_etag(
        ontology_id=ontology_id,
        include=profile,
        sources=sources,
    )

    return {
        "ontology_id": ontology_id,
        "ontology_name": self_entry.get("name") or ontology_id,
        "include": profile,
        "sources": sources,
        "classes": classes,
        "edges": edges,
        "properties": properties,
        "conflicts": conflicts,
        "etag": etag,
        "truncated": False,
    }


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------


def _compute_source_closure(
    db: StandardDatabase,
    *,
    self_entry: dict[str, Any],
    max_depth: int,
) -> list[dict[str, Any]]:
    """Return ``[self] + transitive imports``, each with depth + is_self.

    OUTBOUND from the target through ``imports`` walks the *ancestors* --
    i.e. the ontologies the target imports (directly or transitively).
    INBOUND would be "who imports me", which is a different question and
    is NOT relevant to the effective graph: a downstream consumer is not
    part of the target's own definition.

    The self entry is always included at depth 0, even if the target has
    no imports edges, so callers always see at least one source row.
    Sorted by (depth ASC, name ASC) so the wire shape is deterministic
    across re-fetches -- the canvas keys legend entries on source name
    and would otherwise flicker.
    """
    self_key = str(self_entry["_key"])
    self_source = {
        "_key": self_key,
        "name": self_entry.get("name") or self_key,
        "tier": self_entry.get("tier"),
        "status": self_entry.get("status"),
        "updated_at": _coerce_updated_at(self_entry),
        "is_self": True,
        "depth": 0,
    }

    if not db.has_collection("imports"):
        return [self_source]

    target_id = f"ontology_registry/{self_key}"
    rows = list(
        run_aql(
            db,
            """
            FOR v, e, p IN 1..@max_depth OUTBOUND @target imports
              OPTIONS { uniqueVertices: 'global', bfs: true }
              FILTER e.expired == @never
              RETURN {
                _key: v._key,
                name: v.name || v.label || v._key,
                tier: v.tier,
                status: v.status,
                updated_at: v.updated_at,
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

    seen: dict[str, dict[str, Any]] = {self_key: self_source}
    for row in rows:
        key = str(row.get("_key") or "")
        if not key or key in seen:
            continue
        seen[key] = {
            "_key": key,
            "name": row.get("name") or key,
            "tier": row.get("tier"),
            "status": row.get("status"),
            "updated_at": _coerce_updated_at(row),
            "is_self": False,
            "depth": int(row.get("depth", 1)),
        }

    return sorted(
        seen.values(),
        key=lambda s: (int(s.get("depth", 0)), str(s.get("name") or "").lower()),
    )


def _coerce_updated_at(entry: dict[str, Any]) -> Any:
    """Pick the freshest temporal marker available on a registry row.

    Registry rows historically used ``updated_at``; some older rows only
    carry ``created_at`` / ``created``. We prefer ``updated_at`` when
    present so post-import mutations bust the ETag; otherwise we fall
    back to the row's creation timestamp.
    """
    for field in ("updated_at", "modified_at", "created_at", "created"):
        val = entry.get(field)
        if val is not None:
            return val
    return None


# ---------------------------------------------------------------------------
# Entity fetch + annotation
# ---------------------------------------------------------------------------


def _fetch_entities_for_ontologies(
    db: StandardDatabase,
    ontology_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Pull live classes / edges / properties for all ontologies in one shot.

    Three AQL round-trips total (one per entity kind), each filtered by
    ``ontology_id IN @oids``. Compared to a per-ontology fan-out this is
    O(1) round-trips regardless of closure size, which matters when an
    ontology imports several large library ontologies.

    Only includes collections that actually exist. Missing collections
    contribute no rows, mirroring the behaviour of the per-ontology
    ``/classes`` and ``/edges`` endpoints on fresh databases.
    """
    if not ontology_ids:
        return [], [], []

    classes: list[dict[str, Any]] = []
    if db.has_collection("ontology_classes"):
        classes = list(
            run_aql(
                db,
                """
                FOR c IN ontology_classes
                  FILTER c.ontology_id IN @oids AND c.expired == @never
                  SORT c.label ASC
                  RETURN c
                """,
                bind_vars={"oids": ontology_ids, "never": NEVER_EXPIRES},
            )
        )

    edges = _fetch_edges_across_ontologies(db, ontology_ids)
    properties = _fetch_properties_across_ontologies(db, ontology_ids)

    return classes, edges, properties


def _fetch_edges_across_ontologies(
    db: StandardDatabase,
    ontology_ids: list[str],
) -> list[dict[str, Any]]:
    """Union live edges across every edge collection in the allow-list.

    Each row is tagged with an ``edge_type`` naming the source collection
    so downstream consumers can distinguish (e.g.) ``subclass_of`` from
    ``rdfs_range_class`` -- the canvas styles them differently.
    """
    existing = _existing_collection_names(db)
    edge_cols = tuple(c for c in LIVE_EDGE_COLLECTIONS if c in existing)
    if not edge_cols:
        return []

    subqueries = ",\n            ".join(
        f"(FOR e IN {col} FILTER e.ontology_id IN @oids AND e.expired == @never "
        f'RETURN MERGE(e, {{edge_type: "{col}"}}))'
        for col in edge_cols
    )
    query = f"LET edges = FLATTEN([\n            {subqueries}\n        ], 1)\nRETURN edges"
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"oids": ontology_ids, "never": NEVER_EXPIRES},
        )
    )
    if not rows:
        return []
    raw = cast("list[Any]", rows[0] or [])
    return [e for e in raw if isinstance(e, dict)]


def _fetch_properties_across_ontologies(
    db: StandardDatabase,
    ontology_ids: list[str],
) -> list[dict[str, Any]]:
    """Union live property docs across the property collection allow-list."""
    existing = _existing_collection_names(db)
    prop_cols = tuple(c for c in LIVE_PROP_COLLECTIONS if c in existing)
    if not prop_cols:
        return []

    subqueries = ",\n            ".join(
        f"(FOR p IN {col} FILTER p.ontology_id IN @oids AND p.expired == @never RETURN p)"
        for col in prop_cols
    )
    query = f"LET props = FLATTEN([\n            {subqueries}\n        ], 1)\nRETURN props"
    rows = list(
        run_aql(
            db,
            query,
            bind_vars={"oids": ontology_ids, "never": NEVER_EXPIRES},
        )
    )
    if not rows:
        return []
    raw = cast("list[Any]", rows[0] or [])
    return [p for p in raw if isinstance(p, dict)]


def _annotate_and_project(
    rows: list[dict[str, Any]],
    *,
    self_oid: str,
    source_name_by_key: dict[str, str],
    projector: Any,
) -> list[dict[str, Any]]:
    """Stamp every row with source info, optionally project to summary shape.

    Annotation fields are added AFTER projection so they survive the
    allow-list strip. This is deliberate: ``source_ontology_id`` is part
    of the effective-graph wire contract, not the per-ontology projection
    contract, so the projection module does not need to know about it.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        oid = str(row.get("ontology_id") or "")
        projected = projector(row) if projector is not None else dict(row)
        projected["source_ontology_id"] = oid
        projected["source_ontology_name"] = source_name_by_key.get(oid, oid or "unknown")
        projected["is_imported"] = bool(oid and oid != self_oid)
        out.append(projected)
    return out


# ---------------------------------------------------------------------------
# Conflict detection (H.13)
# ---------------------------------------------------------------------------


def _detect_conflicts(
    *,
    classes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_name_by_key: dict[str, str],
    self_oid: str,
) -> list[dict[str, Any]]:
    """Find merge conflicts across imported ontologies.

    Three kinds are detected:

    * ``duplicate_uri`` -- the same ``uri`` appears in two or more
      *different* ``source_ontology_id``s. Same-ontology duplicates are
      a writer bug, not a merge conflict, and are filtered upstream by
      the per-ontology projection path.
    * ``duplicate_label`` -- the same ``label`` (case-insensitive,
      whitespace-stripped) appears in two or more different sources with
      *different* URIs. Same-URI duplicates would already surface as
      ``duplicate_uri`` and are skipped here to avoid double-reporting.
    * ``subclass_cycle_via_import`` -- the merged ``subclass_of`` edge
      set forms a cycle that no single source ontology contains. (A
      cycle inside one ontology is a writer bug, not a merge effect.)

    Same-source duplicates are intentionally NOT flagged: those are
    writer bugs that the per-ontology API surface owns, not effects of
    the merge. The conflict report's job is to tell the *importer* what
    they need to disambiguate before publishing.
    """
    conflicts: list[dict[str, Any]] = []
    conflicts.extend(_uri_conflicts(classes, source_name_by_key))
    conflicts.extend(_label_conflicts(classes, source_name_by_key))
    conflicts.extend(_cycle_conflicts(edges, classes, source_name_by_key, self_oid))
    return conflicts


def _uri_conflicts(
    classes: list[dict[str, Any]],
    source_name_by_key: dict[str, str],
) -> list[dict[str, Any]]:
    by_uri: dict[str, list[dict[str, Any]]] = {}
    for cls in classes:
        uri = str(cls.get("uri") or "").strip()
        if not uri:
            continue
        by_uri.setdefault(uri, []).append(cls)

    out: list[dict[str, Any]] = []
    for uri, members in by_uri.items():
        sources = {
            str(m.get("source_ontology_id") or "") for m in members if m.get("source_ontology_id")
        }
        if len(sources) < 2:
            continue
        out.append(
            {
                "kind": "duplicate_uri",
                "key": uri,
                "sources": [
                    {
                        "ontology_id": str(m.get("source_ontology_id") or ""),
                        "ontology_name": source_name_by_key.get(
                            str(m.get("source_ontology_id") or ""),
                            str(m.get("source_ontology_id") or ""),
                        ),
                        "entity_key": str(m.get("_key") or ""),
                    }
                    for m in members
                ],
                "message": (
                    f"URI '{uri}' is defined in {len(sources)} imported ontologies; "
                    "consumers may see ambiguous resolution."
                ),
            }
        )
    return sorted(out, key=lambda c: cast(str, c["key"]))


def _label_conflicts(
    classes: list[dict[str, Any]],
    source_name_by_key: dict[str, str],
) -> list[dict[str, Any]]:
    by_label: dict[str, list[dict[str, Any]]] = {}
    for cls in classes:
        label = str(cls.get("label") or "").strip().lower()
        if not label:
            continue
        by_label.setdefault(label, []).append(cls)

    out: list[dict[str, Any]] = []
    for label, members in by_label.items():
        uris = {str(m.get("uri") or "") for m in members if m.get("uri")}
        sources = {
            str(m.get("source_ontology_id") or "") for m in members if m.get("source_ontology_id")
        }
        if len(sources) < 2 or len(uris) < 2:
            continue
        out.append(
            {
                "kind": "duplicate_label",
                "key": label,
                "sources": [
                    {
                        "ontology_id": str(m.get("source_ontology_id") or ""),
                        "ontology_name": source_name_by_key.get(
                            str(m.get("source_ontology_id") or ""),
                            str(m.get("source_ontology_id") or ""),
                        ),
                        "entity_key": str(m.get("_key") or ""),
                    }
                    for m in members
                ],
                "message": (
                    f"Label '{members[0].get('label')}' is reused by {len(sources)} "
                    "imported ontologies with different URIs; the canvas may show "
                    "indistinguishable nodes."
                ),
            }
        )
    return sorted(out, key=lambda c: cast(str, c["key"]))


def _cycle_conflicts(
    edges: list[dict[str, Any]],
    classes: list[dict[str, Any]],
    source_name_by_key: dict[str, str],
    self_oid: str,
) -> list[dict[str, Any]]:
    """Detect subclass cycles that only exist after merging.

    We build a directed graph from live ``subclass_of`` edges where
    ``_from`` is the child and ``_to`` is the parent (i.e. an edge
    indicates "child IS-A parent"), then look for cycles via iterative
    DFS. Each cycle is reported once per cycle, using the smallest class
    ``_id`` in the cycle as the deterministic ``key`` so the wire shape
    is stable across re-fetches.
    """
    graph: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        if edge.get("edge_type") != "subclass_of":
            continue
        frm = str(edge.get("_from") or "")
        to = str(edge.get("_to") or "")
        if not frm or not to:
            continue
        graph.setdefault(frm, []).append((to, str(edge.get("source_ontology_id") or "")))

    if not graph:
        return []

    class_by_id: dict[str, dict[str, Any]] = {}
    for cls in classes:
        cid = str(cls.get("_id") or "")
        if cid:
            class_by_id[cid] = cls

    cycles_seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []

    for start in list(graph.keys()):
        stack: list[tuple[str, list[str], list[str]]] = [(start, [start], [])]
        while stack:
            node, path, edge_sources = stack.pop()
            for nxt, edge_src in graph.get(node, []):
                if nxt in path:
                    cycle_nodes = [*path[path.index(nxt) :], nxt]
                    canonical = _canonicalise_cycle(cycle_nodes)
                    if canonical in cycles_seen:
                        continue
                    cycles_seen.add(canonical)
                    cycle_edge_sources = [*edge_sources, edge_src]
                    if not _cycle_requires_import(cycle_edge_sources, self_oid):
                        continue
                    out.append(_format_cycle_conflict(canonical, class_by_id, source_name_by_key))
                else:
                    stack.append((nxt, [*path, nxt], [*edge_sources, edge_src]))

    return sorted(out, key=lambda c: cast(str, c["key"]))


def _canonicalise_cycle(nodes: list[str]) -> tuple[str, ...]:
    """Rotate the cycle so the lexicographically smallest node is first.

    Two traversals can hit the same cycle starting from different nodes;
    without canonicalisation we would report the cycle once per member.
    The last entry of ``nodes`` is the closing node (== first); we drop
    it before rotating so the cycle is rendered as a single open list.
    """
    if not nodes:
        return tuple()
    body = nodes[:-1] if len(nodes) > 1 and nodes[0] == nodes[-1] else nodes
    if not body:
        return tuple()
    min_idx = min(range(len(body)), key=lambda i: body[i])
    rotated = body[min_idx:] + body[:min_idx]
    return tuple(rotated)


def _cycle_requires_import(edge_sources: list[str], self_oid: str) -> bool:
    """True if the cycle traverses at least one imported source.

    A cycle that lives entirely inside the self ontology is a writer bug
    in the local ontology and is owned by the per-ontology validation
    surface, not by the merge conflict report.
    """
    return any(src and src != self_oid for src in edge_sources)


def _format_cycle_conflict(
    cycle_nodes: tuple[str, ...],
    class_by_id: dict[str, dict[str, Any]],
    source_name_by_key: dict[str, str],
) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    labels: list[str] = []
    for cid in cycle_nodes:
        cls = class_by_id.get(cid)
        if cls is None:
            labels.append(cid)
            continue
        labels.append(str(cls.get("label") or cls.get("uri") or cid))
        oid = str(cls.get("source_ontology_id") or "")
        members.append(
            {
                "ontology_id": oid,
                "ontology_name": source_name_by_key.get(oid, oid or "unknown"),
                "entity_key": str(cls.get("_key") or ""),
            }
        )

    return {
        "kind": "subclass_cycle_via_import",
        "key": " -> ".join(cycle_nodes),
        "sources": members,
        "message": (
            "Merging imported ontologies introduces a subclass cycle: "
            + " -> ".join(labels)
            + ". Review the import set or remove one of the offending subclass edges."
        ),
    }


# ---------------------------------------------------------------------------
# ETag
# ---------------------------------------------------------------------------


def _compute_etag(
    *,
    ontology_id: str,
    include: str,
    sources: list[dict[str, Any]],
) -> str:
    """Hash of ``(self id, include profile, every source's freshest mtime)``.

    Cache invalidates naturally when any participating ontology mutates
    (registry ``updated_at`` bumps) or when the closure changes (add/
    remove an import edge changes the source set membership). Include
    profile is part of the key so ``summary`` and ``full`` cannot
    collide.
    """
    parts: list[str] = [f"oid={ontology_id}", f"include={include}"]
    for src in sources:
        key = src.get("_key") or ""
        mtime = src.get("updated_at")
        parts.append(f"{key}:{mtime}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f'W/"{digest[:32]}"'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_registry_entry(db: StandardDatabase, ontology_id: str) -> dict[str, Any] | None:
    try:
        doc = db.collection("ontology_registry").get(ontology_id)
    except Exception:
        return None
    return cast("dict[str, Any] | None", doc)


def _existing_collection_names(db: StandardDatabase) -> set[str]:
    """Return the set of collection names that currently exist on ``db``.

    python-arango types ``db.collections()`` as a sync-vs-async union
    (``list[dict] | AsyncJob | BatchJob | None``); in synchronous mode it
    always returns the list. Centralising the narrow here keeps the
    callers focussed on intent rather than type plumbing.
    """
    collections = cast("list[dict[str, Any]]", db.collections() or [])
    return {col["name"] for col in collections if isinstance(col, dict) and "name" in col}


# Re-export INCLUDE_FULL so callers can build their own profile checks
# without round-tripping through ``ontology_projections``.
__all__ = [
    "DEFAULT_MAX_DEPTH",
    "INCLUDE_FULL",
    "INCLUDE_SUMMARY",
    "compute_effective_ontology",
]
