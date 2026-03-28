"""Unit tests for extraction parsing and validation — mock LLM responses from fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.extraction.agents.extractor import _parse_llm_response
from app.models.ontology import ExtractionResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "llm_responses"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class TestParseLLMResponse:
    def test_parse_valid_fixture_01(self):
        fixture = _load_fixture("extraction_response_01.json")
        raw_json = json.dumps(fixture)

        result = _parse_llm_response(raw_json, pass_number=1, model_name="test-model")

        assert isinstance(result, ExtractionResult)
        assert len(result.classes) == 5
        assert result.pass_number == 1
        assert result.model == "test-model"

        org_class = next(c for c in result.classes if c.label == "Organization")
        assert org_class.confidence == 0.95
        assert org_class.parent_uri is None

        dept_class = next(c for c in result.classes if c.label == "Department")
        assert dept_class.parent_uri == "http://example.org/enterprise#Organization"

    def test_parse_valid_fixture_02(self):
        fixture = _load_fixture("extraction_response_02.json")
        raw_json = json.dumps(fixture)

        result = _parse_llm_response(raw_json, pass_number=2, model_name="test-model")

        assert isinstance(result, ExtractionResult)
        assert len(result.classes) == 6
        assert result.pass_number == 2

        manager = next(c for c in result.classes if c.label == "Manager")
        assert manager.parent_uri == "http://example.org/enterprise#Employee"

    def test_parse_with_markdown_fences(self):
        fixture = _load_fixture("extraction_response_01.json")
        raw_json = f"```json\n{json.dumps(fixture)}\n```"

        result = _parse_llm_response(raw_json, pass_number=1, model_name="test-model")
        assert isinstance(result, ExtractionResult)
        assert len(result.classes) == 5

    def test_parse_injects_pass_number_and_model(self):
        fixture = _load_fixture("extraction_response_01.json")
        raw_json = json.dumps(fixture)

        result = _parse_llm_response(raw_json, pass_number=42, model_name="custom-model")
        assert result.pass_number == 42
        assert result.model == "custom-model"

    def test_parse_adds_default_properties_if_missing(self):
        minimal = {
            "classes": [
                {
                    "uri": "http://example.org/test#Foo",
                    "label": "Foo",
                    "description": "A test class",
                    "confidence": 0.9,
                }
            ]
        }
        raw_json = json.dumps(minimal)

        result = _parse_llm_response(raw_json, pass_number=1, model_name="test")
        assert result.classes[0].properties == []

    def test_parse_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError, KeyError)):
            _parse_llm_response("not valid json at all", pass_number=1, model_name="test")

    def test_parse_invalid_schema_raises(self):
        bad_data = {"classes": [{"uri": "x", "label": "y"}]}
        with pytest.raises((ValueError, KeyError, TypeError)):
            _parse_llm_response(json.dumps(bad_data), pass_number=1, model_name="test")

    def test_all_fixtures_produce_valid_results(self):
        for fixture_file in sorted(FIXTURES_DIR.glob("extraction_response_*.json")):
            fixture = json.loads(fixture_file.read_text())
            raw_json = json.dumps(fixture)
            result = _parse_llm_response(
                raw_json, pass_number=1, model_name="test"
            )
            assert isinstance(result, ExtractionResult)
            assert len(result.classes) > 0
