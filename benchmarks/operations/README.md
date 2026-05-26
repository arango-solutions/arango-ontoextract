# Ops Benchmarks

Operational benchmarks for the AOE backend (Stream 7 PR 4 — E.5).

These benchmarks measure the application code's contribution to
latency and throughput, with ArangoDB / HTTP / LLM I/O **mocked**.
That gives a stable floor that's independent of host hardware,
network, and Arango configuration — exactly the signal we want for
catching regressions in middleware / serialization / materialization
logic.

For real-DB end-to-end benchmarks, see `docs/benchmarks.md`
("How to Run Benchmarks") and the **infrastructure sizing** notes
there.

---

## What lives here

| File | Measures |
| --- | --- |
| `harness.py` | Shared timing helpers (`measure_latencies`, percentile rendering, Markdown table formatting). |
| `bench_api_latency.py` | `GET /health`, `GET /api/v1/metrics`, `GET /ready` (mocked DB) — middleware + serialization floor. |
| `bench_materialize.py` | `_materialize_to_graph` across 10 / 100 / 500 classes — extraction-write code path. |
| `bench_temporal_snapshot.py` | `get_snapshot` across 10c/30p/20e, 100c/300p/200e, 500c/1500p/1000e — temporal aggregation. |
| `run_baselines.py` | Driver that runs every benchmark and optionally writes `baseline.md`. |
| `baseline.md` | Committed baseline numbers + host snapshot. |

---

## How to run

```bash
# Print results to stdout (safe for CI smoke checks)
python -m benchmarks.operations.run_baselines

# Print AND overwrite baseline.md with the new numbers
python -m benchmarks.operations.run_baselines --update-baseline

# Run a single benchmark in isolation (handy when iterating on
# a specific code path you've just changed)
python -m benchmarks.operations.bench_api_latency
python -m benchmarks.operations.bench_materialize
python -m benchmarks.operations.bench_temporal_snapshot
```

Via Make:

```bash
make bench               # equivalent to `python -m benchmarks.operations.run_baselines`
make bench-update        # equivalent to `... --update-baseline`
```

---

## Interpreting the numbers

* **p50** — the value below which half the requests fell. The
  steady-state expectation when everything is warm.
* **p95** — the SLO target line. Most production budgets quote p95.
* **p99** — the tail latency. Watch this for warning signs of GC
  pauses, slow Python imports, or contention.
* **min/max/mean** — sanity check that the percentiles aren't being
  drowned out by an outlier. A `max` that's 20× the `p99` usually
  means the OS context-switched the benchmark process during one
  sample, not that the code itself is unstable.

The first run after a `git pull` may show a slow `bench_api_latency`
because FastAPI / Pydantic do a lot of lazy module-level work on
the first request; the harness includes 5 warmup invocations to
amortize this, but on cold-cache filesystems (eg the very first
run on a new clone) the first scenario may still be 2-3× slower
than steady-state. Re-run if you see this; the committed baseline
was recorded on a warm host.

---

## When to update `baseline.md`

Update on these events (only):

1. **Intentional performance change** — a PR that explicitly aims
   to make something faster (or slower in exchange for correctness).
   The PR body should call out the expected delta and include the
   new baseline output.
2. **Hardware migration** — when the recording host changes (eg
   moving from Intel to Apple Silicon). The host snapshot in
   `baseline.md` documents the new hardware.
3. **Major dependency bump** — FastAPI / Pydantic / Starlette
   majors can shift the API latency floor by 10-30%. The new
   baseline becomes the regression target.

**Do not update** to silence a regression that has no other
justification. The baseline is the contract; if a routine PR
makes `GET /health` 50% slower, that's a bug to investigate, not
a baseline to refresh.

---

## What this does NOT measure

* **Real ArangoDB latency** — every benchmark mocks the DB.
  Real-DB benchmarks live in `docs/benchmarks.md` "How to Run".
* **LLM provider latency** — `bench_materialize` runs *after* the
  LangGraph pipeline has produced a result; the LLM cost is
  measured separately by the ontology-extraction benchmarks under
  `benchmarks/ontology_extraction/`.
* **Concurrent load** — these are single-threaded latency
  benchmarks. For throughput-under-concurrency, use `k6` /
  `locust` against a running backend per the load-testing notes
  in `docs/benchmarks.md`.
* **Frontend rendering** — `frontend/e2e/` is the home for any
  Playwright-based render benchmarks.
