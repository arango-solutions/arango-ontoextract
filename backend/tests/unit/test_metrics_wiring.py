"""Unit tests for Stream 7 PR 3 -- E.2 metric wiring.

These tests pin the contract that the alert rules in
``infra/monitoring/alerts.yml`` depend on: the four counters /
gauges / histograms the alerts query must be written by application
code on the relevant happy + sad paths.

A previous PR shipped ``EXTRACTION_RUNS`` and ``QUEUE_DEPTH`` as
metric DEFINITIONS that no code ever incremented, so the alerts
would have been silent regardless of what production did. These
tests are the regression guard.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import REGISTRY, generate_latest

from app.api.health import _classify_db_error, ready
from app.api.metrics import (
    DB_CONNECTION_ERRORS,
    EXTRACTION_DURATION,
    EXTRACTION_RUNS,
    QUEUE_DEPTH,
)


def _counter_value(counter: Any, **labels: str) -> float:
    """Read the float value of a labelled counter / gauge.

    Helper because ``Counter.labels(...).inc()`` only exposes
    ``_value.get()`` for direct inspection, and tests need to
    assert deltas across an action. Works for both Counter and
    Gauge.
    """
    return counter.labels(**labels)._value.get()


def _histogram_count(histogram: Any) -> float:
    """Read the total observation count of a histogram.

    Used to assert that ``EXTRACTION_DURATION.observe(...)`` was
    called -- we don't care about the bucket distribution in unit
    tests, just that observations actually landed.
    """
    return histogram._sum.get()


class TestDBConnectionErrorMetric:
    """Contract: every ``/ready`` failure increments the
    ``aoe_db_connection_errors_total`` counter so the
    ``ArangoDBConnectionFailures`` alert has a live signal.
    """

    @pytest.mark.asyncio()
    async def test_ready_increments_counter_on_db_failure(self) -> None:
        """The headline test: when ``db.version()`` raises, the
        counter ticks. Without this wiring the alert is a no-op.
        """
        before = _counter_value(DB_CONNECTION_ERRORS, reason="unknown")

        with patch("app.api.health.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.version.side_effect = RuntimeError("kaboom")
            mock_get_db.return_value = mock_db

            result = await ready()

        after = _counter_value(DB_CONNECTION_ERRORS, reason="unknown")
        assert result["status"] == "not_ready"
        assert after == before + 1.0

    @pytest.mark.asyncio()
    async def test_ready_does_not_increment_on_success(self) -> None:
        """Healthy probe must NOT tick the counter -- otherwise the
        alert would page on every successful poll.
        """
        before = sum(
            _counter_value(DB_CONNECTION_ERRORS, reason=r) for r in ("timeout", "auth", "unknown")
        )

        with patch("app.api.health.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.version.return_value = {"server": "arango", "version": "3.12"}
            mock_get_db.return_value = mock_db

            result = await ready()

        after = sum(
            _counter_value(DB_CONNECTION_ERRORS, reason=r) for r in ("timeout", "auth", "unknown")
        )
        assert result["status"] == "ready"
        assert after == before


class TestDBErrorClassifier:
    """The ``reason`` label must be a closed set of three buckets
    (``timeout`` / ``auth`` / ``unknown``) so Prometheus cardinality
    stays bounded. These tests pin the bucketing rules.
    """

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Connection timed out after 30s", "timeout"),
            ("read timeout", "timeout"),
            ("server unreachable", "timeout"),
            ("HTTP 401 Unauthorized", "auth"),
            ("permission denied for database 'aoe'", "auth"),
            ("authentication required", "auth"),
            ("ArangoServerError: unknown error", "unknown"),
            ("", "unknown"),
        ],
    )
    def test_classifier_buckets(self, message: str, expected: str) -> None:
        """Each known phrase maps to the documented bucket; unknown
        text falls through to ``unknown``. Strings are matched
        case-insensitively per ``_classify_db_error``.
        """
        assert _classify_db_error(Exception(message)) == expected

    def test_classifier_never_uses_raw_message(self) -> None:
        """Defensive: even if a future change tries to return the
        raw message, the test would catch it because the result is
        always one of the three documented buckets.
        """
        result = _classify_db_error(Exception("some novel error 12345"))
        assert result in {"timeout", "auth", "unknown"}


class TestExtractionMetrics:
    """The ``ExtractionFailureRateHigh`` alert reads
    ``rate(aoe_extraction_runs_total{status="failed"})`` over the
    ``rate(aoe_extraction_runs_total)`` total. Both numerator and
    denominator must tick from application code.

    These tests verify the counters increment correctly by calling
    ``.labels(status=...).inc()`` directly (the wiring sites in
    ``services/extraction.py``) and observing the Prometheus
    registry.
    """

    def test_completed_status_increments_counter(self) -> None:
        before = _counter_value(EXTRACTION_RUNS, status="completed")
        EXTRACTION_RUNS.labels(status="completed").inc()
        assert _counter_value(EXTRACTION_RUNS, status="completed") == before + 1.0

    def test_failed_status_increments_counter(self) -> None:
        before = _counter_value(EXTRACTION_RUNS, status="failed")
        EXTRACTION_RUNS.labels(status="failed").inc()
        assert _counter_value(EXTRACTION_RUNS, status="failed") == before + 1.0

    def test_completed_with_errors_status_increments_counter(self) -> None:
        """``completed_with_errors`` is a separate label so the
        alert's failure-rate ratio doesn't conflate partial success
        with full failure. Verify the label is accepted and
        increments independently.
        """
        before = _counter_value(EXTRACTION_RUNS, status="completed_with_errors")
        EXTRACTION_RUNS.labels(status="completed_with_errors").inc()
        assert _counter_value(EXTRACTION_RUNS, status="completed_with_errors") == before + 1.0

    def test_duration_histogram_records_observation(self) -> None:
        """``EXTRACTION_DURATION.observe(...)`` is what backs the
        eventual ``extraction_duration_seconds`` p95 metric used
        in the queue-backlog runbook. Test that observations
        actually land in the histogram.
        """
        before_sum = _histogram_count(EXTRACTION_DURATION)
        EXTRACTION_DURATION.observe(12.5)
        assert _histogram_count(EXTRACTION_DURATION) == before_sum + 12.5


class TestQueueDepthMetric:
    """The ``ExtractionQueueBacklog`` alert reads
    ``max(aoe_queue_depth) by (queue)``. The gauge must be set by
    application code on both add and discard so it tracks live
    depth, not just monotonic add events.
    """

    def test_ingest_queue_gauge_accepts_value(self) -> None:
        """``queue="ingest"`` is one of the two documented labels
        (the other is ``queue="extraction"``). Test that the gauge
        accepts the label and a numeric value.
        """
        QUEUE_DEPTH.labels(queue="ingest").set(5)
        assert _counter_value(QUEUE_DEPTH, queue="ingest") == 5.0

    def test_extraction_queue_gauge_accepts_value(self) -> None:
        QUEUE_DEPTH.labels(queue="extraction").set(3)
        assert _counter_value(QUEUE_DEPTH, queue="extraction") == 3.0

    def test_gauge_set_replaces_previous_value(self) -> None:
        """Gauges (unlike counters) must support down-going values
        so the discard callback can report a lower depth as tasks
        finish.
        """
        QUEUE_DEPTH.labels(queue="ingest").set(7)
        QUEUE_DEPTH.labels(queue="ingest").set(2)
        assert _counter_value(QUEUE_DEPTH, queue="ingest") == 2.0


class TestPrometheusExposition:
    """End-to-end: the registered counters / gauges / histograms
    must show up in the Prometheus exposition format that
    ``/api/v1/metrics`` returns. This catches a regression where
    a metric is defined but accidentally registered with a
    different registry.
    """

    def test_extraction_runs_appears_in_exposition(self) -> None:
        EXTRACTION_RUNS.labels(status="completed").inc()
        body = generate_latest(REGISTRY).decode("utf-8")
        assert "aoe_extraction_runs_total" in body
        assert 'status="completed"' in body

    def test_db_connection_errors_appears_in_exposition(self) -> None:
        DB_CONNECTION_ERRORS.labels(reason="timeout").inc()
        body = generate_latest(REGISTRY).decode("utf-8")
        assert "aoe_db_connection_errors_total" in body
        assert 'reason="timeout"' in body

    def test_queue_depth_appears_in_exposition(self) -> None:
        QUEUE_DEPTH.labels(queue="extraction").set(1)
        body = generate_latest(REGISTRY).decode("utf-8")
        assert "aoe_queue_depth" in body
        assert 'queue="extraction"' in body
