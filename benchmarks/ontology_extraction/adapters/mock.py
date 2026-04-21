"""Deterministic, offline adapter used in CI and for harness sanity tests.

The mock scans the document text for a small, configurable vocabulary and emits
one class mention per match plus naive ``subject-verb-object`` relations derived
from adjacent sentences. This is not a useful extractor — it is a reproducible
baseline that exercises the metrics and dataset loaders end-to-end without
touching LLMs, databases, or the real pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from benchmarks.ontology_extraction.adapters.base import ExtractionAdapter, ExtractionResult
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


_WORD = re.compile(r"\b([A-Z][a-zA-Z][a-zA-Z0-9_-]+)\b")
_SENT = re.compile(r"[^.!?]+[.!?]")


@dataclass
class MockAdapter(ExtractionAdapter):
    """Regex-based deterministic extractor.

    Parameters
    ----------
    known_types:
        Optional mapping of ``label → type`` used to type the extracted class
        mentions. Labels found in the document but missing from the map are
        emitted with an empty type.
    known_relations:
        Optional set of relation verbs (or phrases) that the adapter will look
        for in sentences. When found, a ``(head, relation, tail)`` triple is
        emitted using the capitalized tokens on either side of the verb.
    """

    known_types: dict[str, str] = field(default_factory=dict)
    known_relations: set[str] = field(
        default_factory=lambda: {"is", "has", "uses", "contains", "owns", "knows"}
    )
    name: str = "mock"

    def extract(self, document_id: str, text: str) -> ExtractionResult:  # noqa: ARG002
        if not isinstance(text, str):
            raise TypeError("MockAdapter.extract(): text must be a string")

        classes: set[ClassMention] = set()
        relations: set[Triple] = set()

        for m in _WORD.finditer(text):
            label = m.group(1)
            type_ = self.known_types.get(label, "")
            classes.add(ClassMention.of(label, type_))

        for sentence in _SENT.findall(text):
            tokens = sentence.strip().split()
            for i, tok in enumerate(tokens):
                low = tok.lower().rstrip(",;:")
                if low in self.known_relations and 0 < i < len(tokens) - 1:
                    head = tokens[i - 1].rstrip(",;:")
                    tail = tokens[i + 1].rstrip(".,;:!?")
                    if _WORD.match(head) and _WORD.match(tail):
                        relations.add(Triple.of(head, low, tail))

        return ExtractionResult(classes=classes, relations=relations)
