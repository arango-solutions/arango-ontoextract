"""Unit tests for the Re-DocRED and WebNLG dataset loaders.

These tests write tiny synthetic fixtures to a temp directory so they run
without any downloaded corpora.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.ontology_extraction.datasets import hitl_regression, redocred, webnlg
from benchmarks.ontology_extraction.metrics import ClassMention, Triple

# ─────────────────────────── Re-DocRED ────────────────────────────


REDOCRED_SAMPLE = [
    {
        "title": "Alice and Bob",
        "sents": [
            ["Alice", "works", "at", "Acme", "."],
            ["Bob", "knows", "Alice", "."],
        ],
        "vertexSet": [
            [{"name": "Alice", "type": "PER", "sent_id": 0, "pos": [0, 1]}],
            [{"name": "Bob", "type": "PER", "sent_id": 1, "pos": [0, 1]}],
            [{"name": "Acme", "type": "ORG", "sent_id": 0, "pos": [3, 4]}],
        ],
        "labels": [
            {"h": 0, "t": 2, "r": "P108", "evidence": [0]},  # Alice works_at Acme
            {"h": 1, "t": 0, "r": "P26", "evidence": [1]},   # Bob knows Alice
        ],
    }
]


class TestRedocredLoader:
    def test_loads_document(self, tmp_path: Path):
        root = tmp_path / "redocred"
        root.mkdir()
        (root / "dev_revised.json").write_text(json.dumps(REDOCRED_SAMPLE), encoding="utf-8")

        docs = list(redocred.load(root))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "Alice and Bob"
        assert "Alice works at Acme" in doc.text
        assert ClassMention.of("Alice", "PER") in doc.gold_classes
        assert ClassMention.of("Acme", "ORG") in doc.gold_classes
        assert Triple.of("Alice", "P108", "Acme") in doc.gold_relations

    def test_limit_truncates(self, tmp_path: Path):
        root = tmp_path / "redocred"
        root.mkdir()
        docs_json = REDOCRED_SAMPLE * 5
        (root / "dev_revised.json").write_text(json.dumps(docs_json), encoding="utf-8")

        assert len(list(redocred.load(root, limit=2))) == 2

    def test_missing_file_raises(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            list(redocred.load(empty))

    def test_relation_with_dangling_vertex_index_is_skipped(self, tmp_path: Path):
        root = tmp_path / "redocred"
        root.mkdir()
        bad = json.dumps(
            [
                {
                    "title": "bad",
                    "sents": [["X"]],
                    "vertexSet": [[{"name": "X", "type": "MISC"}]],
                    "labels": [{"h": 0, "t": 99, "r": "P0"}],
                }
            ]
        )
        (root / "dev_revised.json").write_text(bad, encoding="utf-8")
        docs = list(redocred.load(root))
        assert docs[0].gold_relations == set()


# ─────────────────────────── WebNLG ────────────────────────────


WEBNLG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<benchmark>
  <entries>
    <entry eid="Id1" size="2">
      <modifiedtripleset>
        <mtriple>Alice | works_at | Acme</mtriple>
        <mtriple>Bob | knows | Alice</mtriple>
      </modifiedtripleset>
      <lex comment="good">Alice works at Acme and Bob knows Alice.</lex>
      <lex comment="also-good">Bob is acquainted with Alice, who is employed by Acme.</lex>
    </entry>
    <entry eid="Id2">
      <modifiedtripleset>
        <mtriple>Paris | capital_of | France</mtriple>
      </modifiedtripleset>
      <lex>Paris is the capital of France.</lex>
    </entry>
  </entries>
</benchmark>
"""


class TestWebnlgLoader:
    def test_loads_entries(self, tmp_path: Path):
        root = tmp_path / "webnlg"
        root.mkdir()
        (root / "rdf-to-text-test.xml").write_text(WEBNLG_XML, encoding="utf-8")

        docs = list(webnlg.load(root))
        assert [d.id for d in docs] == ["Id1", "Id2"]
        first = docs[0]
        assert first.text == "Alice works at Acme and Bob knows Alice."
        assert Triple.of("Alice", "works_at", "Acme") in first.gold_relations
        assert Triple.of("Bob", "knows", "Alice") in first.gold_relations
        assert ClassMention.of("Alice", "entity") in first.gold_classes

    def test_merge_lex_concatenates_realizations(self, tmp_path: Path):
        root = tmp_path / "webnlg"
        root.mkdir()
        (root / "rdf-to-text-test.xml").write_text(WEBNLG_XML, encoding="utf-8")

        docs = list(webnlg.load(root, merge_lex=True))
        assert "acquainted" in docs[0].text

    def test_limit_truncates(self, tmp_path: Path):
        root = tmp_path / "webnlg"
        root.mkdir()
        (root / "rdf-to-text-test.xml").write_text(WEBNLG_XML, encoding="utf-8")

        assert len(list(webnlg.load(root, limit=1))) == 1

    def test_missing_file_raises(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            list(webnlg.load(empty))


# ─────────────────────── HITL Regression ────────────────────────


HITL_FIXTURE = {
    "schema_version": "hitl-regression-v1",
    "ontology_id": "onto_1",
    "generated_from": "curation_decisions",
    "documents": [
        {
            "id": "hitl-d1-Customer",
            "text": "A customer opens an account.",
            "gold_classes": [{"label": "Customer", "type": "DomainClass"}],
            "gold_relations": [
                {"head": "Customer", "relation": "opens", "tail": "Account"}
            ],
            "negative_classes": [{"label": "Ghost", "type": ""}],
            "negative_relations": [],
            "source_meta": {
                "decision_key": "d1",
                "issue_reasons": ["bad_label"],
            },
        }
    ],
}


class TestHitlRegressionLoader:
    def test_loads_hitl_regression_fixture(self, tmp_path: Path):
        root = tmp_path / "hitl"
        root.mkdir()
        (root / "hitl_regression.json").write_text(
            json.dumps(HITL_FIXTURE),
            encoding="utf-8",
        )

        docs = list(hitl_regression.load(root))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "hitl-d1-Customer"
        assert ClassMention.of("Customer", "DomainClass") in doc.gold_classes
        assert Triple.of("Customer", "opens", "Account") in doc.gold_relations
        assert doc.source_meta["negative_classes"] == [{"label": "Ghost", "type": ""}]
        assert doc.source_meta["decision_key"] == "d1"

    def test_accepts_direct_fixture_file_path(self, tmp_path: Path):
        fixture = tmp_path / "fixture.json"
        fixture.write_text(json.dumps(HITL_FIXTURE), encoding="utf-8")

        assert len(list(hitl_regression.load(fixture, limit=1))) == 1

    def test_rejects_wrong_schema_version(self, tmp_path: Path):
        fixture = tmp_path / "hitl_regression.json"
        fixture.write_text(json.dumps({"schema_version": "nope"}), encoding="utf-8")

        with pytest.raises(ValueError):
            list(hitl_regression.load(fixture))
