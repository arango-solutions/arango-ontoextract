"""Precision / recall / F1 over class and relation sets.

The benchmark reduces ontology extraction to two set-comparison tasks:

* **Classes** — the set of ``(label, type)`` pairs extracted from a document.
* **Relations** — the set of ``(head, relation, tail)`` triples extracted
  from a document.

Exact set overlap is the default matcher. Labels are normalized (lower-cased,
whitespace-collapsed) before comparison; downstream code can override
:func:`normalize` to plug in lemmatization or alias-aware matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonicalize a label for set-comparison matching.

    Lower-cases, strips, and collapses internal whitespace. Intentionally
    conservative — callers that need lemmatization or alias-aware matching
    should wrap this function, not replace it.
    """
    if text is None:
        raise TypeError("normalize(): text must not be None")
    return _WS.sub(" ", text.strip()).lower()


@dataclass(frozen=True)
class Triple:
    """A typed relation triple ``(head, relation, tail)`` with normalized fields."""

    head: str
    relation: str
    tail: str

    @classmethod
    def of(cls, head: str, relation: str, tail: str) -> "Triple":
        return cls(normalize(head), normalize(relation), normalize(tail))


@dataclass(frozen=True)
class ClassMention:
    """A typed class mention ``(label, type)`` with normalized fields."""

    label: str
    type_: str = ""

    @classmethod
    def of(cls, label: str, type_: str = "") -> "ClassMention":
        return cls(normalize(label), normalize(type_))


@dataclass(frozen=True)
class PRF:
    """Precision / recall / F1 scores plus raw TP/FP/FN counts."""

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def _prf(tp: int, fp: int, fn: int) -> PRF:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    return PRF(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn)


def score_sets(predicted: Iterable, gold: Iterable) -> PRF:
    """Compute set-overlap precision/recall/F1.

    Both inputs are materialized to sets — duplicates collapse. Empty gold *and*
    empty predicted yields a zero score (not 1.0) to avoid silently rewarding
    empty-extraction baselines.
    """
    pred_set = set(predicted)
    gold_set = set(gold)
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    return _prf(tp, fp, fn)


@dataclass
class DocumentScore:
    """Per-document score, retained so we can compute macro averages."""

    document_id: str
    classes: PRF
    relations: PRF


@dataclass
class AggregateReport:
    """Aggregate report across all scored documents.

    * ``micro_*`` — sums TP/FP/FN across documents then computes PRF once.
    * ``macro_*`` — averages per-document PRF; empty documents are skipped.
    """

    document_scores: list[DocumentScore] = field(default_factory=list)
    micro_classes: PRF = field(default_factory=lambda: _prf(0, 0, 0))
    micro_relations: PRF = field(default_factory=lambda: _prf(0, 0, 0))
    macro_classes: PRF = field(default_factory=lambda: _prf(0, 0, 0))
    macro_relations: PRF = field(default_factory=lambda: _prf(0, 0, 0))

    def as_dict(self) -> dict:
        return {
            "documents": len(self.document_scores),
            "micro": {
                "classes": self.micro_classes.as_dict(),
                "relations": self.micro_relations.as_dict(),
            },
            "macro": {
                "classes": self.macro_classes.as_dict(),
                "relations": self.macro_relations.as_dict(),
            },
            "per_document": [
                {
                    "document_id": ds.document_id,
                    "classes": ds.classes.as_dict(),
                    "relations": ds.relations.as_dict(),
                }
                for ds in self.document_scores
            ],
        }


def aggregate(document_scores: list[DocumentScore]) -> AggregateReport:
    """Compute micro and macro averages over a list of per-document scores."""

    if not document_scores:
        return AggregateReport()

    micro_tp_c = sum(d.classes.tp for d in document_scores)
    micro_fp_c = sum(d.classes.fp for d in document_scores)
    micro_fn_c = sum(d.classes.fn for d in document_scores)
    micro_tp_r = sum(d.relations.tp for d in document_scores)
    micro_fp_r = sum(d.relations.fp for d in document_scores)
    micro_fn_r = sum(d.relations.fn for d in document_scores)

    def _macro(getter) -> PRF:
        non_empty = [getter(d) for d in document_scores if getter(d).tp + getter(d).fp + getter(d).fn]
        if not non_empty:
            return _prf(0, 0, 0)
        precision = sum(p.precision for p in non_empty) / len(non_empty)
        recall = sum(p.recall for p in non_empty) / len(non_empty)
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
        # macro averages don't carry TP/FP/FN as meaningful integers; report sums for transparency
        tp = sum(p.tp for p in non_empty)
        fp = sum(p.fp for p in non_empty)
        fn = sum(p.fn for p in non_empty)
        return PRF(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn)

    return AggregateReport(
        document_scores=document_scores,
        micro_classes=_prf(micro_tp_c, micro_fp_c, micro_fn_c),
        micro_relations=_prf(micro_tp_r, micro_fp_r, micro_fn_r),
        macro_classes=_macro(lambda d: d.classes),
        macro_relations=_macro(lambda d: d.relations),
    )
