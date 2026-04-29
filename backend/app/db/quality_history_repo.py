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
    db: StandardDatabase | None = None,
) -> dict[str, Any]:
    """Persist a compact snapshot from a quality report."""
    db = _ensure_collection(db)
    calibration = report.get("confidence_calibration")
    expected_calibration_error = (
        calibration.get("expected_calibration_error")
        if isinstance(calibration, dict)
        else None
    )
    doc = {
        field: report.get(field)
        for field in _SNAPSHOT_FIELDS
        if field in report
    }
    doc.update({
        "ontology_id": ontology_id,
        "timestamp": now_iso(),
        "expected_calibration_error": expected_calibration_error,
        "source": "quality_api",
    })
    result = cast("dict[str, Any]", db.collection(_COLLECTION).insert(doc, return_new=True))
    return result["new"]


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
