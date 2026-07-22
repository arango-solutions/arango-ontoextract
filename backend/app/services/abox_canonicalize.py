"""A-box canonicalization / entity linking (Stream 21 / AB-PR3, PRD §6.18 FR-18.4).

AB-PR2 collapses coreferent mentions by exact (class, normalized-label) within a
single extraction run. AB-PR3 goes further: it finds individuals of the *same
type* whose labels are near-duplicates (Jaro-Winkler ≥ threshold) across the
persisted A-box and merges them into a golden individual — reassigning their
assertion edges, unioning provenance, and temporally expiring the duplicate.

Only same-type individuals are compared (a Person and an Organization with
similar names must not merge). Merging is a curated action: detection returns
candidates for review; ``auto_merge`` is opt-in for high-confidence runs.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from arango.database import StandardDatabase

from app.db import individuals_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services import matching
from app.services.temporal import expire_entity

log = logging.getLogger(__name__)

_INDIVIDUALS = "ontology_individuals"
_RDF_TYPE = "rdf_type"
_ASSERTION = "individual_assertion"


def find_individual_duplicates(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    min_score: float = 0.85,
) -> list[dict[str, Any]]:
    """Find same-type near-duplicate individuals by label similarity.

    Returns candidate merges ``{keep_key, drop_key, keep_label, drop_label,
    type, score}`` sorted by score desc. ``keep`` is the individual grounded in
    more source spans (tie → lexicographically smaller key), so the survivor is
    the better-evidenced one.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(_INDIVIDUALS):
        return []

    rows = list(
        run_aql(
            db,
            f"""
            FOR i IN {_INDIVIDUALS}
              FILTER i.ontology_id == @oid AND i.expired == @never
              LET t = FIRST(
                FOR e IN {_RDF_TYPE}
                  FILTER e._from == i._id AND e.expired == @never
                  RETURN e._to
              )
              RETURN {{key: i._key, label: i.label, type: t, prov: LENGTH(i.provenance)}}
            """,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )

    by_type: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_type[r.get("type")].append(r)

    out: list[dict[str, Any]] = []
    for group in by_type.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                score = matching.jaro_winkler_sim(
                    str(a.get("label") or ""), str(b.get("label") or "")
                )
                if score < min_score:
                    continue
                # keep = more provenance; tie -> smaller key
                a_rank = (int(a.get("prov") or 0), _neg_key(a["key"]))
                b_rank = (int(b.get("prov") or 0), _neg_key(b["key"]))
                keep, drop = (a, b) if a_rank >= b_rank else (b, a)
                out.append(
                    {
                        "keep_key": keep["key"],
                        "drop_key": drop["key"],
                        "keep_label": keep.get("label"),
                        "drop_label": drop.get("label"),
                        "type": a.get("type"),
                        "score": round(score, 4),
                    }
                )

    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def _neg_key(key: str) -> tuple[int, ...]:
    """Sort helper so the lexicographically smaller key ranks higher on ties."""
    return tuple(-ord(c) for c in str(key))


def merge_individuals(
    db: StandardDatabase | None,
    *,
    ontology_id: str,
    keep_key: str,
    drop_key: str,
) -> dict[str, Any]:
    """Merge ``drop`` into ``keep``: reassign edges, union provenance, expire drop.

    Assertion edges touching ``drop`` are recreated at ``keep`` (ArangoDB edge
    endpoints are immutable, so we add-new + expire-old) — self-loops produced by
    the merge are dropped. The dropped individual's ``rdf_type`` edge and the
    individual itself are temporally expired.
    """
    if db is None:
        db = get_db()
    keep_id = f"{_INDIVIDUALS}/{keep_key}"
    drop_id = f"{_INDIVIDUALS}/{drop_key}"

    reassigned = 0
    if db.has_collection(_ASSERTION):
        edges = list(
            run_aql(
                db,
                f"""
                FOR e IN {_ASSERTION}
                  FILTER (e._from == @d OR e._to == @d) AND e.expired == @never
                  RETURN e
                """,
                bind_vars={"d": drop_id, "never": NEVER_EXPIRES},
            )
        )
        for e in edges:
            new_from = keep_id if e["_from"] == drop_id else e["_from"]
            new_to = keep_id if e["_to"] == drop_id else e["_to"]
            if new_from != new_to:  # skip a self-loop introduced by the merge
                individuals_repo.add_assertion(
                    db,
                    ontology_id=ontology_id,
                    from_individual_id=new_from,
                    to_id=new_to,
                    predicate=str(e.get("predicate") or ""),
                    provenance=e.get("provenance") or [],
                )
                reassigned += 1
            expire_entity(db, collection=_ASSERTION, key=e["_key"])

    # Union provenance onto the survivor (derived field; direct update).
    col = db.collection(_INDIVIDUALS)
    keep_doc = col.get(keep_key)
    drop_doc = col.get(drop_key)
    if isinstance(keep_doc, dict) and isinstance(drop_doc, dict):
        merged_prov = [
            *(keep_doc.get("provenance") or []),
            *(drop_doc.get("provenance") or []),
        ]
        merged_from = [*(keep_doc.get("merged_from") or []), drop_key]
        col.update({"_key": keep_key, "provenance": merged_prov, "merged_from": merged_from})

    # Expire the dropped individual's rdf:type edge(s) + the individual itself.
    if db.has_collection(_RDF_TYPE):
        for e in run_aql(
            db,
            f"FOR e IN {_RDF_TYPE} FILTER e._from == @d AND e.expired == @never RETURN e",
            bind_vars={"d": drop_id, "never": NEVER_EXPIRES},
        ):
            expire_entity(db, collection=_RDF_TYPE, key=e["_key"])
    expire_entity(db, collection=_INDIVIDUALS, key=drop_key)

    return {"keep": keep_key, "drop": drop_key, "reassigned": reassigned}


def canonicalize_ontology(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    min_score: float = 0.85,
    auto_merge: bool = False,
) -> dict[str, Any]:
    """Detect (and optionally auto-merge) duplicate individuals for an ontology.

    Returns ``{candidates, merged}``. With ``auto_merge``, each candidate is
    merged unless one of its endpoints was already dropped by an earlier merge in
    this pass (so chains collapse safely rather than resurrecting a dropped id).
    """
    if db is None:
        db = get_db()
    candidates = find_individual_duplicates(db, ontology_id, min_score=min_score)
    merged = 0
    if auto_merge:
        dropped: set[str] = set()
        for c in candidates:
            if c["drop_key"] in dropped or c["keep_key"] in dropped:
                continue
            merge_individuals(
                db, ontology_id=ontology_id, keep_key=c["keep_key"], drop_key=c["drop_key"]
            )
            dropped.add(c["drop_key"])
            merged += 1
    log.info(
        "[abox] canonicalize %s: %d candidates, %d merged (min_score=%.2f)",
        ontology_id,
        len(candidates),
        merged,
        min_score,
    )
    return {"ontology_id": ontology_id, "candidates": candidates, "merged": merged}
