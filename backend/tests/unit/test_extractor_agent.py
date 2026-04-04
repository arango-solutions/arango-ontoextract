"""Unit tests for the extractor agent: _get_llm, _batch_chunks, _parse_llm_response,
_retrieve_relevant_chunks, and the extractor_node LangGraph node.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extraction.agents.extractor import (
    _batch_chunks,
    _get_llm,
    _parse_llm_response,
    _retrieve_relevant_chunks,
    extractor_node,
)
from app.models.ontology import ExtractionResult

# ---------------------------------------------------------------------------
# _get_llm
# ---------------------------------------------------------------------------


class TestGetLlm:
    def test_returns_anthropic_for_claude(self):
        mock_anthropic_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatAnthropic = mock_anthropic_cls
        with (
            patch("app.extraction.agents.extractor.settings") as mock_settings,
            patch.dict("sys.modules", {"langchain_anthropic": mock_module}),
        ):
            mock_settings.anthropic_api_key = "sk-test"
            _get_llm("claude-3-opus")
        mock_anthropic_cls.assert_called_once()

    def test_returns_openai_for_gpt(self):
        mock_openai_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOpenAI = mock_openai_cls
        with (
            patch("app.extraction.agents.extractor.settings") as mock_settings,
            patch.dict("sys.modules", {"langchain_openai": mock_module}),
        ):
            mock_settings.openai_api_key = "sk-test"
            mock_settings.openai_base_url = ""
            _get_llm("gpt-4o")
        mock_openai_cls.assert_called_once()


# ---------------------------------------------------------------------------
# _batch_chunks
# ---------------------------------------------------------------------------


class TestBatchChunks:
    def test_single_batch(self):
        chunks = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        batches = _batch_chunks(chunks, batch_size=5)
        assert len(batches) == 1
        assert "[Chunk 1]" in batches[0]
        assert "[Chunk 3]" in batches[0]

    def test_multiple_batches(self):
        chunks = [{"text": f"chunk{i}"} for i in range(7)]
        batches = _batch_chunks(chunks, batch_size=3)
        assert len(batches) == 3  # 3+3+1
        assert "[Chunk 1]" in batches[0]
        assert "[Chunk 4]" in batches[1]

    def test_empty_chunks(self):
        assert _batch_chunks([], batch_size=5) == []


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_parses_valid_json(self):
        data = {
            "classes": [
                {
                    "uri": "http://ex.org#A",
                    "label": "A",
                    "description": "A class",
                    "confidence": 0.9,
                }
            ]
        }
        result = _parse_llm_response(json.dumps(data), pass_number=1, model_name="m")
        assert isinstance(result, ExtractionResult)
        assert len(result.classes) == 1
        assert result.pass_number == 1
        assert result.model == "m"

    def test_strips_markdown_fences(self):
        data = {"classes": [{"uri": "u", "label": "L", "description": "d", "confidence": 0.5}]}
        raw = f"```json\n{json.dumps(data)}\n```"
        result = _parse_llm_response(raw, 1, "m")
        assert len(result.classes) == 1

    def test_clamps_confidence(self):
        data = {"classes": [{"uri": "u", "label": "L", "description": "d", "confidence": 1.5}]}
        result = _parse_llm_response(json.dumps(data), 1, "m")
        assert result.classes[0].confidence == 1.0

    def test_adds_default_property_confidence(self):
        data = {
            "classes": [
                {
                    "uri": "u",
                    "label": "L",
                    "description": "d",
                    "confidence": 0.8,
                    "properties": [
                        {
                            "uri": "p1",
                            "label": "P",
                            "description": "pd",
                            "property_type": "datatype",
                            "range": "xsd:string",
                        }
                    ],
                }
            ]
        }
        result = _parse_llm_response(json.dumps(data), 1, "m")
        assert result.classes[0].properties[0].confidence == 0.5

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_response("not json", 1, "m")

    def test_fills_missing_pass_and_model(self):
        data = {"classes": []}
        result = _parse_llm_response(json.dumps(data), 2, "gpt-4o")
        assert result.pass_number == 2
        assert result.model == "gpt-4o"


# ---------------------------------------------------------------------------
# _retrieve_relevant_chunks
# ---------------------------------------------------------------------------


class TestRetrieveRelevantChunks:
    def test_falls_back_when_no_collection(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        chunks = [{"text": "a"}]
        with patch("app.extraction.agents.extractor.get_db", return_value=mock_db):
            result = _retrieve_relevant_chunks("doc1", chunks, "batch text")
        assert result is chunks

    def test_falls_back_when_no_embedding(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        chunks = [{"text": "a"}]  # no embedding key
        with patch("app.extraction.agents.extractor.get_db", return_value=mock_db):
            result = _retrieve_relevant_chunks("doc1", chunks, "batch text")
        assert result is chunks

    def test_returns_vector_results_when_available(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        chunks = [{"text": "a", "embedding": [0.1, 0.2]}]
        vector_results = [{"text": "similar chunk"}]

        with (
            patch("app.extraction.agents.extractor.get_db", return_value=mock_db),
            patch("app.extraction.agents.extractor.run_aql", return_value=vector_results),
        ):
            result = _retrieve_relevant_chunks("doc1", chunks, "batch text")
        assert result == vector_results

    def test_falls_back_on_exception(self):
        chunks = [{"text": "a", "embedding": [0.1]}]
        with patch("app.extraction.agents.extractor.get_db", side_effect=RuntimeError("no db")):
            result = _retrieve_relevant_chunks("doc1", chunks, "batch text")
        assert result is chunks


# ---------------------------------------------------------------------------
# extractor_node
# ---------------------------------------------------------------------------


class TestExtractorNode:
    def _make_state(self, chunks=None) -> dict:
        return {
            "run_id": "r1",
            "document_id": "d1",
            "document_chunks": chunks or [{"text": "hello"}],
            "extraction_passes": [],
            "errors": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "step_logs": [],
            "current_step": "strategy_selector",
            "strategy_config": {
                "model_name": "test-model",
                "prompt_template_key": "tier1_standard",
                "chunk_batch_size": 10,
                "num_passes": 1,
            },
            "domain_context": "",
            "metadata": {},
        }

    @pytest.mark.asyncio
    async def test_produces_extraction_passes(self):
        extraction_json = json.dumps(
            {"classes": [{"uri": "u1", "label": "L", "description": "d", "confidence": 0.8}]}
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content=extraction_json, usage_metadata=None)

        mock_template = MagicMock()
        mock_template.render.return_value = ("system msg", "user msg")

        with (
            patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
            patch("app.extraction.agents.extractor.get_template", return_value=mock_template),
            patch(
                "app.extraction.agents.extractor._retrieve_relevant_chunks",
                side_effect=lambda did, c, bt: c,
            ),
        ):
            result = await extractor_node(self._make_state())

        assert len(result["extraction_passes"]) == 1
        assert len(result["extraction_passes"][0].classes) == 1
        assert len(result["step_logs"]) == 1

    @pytest.mark.asyncio
    async def test_handles_empty_chunks(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content=json.dumps({"classes": []}), usage_metadata=None
        )
        mock_template = MagicMock()
        mock_template.render.return_value = ("sys", "usr")

        with (
            patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
            patch("app.extraction.agents.extractor.get_template", return_value=mock_template),
            patch(
                "app.extraction.agents.extractor._retrieve_relevant_chunks",
                side_effect=lambda did, c, bt: c,
            ),
        ):
            result = await extractor_node(self._make_state(chunks=[]))

        # 0 chunks -> 0 batches -> 0 classes but still completes
        assert len(result["extraction_passes"]) == 1

    @pytest.mark.asyncio
    async def test_accumulates_token_usage(self):
        extraction_json = json.dumps({"classes": []})
        mock_response = MagicMock(content=extraction_json)
        mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        mock_template = MagicMock()
        mock_template.render.return_value = ("sys", "usr")

        with (
            patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
            patch("app.extraction.agents.extractor.get_template", return_value=mock_template),
            patch(
                "app.extraction.agents.extractor._retrieve_relevant_chunks",
                side_effect=lambda did, c, bt: c,
            ),
        ):
            result = await extractor_node(self._make_state())

        assert result["token_usage"]["prompt_tokens"] >= 100
        assert result["token_usage"]["completion_tokens"] >= 50
