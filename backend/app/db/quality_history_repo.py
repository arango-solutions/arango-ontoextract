"""Repository for timestamped ontology quality snapshots."""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import now_iso, run_aql

log = logging.getLogger(__name__)

_COLLECTION = "quality_history"

_SNAPSHOT_FIELDS = {
    "ontology_id",
    "health_score",
    "avg_confidence",
    "avg_faithfulness",
    "avg_semantic_validity",
    "completeness",
    "connectivity",
    "acceptance_rate",
    "class_count",
    "property_count",
    "relationship_count",
    "orphan_count",
    "has_cycles",
    "schema_metrics",
    "assertion_metrics",
}


def _ensure_collection(db: StandardDatabase | None = None) -> StandardDatabase:
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)
    return db


def save_quality_snapshot(
    ontology_id: str,
    report: dict[str, Any],
    *,
    source: str = "quality_api",
    run_id: str | None = None,
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Persist a compact snapshot from a quality report.

    ``source`` records where this snapshot came from so the trend chart can
    distinguish "user opened the report" from "extraction completed" or
    "staging promoted to production". Known values:

    - ``"quality_api"`` — recorded on each ``GET /quality/{id}`` view.
    - ``"extraction_completion"`` — recorded after a successful extraction
      run finished writing into the ontology graph (Q.2).
    - ``"promotion"`` — recorded after a staging→production promotion.
    - ``"manual"`` — recorded by an operator via the snapshot helper or MCP.

    ``run_id`` (when provided) attaches the snapshot to the originating
    extraction run, which lets Q.3 sparklines mark "this is the snapshot that
    landed because run ``run_xyz`` completed".
    """
    db = _ensure_collection(db)
    calibration = report.get("confidence_calibration")
    expected_calibration_error = (
        calibration.get("expected_calibration_error") if isinstance(calibration, dict) else None
    )
    doc = {field: report.get(field) for field in _SNAPSHOT_FIELDS if field in report}
    doc.update(
        {
            "ontology_id": ontology_id,
            "timestamp": now_iso(),
            "expected_calibration_error": expected_calibration_error,
            "source": source,
        }
    )
    if run_id:
        doc["run_id"] = run_id
    result = cast("dict[str, Any]", db.collection(_COLLECTION).insert(doc, return_new=True))
    return cast(dict[str, Any], result["new"])


def record_event_snapshot(
    ontology_id: str,
    *,
    source: str,
    run_id: str | None = None,
    db: StandardDatabase | None = None,
) -> dict[str, Any] | None:
    """Compute the current quality report and persist it as an event snapshot.

    Convenience wrapper for callers (extraction completion, promotion) that
    do not already have a computed report in hand. Failures are logged and
    swallowed so a snapshot bug never breaks the extraction or promotion
    write path.
    """
    from app.services.quality_metrics import compute_quality_report

    target_db = db or get_db()
    try:
        report = compute_quality_report(target_db, ontology_id, record_snapshot=False)
        return save_quality_snapshot(
            ontology_id,
            report,
            source=source,
            run_id=run_id,
            db=target_db,
        )
    except Exception:
        log.warning(
            "quality history snapshot failed",
            extra={"ontology_id": ontology_id, "source": source, "run_id": run_id},
            exc_info=True,
        )
        return None


def list_quality_history(
    ontology_id: str,
    *,
    limit: int = 50,
    db: StandardDatabase | None = None,
) -> list[dict[str, Any]]:
    """Return recent snapshots oldest-to-newest for trend charts."""
    db = db or get_db()
    if not db.has_collection(_COLLECTION):
        return []
    rows = list(
        run_aql(
            db,
            f"FOR q IN {_COLLECTION} "
            "FILTER q.ontology_id == @oid "
            "SORT q.timestamp DESC "
            "LIMIT @limit "
            "RETURN UNSET(q, '_id', '_rev')",
            bind_vars={"oid": ontology_id, "limit": limit},
        )
    )
    return list(reversed(rows))
