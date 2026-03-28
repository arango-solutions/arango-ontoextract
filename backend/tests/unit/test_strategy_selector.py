"""Unit tests for the Strategy Selector agent."""

from __future__ import annotations

from app.extraction.agents.strategy import _classify_document, strategy_selector_node
from app.extraction.state import ExtractionPipelineState


class TestClassifyDocument:
    def test_empty_chunks_returns_default(self):
        assert _classify_document([]) == "default"

    def test_short_technical_doc(self):
        chunks = [
            {"text": "This specification defines requirements per ISO 27001."},
            {"text": "RFC 2119 keywords SHALL and MUST are used throughout."},
            {"text": "Section 3.1: definitions per the standard."},
        ]
        result = _classify_document(chunks)
        assert result == "short_technical"

    def test_tabular_document(self):
        chunks = [
            {"text": "| Column A | Column B | Column C | Column D | Column E |"},
            {"text": "| val1 | val2 | val3 | val4 | val5 |"},
            {"text": "| Row | Data | More | Info | Here |"},
            {"text": "| X | Y | Z | W | V |"},
        ]
        result = _classify_document(chunks)
        assert result == "tabular_structured"

    def test_long_narrative_doc(self):
        chunks = [{"text": f"Paragraph {i} of a long narrative document."} for i in range(55)]
        result = _classify_document(chunks)
        assert result == "long_narrative"

    def test_default_classification(self):
        chunks = [
            {"text": "This is a general document about business processes."},
            {"text": "It discusses various organizational topics."},
        ]
        result = _classify_document(chunks)
        assert result == "default"


class TestStrategySelectorNode:
    def test_returns_strategy_config(self):
        state: ExtractionPipelineState = {
            "run_id": "test_run_1",
            "document_id": "doc_1",
            "document_chunks": [
                {"text": "ISO 9001 specification requirement for quality management."},
                {"text": "This standard defines the requirements for certification."},
            ],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "initialized",
            "metadata": {},
        }

        result = strategy_selector_node(state)

        assert "strategy_config" in result
        config = result["strategy_config"]
        assert "model_name" in config
        assert "prompt_template_key" in config
        assert "chunk_batch_size" in config
        assert "num_passes" in config
        assert config["num_passes"] > 0

    def test_produces_step_log(self):
        state: ExtractionPipelineState = {
            "run_id": "test_run_2",
            "document_id": "doc_2",
            "document_chunks": [{"text": "Some text."}],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "initialized",
            "metadata": {},
        }

        result = strategy_selector_node(state)

        assert "step_logs" in result
        assert len(result["step_logs"]) == 1
        log_entry = result["step_logs"][0]
        assert log_entry["step"] == "strategy_selector"
        assert log_entry["status"] == "completed"
        assert "duration_seconds" in log_entry

    def test_different_doc_types_produce_different_configs(self):
        technical_state: ExtractionPipelineState = {
            "run_id": "t1",
            "document_id": "d1",
            "document_chunks": [
                {"text": "This RFC specification defines requirements."},
                {"text": "Per ISO standard section 4.2."},
            ],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "initialized",
            "metadata": {},
        }

        narrative_state: ExtractionPipelineState = {
            "run_id": "t2",
            "document_id": "d2",
            "document_chunks": [
                {"text": f"Chapter {i}: long narrative content."} for i in range(55)
            ],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "initialized",
            "metadata": {},
        }

        tech_result = strategy_selector_node(technical_state)
        narr_result = strategy_selector_node(narrative_state)

        assert (
            tech_result["strategy_config"]["prompt_template_key"]
            != narr_result["strategy_config"]["prompt_template_key"]
            or tech_result["strategy_config"]["chunk_batch_size"]
            != narr_result["strategy_config"]["chunk_batch_size"]
        )
