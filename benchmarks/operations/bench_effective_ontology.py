"""Effective-ontology computation benchmark (Stream 12 T6).

Profiles ``compute_effective_ontology`` -- the endpoint the workspace
canvas actually loads on a workspace switch (``GET /{id}/effective``).
Unlike the other ops benchmarks this one runs against a **real**
ArangoDB, because T6's whole question is where the WTW-switch cost goes
on a 1000+ class ontology, and that cost lives in the AQL round-trips
(closure traversal + the 3-AQL entity fetch), not in the Python.

It seeds a throwaway database with a synthetic ontology + a transitive
``imports`` chain, then times the computation end-to-end (latency
percentiles via the shared harness) AND captures the per-stage ``ms_*``
breakdown emitted by the service's ``_log_timing`` telemetry. The
per-stage table is the T6 deliverable: it names the dominant stage so
we can decide whether pagination / query tuning is warranted.

Run::

    # against the no-auth test ArangoDB (default :8550)
    ARANGO_TEST_HOST=http://localhost:8550 \
        python -m benchmarks.operations.bench_effective_ontology

    # bigger sweep / custom sizes
    AOE_BENCH_SIZES=1500,3000,6000 AOE_BENCH_DEPTH=3 \
        python -m benchmarks.operations.bench_effective_ontology

The seeded database is dropped on exit (even on error).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("ANTHROPIC_API_KEY", "bench-noop")
os.environ.setdefault("OPENAI_API_KEY", "bench-noop")
os.environ.setdefault("ARANGO_PASSWORD", "bench-noop")
os.environ.setdefault("JWT_SECRET_KEY", "bench-noop-secret-key-32-bytes!!")
# Keep the service's own INFO timing line out of stdout during the run;
# we capture it structurally via a handler instead (see _StageCapture).
os.environ.setdefault("APP_LOG_LEVEL", "ERROR")

from arango import ArangoClient  # noqa: E402

from app.db.temporal_constants import NEVER_EXPIRES  # noqa: E402
from app.services.ontology_effective import compute_effective_ontology  # noqa: E402
from app.services.ontology_projections import (  # noqa: E402
    LIVE_EDGE_COLLECTIONS,
    LIVE_PROP_COLLECTIONS,
)
from benchmarks.operations.harness import (  # noqa: E402
    BenchResult,
    measure_latencies,
    print_results_table,
)

ARANGO_TEST_HOST = os.getenv("ARANGO_TEST_HOST", "http://localhost:8550")
ARANGO_TEST_USER = os.getenv("ARANGO_TEST_USER", "root")
ARANGO_TEST_PASSWORD = os.getenv("ARANGO_TEST_PASSWORD", "")

# Stage fields in the order the service computes them.
_STAGE_FIELDS = (
    "ms_meta_snapshot",
    "ms_closure_aql",
    "ms_fetch_aql",
    "ms_project",
    "ms_conflicts",
    "ms_etag",
    "ms_total_handler",
)


class _StageCapture(logging.Handler):
    """Buffers the per-stage ``ms_*`` fields off the service's timing log.

    ``compute_effective_ontology`` emits one INFO record per call with the
    stage timings on ``extra=``. We attach this handler to that logger and
    read the fields straight off the ``LogRecord`` -- no string parsing.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, float]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "ms_total_handler", None) is None:
            return
        self.records.append({f: float(getattr(record, f, 0.0)) for f in _STAGE_FIELDS})


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _seed_collections(db: Any) -> None:
    """Create the registry + class + edge + property collections."""
    db.create_collection("ontology_registry")
    db.create_collection("ontology_classes")
    db.create_collection("imports", edge=True)
    for name in LIVE_EDGE_COLLECTIONS:
        db.create_collection(name, edge=True)
    for name in LIVE_PROP_COLLECTIONS:
        db.create_collection(name)


