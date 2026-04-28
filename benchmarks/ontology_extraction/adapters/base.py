"""Extractor adapter protocol shared across benchmark backends."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from benchmarks.ontology_extraction.metrics import ClassMention, Triple


@dataclass
class ExtractionResult:
    """Adapter output for a single document."""

    classes: set[ClassMention] = field(default_factory=set)
    relations: set[Triple] = field(default_factory=set)
    metadata: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.classes and not self.relations


@runtime_checkable
class ExtractionAdapter(Protocol):
    """Uniform interface for anything that extracts classes + relations from text.

    Implementations MUST be safe to call in any environment — mock adapters are
    used in CI without AOE's backend, LLMs, or ArangoDB.
    """

    name: str

    def extract(self, document_id: str, text: str) -> ExtractionResult:
        """Return extracted classes + relations for the given document."""
        ...
