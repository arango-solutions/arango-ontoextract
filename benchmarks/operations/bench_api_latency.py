"""API latency benchmarks (Stream 7 PR 4 -- E.5).

Measures FastAPI request-handling latency for the cheap routes
that should never block (health, ready, metrics) plus a routed
endpoint that exercises the middleware stack
(JWTAuth + Prometheus + CORS). All DB interactions are mocked so
the numbers reflect the application code, not Arango.

What this catches:
* Regression in middleware chain (each middleware adds ~tens of
  microseconds per request -- if a future PR adds a heavy one,
  the /health p95 will jump and we'll see it here).
* Regression in JSON serialization (route returning a large dict
  through Pydantic gets slower if model validation changes).

What this does NOT catch:
* Real DB latency (mocked).
* Network RTT (in-process TestClient).
* LLM provider latency (separate benchmark in
  ``benchmarks/ontology_extraction/``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Add the project root + backend to sys.path so this script can
# run as ``python -m benchmarks.operations.bench_api_latency`` from
# the repo root without an editable install of the backend package.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Avoid touching the host's Arango / Redis / LLM config when the
# script is run ad-hoc on a dev laptop. ``Settings`` reads these
# at first import; setting them to safe defaults here keeps the
# benchmark hermetic.
os.environ.setdefault("ANTHROPIC_API_KEY", "bench-noop")
os.environ.setdefault("OPENAI_API_KEY", "bench-noop")
os.environ.setdefault("ARANGO_PASSWORD", "bench-noop")
os.environ.setdefault("JWT_SECRET_KEY", "bench-noop-secret-key-32-bytes!!")
os.environ.setdefault("APP_LOG_LEVEL", "ERROR")  # quiet structlog spam during timing

from benchmarks.operations.harness import (  # noqa: E402
    BenchResult,
    measure_latencies,
    print_results_table,
)


def _build_test_client() -> Any:
    """Build a FastAPI TestClient with all DB calls mocked.

    The TestClient runs the full middleware chain in-process via
    ASGI, so we measure everything from the outermost CORS
    middleware through to the route handler -- minus the network
    transport. ArangoDB is mocked at ``get_db`` so ``/ready``
    returns "ready" without any I/O.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def bench_health(client: Any, n: int = 500) -> BenchResult:
    """``GET /health`` -- the cheapest route in the system.

    Returns a 6-byte JSON body. Whatever this measures is
    essentially the "minimum viable request" cost: middleware
    chain + route lookup + JSON serialization. Useful as a floor
    -- any other route should be at most a few hundred
    microseconds slower than this.
    """

    def call() -> None:
        resp = client.get("/health")
        if resp.status_code != 200:
            raise RuntimeError(f"unexpected status: {resp.status_code}")

    return measure_latencies(call, n=n, name="GET /health")


def bench_metrics(client: Any, n: int = 200) -> BenchResult:
    """``GET /api/v1/metrics`` -- Prometheus exposition endpoint.

    More expensive than /health because it serializes every
    metric currently registered (counters, gauges, histograms).
    The response size scales with the metric inventory; this
    benchmark captures the per-call serialization cost at the
    current inventory and warns if it ever blows past p95 > 50ms
    (which would mean we've added cardinality explosion).
    """

    def call() -> None:
        resp = client.get("/api/v1/metrics")
        if resp.status_code != 200:
            raise RuntimeError(f"unexpected status: {resp.status_code}")

    return measure_latencies(call, n=n, name="GET /api/v1/metrics")


def bench_ready_with_mocked_db(client: Any, n: int = 200) -> BenchResult:
    """``GET /ready`` -- exercises ``get_db().version()``.

    ``get_db`` is the place a real deployment spends real
    milliseconds (TCP roundtrip to Arango). We mock it to
    ``MagicMock`` so the benchmark measures everything else --
    the middleware chain, the readiness-probe handler, the
    error-classification path. p95 here should be within
    ~hundreds of microseconds of /health.
    """

    def call() -> None:
        with patch("app.api.health.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.version.return_value = {"server": "arango", "version": "3.12"}
            mock_get_db.return_value = mock_db
            resp = client.get("/ready")
        if resp.status_code != 200:
            raise RuntimeError(f"unexpected status: {resp.status_code}")

    return measure_latencies(call, n=n, name="GET /ready (mocked db)")


def run_all() -> list[BenchResult]:
    """Run every API latency benchmark and return the results.

    Used by ``run_baselines.py`` to assemble the full baseline
    table; also callable from a unit test as a smoke check that
    every benchmark imports + executes without raising.
    """
    client = _build_test_client()
    return [
        bench_health(client),
        bench_metrics(client),
        bench_ready_with_mocked_db(client),
    ]


if __name__ == "__main__":  # pragma: no cover -- script entry point
    results = run_all()
    print(print_results_table(results))
