"""Unit tests for the Stream 16 domain_segmenter node (DD.1).

Covers the disabled pass-through, the no-chunks path, LLM success, graceful
failure, response parsing (coverage + unknown-id dropping), and the
capped-document sampling/expansion path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extraction.agents.domain_segmenter import (
    _expand_sampled_segments,
    _parse_domain_response,
    _sample_indices,
    domain_segmenter_node,
)

_CHUNKS = [
    {"_key": "c1", "text": "quarterly revenue and accounts"},
    {"_key": "c2", "text": "balance sheet and ledgers"},
    {"_key": "c3", "text": "employee onboarding and payroll"},
]


def _llm_returning(content: str) -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


class TestDisabled:
    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self):
        with patch("app.extraction.agents.domain_segmenter.settings") as s:
            s.domain_detection_enabled = False
            out = await domain_segmenter_node({"run_id": "r", "document_chunks": _CHUNKS})
        assert out["domain_segments"] == []
        assert out["step_logs"][0]["status"] == "skipped"
        assert out["step_logs"][0]["metadata"]["reason"] == "domain_detection_disabled"


class TestNoChunks:
    @pytest.mark.asyncio
    async def test_empty_chunks(self):
        with patch("app.extraction.agents.domain_segmenter.settings") as s:
            s.domain_detection_enabled = True
            out = await domain_segmenter_node({"run_id": "r", "document_chunks": []})
        assert out["domain_segments"] == []
        assert out["step_logs"][0]["metadata"]["reason"] == "no_chunks"


class TestLlmPath:
    @pytest.mark.asyncio
    async def test_multi_domain_success(self):
        content = (
            '{"domains": ['
            '{"domain": "Finance", "chunk_ids": ["c1", "c2"], "confidence": 0.9},'
            '{"domain": "HR", "chunk_ids": ["c3"], "confidence": 0.85}]}'
        )
        with (
            patch("app.extraction.agents.domain_segmenter.settings") as s,
            patch(
                "app.extraction.agents.domain_segmenter.get_chat_model",
                return_value=_llm_returning(content),
            ),
        ):
            s.domain_detection_enabled = True
            s.domain_detection_model = ""
            s.llm_extraction_model = "gpt-4o"
            s.domain_detection_max_chunks = 200
            out = await domain_segmenter_node({"run_id": "r", "document_chunks": _CHUNKS})

        segments = out["domain_segments"]
        domains = {s["domain"] for s in segments}
        assert domains == {"Finance", "HR"}
        assert out["step_logs"][0]["status"] == "completed"
        assert out["step_logs"][0]["metadata"]["domain_count"] == 2

    @pytest.mark.asyncio
    async def test_graceful_failure_returns_empty(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
        with (
            patch("app.extraction.agents.domain_segmenter.settings") as s,
            patch("app.extraction.agents.domain_segmenter.get_chat_model", return_value=llm),
        ):
            s.domain_detection_enabled = True
            s.domain_detection_model = ""
            s.llm_extraction_model = "gpt-4o"
            s.domain_detection_max_chunks = 200
            out = await domain_segmenter_node({"run_id": "r", "document_chunks": _CHUNKS})

        assert out["domain_segments"] == []
        assert out["step_logs"][0]["status"] == "failed"
        assert out["step_logs"][0]["error"]


class TestParseDomainResponse:
    def test_drops_unknown_ids_and_covers_leftovers(self):
        raw = (
            '{"domains": ['
            '{"domain": "A", "chunk_ids": ["c1", "zzz"], "confidence": 0.9},'
            '{"domain": "B", "chunk_ids": ["c2"], "confidence": 0.4}]}'
        )
        segments = _parse_domain_response(raw, ["c1", "c2", "c3"])
        # c3 was never assigned -> folded into the highest-confidence segment (A).
        all_ids = {cid for seg in segments for cid in seg["chunk_ids"]}
        assert all_ids == {"c1", "c2", "c3"}
        a_seg = next(s for s in segments if s["domain"] == "A")
        assert "zzz" not in a_seg["chunk_ids"]
        assert "c3" in a_seg["chunk_ids"]

    def test_strips_markdown_fence(self):
        raw = '```json\n{"domains": [{"domain": "A", "chunk_ids": ["c1"], "confidence": 1.0}]}\n```'
        segments = _parse_domain_response(raw, ["c1"])
        assert segments[0]["domain"] == "A"

    def test_raises_on_no_valid_segments(self):
        with pytest.raises(ValueError):
            _parse_domain_response('{"domains": []}', ["c1"])


class TestSampling:
    def test_sample_indices_under_cap(self):
        assert _sample_indices(3, 200) == [0, 1, 2]

    def test_sample_indices_over_cap(self):
        idx = _sample_indices(10, 3)
        assert len(idx) <= 3
        assert idx[0] == 0
        assert all(0 <= i < 10 for i in idx)

    def test_expand_covers_all_chunks(self):
        chunks = [{"_key": f"c{i}"} for i in range(6)]
        sampled = [0, 3]
        segments = [
            {"domain": "A", "chunk_ids": ["c1"], "confidence": 0.9},
            {"domain": "B", "chunk_ids": ["c4"], "confidence": 0.8},
        ]
        # _chunk_id for sampled index 0 -> "c0", index 3 -> "c3". Remap the
        # sampled segments to those ids so expansion has anchors.
        segments = [
            {"domain": "A", "chunk_ids": ["c0"], "confidence": 0.9},
            {"domain": "B", "chunk_ids": ["c3"], "confidence": 0.8},
        ]
        expanded = _expand_sampled_segments(segments, chunks, sampled)
        all_ids = {cid for seg in expanded for cid in seg["chunk_ids"]}
        assert all_ids == {f"c{i}" for i in range(6)}
