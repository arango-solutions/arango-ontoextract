"""Unit tests for the Consistency Checker agent."""

from __future__ import annotations

from app.extraction.agents.consistency import consistency_checker_node
from app.extraction.state import ExtractionPipelineState
from app.models.ontology import ExtractedClass, ExtractedProperty, ExtractionResult


def _make_class(
    uri: str,
    label: str,
    description: str = "desc",
    parent_uri: str | None = None,
    confidence: float = 0.9,
    properties: list[ExtractedProperty] | None = None,
) -> ExtractedClass:
    return ExtractedClass(
        uri=uri,
        label=label,
        description=description,
        parent_uri=parent_uri,
        confidence=confidence,
        properties=properties or [],
    )


def _make_result(
    classes: list[ExtractedClass],
    pass_number: int = 1,
) -> ExtractionResult:
    return ExtractionResult(
        classes=classes,
        pass_number=pass_number,
        model="test-model",
    )


class TestConsistencyChecker:
    def test_keeps_classes_appearing_in_all_passes(self):
        org = _make_class("http://ex.org#Org", "Organization")
        dept = _make_class("http://ex.org#Dept", "Department")

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([org, dept], pass_number=1),
                _make_result([org, dept], pass_number=2),
                _make_result([org, dept], pass_number=3),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)

        cr = result["consistency_result"]
        assert cr is not None
        assert len(cr.classes) == 2
        for cls in cr.classes:
            assert cls.confidence == 1.0

    def test_filters_classes_below_threshold(self):
        org = _make_class("http://ex.org#Org", "Organization")
        rare = _make_class("http://ex.org#Rare", "RareConcept")

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([org, rare], pass_number=1),
                _make_result([org], pass_number=2),
                _make_result([org], pass_number=3),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)

        cr = result["consistency_result"]
        assert cr is not None
        uris = {c.uri.lower() for c in cr.classes}
        assert "http://ex.org#org" in uris
        assert "http://ex.org#rare" not in uris

    def test_confidence_scores_reflect_agreement_ratio(self):
        org = _make_class("http://ex.org#Org", "Organization")
        dept = _make_class("http://ex.org#Dept", "Department")

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([org, dept], pass_number=1),
                _make_result([org, dept], pass_number=2),
                _make_result([org], pass_number=3),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)
        cr = result["consistency_result"]

        org_cls = next(c for c in cr.classes if "org" in c.uri.lower())
        dept_cls = next(c for c in cr.classes if "dept" in c.uri.lower())

        assert org_cls.confidence == 1.0
        assert dept_cls.confidence == pytest.approx(2 / 3, abs=0.01)

    def test_merges_descriptions_longest_wins(self):
        short = _make_class("http://ex.org#X", "X", description="Short")
        long = _make_class("http://ex.org#X", "X", description="A much longer description")

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([short], pass_number=1),
                _make_result([long], pass_number=2),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)
        cr = result["consistency_result"]
        assert cr.classes[0].description == "A much longer description"

    def test_unions_properties_across_passes(self):
        prop_a = ExtractedProperty(
            uri="http://ex.org#propA",
            label="Property A",
            description="First property",
            property_type="object",
            range="http://ex.org#Y",
            confidence=0.9,
        )
        prop_b = ExtractedProperty(
            uri="http://ex.org#propB",
            label="Property B",
            description="Second property",
            property_type="datatype",
            range="xsd:string",
            confidence=0.8,
        )

        cls1 = _make_class("http://ex.org#X", "X", properties=[prop_a])
        cls2 = _make_class("http://ex.org#X", "X", properties=[prop_b])

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([cls1], pass_number=1),
                _make_result([cls2], pass_number=2),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)
        cr = result["consistency_result"]
        assert len(cr.classes[0].properties) == 2

    def test_empty_passes_produces_error(self):
        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)
        assert result["consistency_result"] is None
        assert any("No extraction passes" in e for e in result["errors"])

    def test_step_log_emitted(self):
        org = _make_class("http://ex.org#Org", "Org")

        state: ExtractionPipelineState = {
            "run_id": "test",
            "document_id": "doc",
            "document_chunks": [],
            "extraction_passes": [
                _make_result([org], pass_number=1),
                _make_result([org], pass_number=2),
            ],
            "strategy_config": {"consistency_threshold": 2},
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "extractor",
            "metadata": {},
        }

        result = consistency_checker_node(state)
        assert len(result["step_logs"]) == 1
        assert result["step_logs"][0]["step"] == "consistency_checker"


import pytest  # noqa: E402 — used by approx above
