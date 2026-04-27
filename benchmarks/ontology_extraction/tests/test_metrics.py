"""Unit tests for the benchmark metrics module."""
from __future__ import annotations

import pytest

from benchmarks.ontology_extraction.metrics import (
    AggregateReport,
    ClassMention,
    DocumentScore,
    Triple,
    aggregate,
    expand_aliases,
    normalize,
    score_sets,
)


class TestNormalize:
    def test_lowercases_and_trims(self):
        assert normalize("  Hello World  ") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize("Hello\n\tWorld") == "hello world"

    def test_none_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize(None)  # type: ignore[arg-type]


class TestAliases:
    def test_expand_aliases_normalizes_canonical_and_alias_values(self):
        aliases = expand_aliases({"Customer Account": ["Client Account", "Acct"]})
        assert aliases["customer account"] == "customer account"
        assert aliases["client account"] == "customer account"
        assert aliases["acct"] == "customer account"


class TestTriple:
    def test_of_normalizes_all_fields(self):
        t = Triple.of(" Alice ", "KNOWS", " BOB ")
        assert t == Triple(head="alice", relation="knows", tail="bob")

    def test_triples_are_hashable_and_set_safe(self):
        t1 = Triple.of("Alice", "knows", "Bob")
        t2 = Triple.of("alice", "KNOWS", "bob")
        assert {t1, t2} == {t1}


class TestClassMention:
    def test_default_type_is_empty(self):
        cm = ClassMention.of("Alice")
        assert cm == ClassMention(label="alice", type_="")

    def test_same_label_different_type_is_distinct(self):
        a = ClassMention.of("Alice", "Person")
        b = ClassMention.of("Alice", "Author")
        assert a != b


class TestScoreSets:
    def test_perfect_match(self):
        prf = score_sets({"a", "b"}, {"a", "b"})
        assert prf.precision == 1.0
        assert prf.recall == 1.0
        assert prf.f1 == 1.0
        assert (prf.tp, prf.fp, prf.fn) == (2, 0, 0)

    def test_partial_overlap(self):
        prf = score_sets({"a", "b", "c"}, {"b", "c", "d"})
        assert prf.tp == 2
        assert prf.fp == 1
        assert prf.fn == 1
        assert prf.precision == pytest.approx(2 / 3)
        assert prf.recall == pytest.approx(2 / 3)
        assert prf.f1 == pytest.approx(2 / 3)

    def test_empty_prediction_empty_gold_is_zero_not_one(self):
        prf = score_sets(set(), set())
        assert (prf.precision, prf.recall, prf.f1) == (0.0, 0.0, 0.0)

    def test_empty_prediction_nonempty_gold(self):
        prf = score_sets(set(), {"a", "b"})
        assert prf.recall == 0.0
        assert prf.precision == 0.0
        assert prf.f1 == 0.0
        assert prf.fn == 2

    def test_nonempty_prediction_empty_gold(self):
        prf = score_sets({"a"}, set())
        assert prf.precision == 0.0
        assert prf.fp == 1

    def test_duplicates_are_collapsed(self):
        prf = score_sets(["a", "a", "b"], ["a", "b"])
        assert prf.tp == 2
        assert prf.fp == 0

    def test_accepts_arbitrary_hashables(self):
        t1 = Triple.of("A", "r", "B")
        t2 = Triple.of("A", "r", "C")
        prf = score_sets({t1}, {t1, t2})
        assert prf.tp == 1 and prf.fn == 1

    def test_alias_aware_class_matching(self):
        aliases = expand_aliases({"customer account": ["client account"]})
        prf = score_sets(
            {ClassMention.of("Client Account", "entity")},
            {ClassMention.of("Customer Account", "entity")},
            label_aliases=aliases,
        )
        assert prf.tp == 1
        assert prf.fp == 0
        assert prf.fn == 0

    def test_alias_aware_relation_matching(self):
        label_aliases = expand_aliases({"acme": ["acme corp"]})
        relation_aliases = expand_aliases({"works at": ["employed by"]})
        prf = score_sets(
            {Triple.of("Alice", "employed by", "Acme Corp")},
            {Triple.of("Alice", "works at", "Acme")},
            label_aliases=label_aliases,
            relation_aliases=relation_aliases,
        )
        assert prf.tp == 1
        assert prf.fp == 0
        assert prf.fn == 0


def _ds(doc_id: str, cls: tuple[int, int, int], rel: tuple[int, int, int]) -> DocumentScore:
    from benchmarks.ontology_extraction.metrics import _prf  # type: ignore[attr-defined]

    return DocumentScore(
        document_id=doc_id,
        classes=_prf(*cls),
        relations=_prf(*rel),
    )


class TestAggregate:
    def test_empty_input_returns_empty_report(self):
        report = aggregate([])
        assert isinstance(report, AggregateReport)
        assert report.document_scores == []
        assert report.micro_classes.f1 == 0.0
        assert report.macro_classes.f1 == 0.0

    def test_micro_sums_counts_then_computes_prf(self):
        scores = [
            _ds("a", cls=(2, 0, 0), rel=(1, 1, 0)),
            _ds("b", cls=(1, 1, 1), rel=(0, 0, 2)),
        ]
        report = aggregate(scores)
        # micro classes: tp=3, fp=1, fn=1 → P=0.75 R=0.75 F1=0.75
        assert report.micro_classes.tp == 3
        assert report.micro_classes.fp == 1
        assert report.micro_classes.fn == 1
        assert report.micro_classes.precision == pytest.approx(0.75)
        # micro relations: tp=1, fp=1, fn=2 → P=0.5 R=0.333 F1=0.4
        assert report.micro_relations.precision == pytest.approx(0.5)
        assert report.micro_relations.recall == pytest.approx(1 / 3)

    def test_macro_skips_empty_documents(self):
        scores = [
            _ds("a", cls=(2, 0, 0), rel=(0, 0, 0)),
            _ds("b", cls=(0, 0, 0), rel=(1, 1, 1)),
        ]
        report = aggregate(scores)
        # only the non-empty class score ('a') contributes to macro_classes
        assert report.macro_classes.precision == pytest.approx(1.0)
        # only 'b' contributes to macro_relations
        assert report.macro_relations.precision == pytest.approx(0.5)

    def test_as_dict_round_trips_per_document_entries(self):
        scores = [_ds("a", cls=(1, 0, 0), rel=(0, 0, 0))]
        report = aggregate(scores)
        payload = report.as_dict()
        assert payload["documents"] == 1
        assert payload["per_document"][0]["document_id"] == "a"
        assert payload["per_document"][0]["classes"]["tp"] == 1
