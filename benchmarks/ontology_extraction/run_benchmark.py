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
from time import perf_counter

from benchmarks.ontology_extraction import metrics
from benchmarks.ontology_extraction.adapters.base import ExtractionAdapter
from benchmarks.ontology_extraction.adapters.mock import MockAdapter
from benchmarks.ontology_extraction.datasets import GoldDocument, hitl_regression, redocred, webnlg

log = logging.getLogger("benchmark")


DatasetLoader = Callable[[Path, int | None], Iterator[GoldDocument]]


DATASETS: dict[str, tuple[DatasetLoader, str]] = {
    "hitl-regression": (hitl_regression.load, "samples/corpora/hitl-regression"),
    "redocred": (redocred.load, "samples/corpora/external/redocred"),
    "webnlg": (webnlg.load, "samples/corpora/external/webnlg"),
}


def _build_adapter(name: str) -> ExtractionAdapter:
    if name == "mock":
        return MockAdapter()
    if name == "aoe":
        # Lazy import — the AOE adapter pulls in the backend package.
        from benchmarks.ontology_extraction.adapters.aoe import AOEAdapter

        return AOEAdapter()
    raise SystemExit(f"unknown adapter: {name!r}. Known: mock, aoe.")


def score_document(
    doc: GoldDocument,
    adapter: ExtractionAdapter,
    *,
    label_aliases: dict[str, str] | None = None,
    relation_aliases: dict[str, str] | None = None,
) -> metrics.DocumentScore:
    started = perf_counter()
    result = adapter.extract(doc.id, doc.text)
    duration_ms = (perf_counter() - started) * 1000
    return metrics.DocumentScore(
        document_id=doc.id,
        classes=metrics.score_sets(
            result.classes,
            doc.gold_classes,
            label_aliases=label_aliases,
        ),
        relations=metrics.score_sets(
            result.relations,
            doc.gold_relations,
            label_aliases=label_aliases,
            relation_aliases=relation_aliases,
        ),
        duration_ms=duration_ms,
        metadata=_normalize_result_metadata(result.metadata),
    )


def run(
    dataset: str,
    adapter_name: str,
    limit: int | None = None,
    corpus_root: Path | None = None,
    label_aliases: dict[str, str] | None = None,
    relation_aliases: dict[str, str] | None = None,
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
            document_scores.append(
                score_document(
                    doc,
                    adapter,
                    label_aliases=label_aliases,
                    relation_aliases=relation_aliases,
                )
            )
        except Exception as exc:
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
    print(
        "Runtime: "
        f"total={report.total_duration_ms:.1f}ms "
        f"avg/document={report.avg_duration_ms:.1f}ms"
    )
    print(
        "Efficiency: "
        f"tokens={report.total_tokens} "
        f"cost=${report.total_estimated_cost_usd:.4f} "
        f"quality/$={_fmt_optional(report.quality_per_dollar)} "
        f"quality/min={_fmt_optional(report.quality_per_minute)}"
    )


def _print_prf(label: str, prf: metrics.PRF) -> None:
    print(
        f"{label}  P={prf.precision:.3f}  R={prf.recall:.3f}  F1={prf.f1:.3f}  "
        f"(tp={prf.tp} fp={prf.fp} fn={prf.fn})"
    )


def _fmt_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _normalize_result_metadata(metadata: dict) -> dict:
    normalized = dict(metadata or {})
    input_tokens = _int_or_zero(normalized.get("input_tokens"))
    output_tokens = _int_or_zero(normalized.get("output_tokens"))
    total_tokens = _int_or_zero(normalized.get("total_tokens"))
    if not total_tokens and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    normalized["input_tokens"] = input_tokens
    normalized["output_tokens"] = output_tokens
    normalized["total_tokens"] = total_tokens
    normalized["estimated_cost_usd"] = _float_or_zero(normalized.get("estimated_cost_usd"))
    return normalized


def _int_or_zero(value) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _float_or_zero(value) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmarks.ontology_extraction.run_benchmark",
        description="Run AOE ontology-extraction benchmark.",
    )
    parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    parser.add_argument("--adapter", required=True, choices=["mock", "aoe"])
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of documents to score.",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Override dataset directory.",
    )
    parser.add_argument(
        "--alias-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON file with 'labels' and/or 'relations' alias groups: "
            "{\"canonical\": [\"alias\"]}."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON report to this path.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    label_aliases, relation_aliases = _load_aliases(args.alias_file)

    report = run(
        dataset=args.dataset,
        adapter_name=args.adapter,
        limit=args.limit,
        corpus_root=args.corpus_root,
        label_aliases=label_aliases,
        relation_aliases=relation_aliases,
    )
    _print_summary(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            json.dump(report.as_dict(), fh, indent=2)
        log.info("wrote %s", args.out)

    return 0


def _load_aliases(path: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    if path is None:
        return {}, {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return (
        metrics.expand_aliases(data.get("labels", {})),
        metrics.expand_aliases(data.get("relations", {})),
    )


if __name__ == "__main__":
    sys.exit(main())
