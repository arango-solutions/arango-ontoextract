"""Shared types for gold-standard dataset loaders."""
from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.ontology_extraction.metrics import ClassMention, Triple


@dataclass
class GoldDocument:
    """A single annotated document in a benchmark corpus.

    ``id`` is the stable document key used when reporting per-document scores.
    ``text`` is the raw text fed to the extractor adapter.
    ``gold_classes`` and ``gold_relations`` are the normalized reference sets.
    ``source_meta`` carries loader-specific metadata (useful for debugging but
    not consumed by the metric computation).
    """

    id: str
    text: str
    gold_classes: set[ClassMention] = field(default_factory=set)
    gold_relations: set[Triple] = field(default_factory=set)
    source_meta: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.text.strip()
