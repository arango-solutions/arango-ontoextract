"""Shared timing utilities for the operations benchmarks.

Single-purpose helpers so each ``bench_*.py`` script stays tight on
the thing it measures. No external dependencies (no
``pytest-benchmark``, ``numpy``, etc) -- ``time.perf_counter`` plus
``statistics`` give us enough resolution and percentile accuracy
for the run-locally-on-dev-hardware target.

Why not ``pytest-benchmark``? It pulls in matplotlib for histograms
and changes the test-runner contract (these are scripts, not unit
tests). Plain Python keeps the dep surface tiny and lets the
harness double as a CLI smoke test in CI.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class BenchResult:
    """Result of one benchmark scenario.

    Holds enough data to (a) print a human-readable table row, (b)
    serialize to JSON for the baselines file, (c) compare against
    a previous baseline. Percentiles are stored explicitly because
    the median + p95 + p99 picture is what matters for SLOs --
    callers should NOT re-derive these from ``samples_s`` because
    ``statistics.quantiles`` interpolation choices can change
    between Python versions.
    """

    name: str
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    metadata: dict[str, str | int | float] = field(default_factory=dict)

    def as_row(self) -> str:
        """Format as a single Markdown table row.

        Column order matches the header rendered by
        ``print_results_table`` so callers don't have to thread
        headers separately.
        """
        return (
            f"| {self.name} | {self.n} | {self.p50_ms:.2f} | "
            f"{self.p95_ms:.2f} | {self.p99_ms:.2f} | "
            f"{self.min_ms:.2f} | {self.max_ms:.2f} | "
            f"{self.mean_ms:.2f} |"
        )


def measure_latencies(
    fn: Callable[[], object],
    *,
    n: int,
    warmup: int = 5,
    name: str = "anonymous",
    metadata: dict[str, str | int | float] | None = None,
) -> BenchResult:
    """Run ``fn()`` ``n`` times and compute latency percentiles.

    A few defaults worth defending:

    * **``warmup=5``** -- amortizes Python import / JIT warm-up
      effects across the first invocations. Without warmup, the
      first sample is often 2-10x slower than steady-state
      because of module-level lazy initialisation (eg
      ``ArangoClient`` instantiation, ``rdflib`` namespace
      caching) that lands on the first call into the codepath.
    * **No outer try/except** -- if the function raises, the
      benchmark is broken and we want a loud failure, not a
      poisoned baseline.
    * **``time.perf_counter``** -- monotonic and the highest
      resolution clock available on the host. Don't replace
      with ``time.time()`` (wall clock, can jump backwards).
    """
    for _ in range(warmup):
        fn()

    samples_s: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        samples_s.append(elapsed)

    samples_ms = [s * 1000.0 for s in samples_s]
    return BenchResult(
        name=name,
        n=n,
        p50_ms=_percentile(samples_ms, 50),
        p95_ms=_percentile(samples_ms, 95),
        p99_ms=_percentile(samples_ms, 99),
        min_ms=min(samples_ms),
        max_ms=max(samples_ms),
        mean_ms=statistics.fmean(samples_ms),
        metadata=metadata or {},
    )


def _percentile(samples: list[float], pct: int) -> float:
    """Compute the ``pct``th percentile via nearest-rank interpolation.

    We deliberately do NOT use ``statistics.quantiles`` because its
    default interpolation method changed across Python versions
    (3.10 vs 3.13) and we want the same numbers on every host.
    Nearest-rank is the simplest definition that maps to the
    intuition "the value below which p% of samples fall".
    """
    if not samples:
        return 0.0
    if pct <= 0:
        return min(samples)
    if pct >= 100:
        return max(samples)
    sorted_samples = sorted(samples)
    # ``ceil(n * pct / 100) - 1`` indexes into the sorted list.
    # For n=100, pct=95 -> index 94 (the 95th value).
    rank = max(0, int(-(-len(sorted_samples) * pct // 100)) - 1)
    return sorted_samples[rank]


def print_results_table(results: list[BenchResult]) -> str:
    """Format a list of results as a Markdown table.

    Returned as a string so callers can write it to a baseline
    file in one shot rather than streaming line-by-line. The
    table header matches ``BenchResult.as_row``'s column order
    one-for-one.
    """
    lines = [
        "| Scenario | n | p50 (ms) | p95 (ms) | p99 (ms) | min (ms) | max (ms) | mean (ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(r.as_row() for r in results)
    return "\n".join(lines)
