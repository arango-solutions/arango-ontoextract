"""Shared candidate matcher for entity-to-entity similarity (Stream SF.2).

Generalizes the pairwise scoring that lived inside
``er.py::get_cross_tier_candidates`` into a reusable, N-source-aware blend so
ontology alignment (Stream 20), the A-box canonicalizer (Stream 21), and entity
resolution all score candidate pairs the same way.

Signals (each computed only when its inputs are available):

* ``label``       -- Jaro-Winkler on labels (lexical).
* ``description`` -- Jaccard token overlap on descriptions (textual).
* ``embedding``   -- cosine on precomputed embeddings (semantic; see
                     ``ontology_embeddings`` / SF.1). Read from the entity's
                     ``embedding`` field.
* ``structural``  -- Jaccard overlap of structural neighbours (parent URIs /
                     property names), computed only when the caller supplies
                     ``a_neighbors`` / ``b_neighbors``.

:func:`score_candidate` blends the signals with per-signal weights, renormalising
over the *available* signals so a missing embedding or missing neighbour set does
not deflate the combined score. Passing ``weights={"label": 0.6, "description":
0.4}`` reproduces the exact pre-SF.2 ER blend (both signals always present, so the
denominator is 1.0).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

# Default weights for ontology alignment (Stream 20). Callers such as ER pass
# their own weights to preserve their historical blend.
DEFAULT_WEIGHTS: dict[str, float] = {"label": 0.4, "description": 0.2, "embedding": 0.4}

# Default lexical/structural threshold for a *classical* anchor (Stream 20 AL-PR8).
CLASSICAL_ANCHOR_THRESHOLD: float = 0.6


def jaro_winkler_sim(s1: str, s2: str) -> float:
    """Simplified Jaro-Winkler similarity in [0, 1] (case-insensitive)."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    s1_lower, s2_lower = s1.lower(), s2.lower()
    if s1_lower == s2_lower:
        return 1.0

    len1, len2 = len(s1_lower), len(s2_lower)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1_lower[i] != s2_lower[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1_lower[i] != s2_lower[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3

    prefix_len = 0
    for i in range(min(4, min(len1, len2))):
        if s1_lower[i] == s2_lower[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * 0.1 * (1 - jaro)


def token_overlap(text1: str, text2: str) -> float:
    """Token-level overlap similarity (Jaccard on lowercased words) in [0, 1]."""
    if not text1 or not text2:
        return 0.0
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)


def cosine_sim(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors, clamped to [0, 1].

    Returns 0.0 for empty, length-mismatched, or zero-magnitude inputs. The
    clamp keeps the signal on the same [0, 1] scale as the lexical/structural
    signals so the weighted blend is well-behaved; negative cosine (semantically
    opposite) is treated as "no similarity".
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(na) * math.sqrt(nb))
    if sim < 0.0:
        return 0.0
    if sim > 1.0:
        return 1.0
    return sim


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_candidate(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    *,
    weights: Mapping[str, float] | None = None,
    a_neighbors: Sequence[str] | None = None,
    b_neighbors: Sequence[str] | None = None,
) -> dict[str, float]:
    """Score a candidate correspondence between two entities.

    ``a`` / ``b`` are entity mappings with (optionally) ``label``,
    ``description``, and ``embedding`` fields. ``weights`` selects which signals
    contribute and how much; only signals whose inputs are available are blended,
    and the result is renormalised over the available weights.

    Returns a dict of the per-signal scores that were computed plus ``combined``
    (all rounded to 4 dp). ``label`` and ``description`` are always computed;
    ``embedding`` is computed only when both entities carry a non-empty,
    equal-length ``embedding``; ``structural`` only when both neighbour sets are
    supplied.
    """
    w = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)

    scores: dict[str, float] = {
        "label": jaro_winkler_sim(str(a.get("label") or ""), str(b.get("label") or "")),
        "description": token_overlap(
            str(a.get("description") or ""), str(b.get("description") or "")
        ),
    }

    ea = a.get("embedding")
    eb = b.get("embedding")
    if (
        w.get("embedding")
        and isinstance(ea, (list, tuple))
        and isinstance(eb, (list, tuple))
        and len(ea) > 0
        and len(ea) == len(eb)
    ):
        scores["embedding"] = cosine_sim(ea, eb)

    if w.get("structural") and a_neighbors is not None and b_neighbors is not None:
        scores["structural"] = _jaccard(set(a_neighbors), set(b_neighbors))

    # Blend over signals that are both weighted and available; renormalise so a
    # missing signal does not deflate the score.
    active = {k: wt for k, wt in w.items() if wt and k in scores}
    total_w = sum(active.values())
    combined = sum(scores[k] * wt for k, wt in active.items()) / total_w if total_w else 0.0

    out = {k: round(v, 4) for k, v in scores.items()}
    out["combined"] = round(combined, 4)
    return out


# ---------------------------------------------------------------------------
# Classical-anchor ensemble (Stream 20 / AL-PR8, PRD §6.17 FR-17.9 / FR-17.10)
# ---------------------------------------------------------------------------
#
# Classical matchers (LogMap/AML) have plateaued on OAEI, so AOE retains them as
# *anchors*, not the primary engine (PRD §6.17). The built-in anchor uses the
# non-LLM, non-embedding lexical/structural signals — the "source labels/axioms"
# grounding OAEI-LLM hallucination control checks an LLM correspondence against.
# ``embedding`` is deliberately excluded: it is the semantic retrieval signal, not
# a source-label anchor. An external LogMap/AML adapter can be plugged in via
# ``set_classical_matcher`` (it receives the per-signal scores and returns the same
# anchor dict).


def classical_anchor(
    scores: Mapping[str, Any],
    *,
    threshold: float = CLASSICAL_ANCHOR_THRESHOLD,
) -> dict[str, Any]:
    """Return the classical lexical/structural anchor for a candidate's scores.

    ``{anchored, anchor_score, threshold}`` — ``anchored`` iff the strongest of the
    label / description / structural signals meets ``threshold``. Embedding is
    excluded on purpose (see module note).
    """
    lexical = max(
        float(scores.get("label") or 0.0),
        float(scores.get("description") or 0.0),
        float(scores.get("structural") or 0.0),
    )
    return {
        "anchored": lexical >= threshold,
        "anchor_score": round(lexical, 4),
        "threshold": threshold,
    }


# Pluggable classical-matcher hook. Defaults to the built-in lexical anchor; an
# integrator can install a LogMap/AML-backed signal with ``set_classical_matcher``.
ClassicalMatcher = Callable[[Mapping[str, Any]], dict[str, Any]]
_CLASSICAL_MATCHER: ClassicalMatcher | None = None


def set_classical_matcher(fn: ClassicalMatcher | None) -> None:
    """Install (or clear, with ``None``) an external classical-matcher adapter."""
    global _CLASSICAL_MATCHER
    _CLASSICAL_MATCHER = fn


def get_classical_anchor(
    scores: Mapping[str, Any],
    *,
    threshold: float = CLASSICAL_ANCHOR_THRESHOLD,
) -> dict[str, Any]:
    """Anchor via the installed adapter if any, else the built-in lexical anchor."""
    if _CLASSICAL_MATCHER is not None:
        return _CLASSICAL_MATCHER(scores)
    return classical_anchor(scores, threshold=threshold)
