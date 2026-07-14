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

import logging
from collections import defaultdict
from typing import Any

from arango.database import StandardDatabase

from app.db import alignment_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
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
