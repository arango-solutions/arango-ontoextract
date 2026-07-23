"""Multi-source ontology alignment (Stream 20, PRD §6.17).

AL-PR1 (session lifecycle) + AL-PR2 (embedding-aware candidate generation).

Candidate generation scores every cross-source class pair with the shared
matcher (``app.services.matching`` / SF.2), which folds in the entity embeddings
populated by ``ontology_embeddings`` (SF.1) when present. Only pairs at or above
``min_score`` become candidate correspondences; each carries per-signal scores, a
confidence, and a *provisional* type by score band.

Scope note (P1): this scores all cross-source pairs, which is fine for the small,
use-case-scoped masters P1 targets (CDF M3). For large sources, narrow the
candidate set first with ``ontology_embeddings.search_similar`` (embedding
retrieval) before scoring — deferred to the scale PR. The expensive LLM
adjudication of borderline pairs is AL-PR3; here every candidate's type is a
cheap heuristic.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from arango.database import StandardDatabase
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.db import alignment_repo, ontology_repo, registry_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.extraction.agents.extractor import _get_llm
from app.services import matching

log = logging.getLogger(__name__)

# Score bands for the provisional correspondence type (refined by the LLM in
# AL-PR3). At/above EQUIVALENT_BAND we provisionally call it equivalence;
# otherwise a looser related-match.
_EQUIVALENT_BAND = 0.9


def _provisional_type(a: dict[str, Any], b: dict[str, Any], combined: float) -> str:
    if a.get("uri") and a.get("uri") == b.get("uri"):
        return "owl:equivalentClass"
    return "owl:equivalentClass" if combined >= _EQUIVALENT_BAND else "skos:relatedMatch"


def generate_candidates(
    db: StandardDatabase,
    *,
    source_ontology_ids: list[str],
    min_score: float = 0.5,
    weights: dict[str, float] | None = None,
    scope: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Score cross-source class pairs and return candidate correspondences.

    Returns a list of correspondence dicts (without persistence fields), sorted
    by confidence descending. Same-source pairs are never emitted. Requires ≥2
    distinct source ontologies.

    ``scope`` (AL-PR10) restricts generation to pairs touching a changed entity:
    ``{ontology_id: {entity_key, ...}}``. When set, a pair is emitted only if at
    least one of its two nodes is in scope, so a source edit re-aligns just the
    affected subset instead of the full NxM product.
    """
    oids = list(dict.fromkeys(source_ontology_ids))  # dedup, preserve order
    if len(oids) < 2 or not db.has_collection("ontology_classes"):
        return []

    rows = list(
        run_aql(
            db,
            """
            FOR c IN ontology_classes
              FILTER c.ontology_id IN @oids AND c.expired == @never
              RETURN {
                _key: c._key,
                ontology_id: c.ontology_id,
                label: c.label,
                description: c.description,
                uri: c.uri,
                embedding: c.embedding
              }
            """,
            bind_vars={"oids": oids, "never": NEVER_EXPIRES},
        )
    )

    by_oid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_oid[str(row.get("ontology_id") or "")].append(row)

    def _in_scope(oid: str, key: str) -> bool:
        return scope is not None and key in scope.get(oid, set())

    candidates: list[dict[str, Any]] = []
    for i in range(len(oids)):
        for j in range(i + 1, len(oids)):
            for a in by_oid.get(oids[i], []):
                for b in by_oid.get(oids[j], []):
                    if scope is not None and not (
                        _in_scope(oids[i], a["_key"]) or _in_scope(oids[j], b["_key"])
                    ):
                        continue  # scoped refresh: only pairs touching a changed class
                    scored = matching.score_candidate(a, b, weights=weights)
                    combined = scored["combined"]
                    if combined < min_score:
                        continue
                    candidates.append(
                        {
                            "source_a": {
                                "ontology_id": a["ontology_id"],
                                "entity_key": a["_key"],
                                "label": a.get("label"),
                            },
                            "source_b": {
                                "ontology_id": b["ontology_id"],
                                "entity_key": b["_key"],
                                "label": b.get("label"),
                            },
                            "scores": scored,
                            "confidence": combined,
                            "type": _provisional_type(a, b, combined),
                            "status": "candidate",
                        }
                    )

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# AL-PR3 — selective LLM adjudication of borderline correspondences
# ---------------------------------------------------------------------------

