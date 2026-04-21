"""CLI entry point for the AOE ontology-extraction benchmark harness.

Examples
--------
Run the mock adapter against 20 Re-DocRED documents (CI-friendly)::

    python -m benchmarks.ontology_extraction.run_benchmark \
        --dataset redocred --adapter mock --limit 20

Run AOE's real pipeline against the full WebNLG test split and write a JSON
report::

    python -m benchmarks.ontology_extraction.run_benchmark \
        --dataset webnlg --adapter aoe \
        --out reports/webnlg-2026-04-17.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

from benchmarks.ontology_extraction import metrics
from benchmarks.ontology_extraction.adapters.base import ExtractionAdapter
from benchmarks.ontology_extraction.adapters.mock import MockAdapter
from benchmarks.ontology_extraction.datasets import GoldDocument
from benchmarks.ontology_extraction.datasets import redocred, webnlg


log = logging.getLogger("benchmark")


DatasetLoader = Callable[[Path, int | None], Iterator[GoldDocument]]


DATASETS: dict[str, tuple[DatasetLoader, str]] = {
    "redocred": (redocred.load, "samples/corpora/external/redocred"),
    "webnlg": (webnlg.load, "samples/corpora/external/webnlg"),
}


def _build_adapter(name: str) -> ExtractionAdapter:
    if name == "mock":
        return MockAdapter()
    if name == "aoe":
        # Lazy import — the AOE adapter pulls in the backend package.
        from benchmarks.ontology_extraction.adapters.aoe import AOEAdapter  # noqa: PLC0415

        return AOEAdapter()
    raise SystemExit(f"unknown adapter: {name!r}. Known: mock, aoe.")


def score_document(
    doc: GoldDocument, adapter: ExtractionAdapter
) -> metrics.DocumentScore:
    result = adapter.extract(doc.id, doc.text)
    return metrics.DocumentScore(
        document_id=doc.id,
        classes=metrics.score_sets(result.classes, doc.gold_classes),
        relations=metrics.score_sets(result.relations, doc.gold_relations),
    )


def run(
    dataset: str,
    adapter_name: str,
    limit: int | None = None,
    corpus_root: Path | None = None,
) -> metrics.AggregateReport:
    if dataset not in DATASETS:
        raise SystemExit(f"unknown dataset: {dataset!r}. Known: {', '.join(DATASETS)}.")

    loader, default_root = DATASETS[dataset]
    root = corpus_root or (Path(__file__).resolve().parents[2] / default_root)
    log.info("loading %s from %s", dataset, root)

    adapter = _build_adapter(adapter_name)
    log.info("running adapter %s over at most %s documents", adapter.name, limit)

    document_scores: list[metrics.DocumentScore] = []
    for doc in loader(root, limit):
        if doc.is_empty():
            log.warning("skipping empty document %s", doc.id)
            continue
        try:
            document_scores.append(score_document(doc, adapter))
        except Exception as exc:  # noqa: BLE001
            log.error("document %s failed: %s", doc.id, exc)

    report = metrics.aggregate(document_scores)
    return report


def _print_summary(report: metrics.AggregateReport) -> None:
    print("")
    print(f"Documents scored: {len(report.document_scores)}")
    print("")
    print("Micro-averaged:")
    _print_prf("  classes  ", report.micro_classes)
    _print_prf("  relations", report.micro_relations)
    print("Macro-averaged:")
    _print_prf("  classes  ", report.macro_classes)
    _print_prf("  relations", report.macro_relations)


def _print_prf(label: str, prf: metrics.PRF) -> None:
    print(
        f"{label}  P={prf.precision:.3f}  R={prf.recall:.3f}  F1={prf.f1:.3f}  "
        f"(tp={prf.tp} fp={prf.fp} fn={prf.fn})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmarks.ontology_extraction.run_benchmark",
        description="Run AOE ontology-extraction benchmark.",
    )
    parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    parser.add_argument("--adapter", required=True, choices=["mock", "aoe"])
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of documents to score.")
    parser.add_argument("--corpus-root", type=Path, default=None, help="Override dataset directory.")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON report to this path.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    report = run(
        dataset=args.dataset,
        adapter_name=args.adapter,
        limit=args.limit,
        corpus_root=args.corpus_root,
    )
    _print_summary(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            json.dump(report.as_dict(), fh, indent=2)
        log.info("wrote %s", args.out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
