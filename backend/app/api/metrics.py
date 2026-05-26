"""Prometheus metrics endpoint — PRD Section 8.5.

Exposes request latency, extraction throughput, queue depth, and error rates
in Prometheus text format at ``GET /api/v1/metrics``.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse

router = APIRouter(tags=["metrics"])

REQUEST_LATENCY = Histogram(
    "aoe_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["method", "path", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUEST_COUNT = Counter(
    "aoe_http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "path", "status"],
)

ERROR_COUNT = Counter(
    "aoe_http_errors_total",
    "Total HTTP error responses (4xx and 5xx)",
    labelnames=["method", "path", "status"],
)

EXTRACTION_RUNS = Counter(
    "aoe_extraction_runs_total",
    "Total extraction runs triggered",
    labelnames=["status"],
)

EXTRACTION_DURATION = Histogram(
    "aoe_extraction_duration_seconds",
    "Extraction run duration in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

QUEUE_DEPTH = Gauge(
    "aoe_queue_depth",
    "Current depth of the processing queue",
    labelnames=["queue"],
)

ACTIVE_WEBSOCKETS = Gauge(
    "aoe_active_websocket_connections",
    "Number of active WebSocket connections",
    labelnames=["endpoint"],
)

# -- Database connectivity (Stream 7 PR 3 -- E.2) -----------------------
# Incremented every time a connection to ArangoDB fails (eg the
# ``/ready`` probe can't reach ``db.version()``). The companion alert
# rule in ``infra/monitoring/alerts.yml`` fires when this counter
# increases at all over a 5m window -- ie any connection failure in
# production is page-worthy. Operators get visibility into transient
# Arango flakiness before users notice. Label ``reason`` keeps the
# cardinality tiny (``timeout`` / ``auth`` / ``unknown``) while
# splitting the dashboard into useful slices.
DB_CONNECTION_ERRORS = Counter(
    "aoe_db_connection_errors_total",
    "Total ArangoDB connection failures observed on the readiness probe",
    labelnames=["reason"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Records request latency and counts for Prometheus."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> StarletteResponse:
        if request.url.path == "/api/v1/metrics":
            return await call_next(request)

        method = request.method
        path = self._normalize_path(request.url.path)
        start = time.perf_counter()

        response = await call_next(request)

        elapsed = time.perf_counter() - start
        status = str(response.status_code)

        REQUEST_LATENCY.labels(method=method, path=path, status=status).observe(elapsed)
        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()

        if response.status_code >= 400:
            ERROR_COUNT.labels(method=method, path=path, status=status).inc()

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Collapse path parameters to reduce cardinality."""
        parts = path.strip("/").split("/")
        normalized = []
        for part in parts:
            if len(part) > 20 or (len(part) > 8 and not part.isalpha()):
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized)


@router.get("/api/v1/metrics")
async def metrics() -> Response:
    """Prometheus-format metrics scrape endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