_ADJUDICATE_SYSTEM_PROMPT = (
    "You are an ontology-alignment judge. Given two classes from different "
    "ontologies and their computed similarity signals, decide their relationship. "
    "Respond ONLY with a JSON object: "
    '{"verdict": "equivalent"|"subclass"|"superclass"|"related"|"none", '
    '"confidence": <0.0-1.0>, "rationale": "<one sentence>"}. '
    '"subclass" means A is a subclass of B; "superclass" means A is a superclass '
    'of B; "equivalent" means the same concept; "related" means associated but not '
    'the same or hierarchical; "none" means unrelated.'
)

_VERDICTS = ("equivalent", "subclass", "superclass", "related", "none")
_UNCERTAIN = {"verdict": "uncertain", "confidence": 0.0, "rationale": "llm_unavailable"}


def _type_from_verdict(verdict: str, fallback: str) -> str:
    return {
        "equivalent": "owl:equivalentClass",
        "subclass": "rdfs:subClassOf",
        "superclass": "rdfs:subClassOf",
        "related": "skos:relatedMatch",
    }.get(verdict, fallback)


def _recommendation(verdict: str, confidence: float) -> str:
    """Map a verdict + confidence to accept / review / reject."""
    if verdict in ("equivalent", "subclass", "superclass") and confidence >= 0.5:
        return "accept"
    if verdict == "none":
        return "reject"
    return "review"


_ACCEPT_VERDICTS = frozenset({"equivalent", "subclass", "superclass"})


def _llm_proposes_match(verdict: dict[str, Any]) -> bool:
    return (
        str(verdict.get("verdict")) in _ACCEPT_VERDICTS
        and float(verdict.get("confidence") or 0.0) >= 0.5
    )


def ensemble_adjudicate(
    verdict: dict[str, Any],
    scores: dict[str, Any],
    *,
    anchor_threshold: float | None = None,
) -> dict[str, Any]:
    """Cross-check an LLM verdict against the classical anchor (AL-PR8).

    Returns the ensemble decision fields to merge into the adjudication record:
    ``classical`` (the anchor), ``grounded``, ``disagreement``, ``hallucination``
    and a ``recommendation`` / ``review_priority`` that enforce FR-17.9 / FR-17.10:

    * **Hallucination control (FR-17.10):** an LLM match with no grounded source
      anchor is never recommended for acceptance — routed to ``review``.
    * **Disagreement prioritization (FR-17.9):** when the LLM and the classical
      anchor disagree, route to ``review`` and rank it ahead of agreements.
    """
    threshold = (
        anchor_threshold
        if anchor_threshold is not None
        else settings.alignment_classical_anchor_threshold
    )
    anchor = matching.get_classical_anchor(scores, threshold=threshold)
    grounded = bool(anchor["anchored"])
    llm_match = _llm_proposes_match(verdict)
    disagreement = llm_match != grounded
    hallucination = llm_match and not grounded

    base = _recommendation(
        str(verdict.get("verdict") or ""), float(verdict.get("confidence") or 0.0)
    )
    recommendation = "review" if (hallucination or disagreement) else base
    review_priority = 2 if hallucination else (1 if disagreement else 0)

    return {
        "classical": anchor,
        "grounded": grounded,
        "disagreement": disagreement,
        "hallucination": hallucination,
        "recommendation": recommendation,
        "review_priority": review_priority,
    }


