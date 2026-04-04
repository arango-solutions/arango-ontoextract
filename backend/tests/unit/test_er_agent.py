"""Unit tests for the ER LangGraph agent node."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from app.extraction.agents.er_agent import (
    _create_extension_edges,
    _run_er_matching,
    er_agent_node,
)
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


class TestRunERMatching:
    """Tests for _run_er_matching internal function."""

    def test_skips_when_no_ontology_classes_collection(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        mock_er_module = MagicMock()
        mock_db_client_module = MagicMock()
        mock_db_client_module.get_db.return_value = mock_db
        mock_temporal_module = MagicMock()
        mock_temporal_module.NEVER_EXPIRES = "9999-12-31T00:00:00Z"

        with patch.dict(sys.modules, {
            "app.services.er": mock_er_module,
            "app.db.client": mock_db_client_module,
            "app.services.temporal": mock_temporal_module,
        }):
            result = _run_er_matching(
                run_id="r1", extracted_classes=[], ontology_id="onto1"
            )
        assert result["status"] == "skipped"
        assert result["reason"] == "no_ontology_classes_collection"

    def test_returns_empty_when_no_existing_classes(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        mock_db_client_module = MagicMock()
        mock_db_client_module.get_db.return_value = mock_db
        mock_temporal_module = MagicMock()
        mock_temporal_module.NEVER_EXPIRES = "9999-12-31T00:00:00Z"

        with (
            patch.dict(sys.modules, {
                "app.services.er": MagicMock(),
                "app.db.client": mock_db_client_module,
                "app.services.temporal": mock_temporal_module,
            }),
            patch("app.extraction.agents.er_agent.run_aql", return_value=iter([])),
        ):
            result = _run_er_matching(
                run_id="r1",
                extracted_classes=[ExtractedClass(
                    uri="u1", label="A", description="d", confidence=0.9
                )],
                ontology_id="onto1",
            )
        assert result["status"] == "completed"
        assert result["merge_candidates"] == []

    def test_finds_merge_candidates_above_threshold(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        mock_db_client_module = MagicMock()
        mock_db_client_module.get_db.return_value = mock_db
        mock_temporal_module = MagicMock()
        mock_temporal_module.NEVER_EXPIRES = "9999-12-31T00:00:00Z"

        mock_explain = MagicMock(return_value={
            "combined_score": 0.95,
            "field_scores": {"label": 0.9},
        })
        mock_er_module = MagicMock()
        mock_er_module.explain_match = mock_explain

        with (
            patch.dict(sys.modules, {
                "app.services.er": mock_er_module,
                "app.db.client": mock_db_client_module,
                "app.services.temporal": mock_temporal_module,
            }),
            patch("app.extraction.agents.er_agent.run_aql", return_value=iter([
                {"key": "k1", "label": "ExistingA", "uri": "http://ex.org#ExA"},
            ])),
            patch("app.extraction.agents.er_agent.settings") as mock_settings,
        ):
            mock_settings.er_vector_similarity_threshold = 0.7
            result = _run_er_matching(
                run_id="r1",
                extracted_classes=[ExtractedClass(
                    uri="u1", label="A", description="d", confidence=0.9
                )],
                ontology_id="onto1",
            )

        assert result["status"] == "completed"
        assert len(result["merge_candidates"]) == 1
        assert result["merge_candidates"][0]["combined_score"] == 0.95

    def test_handles_db_exception_gracefully(self):
        mock_er_module = MagicMock()
        mock_db_client_module = MagicMock()
        mock_db_client_module.get_db.side_effect = RuntimeError("no db")
        mock_temporal_module = MagicMock()
        mock_temporal_module.NEVER_EXPIRES = "9999-12-31T00:00:00Z"

        with patch.dict(sys.modules, {
            "app.services.er": mock_er_module,
            "app.db.client": mock_db_client_module,
            "app.services.temporal": mock_temporal_module,
        }):
            result = _run_er_matching(
                run_id="r1", extracted_classes=[], ontology_id="onto1"
            )
        assert result["status"] == "completed"
        assert result["merge_candidates"] == []


class TestCreateExtensionEdges:
    """Tests for _create_extension_edges internal function."""

    def test_returns_edge_count_on_success(self):
        mock_result = MagicMock()
        mock_result.edges_created = 3
        mock_cross_tier = MagicMock()
        mock_cross_tier.create_cross_tier_edges.return_value = mock_result

        with patch.dict(sys.modules, {
            "app.services.cross_tier": mock_cross_tier,
        }):
            count = _create_extension_edges(
                run_id="r1", extracted_classes=[], ontology_id="onto1"
            )
        assert count == 3

    def test_returns_zero_on_failure(self):
        mock_cross_tier = MagicMock()
        mock_cross_tier.create_cross_tier_edges.side_effect = RuntimeError("fail")

        with patch.dict(sys.modules, {
            "app.services.cross_tier": mock_cross_tier,
        }):
            count = _create_extension_edges(
                run_id="r1", extracted_classes=[], ontology_id="onto1"
            )
        assert count == 0
