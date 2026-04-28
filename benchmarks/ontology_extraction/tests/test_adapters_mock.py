"""Unit tests for the mock extraction adapter."""
from __future__ import annotations

import pytest

from benchmarks.ontology_extraction.adapters import ExtractionAdapter, MockAdapter
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


class TestMockAdapter:
    def test_conforms_to_adapter_protocol(self):
        adapter = MockAdapter()
        assert isinstance(adapter, ExtractionAdapter)
        assert adapter.name == "mock"

    def test_extracts_capitalized_tokens_as_classes(self):
        adapter = MockAdapter()
        result = adapter.extract("doc1", "Alice knows Bob.")
        labels = {c.label for c in result.classes}
        assert "alice" in labels
        assert "bob" in labels

    def test_applies_known_types(self):
        adapter = MockAdapter(known_types={"Alice": "Person", "Bob": "Person"})
        result = adapter.extract("doc1", "Alice knows Bob.")
        assert ClassMention.of("Alice", "Person") in result.classes

    def test_emits_triples_around_known_relations(self):
        adapter = MockAdapter(known_relations={"knows"})
        result = adapter.extract("doc1", "Alice knows Bob. Carol owns Acme.")
        assert Triple.of("Alice", "knows", "Bob") in result.relations

    def test_deterministic_across_calls(self):
        adapter = MockAdapter()
        a = adapter.extract("doc1", "Alice knows Bob.")
        b = adapter.extract("doc1", "Alice knows Bob.")
        assert a.classes == b.classes
        assert a.relations == b.relations

    def test_empty_text_yields_empty_result(self):
        adapter = MockAdapter()
        result = adapter.extract("doc-empty", "")
        assert result.is_empty()
        assert result.metadata["model"] == "mock"
        assert result.metadata["estimated_cost_usd"] == 0.0

    def test_non_string_text_raises(self):
        adapter = MockAdapter()
        with pytest.raises(TypeError):
            adapter.extract("doc", None)  # type: ignore[arg-type]