async def adjudicate_candidate(
    a_label: str,
    b_label: str,
    scores: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Ask the LLM whether two classes correspond. Never raises.

    Returns ``{verdict, confidence, rationale}``; falls back to an ``uncertain``
    verdict on any LLM/parse error so a bad call routes the pair to human review
    rather than dropping it.
    """
    try:
        llm = _get_llm(model or settings.llm_extraction_model)
        signals = json.dumps({k: v for k, v in scores.items() if k != "combined"})
        user = (
            f"Class A: {a_label!r}\nClass B: {b_label!r}\n"
            f"Similarity signals: {signals}\n"
            f"Combined score: {scores.get('combined')}"
        )
        resp = await llm.ainvoke(
            [SystemMessage(content=_ADJUDICATE_SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _parse_verdict(raw)
    except Exception:
        log.warning("alignment adjudication failed; routing to review", exc_info=True)
        return dict(_UNCERTAIN)


def _parse_verdict(raw: str) -> dict[str, Any]:
    """Parse the LLM JSON verdict, tolerating code fences / surrounding prose."""
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return dict(_UNCERTAIN)
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return dict(_UNCERTAIN)
    verdict = str(data.get("verdict") or "").lower()
    if verdict not in _VERDICTS:
        return dict(_UNCERTAIN)
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (ValueError, TypeError):
        confidence = 0.0
    return {
        "verdict": verdict,
        "confidence": confidence,
        "rationale": str(data.get("rationale") or ""),
    }


async def adjudicate_session(
    db: StandardDatabase | None = None,
    *,
    session_id: str,
    auto_accept_band: float | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Adjudicate a session's candidate correspondences (AL-PR3).

    Correspondences at/above ``auto_accept_band`` auto-accept (method ``score``,
    no LLM); the rest get a selective LLM verdict (method ``llm``). Each gets an
    ``adjudication`` record + a refined type; the curation ``status`` is left for
    a human. Returns counts.
    """
    if db is None:
        db = get_db()
    band = auto_accept_band if auto_accept_band is not None else settings.alignment_auto_accept_band

    cands = alignment_repo.list_correspondences(db, session_id, status="candidate", limit=10_000)
    llm_calls = 0
    hallucinations = 0
    disagreements = 0
    for c in cands:
        confidence = float(c.get("confidence") or 0.0)
        scores = c.get("scores") or {}
        if confidence >= band:
            # Classical/high-score auto-accept: attach the anchor for transparency
            # but leave the recommendation (this is not an LLM correspondence, so
            # FR-17.10's LLM-grounding gate does not apply).
            adj = {
                "method": "score",
                "verdict": "equivalent",
                "confidence": confidence,
                "recommendation": "accept",
                "classical": matching.get_classical_anchor(
                    scores, threshold=settings.alignment_classical_anchor_threshold
                ),
            }
            new_type = c.get("type")
        else:
            src_a = c.get("source_a") or {}
            src_b = c.get("source_b") or {}
            verdict = await adjudicate_candidate(
                str(src_a.get("label") or ""),
                str(src_b.get("label") or ""),
                scores,
                model=model,
            )
            llm_calls += 1
            ensemble = ensemble_adjudicate(verdict, scores)
            adj = {"method": "llm", **verdict, **ensemble}
            hallucinations += int(ensemble["hallucination"])
            disagreements += int(ensemble["disagreement"])
            new_type = _type_from_verdict(verdict["verdict"], c.get("type") or "skos:relatedMatch")
        alignment_repo.set_correspondence_adjudication(
            db, c["_key"], adj, correspondence_type=new_type
        )

    log.info(
        "[alignment] adjudicated session %s: %d candidates, %d LLM calls (band=%.2f), "
        "%d hallucination-flagged, %d disagreements",
        session_id,
        len(cands),
        llm_calls,
        band,
        hallucinations,
        disagreements,
    )
    return {
        "session_id": session_id,
        "adjudicated": len(cands),
        "llm_calls": llm_calls,
        "hallucination_flagged": hallucinations,
        "disagreements": disagreements,
    }


def create_alignment_session(
    db: StandardDatabase | None = None,
    *,
    source_ontology_ids: list[str],
    min_score: float = 0.5,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Create a session over N sources, generate candidates, and persist them.

    Returns the session doc augmented with ``candidate_count``.
    """
    if db is None:
        db = get_db()
    if len(set(source_ontology_ids)) < 2:
        raise ValueError("alignment requires at least 2 distinct source ontologies")

    session = alignment_repo.create_session(
        db,
        source_ontology_ids=source_ontology_ids,
        params={"min_score": min_score, "weights": weights or matching.DEFAULT_WEIGHTS},
    )
    candidates = generate_candidates(
        db,
        source_ontology_ids=source_ontology_ids,
        min_score=min_score,
        weights=weights,
    )
    count = alignment_repo.save_correspondences(db, session["_key"], candidates)
    log.info(
        "[alignment] session %s: %d candidates over %d sources",
        session["_key"],
        count,
        len(set(source_ontology_ids)),
    )
    return {**session, "candidate_count": count}


def get_alignment_session(db: StandardDatabase | None, session_id: str) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    return alignment_repo.get_session(db, session_id)


def list_session_candidates(
    db: StandardDatabase | None,
    session_id: str,
    *,
    status: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if db is None:
        db = get_db()
    return alignment_repo.list_correspondences(
        db,
        session_id,
        status=status,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )


def set_candidate_status(
    db: StandardDatabase | None, correspondence_key: str, status: str
) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    if status not in ("candidate", "accepted", "rejected"):
        raise ValueError(f"invalid correspondence status: {status}")
    return alignment_repo.set_correspondence_status(db, correspondence_key, status)


# ---------------------------------------------------------------------------
# AL-PR4 — master materialization + provenance
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_STRIP.sub("-", (text or "concept").lower()).strip("-") or "concept"


class _UnionFind:
    """Minimal union-find over hashable nodes for transitive merge grouping."""

    def __init__(self) -> None:
        self._parent: dict[Any, Any] = {}

    def find(self, x: Any) -> Any:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # path compression
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: Any, b: Any) -> None:
        self._parent[self.find(a)] = self.find(b)

    def groups(self) -> list[list[Any]]:
        out: dict[Any, list[Any]] = defaultdict(list)
        for node in self._parent:
            out[self.find(node)].append(node)
        return list(out.values())


def materialize_master(
    db: StandardDatabase | None = None,
    *,
    session_id: str,
    name: str | None = None,
    created_by: str = "alignment",
) -> dict[str, Any]:
    """Materialize a reconciled master ontology from a session's ACCEPTED pairs.

    Transitively clusters accepted correspondences (A≡B, B≡C -> one cluster),
    creates one master class per cluster with ``source_ontology_ids`` +
    ``provenance``, links each member source class via an ``owl:equivalentClass``
    edge, and records the master id on the session. Unmatched source classes are
    NOT auto-carried in P1 (CDF M3 accepts a small, hand-completed master);
    carrying the union over is a documented P2 follow-up.
    """
    if db is None:
        db = get_db()
    session = alignment_repo.get_session(db, session_id)
    if session is None:
        raise ValueError(f"alignment session '{session_id}' not found")

    accepted = alignment_repo.list_correspondences(db, session_id, status="accepted", limit=100_000)

    # AL-PR7 — minimally-destructive coherence repair BEFORE clustering, so the
    # master never merges a declared-disjoint pair into one equivalence class.
    # A no-op when no disjointness is declared (the common case).
    repair_removals: list[dict[str, Any]] = []
    source_oids = session.get("source_ontology_ids") or []
    if settings.alignment_repair_enabled:
        from app.services import alignment_repair

        disjoint_pairs = alignment_repair.build_disjoint_pairs(db, source_oids)
        accepted, repair_removals = alignment_repair.repair_correspondences(
            accepted, disjoint_pairs
        )

    uf = _UnionFind()
    node_info: dict[tuple[str, str], dict[str, Any]] = {}
    for c in accepted:
        a, b = c.get("source_a") or {}, c.get("source_b") or {}
        na = (str(a.get("ontology_id")), str(a.get("entity_key")))
        nb = (str(b.get("ontology_id")), str(b.get("entity_key")))
        node_info[na] = a
        node_info[nb] = b
        uf.union(na, nb)

    n_sources = len(source_oids)
    master_name = name or f"Aligned master ({n_sources} sources)"
    master = registry_repo.create_registry_entry(
        {
            "name": master_name,
            "tier": "master",
            "description": f"Reconciled master from alignment session {session_id}",
            "alignment_session_id": session_id,
            # AL-PR7: durable audit of correspondences dropped to keep the master
            # coherent (report every removal, never silent).
            "repair_removals": repair_removals,
        },
        db=db,
    )
    master_oid = str(master["_key"])

    class_count = 0
    edge_count = 0
    for cluster in uf.groups():
        members = [node_info[n] for n in cluster]
        label = str(members[0].get("label") or "concept")
        oids = sorted({str(m.get("ontology_id")) for m in members})
        provenance = [
            {"ontology_id": str(m.get("ontology_id")), "entity_key": str(m.get("entity_key"))}
            for m in members
        ]
        master_class = ontology_repo.create_class(
            db,
            ontology_id=master_oid,
            data={
                "label": label,
                "uri": f"urn:aoe:master:{master_oid}:{_slug(label)}",
                "source_ontology_ids": oids,
                "provenance": provenance,
                "status": "approved",
            },
            created_by=created_by,
        )
        class_count += 1
        for m in members:
            ontology_repo.create_edge(
                db,
                edge_collection="equivalent_class",
                from_id=str(master_class["_id"]),
                to_id=f"ontology_classes/{m.get('entity_key')}",
                data={
                    "ontology_id": master_oid,
                    "source": "alignment",
                    "alignment_session_id": session_id,
                },
            )
            edge_count += 1

    alignment_repo.set_session_master(db, session_id, master_oid)
    log.info(
        "[alignment] materialized master %s from session %s: %d classes, %d equivalence "
        "edges, %d correspondences removed for coherence",
        master_oid,
        session_id,
        class_count,
        edge_count,
        len(repair_removals),
    )
    return {
        "session_id": session_id,
        "master_id": master_oid,
        "class_count": class_count,
        "equivalence_edges": edge_count,
        "cluster_count": class_count,
        "repair": {"removed": len(repair_removals), "removals": repair_removals},
    }


# ---------------------------------------------------------------------------
# AL-PR10 — iterative refinement (re-align on source change, scoped)
# ---------------------------------------------------------------------------


def _correspondence_nodes(c: dict[str, Any]) -> list[tuple[str, str]]:
    a = c.get("source_a") or {}
    b = c.get("source_b") or {}
    return [
        (str(a.get("ontology_id")), str(a.get("entity_key"))),
        (str(b.get("ontology_id")), str(b.get("entity_key"))),
    ]


def _touches(c: dict[str, Any], ontology_id: str, keys: set[str]) -> bool:
    return any(oid == ontology_id and key in keys for oid, key in _correspondence_nodes(c))


def refresh_alignment(
    db: StandardDatabase | None = None,
    *,
    session_id: str,
    changed_ontology_id: str,
    changed_keys: list[str],
) -> dict[str, Any]:
    """Re-align just the correspondences affected by a source change (RE-3).

    Scoped, dependency-directed: correspondences touching a changed class are
    removed (their prior human decisions are invalidated by the edit and reported
    in the summary), then fresh candidates are generated **only** for pairs that
    involve a changed class (via ``generate_candidates(scope=...)``) and appended.
    Correspondences on untouched pairs — and their curation decisions — are
    preserved. A removed/expired class simply produces no new candidates, so its
    stale correspondences are dropped. Returns a summary of the delta.

    Does not re-materialize: if the session already produced a master, the summary
    flags ``master_stale`` so a caller can re-run ``materialize_master``.
    """
    if db is None:
        db = get_db()
    session = alignment_repo.get_session(db, session_id)
    if session is None:
        raise ValueError(f"alignment session '{session_id}' not found")

    oids = list(session.get("source_ontology_ids") or [])
    changed = set(changed_keys)
    if changed_ontology_id not in oids or not changed:
        return {
            "session_id": session_id,
            "changed_ontology_id": changed_ontology_id,
            "removed_stale": 0,
            "removed_accepted": 0,
            "added": 0,
            "preserved": 0,
            "skipped": "ontology not in session or no changed keys",
        }

    params = session.get("params") or {}
    min_score = float(params.get("min_score", 0.5))
    weights = params.get("weights")

    existing = alignment_repo.list_correspondences(db, session_id, limit=1_000_000)
    stale = [c for c in existing if _touches(c, changed_ontology_id, changed)]
    stale_keys = [str(c["_key"]) for c in stale]
    removed_accepted = sum(1 for c in stale if c.get("status") == "accepted")
    removed_rejected = sum(1 for c in stale if c.get("status") == "rejected")
    surviving_pairs = {
        frozenset(_correspondence_nodes(c))
        for c in existing
        if str(c["_key"]) not in set(stale_keys)
    }

    alignment_repo.delete_correspondences(db, stale_keys)

    scoped = generate_candidates(
        db,
        source_ontology_ids=oids,
        min_score=min_score,
        weights=weights,
        scope={changed_ontology_id: changed},
    )
    fresh = [c for c in scoped if frozenset(_correspondence_nodes(c)) not in surviving_pairs]
    added = alignment_repo.save_correspondences(db, session_id, fresh)

    log.info(
        "[alignment] refreshed session %s for %d changed %s classes: -%d stale (+%d "
        "accepted/%d rejected invalidated), +%d candidates, %d preserved",
        session_id,
        len(changed),
        changed_ontology_id,
        len(stale_keys),
        removed_accepted,
        removed_rejected,
        added,
        len(surviving_pairs),
    )
    return {
        "session_id": session_id,
        "changed_ontology_id": changed_ontology_id,
        "changed_keys": sorted(changed),
        "removed_stale": len(stale_keys),
        "removed_accepted": removed_accepted,
        "removed_rejected": removed_rejected,
        "added": added,
        "preserved": len(surviving_pairs),
        "master_stale": session.get("target_master_id") is not None,
    }


def refresh_sessions_for_ontology(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    changed_keys: list[str],
) -> dict[str, Any]:
    """Cascade a source change to every alignment session that uses it (RE-3).

    Finds all sessions whose sources include ``ontology_id`` and scoped-refreshes
    each. Returns the per-session summaries so a caller/UI can surface which
    masters went stale.
    """
    if db is None:
        db = get_db()
    sessions = alignment_repo.find_sessions_for_ontology(db, ontology_id)
    results = [
        refresh_alignment(
            db,
            session_id=str(s["_key"]),
            changed_ontology_id=ontology_id,
            changed_keys=changed_keys,
        )
        for s in sessions
    ]
    return {
        "ontology_id": ontology_id,
        "changed_keys": sorted(set(changed_keys)),
        "sessions_refreshed": len(results),
        "results": results,
    }
