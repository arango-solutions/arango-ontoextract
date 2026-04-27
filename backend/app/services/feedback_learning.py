"""Gated HITL feedback learning artifacts.

This service converts structured curation feedback into reviewable prompt guidance
and regression candidates. It intentionally does not mutate prompts, thresholds,
or model routing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql

_REGRESSION_REASONS = {
    "missing_evidence",
    "wrong_class",
    "wrong_parent",
    "wrong_relationship",
    "hallucinated",
    "domain_mismatch",
}


def build_feedback_learning_examples(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Build reviewable learning examples from HITL curation decisions.

    The returned artifacts are safe to inspect, export, or use in offline
    evaluation. They are not automatically applied to runtime extraction.
    """
    if db is None:
        db = get_db()

    if not db.has_collection("curation_decisions"):
        return _empty_payload(ontology_id)

    decisions = _load_feedback_decisions(db, ontology_id=ontology_id, limit=limit)
    examples = [_decision_to_example(d) for d in decisions]
    regression_candidates = [
        example for example in examples if _is_regression_candidate(example)
    ]

    action_counts = Counter(example["action"] for example in examples)
    issue_counts: Counter[str] = Counter()
    for example in examples:
        issue_counts.update(example["issue_reasons"])

    return {
        "ontology_id": ontology_id,
        "status": "ready",
        "auto_apply": False,
        "summary": {
            "total_examples": len(examples),
            "regression_candidates": len(regression_candidates),
            "by_action": dict(sorted(action_counts.items())),
            "by_issue_reason": dict(sorted(issue_counts.items())),
        },
        "examples": examples,
        "regression_candidates": regression_candidates,
    }


def _empty_payload(ontology_id: str | None) -> dict[str, Any]:
    return {
        "ontology_id": ontology_id,
        "status": "not_available",
        "auto_apply": False,
        "summary": {
            "total_examples": 0,
            "regression_candidates": 0,
            "by_action": {},
            "by_issue_reason": {},
        },
        "examples": [],
        "regression_candidates": [],
    }


def _load_feedback_decisions(
    db: StandardDatabase,
    *,
    ontology_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    query = """\
FOR d IN curation_decisions
  FILTER d.action IN ["edit", "reject"]
    OR (HAS(d, "issue_reasons") AND IS_ARRAY(d.issue_reasons) AND LENGTH(d.issue_reasons) > 0)
  FILTER @ontology_id == null
    OR d.ontology_id == @ontology_id
    OR (
      HAS(d, "run_id")
      AND d.run_id IN (
        FOR r IN extraction_runs
          FILTER HAS(r, "ontology_id") AND r.ontology_id == @ontology_id
          RETURN r._key
      )
    )
  SORT d.created_at DESC
  LIMIT @limit
  RETURN d"""
    return list(run_aql(
        db,
        query,
        bind_vars={"ontology_id": ontology_id, "limit": limit},
    ))


def _decision_to_example(decision: dict[str, Any]) -> dict[str, Any]:
    edit_diff = decision.get("edit_diff") or {}
    changed_fields = edit_diff.get("changed_fields") or []
    issue_reasons = decision.get("issue_reasons") or []
    example = {
        "decision_key": decision.get("_key"),
        "run_id": decision.get("run_id"),
        "entity_key": decision.get("entity_key"),
        "entity_type": decision.get("entity_type"),
        "action": decision.get("action"),
        "issue_reasons": issue_reasons,
        "notes": decision.get("notes"),
        "changed_fields": changed_fields,
        "before": edit_diff.get("before") or {},
        "after": edit_diff.get("after") or {},
    }
    return {
        **example,
        "prompt_guidance": _build_prompt_guidance(example),
    }


def _build_prompt_guidance(example: dict[str, Any]) -> str:
    action = example.get("action")
    entity_type = example.get("entity_type") or "assertion"
    reasons = set(example.get("issue_reasons") or [])
    before = example.get("before") or {}
    after = example.get("after") or {}

    if action == "edit" and after:
        corrections = []
        for field in example.get("changed_fields", []):
            old = before.get(field)
            new = after.get(field)
            corrections.append(f"{field}: {old!r} -> {new!r}")
        return (
            f"For future {entity_type} extraction, prefer the curated correction "
            f"({'; '.join(corrections)}) when similar source evidence appears."
        )

    if "missing_evidence" in reasons or "hallucinated" in reasons:
        return (
            f"Do not extract a {entity_type} unless the source text provides direct "
            "supporting evidence and a stable source_chunk_id."
        )
    if "wrong_parent" in reasons:
        return "Only assign parent_uri when the subclass relationship is supported by evidence."
    if "wrong_relationship" in reasons:
        return "Only extract object relationships that are explicitly supported by source text."
    if "domain_mismatch" in reasons:
        return "Check extracted concepts against the domain ontology before classifying them."
    if "too_generic" in reasons:
        return "Avoid generic ontology concepts unless the source defines them as domain terms."
    if "too_specific" in reasons:
        return "Avoid over-specific classes when the source supports a broader reusable concept."

    return "Review this curator decision before reusing it as extraction guidance."


def _is_regression_candidate(example: dict[str, Any]) -> bool:
    reasons = set(example.get("issue_reasons") or [])
    action = example.get("action")
    return action == "reject" or bool(reasons & _REGRESSION_REASONS)
