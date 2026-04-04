"""Unit tests for faithfulness, quality_judge_node, and semantic_validator judges."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extraction.judges.faithfulness import (
    _DEFAULT_SCORE as FAITH_DEFAULT,
)
from app.extraction.judges.faithfulness import (
    _build_user_prompt as faith_build_prompt,
)
from app.extraction.judges.faithfulness import (
    _parse_response as faith_parse_response,
)
from app.extraction.judges.faithfulness import (
    judge_faithfulness,
)
from app.extraction.judges.qualitative_eval_node import (
    run_qualitative_evaluation,
)
from app.extraction.judges.quality_judge_node import quality_judge_node
from app.extraction.judges.semantic_validator import (
    _DEFAULT_SCORE as SEM_DEFAULT,
)
from app.extraction.judges.semantic_validator import (
    _build_user_prompt as sem_build_prompt,
)
from app.extraction.judges.semantic_validator import (
    _parse_response as sem_parse_response,
)
from app.extraction.judges.semantic_validator import (
    validate_semantics,
)
from app.extraction.state import ExtractionPipelineState
from app.models.ontology import ExtractedClass, ExtractedProperty, ExtractionResult


def _cls(uri: str = "http://ex.org#A", label: str = "A", desc: str = "desc") -> ExtractedClass:
    return ExtractedClass(uri=uri, label=label, description=desc, confidence=0.9)


def _cls_with_props(uri: str = "http://ex.org#A") -> ExtractedClass:
    return ExtractedClass(
        uri=uri,
        label="A",
        description="desc",
        confidence=0.9,
        properties=[
            ExtractedProperty(
                uri="http://ex.org#p1",
                label="prop1",
                description="a property",
                property_type="datatype",
                range="xsd:string",
                confidence=0.8,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Faithfulness: _parse_response
# ---------------------------------------------------------------------------


class TestFaithfulnessParseResponse:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "results": [
                {"uri": "http://ex.org#A", "rating": "EXPLICIT", "reason": "ok"},
                {"uri": "http://ex.org#B", "rating": "HALLUCINATED", "reason": "bad"},
            ]
        })
        scores = faith_parse_response(raw, {"http://ex.org#A", "http://ex.org#B"})
        assert scores["http://ex.org#A"] == 1.0
        assert scores["http://ex.org#B"] == 0.1

    def test_fills_defaults_for_missing_uris(self):
        raw = json.dumps({"results": [{"uri": "http://ex.org#A", "rating": "INFERRED"}]})
        scores = faith_parse_response(raw, {"http://ex.org#A", "http://ex.org#B"})
        assert scores["http://ex.org#A"] == 0.7
        assert scores["http://ex.org#B"] == FAITH_DEFAULT

    def test_strips_markdown_fences(self):
        raw = '```json\n{"results": [{"uri": "u1", "rating": "PLAUSIBLE"}]}\n```'
        scores = faith_parse_response(raw, {"u1"})
        assert scores["u1"] == 0.4

    def test_unknown_rating_gets_default(self):
        raw = json.dumps({"results": [{"uri": "u1", "rating": "UNKNOWN"}]})
        scores = faith_parse_response(raw, {"u1"})
        assert scores["u1"] == FAITH_DEFAULT

    def test_skips_empty_uri(self):
        raw = json.dumps({"results": [{"uri": "", "rating": "EXPLICIT"}]})
        scores = faith_parse_response(raw, {"u1"})
        assert "u1" in scores
        assert "" not in scores


class TestFaithfulnessBuildPrompt:
    def test_includes_chunks_and_classes(self):
        classes = [_cls()]
        chunks = [{"text": "hello world"}]
        prompt = faith_build_prompt(classes, chunks)
        assert "hello world" in prompt
        assert "http://ex.org#A" in prompt


# ---------------------------------------------------------------------------
# Faithfulness: judge_faithfulness (async)
# ---------------------------------------------------------------------------


class TestJudgeFaithfulness:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_classes(self):
        result = await judge_faithfulness([], [{"text": "x"}])
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_defaults_for_no_chunks(self):
        classes = [_cls("u1"), _cls("u2")]
        result = await judge_faithfulness(classes, [])
        assert result == {"u1": FAITH_DEFAULT, "u2": FAITH_DEFAULT}

    @pytest.mark.asyncio
    async def test_calls_llm_and_parses(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content=json.dumps({
                "results": [{"uri": "u1", "rating": "EXPLICIT"}]
            })
        )
        with patch("app.extraction.judges.faithfulness._get_llm", return_value=mock_llm):
            result = await judge_faithfulness(
                [_cls("u1")], [{"text": "some text"}], model_name="test-model"
            )
        assert result["u1"] == 1.0
        mock_llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_defaults_on_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("LLM down")
        with patch("app.extraction.judges.faithfulness._get_llm", return_value=mock_llm):
            result = await judge_faithfulness(
                [_cls("u1")], [{"text": "text"}], model_name="test-model"
            )
        assert result == {"u1": FAITH_DEFAULT}


# ---------------------------------------------------------------------------
# Semantic validator: _parse_response
# ---------------------------------------------------------------------------


class TestSemanticParseResponse:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "results": [
                {"uri": "u1", "score": 0.95, "issues": []},
                {"uri": "u2", "score": 0.3, "issues": ["bad range"]},
            ]
        })
        scores = sem_parse_response(raw, {"u1", "u2"})
        assert scores["u1"] == 0.95
        assert scores["u2"] == 0.3

    def test_clamps_scores(self):
        raw = json.dumps({"results": [{"uri": "u1", "score": 1.5}]})
        scores = sem_parse_response(raw, {"u1"})
        assert scores["u1"] == 1.0

        raw2 = json.dumps({"results": [{"uri": "u1", "score": -0.5}]})
        scores2 = sem_parse_response(raw2, {"u1"})
        assert scores2["u1"] == 0.0

    def test_fills_defaults_for_missing_uris(self):
        raw = json.dumps({"results": []})
        scores = sem_parse_response(raw, {"u1"})
        assert scores["u1"] == SEM_DEFAULT

    def test_strips_markdown_fences(self):
        raw = '```json\n{"results": [{"uri": "u1", "score": 0.7}]}\n```'
        scores = sem_parse_response(raw, {"u1"})
        assert scores["u1"] == 0.7


class TestSemanticBuildPrompt:
    def test_includes_class_properties(self):
        classes = [_cls_with_props()]
        prompt = sem_build_prompt(classes)
        assert "prop1" in prompt
        assert "xsd:string" in prompt


# ---------------------------------------------------------------------------
# Semantic validator: validate_semantics (async)
# ---------------------------------------------------------------------------


class TestValidateSemantics:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_classes(self):
        result = await validate_semantics([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_calls_llm_and_parses(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content=json.dumps({"results": [{"uri": "u1", "score": 0.9}]})
        )
        with patch("app.extraction.judges.semantic_validator._get_llm", return_value=mock_llm):
            result = await validate_semantics([_cls("u1")], model_name="test-model")
        assert result["u1"] == 0.9

    @pytest.mark.asyncio
    async def test_returns_defaults_on_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("boom")
        with patch("app.extraction.judges.semantic_validator._get_llm", return_value=mock_llm):
            result = await validate_semantics([_cls("u1")], model_name="test-model")
        assert result == {"u1": SEM_DEFAULT}


# ---------------------------------------------------------------------------
# Quality judge node
# ---------------------------------------------------------------------------


def _make_judge_state(
    *,
    consistency_result: ExtractionResult | None = None,
    chunks: list[dict] | None = None,
) -> ExtractionPipelineState:
    return {
        "run_id": "r1",
        "document_id": "d1",
        "document_chunks": chunks or [],
        "extraction_passes": [],
        "consistency_result": consistency_result,
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "consistency_checker",
        "metadata": {},
        "faithfulness_scores": {},
        "validity_scores": {},
        "er_results": {},
        "filter_results": {},
        "merge_candidates": [],
    }


class TestQualityJudgeNode:
    @pytest.mark.asyncio
    async def test_skips_when_no_consistency_result(self):
        state = _make_judge_state(consistency_result=None)
        result = await quality_judge_node(state)

        assert result["faithfulness_scores"] == {}
        assert result["validity_scores"] == {}
        assert len(result["step_logs"]) == 1
        assert result["step_logs"][0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_skips_when_empty_classes(self):
        cr = ExtractionResult(classes=[], pass_number=0, model="m")
        state = _make_judge_state(consistency_result=cr)
        result = await quality_judge_node(state)
        assert result["step_logs"][0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_runs_both_judges_and_updates_classes(self):
        classes = [_cls("u1"), _cls("u2")]
        cr = ExtractionResult(classes=classes, pass_number=0, model="m")
        state = _make_judge_state(consistency_result=cr, chunks=[{"text": "x"}])

        with (
            patch(
                "app.extraction.judges.quality_judge_node.judge_faithfulness",
                new_callable=AsyncMock,
                return_value={"u1": 0.9, "u2": 0.3},
            ),
            patch(
                "app.extraction.judges.quality_judge_node.validate_semantics",
                new_callable=AsyncMock,
                return_value={"u1": 1.0, "u2": 0.6},
            ),
        ):
            result = await quality_judge_node(state)

        assert result["faithfulness_scores"] == {"u1": 0.9, "u2": 0.3}
        assert result["validity_scores"] == {"u1": 1.0, "u2": 0.6}

        updated_cr = result["consistency_result"]
        u1_cls = next(c for c in updated_cr.classes if c.uri == "u1")
        assert u1_cls.faithfulness_score == 0.9
        assert u1_cls.semantic_validity_score == 1.0

        assert result["step_logs"][0]["status"] == "completed"


class TestQualitativeEvaluation:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_classes(self):
        result = await run_qualitative_evaluation(
            classes=[],
            chunks=[{"text": "hello"}],
        )
        assert result == {"strengths": [], "weaknesses": ["No classes extracted"]}

    @pytest.mark.asyncio
    async def test_map_reduce_with_text_parse_fallback(self):
        """Map phase produces observations, reduce phase synthesises them."""
        call_count = 0

        async def _fake_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            # First call(s) = map phase, last call = reduce phase
            if "Source Text" in messages[0].content:
                return MagicMock(content=json.dumps({
                    "observations": [
                        "ClassA is well-grounded in the text about ontologies",
                    ],
                }))
            return MagicMock(content=json.dumps({
                "strengths": ["- Strong grounding in source text"],
                "weaknesses": ["- Missing some concepts"],
            }))

        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = ValueError("Unsupported")
        mock_llm.ainvoke = AsyncMock(side_effect=_fake_ainvoke)

        with patch(
            "app.extraction.judges.qualitative_eval_node._get_llm",
            return_value=mock_llm,
        ):
            result = await run_qualitative_evaluation(
                classes=[_cls("u1", "ClassA", "desc")],
                chunks=[{"text": "This text discusses ontologies and ClassA."}],
                model_name="test-model",
            )

        assert result["strengths"] == ["- Strong grounding in source text"]
        assert result["weaknesses"] == ["- Missing some concepts"]
        # At least 2 calls: 1 map batch + 1 reduce
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_returns_fallback_on_llm_failure(self):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = ValueError("Unsupported")
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))

        with patch(
            "app.extraction.judges.qualitative_eval_node._get_llm",
            return_value=mock_llm,
        ):
            result = await run_qualitative_evaluation(
                classes=[_cls("u1")],
                chunks=[{"text": "text"}],
                model_name="test-model",
            )

        # Map phase fails -> no observations -> specific weakness message
        weakness = result["weaknesses"][0].lower()
        assert "observations" in weakness or "could not" in weakness
