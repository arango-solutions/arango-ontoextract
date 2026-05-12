"""Find and expire pre-existing duplicate live structural edges.

Companion to :func:`app.db.utils.insert_temporal_edge_if_absent` -- the
helper closes the duplicate-edge bug on the *write* side, but ontologies
extracted before that fix landed (see commit history around the
``FloatingDetailPanel`` duplicate-key warning) carry historical
duplicates that need a one-shot cleanup.

What counts as a "duplicate"
----------------------------

For the structural edges this module supports
(``rdfs_domain`` / ``rdfs_range_class``), a duplicate is any group
of >=2 live edges that share an identical
``(_from, _to, ontology_id)`` triple. Because these edges carry no
per-edge state (label / confidence / evidence live on the connected
property document, not on the edge), every member of such a group
represents the *same* logical relationship. Keeping all of them
breaks the "one edge per logical relationship" contract every
downstream reader assumes -- the workspace
``FloatingDetailPanel`` was the first to surface the symptom.

What we keep, what we expire
----------------------------

For each duplicate group we keep the edge with the **smallest
``created``** timestamp. Rationale: the earliest extraction
"discovered" the relationship, so its provenance reads "this
relationship has held since X" rather than "since the most recent
re-extraction" -- which matches the contract the
:func:`insert_temporal_edge_if_absent` writer now enforces going
forward. Tiebreaker on ``_key`` for determinism so re-running the
dedup against the same data produces identical reports.

Every expired edge is stamped with
``dedup_meta = {"source": DEDUP_SOURCE_MARKER, "reason":
"duplicate_pair"}`` so a future audit query (or undo migration)
can find every edge this module touched.

Scope
-----

Only collections in :data:`DEDUPABLE_COLLECTIONS` are accepted.
``subclass_of`` is intentionally excluded even though its bare
inserter has the same shape: that edge carries an ``evidence``
list and a future writer fix should *merge* evidence rather than
discard it -- a different problem with a different cleanup
contract. Including it here would silently drop evidence on the
floor.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


DEDUP_SOURCE_MARKER = "edge_dedup_v1"

#: Collections whose duplicate live edges this module is allowed to
#: expire. Keep this allowlist tight -- adding a collection here
#: implicitly asserts "this edge has no per-edge state, so collapsing
#: duplicates loses no information".
DEDUPABLE_COLLECTIONS = frozenset({
    "rdfs_domain",
    "rdfs_range_class",
})


@dataclass
class DedupedPair:
    """One duplicate group: which edge we kept, which we expired."""

    pair: str  # "<from>|<to>", for human-readable audit logs
    kept_key: str
    expired_keys: list[str]


@dataclass
class DedupReport:
    ontology_id: str
    collection: str
    dry_run: bool
    pairs_with_duplicates: int = 0
    extra_edges: int = 0  # total edges that would be / were expired
    deduped: list[DedupedPair] = field(default_factory=list)
    skipped_collection_missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ontology_id": self.ontology_id,
            "collection": self.collection,
            "dry_run": self.dry_run,
            "pairs_with_duplicates": self.pairs_with_duplicates,
            "extra_edges": self.extra_edges,
            "skipped_collection_missing": self.skipped_collection_missing,
            "deduped": [
                {
                    "pair": d.pair,
                    "kept_key": d.kept_key,
                    "expired_keys": list(d.expired_keys),
                }
                for d in self.deduped
            ],
        }


def dedupe_live_edges(
    db: Any,
    ontology_id: str,
    collection: str,
    *,
    dry_run: bool = True,
) -> DedupReport:
    """Find (and optionally expire) duplicate live edges in one collection.

    ``dry_run=True`` returns a populated report without touching any
    edges -- safe to call repeatedly to preview a cleanup. With
    ``dry_run=False`` the report covers the same set of duplicates
    and the corresponding ``expired_keys`` rows have been updated
    in-place to ``expired = <now>`` plus the audit ``dedup_meta``
    field. Idempotent: a second non-dry-run call against the same
    collection finds zero duplicates and is a no-op.

    Raises
    ------
    ValueError
        If ``collection`` is not in :data:`DEDUPABLE_COLLECTIONS`.
        Refusing unknown collections is the only safe behaviour --
        a typo in the admin endpoint must not silently expire rows
        in a collection whose edges *do* carry per-edge state.
    """
    if collection not in DEDUPABLE_COLLECTIONS:
        raise ValueError(
            f"collection {collection!r} is not in the dedup allowlist "
            f"{sorted(DEDUPABLE_COLLECTIONS)}. Refusing to operate."
        )

    report = DedupReport(
        ontology_id=ontology_id, collection=collection, dry_run=dry_run
    )

    if not db.has_collection(collection):
        report.skipped_collection_missing = True
        log.info(
            "edge_dedup: collection %r missing for ontology %s -- "
            "nothing to do",
            collection,
            ontology_id,
        )
        return report

    # Pull every duplicate group in one pass. We sort each group's
    # edges by (created ASC, _key ASC) inside AQL so the "kept" edge
    # is deterministically the first element regardless of insert
    # order -- important for reproducibility of the audit log.
    groups = list(
        run_aql(
            db,
            f"FOR e IN {collection} "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT pair = CONCAT(e._from, \"|\", e._to) INTO group "
            "FILTER LENGTH(group) > 1 "
            "LET edges = ("
            "  FOR g IN group "
            "  SORT g.e.created ASC, g.e._key ASC "
            "  RETURN {_key: g.e._key, created: g.e.created}"
            ") "
            "RETURN {pair: pair, edges: edges}",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )

    if not groups:
        return report

    keys_to_expire: list[str] = []

    for grp in groups:
        edges = grp.get("edges") or []
        if len(edges) < 2:
            # Defensive: the AQL filter already guarantees this,
            # but a malformed COLLECT result shouldn't crash the
            # cleanup.
            continue
        kept = edges[0]["_key"]
        extras = [e["_key"] for e in edges[1:]]
        report.deduped.append(
            DedupedPair(pair=grp["pair"], kept_key=kept, expired_keys=extras)
        )
        report.pairs_with_duplicates += 1
        report.extra_edges += len(extras)
        keys_to_expire.extend(extras)

    if dry_run or not keys_to_expire:
        return report

    now = time.time()
    # Single bulk UPDATE for efficiency. We stamp ``dedup_meta`` so a
    # future audit / undo can find these via
    # ``FILTER e.dedup_meta.source == @marker``.
    run_aql(
        db,
        f"FOR e IN {collection} "
        "FILTER e._key IN @keys "
        "UPDATE e WITH { "
        "  expired: @now, "
        "  dedup_meta: { source: @marker, reason: \"duplicate_pair\" } "
        f"}} IN {collection}",
        bind_vars={
            "keys": keys_to_expire,
            "now": now,
            "marker": DEDUP_SOURCE_MARKER,
        },
    )
    log.info(
        "edge_dedup: expired %d duplicate %s edges across %d pairs "
        "in ontology %s",
        len(keys_to_expire),
        collection,
        report.pairs_with_duplicates,
        ontology_id,
    )
    return report
