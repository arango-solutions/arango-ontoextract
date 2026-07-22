"""Alignment incoherence detection + minimally-destructive modular repair.

Stream 20 / AL-PR7, PRD §6.17 FR-17.5.

When accepted correspondences are transitively clustered into equivalence classes
(A≡B, B≡C ⇒ one master class), a cluster can become *incoherent*: two of its
members are declared ``disjoint_with`` each other in their source ontology, yet
the alignment now asserts they are equivalent — an unsatisfiable class. This is
the classic OAEI/AML incoherence: two disjoint source classes both aligned onto a
common target, transitively merging the disjoint pair.

Repair follows AML's *core-fragment / minimally-destructive* principle: rather
than discarding the whole cluster, find the correspondences on the path that
connects the disjoint pair and remove the single **lowest-confidence** one, then
re-cluster and re-check. Iterate until coherent. Every removal is reported (with
the conflict it resolved) — never silent.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# A source class identity across the alignment space.
Node = tuple[str, str]  # (ontology_id, entity_key)


def _corr_nodes(c: dict[str, Any]) -> tuple[Node, Node]:
    a = c.get("source_a") or {}
    b = c.get("source_b") or {}
    return (
        (str(a.get("ontology_id")), str(a.get("entity_key"))),
        (str(b.get("ontology_id")), str(b.get("entity_key"))),
    )


def _confidence(c: dict[str, Any]) -> float:
    try:
        return float(c.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_disjoint_pairs(
    db: StandardDatabase | None,
    ontology_ids: list[str],
) -> set[frozenset[Node]]:
    """Collect declared ``disjoint_with`` class pairs across the source ontologies.

    Returns a set of ``frozenset({node_a, node_b})`` where each node is
    ``(ontology_id, entity_key)``. Empty when the collection is absent (the common
    case — the extraction pipeline rarely materializes disjointness), so repair is
    a no-op and materialization is unchanged.
    """
    if db is None:
        db = get_db()
    if not ontology_ids or not db.has_collection("disjoint_with"):
        return set()
    rows = run_aql(
        db,
        """
        FOR dw IN disjoint_with
          FILTER dw.ontology_id IN @oids AND dw.expired == @never
          RETURN {oid: dw.ontology_id, from: dw._from, to: dw._to}
        """,
        bind_vars={"oids": list(ontology_ids), "never": NEVER_EXPIRES},
    )
    pairs: set[frozenset[Node]] = set()
    for r in rows:
        oid = str(r.get("oid"))
        fkey = str(r.get("from") or "").split("/")[-1]
        tkey = str(r.get("to") or "").split("/")[-1]
        if fkey and tkey and fkey != tkey:
            pairs.add(frozenset({(oid, fkey), (oid, tkey)}))
    return pairs


def _clusters(correspondences: list[dict[str, Any]]) -> dict[Node, int]:
    """Union-find over correspondence edges → ``node -> cluster id``."""
    parent: dict[Node, Node] = {}

    def find(x: Node) -> Node:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: Node, b: Node) -> None:
        parent[find(a)] = find(b)

    for c in correspondences:
        na, nb = _corr_nodes(c)
        union(na, nb)

    roots: dict[Node, int] = {}
    out: dict[Node, int] = {}
    for node in parent:
        r = find(node)
        out[node] = roots.setdefault(r, len(roots))
    return out


def _path_correspondences(
    correspondences: list[dict[str, Any]], src: Node, dst: Node
) -> list[dict[str, Any]]:
    """BFS the correspondence graph for a shortest path ``src``→``dst``.

    Returns the correspondences (edges) along that path, or ``[]`` if disconnected.
    """
    adj: dict[Node, list[tuple[Node, dict[str, Any]]]] = {}
    for c in correspondences:
        na, nb = _corr_nodes(c)
        adj.setdefault(na, []).append((nb, c))
        adj.setdefault(nb, []).append((na, c))

    if src not in adj or dst not in adj:
        return []
    prev: dict[Node, tuple[Node, dict[str, Any]] | None] = {src: None}
    q: deque[Node] = deque([src])
    while q:
        cur = q.popleft()
        if cur == dst:
            break
        for nxt, edge in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, edge)
                q.append(nxt)
    if dst not in prev:
        return []
    edges: list[dict[str, Any]] = []
    node = dst
    while prev[node] is not None:
        parent_node, edge = prev[node]  # type: ignore[misc]
        edges.append(edge)
        node = parent_node
    return edges


def _find_conflict(
    clusters: dict[Node, int], disjoint_pairs: set[frozenset[Node]]
) -> tuple[Node, Node] | None:
    """Return a disjoint pair that shares a cluster (incoherent), else ``None``."""
    for pair in disjoint_pairs:
        a, b = tuple(pair)
        if a in clusters and b in clusters and clusters[a] == clusters[b]:
            return (a, b)
    return None


def repair_correspondences(
    correspondences: list[dict[str, Any]],
    disjoint_pairs: set[frozenset[Node]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(kept, removals)`` such that no disjoint pair shares a cluster.

    Greedy, minimally-destructive: while an incoherent cluster exists, take the
    correspondences on a path connecting the disjoint pair and drop the
    lowest-confidence one (ties → lexicographically smallest ``_key`` for
    determinism). Re-cluster and repeat. Each removal records the conflict it
    resolved.
    """
    kept = list(correspondences)
    removals: list[dict[str, Any]] = []

    # Bound the loop by the number of edges — each iteration removes exactly one.
    for _ in range(len(correspondences) + 1):
        conflict = _find_conflict(_clusters(kept), disjoint_pairs)
        if conflict is None:
            return kept, removals
        d1, d2 = conflict
        path = _path_correspondences(kept, d1, d2)
        if not path:
            # Same cluster but no path found (shouldn't happen); stop to be safe.
            break
        victim = min(path, key=lambda c: (_confidence(c), str(c.get("_key") or "")))
        kept.remove(victim)
        va, vb = _corr_nodes(victim)
        removals.append(
            {
                "correspondence_key": victim.get("_key"),
                "confidence": _confidence(victim),
                "removed_edge": {"a": list(va), "b": list(vb)},
                "resolves_conflict": {"a": list(d1), "b": list(d2)},
                "reason": "coherence_repair_disjoint_equivalence",
            }
        )
        log.info(
            "[alignment] repair removed correspondence %s (conf=%.3f) to resolve "
            "disjoint↔equivalent conflict %s≡%s",
            victim.get("_key"),
            _confidence(victim),
            d1,
            d2,
        )

    return kept, removals


def check_alignment_coherence(
    db: StandardDatabase | None,
    *,
    correspondences: list[dict[str, Any]],
    ontology_ids: list[str],
) -> dict[str, Any]:
    """Dry-run coherence report over a correspondence set (no writes).

    Returns ``{coherent, conflicts, proposed_removals, kept}`` where ``conflicts``
    counts incoherent clusters before repair.
    """
    disjoint_pairs = build_disjoint_pairs(db, ontology_ids)
    incoherent_before = _find_conflict(_clusters(correspondences), disjoint_pairs) is not None
    kept, removals = repair_correspondences(correspondences, disjoint_pairs)
    return {
        "coherent": not incoherent_before,
        "disjoint_axioms": len(disjoint_pairs),
        "proposed_removals": removals,
        "removed_count": len(removals),
        "kept_count": len(kept),
    }
