"""Materialization throughput benchmark (Stream 7 PR 4 -- E.5).

Times ``_materialize_to_graph`` -- the function that writes a
LangGraph consistency result to ArangoDB after extraction. This
is the path that turns LLM output into curatable graph state, so
its cost directly bounds end-to-end extraction time once the LLM
work is done.

The DB is mocked (every ``collection.insert`` is a no-op) so the
benchmark measures the application logic: serialization, edge
construction, NEVER_EXPIRES stamping, has_chunk wiring. A real
deployment adds Arango RTT * num_inserts on top -- a single
ontology with 100 classes does ~hundreds of inserts, so the
real-DB cost is dominated by RTT, not by this code. That's
exactly why we mock here: we want to see the *application*
floor, which is what we control.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
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


def _build_mock_db() -> MagicMock:
    """Return a ``MagicMock`` shaped like ``StandardDatabase`` for
    materialization.

    Covers the collections + edges + AQL surface
    ``_materialize_to_graph`` touches. Each collection's ``insert``
    is a no-op that returns ``{}``, so the time measured is purely
    the Python-side work of building docs + edges.
    """
    mock_db = MagicMock()
    mock_db.has_collection.return_value = True

    collections = {}
    for name in (
        "ontology_classes",
        "ontology_properties",
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_constraints",
        "has_property",
        "subclass_of",
        "related_to",
        "extracted_from",
        "has_chunk",
        "produced_by",
        "rdfs_domain",
        "rdfs_range_class",
    ):
        col = MagicMock()
        col.insert.return_value = {}
        collections[name] = col

    mock_db.collection.side_effect = lambda name: collections.get(name, MagicMock())
    # has_chunk lookup does an AQL query for chunks of the doc; an
    # empty iter is fine for the benchmark (we want to measure the
    # class/property write path, not has_chunk edge creation
    # which is constant-time given n_chunks).
    mock_db.aql.execute.return_value = iter([])
    return mock_db


class _SyntheticModel:
    """Minimal Pydantic-shaped stand-in for benchmarking.

    ``_materialize_to_graph`` does ``cls.model_dump() if hasattr(
    cls, 'model_dump') else dict(cls)`` to normalize input shapes
    (Pydantic v2 has ``model_dump``; legacy paths may pass dicts).
    The simplest way to satisfy that contract without depending on
    the real Pydantic models -- which would drag in the full
    extraction model graph and slow benchmark imports significantly
    -- is to provide our own ``model_dump`` returning a plain dict.
    """

    def __init__(self, **data: Any) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return dict(self._data)


def _synthetic_consistency_result(n_classes: int) -> Any:
    """Build a result object shaped like the consistency-checker
    output of the LangGraph pipeline.

    ``_materialize_to_graph`` reads either ``result.classes`` or
    ``result.get("classes", [])``. We use a ``SimpleNamespace`` for
    the top-level container (it just needs a ``.classes`` attribute)
    and ``_SyntheticModel`` for each class so ``model_dump`` works.
    Each class carries a small number of properties so we exercise
    both the datatype and object-property write paths.
    """
    classes = []
    for i in range(n_classes):
        cls = _SyntheticModel(
            uri=f"http://example.org/cls/{i}",
            label=f"Class{i}",
            description=f"Synthetic class {i}",
            properties=[
                {
                    "uri": f"http://example.org/cls/{i}/prop_label",
                    "label": "label",
                    "range": "xsd:string",
                },
            ],
            attributes=[],
            relationships=[],
            constraints=[],
            chunk_ids=[],
        )
        classes.append(cls)
    return SimpleNamespace(classes=classes)


def bench_materialize_at_size(n_classes: int, n: int = 20) -> BenchResult:
    """Time materialization of ``n_classes`` synthetic classes.

    Repeats ``n`` times (default 20) -- materialization scales
    linearly with class count, so 20 samples is plenty for stable
    p95 numbers at any class count we care about. Larger ``n``
    here would just slow the benchmark without adding signal.
    """
    from app.services.extraction import _materialize_to_graph

    result = _synthetic_consistency_result(n_classes)

    def call() -> None:
        mock_db = _build_mock_db()
        _materialize_to_graph(
            mock_db,
            run_id=f"bench-run-{int(time.time() * 1000)}",
            document_id="bench-doc",
            ontology_id="bench-onto",
            result=result,
        )

    return measure_latencies(
        call,
        n=n,
        name=f"_materialize_to_graph ({n_classes} classes)",
        metadata={"n_classes": n_classes},
    )


def run_all() -> list[BenchResult]:
    """Sweep materialization across realistic class counts.

    Sizes chosen to bracket the PRD scalability targets:
    * 10  -- a tiny extracted ontology from a short document.
    * 100 -- a medium ontology from a 50-page doc.
    * 500 -- the curation-UI's stated render target (PRD §8.1).
    """
    return [
        bench_materialize_at_size(10),
        bench_materialize_at_size(100),
        bench_materialize_at_size(500),
    ]


if __name__ == "__main__":  # pragma: no cover -- script entry point
    results = run_all()
    print(print_results_table(results))
