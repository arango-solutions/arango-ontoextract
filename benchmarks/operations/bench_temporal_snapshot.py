"""Temporal snapshot latency benchmark (Stream 7 PR 4 -- E.5).

Times ``services.temporal.get_snapshot`` over a synthetic dataset.
The AQL execution is mocked so the numbers reflect:

* Bind-variable construction in the snapshot function.
* Result aggregation across the seven temporal collections
  (classes, properties, object_properties, datatype_properties,
  constraints, and the two edge collections).
* The snapshot cache lookup + miss-path cost.

What this catches:
* Regression in ``_ONTOLOGY_VERTEX_COLLECTIONS`` iteration (eg
  if a future PR adds a new collection without considering the
  N-queries-per-snapshot cost).
* Regression in result-shape normalisation (every doc gets
  ``ttlExpireAt`` stripped, IDs converted to keys, etc).

PRD target (``docs/benchmarks.md``): p95 < 500ms for a 500-class
ontology against real Arango. This in-memory benchmark sets the
floor -- real Arango RTT adds on top.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("ANTHROPIC_API_KEY", "bench-noop")
os.environ.setdefault("OPENAI_API_KEY", "bench-noop")
os.environ.setdefault("ARANGO_PASSWORD", "bench-noop")
os.environ.setdefault("JWT_SECRET_KEY", "bench-noop-secret-key-32-bytes!!")
os.environ.setdefault("APP_LOG_LEVEL", "ERROR")

from benchmarks.operations.harness import (  # noqa: E402
    BenchResult,
    measure_latencies,
    print_results_table,
)


def _synthetic_classes(n: int) -> list[dict]:
    """Synthesize ``n`` versioned class documents at time t=100."""
    from app.db.temporal_constants import NEVER_EXPIRES

    return [
        {
            "_key": f"c{i}",
            "_id": f"ontology_classes/c{i}",
            "uri": f"http://example.org/cls/{i}",
            "label": f"Class{i}",
            "ontology_id": "bench-onto",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }
        for i in range(n)
    ]


def _synthetic_properties(n: int) -> list[dict]:
    """Synthesize ``n`` versioned property documents at time t=100."""
    from app.db.temporal_constants import NEVER_EXPIRES

    return [
        {
            "_key": f"p{i}",
            "_id": f"ontology_properties/p{i}",
            "uri": f"http://example.org/prop/{i}",
            "label": f"prop{i}",
            "ontology_id": "bench-onto",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }
        for i in range(n)
    ]


def _synthetic_edges(n: int) -> list[dict]:
    """Synthesize ``n`` versioned edges at time t=100.

    Edges are simpler than vertices -- no ``_key`` required, just
    ``_from``/``_to``/``created``/``expired``. ``get_snapshot``
    streams them through the same iteration so this captures the
    per-edge processing cost.
    """
    from app.db.temporal_constants import NEVER_EXPIRES

    return [
        {
            "_from": f"ontology_classes/c{i}",
            "_to": f"ontology_properties/p{i}",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }
        for i in range(n)
    ]


def _build_mock_db(n_classes: int, n_properties: int, n_edges: int) -> MagicMock:
    """Mock the AQL surface so ``get_snapshot`` finds versioned
    documents at our synthetic timestamp.

    ``get_snapshot`` issues one AQL query per collection in
    ``_ONTOLOGY_VERTEX_COLLECTIONS`` + the edge collections; we
    dispatch on the ``@col`` bind variable to return the right
    synthetic set. Empty iterators for collections we don't
    populate keeps the snapshot function on its real code path
    (it still iterates them).
    """
    classes = _synthetic_classes(n_classes)
    properties = _synthetic_properties(n_properties)
    edges = _synthetic_edges(n_edges)

    mock_db = MagicMock()
    mock_db.has_collection.return_value = True

    def mock_execute(query: str, bind_vars: dict | None = None) -> object:
        col = (bind_vars or {}).get("@col", "")
        if col == "ontology_classes":
            return iter(classes)
        if col == "ontology_properties":
            return iter(properties)
        if col in (
            "ontology_object_properties",
            "ontology_datatype_properties",
            "ontology_constraints",
        ):
            return iter([])
        # Anything else (edge collections, has_chunk, etc) -> edges.
        return iter(edges)

    mock_db.aql.execute = mock_execute
    return mock_db


def bench_snapshot_at_size(
    n_classes: int, n_properties: int, n_edges: int, n: int = 30
) -> BenchResult:
    """Time ``get_snapshot`` over the given dataset.

    Unique ``ontology_id`` per scenario (``{n}``-suffixed) bypasses
    the 5-minute snapshot cache so each repeat hits the real
    aggregation path. Otherwise we'd be timing the cache, not the
    snapshot function.
    """
    from app.services.temporal import get_snapshot

    mock_db = _build_mock_db(n_classes, n_properties, n_edges)

    def call() -> None:
        get_snapshot(
            mock_db,
            ontology_id=f"bench-onto-{n_classes}-{n_properties}-{n_edges}",
            timestamp=200.0,
            bypass_cache=True,
        )

    return measure_latencies(
        call,
        n=n,
        name=f"get_snapshot ({n_classes}c/{n_properties}p/{n_edges}e)",
        metadata={
            "n_classes": n_classes,
            "n_properties": n_properties,
            "n_edges": n_edges,
        },
    )


def run_all() -> list[BenchResult]:
    """Sweep snapshot computation across realistic ontology sizes.

    Sizes mirror ``bench_materialize`` (10 / 100 / 500 classes)
    so the two benchmarks can be cross-referenced. Properties
    and edges scale proportionally -- in real ontologies the
    per-class fan-out is roughly 3-5 properties + 2-4 edges,
    rounded down here to keep numbers tidy.
    """
    return [
        bench_snapshot_at_size(n_classes=10, n_properties=30, n_edges=20),
        bench_snapshot_at_size(n_classes=100, n_properties=300, n_edges=200),
        bench_snapshot_at_size(n_classes=500, n_properties=1500, n_edges=1000),
    ]


if __name__ == "__main__":  # pragma: no cover -- script entry point
    results = run_all()
    print(print_results_table(results))
