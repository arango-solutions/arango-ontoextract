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

    def test_visual_heavy_presentation_via_chunk_kind(self):
        chunks = [
            {"text": "[Slide 1: Overview]", "chunk_kind": "visual"},
            {"text": "[Slide 2: Benefits]\nBody text.", "chunk_kind": "mixed"},
            {
                "text": "[Slide 3: Charts]\n[Visual omitted: slide 3 image 1]",
                "chunk_kind": "visual",
            },
            {"text": "More narrative content.", "chunk_kind": "text"},
        ]
        assert _classify_document(chunks) == "visual_heavy_presentation"

    def test_visual_heavy_via_pptx_format_with_any_visuals(self):
        chunks = [
            {"text": "[Slide 1: Title]", "chunk_kind": "visual", "doc_format": "pptx"},
            {"text": "Body text.", "chunk_kind": "text", "doc_format": "pptx"},
        ]
        assert _classify_document(chunks) == "visual_heavy_presentation"

    def test_legacy_chunks_without_chunk_kind_still_detected(self):
        chunks = [
            {"text": "[Slide 1: Overview]\n[Visual omitted: slide 1 image 1]"},
            {"text": "[Slide 2: Benefits]\n[Visual omitted: slide 2 image 1]"},
            {"text": "[Slide 3: Programs]\n[Visual omitted: slide 3 image 1]"},
            {"text": "Body text here."},
        ]
        assert _classify_document(chunks) == "visual_heavy_presentation"

    def test_one_diagram_does_not_flip_narrative(self):
        chunks = [{"text": f"Paragraph {i}.", "chunk_kind": "text"} for i in range(20)]
        chunks.append({"text": "[Visual omitted: page 5 image 1]", "chunk_kind": "visual"})
        # 1/21 = 0.048 < 0.3 threshold and no pptx format, so narrative wins
        assert _classify_document(chunks) != "visual_heavy_presentation"


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


class TestVisualHeavyStrategyEndToEnd:
    def test_strategy_selector_picks_visual_aware_prompt(self):
        state: ExtractionPipelineState = {
            "run_id": "visual_run",
            "document_id": "deck_1",
            "document_chunks": [
                {"text": "[Slide 1: Overview]", "chunk_kind": "visual"},
                {
                    "text": "[Slide 2: Benefits]\n[Visual omitted: slide 2 image 1]",
                    "chunk_kind": "visual",
                },
                {
                    "text": "[Slide 3: Programs]\n[Visual omitted: slide 3 image 1]",
                    "chunk_kind": "visual",
                },
                {"text": "Some narrative body.", "chunk_kind": "text"},
            ],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "initialized",
            "metadata": {},
        }

        result = strategy_selector_node(state)

        config = result["strategy_config"]
        assert config["prompt_template_key"] == "tier1_visual_aware"
        assert config["document_type"] == "visual_heavy_presentation"
        assert config["chunk_batch_size"] == 3

        step_log = result["step_logs"][0]
        assert step_log["metadata"]["document_type"] == "visual_heavy_presentation"


class TestVisualAwarePromptTemplate:
    def test_template_registers_and_renders(self):
        from app.extraction.prompts import get_template

        template = get_template("tier1_visual_aware")
        assert template.key == "tier1_visual_aware"

        system, user = template.render(
            chunks_text="[Chunk 1 | source_chunk_id=c1]\n[Slide 1: Overview]",
            domain_context="",
            extra_vars={"pass_number": 1, "model_name": "test-model"},
        )
        # Ensures the visual-marker guidance survived rendering.
        assert "[Slide N: Title]" in system
        assert "[Visual omitted:" in system
        assert "[Scanned" in system
        assert "Chunk 1 | source_chunk_id=c1" in user

    def test_template_documents_alt_text_confidence_ceiling(self):
        from app.extraction.prompts import get_template

        system = get_template("tier1_visual_aware").system_prompt
        # Encodes the contract: alt-text-only evidence must be down-weighted.
        assert "alt text" in system.lower()
        assert "0.7" in system or "0.7" in system.replace(" ", "")
