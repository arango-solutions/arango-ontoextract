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


def test_save_quality_snapshot_records_source_and_run_id():
    """``source`` defaults to ``quality_api`` but accepts event-source values
    such as ``extraction_completion``; ``run_id`` (when provided) is
    persisted so the trend chart can attribute a snapshot to one run."""
    from app.db import quality_history_repo

    collection = MagicMock()
    collection.insert.return_value = {"new": {"_key": "snap2"}}
    db = MagicMock()
    db.has_collection.return_value = True
    db.collection.return_value = collection

    with patch.object(quality_history_repo, "now_iso", return_value="2026-05-09T00:00:00+00:00"):
        quality_history_repo.save_quality_snapshot(
            "onto_1",
            {"ontology_id": "onto_1", "health_score": 90},
            source="extraction_completion",
            run_id="run_xyz",
            db=db,
        )

    inserted = collection.insert.call_args.args[0]
    assert inserted["source"] == "extraction_completion"
    assert inserted["run_id"] == "run_xyz"


def test_save_quality_snapshot_omits_run_id_when_none():
    from app.db import quality_history_repo

    collection = MagicMock()
    collection.insert.return_value = {"new": {"_key": "snap3"}}
    db = MagicMock()
    db.has_collection.return_value = True
    db.collection.return_value = collection

    quality_history_repo.save_quality_snapshot(
        "onto_1",
        {"ontology_id": "onto_1", "health_score": 70},
        db=db,
    )

    inserted = collection.insert.call_args.args[0]
    assert inserted["source"] == "quality_api"
    assert "run_id" not in inserted


def test_record_event_snapshot_computes_report_and_persists_it():
    """``record_event_snapshot`` is the helper that extraction completion
    and promotion call: it computes the current quality report (without
    triggering a *second* internal snapshot) and writes it tagged with
    the originating event."""
    from app.db import quality_history_repo

    collection = MagicMock()
    collection.insert.return_value = {"new": {"_key": "snap_event"}}
    db = MagicMock()
    db.has_collection.return_value = True
    db.collection.return_value = collection

    fake_report = {"ontology_id": "onto_1", "health_score": 92}
    with patch(
        "app.services.quality_metrics.compute_quality_report",
        return_value=fake_report,
    ) as mock_compute:
        result = quality_history_repo.record_event_snapshot(
            "onto_1",
            source="extraction_completion",
            run_id="run_42",
            db=db,
        )

    mock_compute.assert_called_once()
    # The internal compute MUST be called with record_snapshot=False so
    # we don't double-record (the helper itself owns the write).
    _args, kwargs = mock_compute.call_args
    assert kwargs["record_snapshot"] is False

    assert result == {"_key": "snap_event"}
    inserted = collection.insert.call_args.args[0]
    assert inserted["source"] == "extraction_completion"
    assert inserted["run_id"] == "run_42"


def test_record_event_snapshot_swallows_compute_failures():
    """A snapshot bug must never break the extraction or promotion write
    path. ``record_event_snapshot`` must log + return ``None`` on error."""
    from app.db import quality_history_repo

    db = MagicMock()
    db.has_collection.return_value = True

    with patch(
        "app.services.quality_metrics.compute_quality_report",
        side_effect=RuntimeError("boom"),
    ):
        result = quality_history_repo.record_event_snapshot(
            "onto_1",
            source="extraction_completion",
            run_id="run_42",
            db=db,
        )

    assert result is None
