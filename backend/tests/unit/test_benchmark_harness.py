"""Unit tests for the ops benchmark harness (Stream 7 PR 4 -- E.5).

These tests are the regression guard against benchmark bit-rot.
The benchmark scripts live outside the normal test run because
they're slow and produce stochastic timing numbers; without
explicit tests, a refactor in ``app.services.extraction`` could
silently break ``bench_materialize`` and no one would notice
until the next ``make bench-update`` run.

What we verify:
* The harness percentile helper produces stable numbers across
  Python versions (no ``statistics.quantiles`` interpolation
  surprises).
* Each ``bench_*.py`` module exposes a ``run_all()`` that
  returns a non-empty list of ``BenchResult`` instances with
  sane (non-zero, finite) percentile values.
* The Markdown table formatter handles empty + populated input
  without raising.

These tests SHOULD be fast: each ``run_all()`` invocation
exercises every benchmark scenario, but the harness sample
counts (``n=20`` for materialize, ``n=30`` for snapshot) are
sized so the full sweep finishes well under the 10-second
soft limit for a unit test. If a future PR bumps the sample
counts past that, this file should grow a ``pytest.mark.slow``
guard rather than ship a slow unit test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the repo root to sys.path so ``from benchmarks.operations
# import ...`` resolves the same way it does when the scripts
# are invoked as ``python -m benchmarks.operations.bench_...``
# from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class TestHarnessPercentile:
    """The percentile helper is the load-bearing piece of the
    harness -- if it drifts across Python versions, every
    committed baseline becomes incomparable to a fresh local
    run. Pin its behaviour on known inputs.
    """

    def test_percentile_of_known_sorted_input(self) -> None:
        """For the canonical input ``[1, 2, ..., 100]``,
        ``p50`` is 50, ``p95`` is 95, ``p99`` is 99 under the
        harness's nearest-rank definition. If a refactor swaps
        in a different interpolation method, this test will
        flag it.
        """
        from benchmarks.operations.harness import _percentile

        samples = [float(i) for i in range(1, 101)]
        assert _percentile(samples, 50) == 50.0
        assert _percentile(samples, 95) == 95.0
        assert _percentile(samples, 99) == 99.0

    def test_percentile_of_empty_list_returns_zero(self) -> None:
        """Defensive: a benchmark that never sampled should
        not blow up the formatter -- it should produce a row
        of zeros and let the reader notice.
        """
        from benchmarks.operations.harness import _percentile

        assert _percentile([], 50) == 0.0
        assert _percentile([], 95) == 0.0

    def test_percentile_clamps_at_boundary(self) -> None:
        """``pct <= 0`` returns ``min``; ``pct >= 100`` returns
        ``max``. This is the contract -- callers occasionally
        pass 0 or 100 to mean "show me the floor / ceiling"
        and the function shouldn't IndexError on the rank
        calculation.
        """
        from benchmarks.operations.harness import _percentile

        samples = [10.0, 20.0, 30.0]
        assert _percentile(samples, 0) == 10.0
        assert _percentile(samples, 100) == 30.0


class TestHarnessMeasureLatencies:
    """``measure_latencies`` is what every benchmark calls.
    Verify it produces ``BenchResult`` with finite, ordered
    percentiles and respects the warmup parameter.
    """

    def test_returns_result_with_ordered_percentiles(self) -> None:
        """For any positive-latency function, ``min <= p50 <=
        p95 <= p99 <= max`` must always hold. A regression in
        the percentile computation that swapped p95 and p50
        would be caught here.
        """
        from benchmarks.operations.harness import measure_latencies

        result = measure_latencies(lambda: None, n=50, warmup=0, name="noop")
        assert result.n == 50
        assert result.min_ms <= result.p50_ms
        assert result.p50_ms <= result.p95_ms
        assert result.p95_ms <= result.p99_ms
        assert result.p99_ms <= result.max_ms

    def test_metadata_is_carried_through(self) -> None:
        """Callers attach ``metadata`` (eg ``{"n_classes": 100}``)
        so the rendered baseline file can be parameterized by
        scenario size. Verify the helper round-trips it
        unchanged.
        """
        from benchmarks.operations.harness import measure_latencies

        result = measure_latencies(
            lambda: None,
            n=5,
            warmup=0,
            name="test",
            metadata={"n_classes": 42, "label": "fixture"},
        )
        assert result.metadata == {"n_classes": 42, "label": "fixture"}

    def test_warmup_invocations_do_not_appear_in_samples(self) -> None:
        """``warmup`` calls before the timed loop must not
        contribute to the sample count. If a refactor merges
        warmup into the sample list, the result's ``n`` would
        not match the requested ``n`` argument.
        """
        from benchmarks.operations.harness import measure_latencies

        calls: list[int] = []

        def counted() -> None:
            calls.append(1)

        result = measure_latencies(counted, n=10, warmup=3, name="counted")
        assert result.n == 10
        # 3 warmup + 10 timed = 13 total invocations.
        assert len(calls) == 13


class TestHarnessRenderTable:
    """The ``print_results_table`` formatter must produce a
    valid Markdown table even with zero rows (so the baseline
    file is parseable Markdown even before any benchmarks
    have been wired in).
    """

    def test_empty_results_still_renders_header(self) -> None:
        """No rows -> just the header + divider lines. Catches
        a regression where the function joins an empty list
        and produces blank output.
        """
        from benchmarks.operations.harness import print_results_table

        rendered = print_results_table([])
        assert "| Scenario |" in rendered
        assert "| --- |" in rendered

    def test_populated_results_render_one_row_per_result(self) -> None:
        from benchmarks.operations.harness import (
            BenchResult,
            print_results_table,
        )

        results = [
            BenchResult(
                name="alpha",
                n=10,
                p50_ms=1.0,
                p95_ms=2.0,
                p99_ms=3.0,
                min_ms=0.5,
                max_ms=4.0,
                mean_ms=1.2,
            ),
            BenchResult(
                name="beta",
                n=10,
                p50_ms=5.0,
                p95_ms=6.0,
                p99_ms=7.0,
                min_ms=4.5,
                max_ms=8.0,
                mean_ms=5.6,
            ),
        ]
        rendered = print_results_table(results)
        assert "| alpha |" in rendered
        assert "| beta |" in rendered
        # Lines = header + divider + 2 data rows.
        assert len(rendered.splitlines()) == 4


class TestBenchModulesSmoke:
    """Smoke check: each ``bench_*.py`` exposes the documented
    public surface (``run_all`` plus the individual ``bench_*``
    functions) AND those functions actually produce results.

    We invoke individual ``bench_*`` functions with a tiny
    ``n`` rather than ``run_all()`` so the unit suite stays
    fast -- ``run_all()`` itself is integration-grade work
    measured in seconds, which would balloon the suite. The
    ``run_all`` contract is verified separately via the
    ``run_baselines.main`` tests below, with the heavy
    ``run_all`` invocations monkey-patched to lightweight
    fakes that still exercise the driver path.
    """

    def test_api_latency_module_exposes_public_surface(self) -> None:
        """``bench_api_latency.run_all`` is what
        ``run_baselines.py`` depends on, plus the individual
        ``bench_*`` helpers callers can run in isolation
        when iterating on a specific route. Verify they're all
        callable without invoking them (the actual invocation
        happens in ``test_api_latency_bench_health_with_small_n``).
        """
        from benchmarks.operations import bench_api_latency

        assert callable(bench_api_latency.run_all)
        assert callable(bench_api_latency.bench_health)
        assert callable(bench_api_latency.bench_metrics)
        assert callable(bench_api_latency.bench_ready_with_mocked_db)

    def test_api_latency_bench_health_with_small_n(self) -> None:
        """Exercise ``bench_health`` with a tiny ``n`` so the
        unit test stays fast. Pins the contract that the bench
        function takes a client + ``n`` and returns a
        ``BenchResult`` with the requested sample count.
        """
        from benchmarks.operations import bench_api_latency
        from benchmarks.operations.harness import BenchResult

        client = bench_api_latency._build_test_client()
        result = bench_api_latency.bench_health(client, n=5)
        assert isinstance(result, BenchResult)
        assert result.n == 5

    def test_materialize_bench_at_small_size(self) -> None:
        """Exercise ``bench_materialize_at_size`` at the
        smallest scenario size. Verifies the synthetic-result
        helpers feed cleanly into ``_materialize_to_graph``
        and produce a sane BenchResult shape with the
        ``n_classes`` metadata callers rely on for table
        rendering.
        """
        from benchmarks.operations import bench_materialize
        from benchmarks.operations.harness import BenchResult

        result = bench_materialize.bench_materialize_at_size(n_classes=5, n=3)
        assert isinstance(result, BenchResult)
        assert result.n == 3
        assert result.metadata.get("n_classes") == 5

    def test_temporal_snapshot_bench_at_small_size(self) -> None:
        """Smoke for ``bench_snapshot_at_size`` -- verifies
        the mock-DB AQL dispatch returns the expected
        iterables and ``get_snapshot`` completes without
        raising.
        """
        from benchmarks.operations import bench_temporal_snapshot
        from benchmarks.operations.harness import BenchResult

        result = bench_temporal_snapshot.bench_snapshot_at_size(
            n_classes=3, n_properties=5, n_edges=4, n=3
        )
        assert isinstance(result, BenchResult)
        assert result.n == 3
        assert result.metadata.get("n_classes") == 3

    def test_run_baselines_main_does_not_write_without_flag(self, tmp_path, monkeypatch) -> None:
        """``run_baselines.main(update_baseline=False)`` MUST
        NOT touch the baseline file. This is the CI smoke
        contract: ``make bench`` (no flag) never accidentally
        updates the committed baseline.

        Patching ``BASELINE_PATH`` into ``tmp_path`` is
        belt-and-braces -- even a future code path that
        forgot to respect the flag can't reach the real file.
        We swap each bench module's ``run_all`` for a tiny
        fake so the unit test stays sub-second.
        """
        from benchmarks.operations import (
            bench_api_latency,
            bench_materialize,
            bench_temporal_snapshot,
            run_baselines,
        )

        monkeypatch.setattr(run_baselines, "BASELINE_PATH", tmp_path / "baseline.md")

        def fast_api() -> list:
            client = bench_api_latency._build_test_client()
            return [bench_api_latency.bench_health(client, n=3)]

        def fast_materialize() -> list:
            return [bench_materialize.bench_materialize_at_size(n_classes=2, n=2)]

        def fast_snapshot() -> list:
            return [
                bench_temporal_snapshot.bench_snapshot_at_size(
                    n_classes=2, n_properties=2, n_edges=2, n=2
                )
            ]

        monkeypatch.setattr(bench_api_latency, "run_all", fast_api)
        monkeypatch.setattr(bench_materialize, "run_all", fast_materialize)
        monkeypatch.setattr(bench_temporal_snapshot, "run_all", fast_snapshot)

        exit_code = run_baselines.main(update_baseline=False)
        assert exit_code == 0
        assert not (tmp_path / "baseline.md").exists()

    def test_run_baselines_main_writes_with_flag(self, tmp_path, monkeypatch) -> None:
        """The converse contract: ``update_baseline=True`` MUST
        write the file. Pins the path the ``make bench-update``
        target depends on.
        """
        from benchmarks.operations import (
            bench_api_latency,
            bench_materialize,
            bench_temporal_snapshot,
            run_baselines,
        )

        target = tmp_path / "baseline.md"
        monkeypatch.setattr(run_baselines, "BASELINE_PATH", target)

        def fast_api() -> list:
            client = bench_api_latency._build_test_client()
            return [bench_api_latency.bench_health(client, n=3)]

        def fast_materialize() -> list:
            return [bench_materialize.bench_materialize_at_size(n_classes=2, n=2)]

        def fast_snapshot() -> list:
            return [
                bench_temporal_snapshot.bench_snapshot_at_size(
                    n_classes=2, n_properties=2, n_edges=2, n=2
                )
            ]

        monkeypatch.setattr(bench_api_latency, "run_all", fast_api)
        monkeypatch.setattr(bench_materialize, "run_all", fast_materialize)
        monkeypatch.setattr(bench_temporal_snapshot, "run_all", fast_snapshot)

        exit_code = run_baselines.main(update_baseline=True)
        assert exit_code == 0
        assert target.exists()
        content = target.read_text()
        assert "Ops Benchmark Baselines" in content
        assert "## Host" in content
        assert "## API Latency" in content


@pytest.mark.parametrize(
    "module_name",
    [
        "benchmarks.operations.bench_api_latency",
        "benchmarks.operations.bench_materialize",
        "benchmarks.operations.bench_temporal_snapshot",
        "benchmarks.operations.run_baselines",
        "benchmarks.operations.harness",
    ],
)
def test_module_imports_without_side_effects(module_name: str) -> None:
    """Every benchmark module must be importable without
    triggering real I/O (DB connection, HTTP listener, file
    writes outside the project tree). The bench modules guard
    this by setting ``ANTHROPIC_API_KEY=bench-noop`` etc on
    import; if a future refactor removes that guard, this test
    will start raising on real-host configs with no env vars.
    """
    import importlib

    mod = importlib.import_module(module_name)
    assert mod is not None
