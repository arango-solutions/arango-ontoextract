"""Unit tests for the ER LangGraph agent node."""

from __future__ import annotations

from unittest.mock import patch

from app.extraction.agents.er_agent import er_agent_node
from app.extraction.state import ExtractionPipelineState
from app.models.ontology import ExtractedClass, ExtractionResult


def _make_state(
    *,
    consistency_result: ExtractionResult | None = None,
    ontology_id: str = "test_onto",
) -> ExtractionPipelineState:
    return {
        "run_id": "test_run",
        "document_id": "doc1",
        "document_chunks": [],
        "extraction_passes": [],
        "consistency_result": consistency_result,
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "consistency_checker",
        "metadata": {"ontology_id": ontology_id},
        "er_results": {},
        "filter_results": {},
        "merge_candidates": [],
    }


def _make_extraction_result(classes: list[ExtractedClass] | None = None) -> ExtractionResult:
    return ExtractionResult(
        classes=classes or [],
        pass_number=0,
        model="test-model",
    )


class TestERAgentNode:
    def test_skips_when_no_consistency_result(self):
        state = _make_state(consistency_result=None)
        result = er_agent_node(state)

        assert result["er_results"]["status"] == "skipped"
        assert result["merge_candidates"] == []
        assert result["current_step"] == "er_agent"

    def test_skips_when_empty_classes(self):
        state = _make_state(consistency_result=_make_extraction_result([]))
        result = er_agent_node(state)

        assert result["er_results"]["status"] == "skipped"

    @patch("app.extraction.agents.er_agent._run_er_matching")
    @patch("app.extraction.agents.er_agent._create_extension_edges")
    def test_runs_er_matching(self, mock_edges, mock_matching):
        mock_matching.return_value = {
            "status": "completed",
            "merge_candidates": [
                {"extracted_uri": "http://ex.org#A", "existing_key": "k1", "combined_score": 0.9}
            ],
        }
        mock_edges.return_value = 1

        classes = [
            ExtractedClass(
                uri="http://ex.org#A",
                label="ClassA",
                description="A class",
                confidence=0.9,
            )
        ]
        state = _make_state(consistency_result=_make_extraction_result(classes))
        result = er_agent_node(state)

        assert result["er_results"]["status"] == "completed"
        assert len(result["merge_candidates"]) == 1
        mock_matching.assert_called_once()
        mock_edges.assert_called_once()

    @patch("app.extraction.agents.er_agent._run_er_matching")
    def test_handles_er_failure_gracefully(self, mock_matching):
        mock_matching.side_effect = RuntimeError("ER failed")

        classes = [
            ExtractedClass(
                uri="http://ex.org#A",
                label="ClassA",
                description="A class",
                confidence=0.9,
            )
        ]
        state = _make_state(consistency_result=_make_extraction_result(classes))
        result = er_agent_node(state)

        assert result["er_results"]["status"] == "failed"
        assert any("ER agent error" in e for e in result["errors"])

    def test_step_log_emitted(self):
        state = _make_state(consistency_result=None)
        result = er_agent_node(state)

        assert len(result["step_logs"]) == 1
        assert result["step_logs"][0]["step"] == "er_agent"

    def test_preserves_existing_errors(self):
        state = _make_state(consistency_result=None)
        state["errors"] = ["previous error"]
        result = er_agent_node(state)

        assert "previous error" in result["errors"]
