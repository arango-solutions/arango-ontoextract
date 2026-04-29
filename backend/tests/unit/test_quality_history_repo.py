"""Unit tests for quality history repository helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_save_quality_snapshot_persists_compact_report():
    from app.db import quality_history_repo

    collection = MagicMock()
    collection.insert.return_value = {
        "new": {
            "_key": "snap1",
            "ontology_id": "onto_1",
            "timestamp": "2026-04-28T00:00:00+00:00",
            "health_score": 80,
        }
    }
    db = MagicMock()
    db.has_collection.return_value = True
    db.collection.return_value = collection

    with patch.object(quality_history_repo, "now_iso", return_value="2026-04-28T00:00:00+00:00"):
        result = quality_history_repo.save_quality_snapshot(
            "onto_1",
            {
                "ontology_id": "onto_1",
                "health_score": 80,
                "avg_confidence": 0.7,
                "confidence_calibration": {"expected_calibration_error": 0.12},
                "large_unused_field": {"skip": True},
            },
            db=db,
        )

    assert result["_key"] == "snap1"
    inserted = collection.insert.call_args.args[0]
    assert inserted["ontology_id"] == "onto_1"
    assert inserted["timestamp"] == "2026-04-28T00:00:00+00:00"
    assert inserted["expected_calibration_error"] == 0.12
    assert inserted["health_score"] == 80
    assert "large_unused_field" not in inserted


def test_list_quality_history_returns_oldest_to_newest():
    from app.db import quality_history_repo

    db = MagicMock()
    db.has_collection.return_value = True
    newest_first = [
        {"timestamp": "2026-04-28T02:00:00+00:00", "health_score": 82},
        {"timestamp": "2026-04-28T01:00:00+00:00", "health_score": 80},
    ]

    with patch.object(quality_history_repo, "run_aql", return_value=iter(newest_first)):
        result = quality_history_repo.list_quality_history("onto_1", limit=2, db=db)

    assert result == list(reversed(newest_first))


def test_list_quality_history_handles_missing_collection():
    from app.db import quality_history_repo

    db = MagicMock()
    db.has_collection.return_value = False

    assert quality_history_repo.list_quality_history("onto_1", db=db) == []
