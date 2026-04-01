"""Entity Resolution LangGraph agent node.

Wraps the ER pipeline to match extraction results against existing ontology
classes, producing merge_candidate edges and extends_domain edges.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.db.utils import run_aql
from app.extraction.state import ExtractionPipelineState, StepLog

log = logging.getLogger(__name__)


def er_agent_node(state: ExtractionPipelineState) -> dict:
    """LangGraph node: run entity resolution against existing ontology classes.

    Takes the consistency-checked extraction results, compares them against
    the existing ontology using the ER pipeline, and produces merge candidates
    and extends_domain edges for EXTENSION entities.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")
    consistency_result = state.get("consistency_result")
    metadata = dict(state.get("metadata", {}))
    errors = list(state.get("errors", []))

    log.info("er_agent started", extra={"run_id": run_id})

    merge_candidates: list[dict[str, Any]] = []
    er_results: dict[str, Any] = {"status": "skipped"}

    if consistency_result is None or not consistency_result.classes:
        log.info("er_agent skipped: no extraction results", extra={"run_id": run_id})
        er_results["reason"] = "no_extraction_results"
    else:
        try:
            ontology_id = metadata.get("ontology_id", "")
            er_results = _run_er_matching(
                run_id=run_id,
                extracted_classes=consistency_result.classes,
                ontology_id=ontology_id,
            )
            merge_candidates = er_results.get("merge_candidates", [])

            _create_extension_edges(
                run_id=run_id,
                extracted_classes=consistency_result.classes,
                ontology_id=ontology_id,
            )

        except Exception as exc:
            error_msg = f"ER agent error: {exc}"
            errors.append(error_msg)
            er_results = {"status": "failed", "error": str(exc)}
            log.exception("er_agent failed", extra={"run_id": run_id})

    duration = time.time() - start
    step_log = StepLog(
        step="er_agent",
        status="completed" if er_results.get("status") != "failed" else "failed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=errors[-1] if errors and er_results.get("status") == "failed" else None,
        metadata={
            "merge_candidates_found": len(merge_candidates),
            "er_status": er_results.get("status", "unknown"),
        },
    )

    existing_logs = list(state.get("step_logs", []))
    existing_logs.append(step_log)

    log.info(
        "er_agent completed",
        extra={
            "run_id": run_id,
            "merge_candidates": len(merge_candidates),
            "duration_seconds": round(duration, 3),
        },
    )

    return {
        "er_results": er_results,
        "merge_candidates": merge_candidates,
        "current_step": "er_agent",
        "errors": errors,
        "step_logs": existing_logs,
    }


def _run_er_matching(
    *,
    run_id: str,
    extracted_classes: list,
    ontology_id: str,
) -> dict[str, Any]:
    """Run ER matching for extracted classes against existing ontology."""
    from app.services.er import explain_match

    candidates: list[dict[str, Any]] = []

    try:
        from app.db.client import get_db
        from app.services.temporal import NEVER_EXPIRES

        db = get_db()
        if not db.has_collection("ontology_classes"):
            return {"status": "skipped", "reason": "no_ontology_classes_collection"}

        existing_classes = list(
            run_aql(
                db,
                """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN {key: cls._key, label: cls.label, uri: cls.uri}""",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

        if not existing_classes:
            return {"status": "completed", "reason": "no_existing_classes", "merge_candidates": []}

        for extracted in extracted_classes:
            for existing in existing_classes:
                try:
                    match = explain_match(
                        db, key1=existing["key"], key2=extracted.uri
                    )
                    score = match.get("combined_score", 0.0)
                    if score >= settings.er_vector_similarity_threshold:
                        candidates.append({
                            "extracted_uri": extracted.uri,
                            "extracted_label": extracted.label,
                            "existing_key": existing["key"],
                            "existing_label": existing["label"],
                            "combined_score": score,
                            "field_scores": match.get("field_scores", {}),
                        })
                except Exception:
                    pass

    except Exception as exc:
        log.warning("ER matching failed, returning partial results", extra={"error": str(exc)})

    candidates.sort(key=lambda c: c.get("combined_score", 0), reverse=True)

    return {
        "status": "completed",
        "merge_candidates": candidates,
        "candidate_count": len(candidates),
    }


def _create_extension_edges(
    *,
    run_id: str,
    extracted_classes: list,
    ontology_id: str,
) -> int:
    """Create extends_domain edges for EXTENSION-classified entities."""
    edges_created = 0

    try:
        from app.services.cross_tier import create_cross_tier_edges

        result = create_cross_tier_edges(
            run_id=run_id,
            ontology_id=ontology_id,
        )
        edges_created = result.edges_created

    except Exception as exc:
        log.warning(
            "cross-tier edge creation failed",
            extra={"run_id": run_id, "error": str(exc)},
        )

    return edges_created
