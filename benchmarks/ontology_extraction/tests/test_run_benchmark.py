"""End-to-end smoke test for the benchmark runner using a tiny synthetic corpus."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.ontology_extraction import run_benchmark

WEBNLG_FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<benchmark>
  <entries>
    <entry eid="Bench1">
      <modifiedtripleset>
        <mtriple>Alice | knows | Bob</mtriple>
      </modifiedtripleset>
      <lex>Alice knows Bob.</lex>
    </entry>
  </entries>
</benchmark>
"""


HITL_FIXTURE_JSON = {
    "schema_version": "hitl-regression-v1",
    "documents": [
        {
            "id": "Hitl1",
            "text": "Alice knows Bob.",
            "gold_classes": [
                {"label": "Alice", "type": ""},
                {"label": "Bob", "type": ""},
            ],
            "gold_relations": [
                {"head": "Alice", "relation": "knows", "tail": "Bob"},
            ],
        }
    ],
}


def _write_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "webnlg"
    root.mkdir()
    (root / "rdf-to-text-test.xml").write_text(WEBNLG_FIXTURE_XML, encoding="utf-8")
    return root


class TestRunBenchmark:
    def test_runs_end_to_end_with_mock_adapter(self, tmp_path: Path):
        corpus = _write_fixture(tmp_path)
        report = run_benchmark.run(
            dataset="webnlg",
            adapter_name="mock",
            corpus_root=corpus,
        )
        assert len(report.document_scores) == 1
        score = report.document_scores[0]
        assert score.document_id == "Bench1"
        # The mock adapter recognises the "knows" relation and emits the
        # corresponding triple. WebNLG gold relations are unpaired with types,
        # so we expect at least one relation TP end-to-end.
        assert report.micro_relations.tp >= 1

    def test_classes_are_scored_even_when_types_differ(self, tmp_path: Path):
        corpus = _write_fixture(tmp_path)
        report = run_benchmark.run(
            dataset="webnlg",
            adapter_name="mock",
            corpus_root=corpus,
        )
        # WebNLG tags all entities with type "entity"; the stock mock emits
        # empty types — so class TP is expected to be 0 but the harness must
        # still produce a well-formed per-document score rather than crash.
        assert report.micro_classes.fp + report.micro_classes.fn > 0

    def test_rejects_unknown_dataset(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            run_benchmark.run(dataset="nope", adapter_name="mock", corpus_root=tmp_path)

    def test_rejects_unknown_adapter(self, tmp_path: Path):
        corpus = _write_fixture(tmp_path)
        with pytest.raises(SystemExit):
            run_benchmark.run(
                dataset="webnlg", adapter_name="definitely-not-real", corpus_root=corpus
            )

    def test_writes_json_report_via_cli(self, tmp_path: Path):
        corpus = _write_fixture(tmp_path)
        out = tmp_path / "report.json"
        exit_code = run_benchmark.main(
            [
                "--dataset",
                "webnlg",
                "--adapter",
                "mock",
                "--corpus-root",
                str(corpus),
                "--out",
                str(out),
            ]
        )
        assert exit_code == 0
        assert out.is_file()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["documents"] == 1
        assert "micro" in payload and "macro" in payload
        assert payload["runtime"]["total_duration_ms"] >= 0
        assert payload["metadata"]["total_tokens"] == 0
        assert payload["efficiency"]["quality_per_dollar"] is None
        assert payload["per_document"][0]["duration_ms"] >= 0
        assert payload["per_document"][0]["metadata"]["model"] == "mock"

    def test_runs_hitl_regression_dataset(self, tmp_path: Path):
        root = tmp_path / "hitl"
        root.mkdir()
        (root / "hitl_regression.json").write_text(
            json.dumps(HITL_FIXTURE_JSON),
            encoding="utf-8",
        )

        report = run_benchmark.run(
            dataset="hitl-regression",
            adapter_name="mock",
            corpus_root=root,
        )

        assert len(report.document_scores) == 1
        assert report.micro_relations.tp == 1

    def test_cli_accepts_alias_file(self, tmp_path: Path):
        corpus = _write_fixture(tmp_path)
        aliases = tmp_path / "aliases.json"
        aliases.write_text(
            json.dumps({
                "labels": {"alice": ["alice person"]},
                "relations": {"knows": ["is acquainted with"]},
            }),
            encoding="utf-8",
        )

        exit_code = run_benchmark.main(
            [
                "--dataset",
                "webnlg",
                "--adapter",
                "mock",
                "--corpus-root",
                str(corpus),
                "--alias-file",
                str(aliases),
            ]
        )

        assert exit_code == 0
