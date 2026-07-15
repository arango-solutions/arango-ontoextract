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
from collections import defaultdict
from typing import Any

from arango.database import StandardDatabase
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.db import alignment_repo
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
) -> list[dict[str, Any]]:
    """Score cross-source class pairs and return candidate correspondences.

    Returns a list of correspondence dicts (without persistence fields), sorted
    by confidence descending. Same-source pairs are never emitted. Requires ≥2
    distinct source ontologies.
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

    candidates: list[dict[str, Any]] = []
    for i in range(len(oids)):
        for j in range(i + 1, len(oids)):
            for a in by_oid.get(oids[i], []):
                for b in by_oid.get(oids[j], []):
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
    for c in cands:
        confidence = float(c.get("confidence") or 0.0)
        if confidence >= band:
            adj = {
                "method": "score",
                "verdict": "equivalent",
                "confidence": confidence,
                "recommendation": "accept",
            }
            new_type = c.get("type")
        else:
            src_a = c.get("source_a") or {}
            src_b = c.get("source_b") or {}
            verdict = await adjudicate_candidate(
                str(src_a.get("label") or ""),
                str(src_b.get("label") or ""),
                c.get("scores") or {},
                model=model,
            )
            llm_calls += 1
            adj = {
                "method": "llm",
                **verdict,
                "recommendation": _recommendation(verdict["verdict"], verdict["confidence"]),
            }
            new_type = _type_from_verdict(verdict["verdict"], c.get("type") or "skos:relatedMatch")
        alignment_repo.set_correspondence_adjudication(
            db, c["_key"], adj, correspondence_type=new_type
        )

    log.info(
        "[alignment] adjudicated session %s: %d candidates, %d LLM calls (band=%.2f)",
        session_id,
        len(cands),
        llm_calls,
        band,
    )
    return {"session_id": session_id, "adjudicated": len(cands), "llm_calls": llm_calls}


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