def _seed_ontology(db: Any, *, n_classes: int, depth: int) -> str:
    """Seed a target ontology importing a ``depth``-long chain.

    ``n_classes`` classes are split evenly across the ``depth + 1``
    ontologies (target + chain). Each ontology's classes form a shallow
    subclass chain so the conflict-detection DFS has real edges to walk,
    and every class gets one datatype + one object property so the
    3-AQL fetch pulls a realistic property volume. Returns the target's
    registry ``_key``.
    """
    n_onts = depth + 1
    ont_keys = [f"ont{i}" for i in range(n_onts)]

    registry = [
        {
            "_key": k,
            "name": f"Ontology {i}",
            "tier": "user",
            "status": "approved",
            "updated_at": i,
        }
        for i, k in enumerate(ont_keys)
    ]
    db.collection("ontology_registry").import_bulk(registry)

    # Chain imports: ont0 -> ont1 -> ... -> ont{depth}. OUTBOUND from
    # ont0 walks the whole chain, exercising the closure traversal depth.
    import_edges = [
        {
            "_from": f"ontology_registry/{ont_keys[i]}",
            "_to": f"ontology_registry/{ont_keys[i + 1]}",
            "expired": NEVER_EXPIRES,
        }
        for i in range(n_onts - 1)
    ]
    if import_edges:
        db.collection("imports").import_bulk(import_edges)

    per_ont = max(1, n_classes // n_onts)
    classes: list[dict[str, Any]] = []
    subclass_edges: list[dict[str, Any]] = []
    dt_props: list[dict[str, Any]] = []
    obj_props: list[dict[str, Any]] = []

    for oi, ok in enumerate(ont_keys):
        for ci in range(per_ont):
            key = f"{ok}_c{ci}"
            classes.append(
                {
                    "_key": key,
                    "uri": f"http://ex.org/{ok}/Class{ci}",
                    "label": f"{ok} Class {ci}",
                    "description": f"Synthetic class {ci} in {ok}",
                    "ontology_id": ok,
                    "tier": "user",
                    "status": "approved",
                    "confidence": 0.9,
                    "expired": NEVER_EXPIRES,
                }
            )
            if ci > 0:
                subclass_edges.append(
                    {
                        "_from": f"ontology_classes/{ok}_c{ci}",
                        "_to": f"ontology_classes/{ok}_c{ci - 1}",
                        "ontology_id": ok,
                        "expired": NEVER_EXPIRES,
                    }
                )
            dt_props.append(
                {
                    "_key": f"{key}_dp",
                    "uri": f"http://ex.org/{ok}/Class{ci}/label",
                    "label": "label",
                    "ontology_id": ok,
                    "range": "xsd:string",
                    "expired": NEVER_EXPIRES,
                }
            )
            obj_props.append(
                {
                    "_key": f"{key}_op",
                    "uri": f"http://ex.org/{ok}/Class{ci}/relatesTo",
                    "label": "relatesTo",
                    "ontology_id": ok,
                    "expired": NEVER_EXPIRES,
                }
            )

    db.collection("ontology_classes").import_bulk(classes)
    if subclass_edges:
        db.collection("subclass_of").import_bulk(subclass_edges)
    db.collection("ontology_datatype_properties").import_bulk(dt_props)
    db.collection("ontology_object_properties").import_bulk(obj_props)

    return ont_keys[0]


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


def bench_effective_at_size(
    client: ArangoClient,
    *,
    n_classes: int,
    depth: int,
    n: int = 15,
    warmup: int = 3,
) -> tuple[BenchResult, dict[str, float]]:
    """Seed ``n_classes`` over a ``depth`` import chain and profile.

    Returns the end-to-end ``BenchResult`` plus a dict of mean per-stage
    ``ms_*`` over the measured (non-warmup) runs.
    """
    connect: dict[str, Any] = {"username": ARANGO_TEST_USER}
    if ARANGO_TEST_PASSWORD:
        connect["password"] = ARANGO_TEST_PASSWORD

    db_name = f"aoe_bench_eff_{uuid4().hex[:8]}"
    sys_db = client.db("_system", **connect)
    sys_db.create_database(db_name)
    db = client.db(db_name, **connect)

    capture = _StageCapture()
    svc_log = logging.getLogger("app.services.ontology_effective")
    prior_level = svc_log.level
    svc_log.setLevel(logging.INFO)
    svc_log.addHandler(capture)
    try:
        _seed_collections(db)
        target = _seed_ontology(db, n_classes=n_classes, depth=depth)

        def call() -> None:
            compute_effective_ontology(db, ontology_id=target, include="summary")

        result = measure_latencies(
            call,
            n=n,
            warmup=warmup,
            name=f"effective ({n_classes} classes, depth {depth})",
            metadata={"n_classes": n_classes, "depth": depth},
        )

        # measure_latencies runs warmup then n; the last n records are the
        # measured runs. Average each stage over those.
        measured = (
            capture.records[-n:] if len(capture.records) >= n else capture.records
        )
        stage_means = {
            f: (sum(r[f] for r in measured) / len(measured) if measured else 0.0)
            for f in _STAGE_FIELDS
        }
        return result, stage_means
    finally:
        svc_log.removeHandler(capture)
        svc_log.setLevel(prior_level)
        sys_db.delete_database(db_name, ignore_missing=True)


def _stage_table(rows: list[tuple[str, dict[str, float]]]) -> str:
    """Render the per-stage ms_* breakdown as a Markdown table."""
    header_fields = [f.replace("ms_", "").replace("_", " ") for f in _STAGE_FIELDS]
    lines = [
        "| Scenario | " + " | ".join(header_fields) + " |",
        "| --- | " + " | ".join("---" for _ in _STAGE_FIELDS) + " |",
    ]
    for name, stages in rows:
        cells = " | ".join(f"{stages[f]:.1f}" for f in _STAGE_FIELDS)
        lines.append(f"| {name} | {cells} |")
    return "\n".join(lines)


def run_all() -> tuple[list[BenchResult], list[tuple[str, dict[str, float]]]]:
    sizes = [
        int(x)
        for x in os.getenv("AOE_BENCH_SIZES", "1500,3000").split(",")
        if x.strip()
    ]
    depth = int(os.getenv("AOE_BENCH_DEPTH", "3"))

    client = ArangoClient(hosts=ARANGO_TEST_HOST)
    results: list[BenchResult] = []
    stage_rows: list[tuple[str, dict[str, float]]] = []
    try:
        for size in sizes:
            res, stages = bench_effective_at_size(client, n_classes=size, depth=depth)
            results.append(res)
            stage_rows.append((res.name, stages))
    finally:
        client.close()
    return results, stage_rows


if __name__ == "__main__":  # pragma: no cover -- script entry point
    print(f"# Effective-ontology profile (host={ARANGO_TEST_HOST})\n")
    results, stage_rows = run_all()
    print("## End-to-end latency\n")
    print(print_results_table(results))
    print("\n## Per-stage breakdown (mean ms over measured runs)\n")
    print(_stage_table(stage_rows))
