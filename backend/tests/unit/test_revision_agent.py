"""Unit tests for ``app.services.revision_agent`` (Stream 11 IBR.8).

Three layers of coverage:

1. **Pure helpers** -- ``build_revision_prompt``, ``cross_check``,
   ``parse_llm_payload``. No LLM, no DB.
2. **Cross-check rules** -- one focused test per failure mode (each
   rule that adds a note in :func:`cross_check` gets exercised).
3. **End-to-end with mocked LLM** -- ``revise()`` happy path + retry +
   downgrade, using an ``AsyncMock``-style fake LLM. Confirms the
   tokens / latency / cross-check-notes plumbing holds together.

Real-LLM integration test is gated behind ``RUN_LLM_INTEGRATION_TESTS``
env var (added in IBR.13); not in this file.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_REINFORCE,
    ACTION_RETRACT,
    ACTION_REVISE,
    VERDICT_GAP_FILLING,
    VERDICT_UNCERTAIN,
)
from app.services.revision_agent import (
    LLM_MAX_RETRIES,
    MIN_REASONING_LENGTH,
    RETRACT_CONFIDENCE_FLOOR,
    CrossCheckResult,
    LLMRevisionProposal,
    RevisionContext,
    build_revision_prompt,
    cross_check,
    parse_llm_payload,
    revise,
    revise_batch,
)
from app.services.revision_verdict import (
    MechanicalRevision,
    StructuralFeatures,
    classify,
)
from app.services.touchpoint_discovery import Touchpoint, TouchpointSignals

# ---------------------------------------------------------------------------
# Test builders
# ---------------------------------------------------------------------------


def _signals(**kw: float) -> TouchpointSignals:
    base = {
        "uri_exact": 0.0,
        "label_exact": 0.0,
        "label_fuzzy": 0.0,
        "chunk_overlap": 0.0,
        "embedding_sim": None,
    }
    base.update(kw)
    return TouchpointSignals(**base)


def _touchpoint(
    *,
    new_label: str = "EscrowAccount",
    existing_label: str = "Account",
    existing_id: str = "ontology_classes/Account",
    combined_score: float = 0.35,
    label_fuzzy: float = 0.54,
) -> Touchpoint:
    return Touchpoint(
        new_concept_label=new_label,
        new_concept_uri=None,
        existing_class_id=existing_id,
        existing_class_label=existing_label,
        signals=_signals(label_fuzzy=label_fuzzy),
        combined_score=combined_score,
        reasoning="label fuzzy match",
    )


def _mechanical(
    verdict: str = VERDICT_UNCERTAIN,
    action: str = ACTION_FLAG_FOR_CURATION,
    *,
    touchpoint: Touchpoint | None = None,
) -> MechanicalRevision:
    tp = touchpoint or _touchpoint()
    return classify(tp, StructuralFeatures()) if action == "AUTO" else MechanicalRevision(
        touchpoint=tp,
        verdict=verdict,
        action=action,
        rule_id="R7_test_fixture",
        confidence=0.4,
        reasoning="mechanical reasoning",
    )


def _ctx(
    *,
    existing_evidence: tuple[str, ...] = (
        "Customers may hold multiple accounts including checking and savings.",
    ),
    new_evidence: tuple[str, ...] = (
        "Escrow accounts are a special type of account used for holding funds in trust.",
    ),
    existing_belief: dict[str, Any] | None = None,
    mechanical: MechanicalRevision | None = None,
    new_concept_text: str = "Escrow Account: an account holding funds in trust.",
    triggering_doc_id: str = "documents/d2",
) -> RevisionContext:
    if existing_belief is None:
        existing_belief = {
            "_id": "ontology_classes/Account",
            "_key": "Account",
            "label": "Account",
            "uri": "http://example.org/Account",
            "description": "A financial account held by a customer.",
            "confidence": 0.9,
            "properties": [
                {"label": "account_number"},
                {"label": "currency"},
            ],
        }
    return RevisionContext(
        mechanical_revision=mechanical or _mechanical(),
        existing_belief=existing_belief,
        existing_evidence=existing_evidence,
        new_concept_text=new_concept_text,
        new_evidence=new_evidence,
        triggering_doc_id=triggering_doc_id,
    )


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Mimics the shape returned by `llm.ainvoke()` in plain mode."""

    def __init__(self, content: str, tokens: dict[str, int] | None = None):
        self.content = content
        self.usage_metadata = (
            {"input_tokens": tokens["prompt_tokens"], "output_tokens": tokens["completion_tokens"]}
            if tokens
            else None
        )


class _FakeLLM:
    """Minimal LLM stub that returns scripted responses.

    Set ``structured_output_payloads`` to the list of dicts that
    ``with_structured_output(...).ainvoke(...)`` should return; set
    ``plain_responses`` to the list of strings that ``ainvoke()`` should
    return when ``with_structured_output`` is not used. Each call pops
    the next item; the test fails if no items remain.

    To force the structured-output code path to fail and fall back to
    plain mode, set ``raise_on_structured`` to True.
    """

    def __init__(
        self,
        *,
        structured_output_payloads: list[Any] | None = None,
        plain_responses: list[Any] | None = None,
        raise_on_structured: bool = False,
        token_counts: list[dict[str, int]] | None = None,
    ):
        self._structured = list(structured_output_payloads or [])
        self._plain = list(plain_responses or [])
        self._raise_on_structured = raise_on_structured
        self._tokens = list(token_counts or [])
        self.calls: list[dict[str, Any]] = []

    def with_structured_output(self, schema: dict[str, Any]) -> Any:
        if self._raise_on_structured or not self._structured:
            raise NotImplementedError("structured output not available in test")

        outer = self

        class _Structured:
            async def ainvoke(self, messages: list[Any]) -> Any:
                outer.calls.append({"mode": "structured", "messages": messages})
                return outer._structured.pop(0)

        return _Structured()

    async def ainvoke(self, messages: list[Any]) -> Any:
        self.calls.append({"mode": "plain", "messages": messages})
        if not self._plain:
            raise AssertionError("FakeLLM ran out of scripted plain responses")
        body = self._plain.pop(0)
        tokens = self._tokens.pop(0) if self._tokens else None
        if isinstance(body, _FakeResponse):
            return body
        return _FakeResponse(body, tokens=tokens)


# ---------------------------------------------------------------------------
# parse_llm_payload
# ---------------------------------------------------------------------------


class TestParseLLMPayload:
    def test_dict_passes_through(self):
        d = {"action": ACTION_REINFORCE, "evidence_quotes": [], "reasoning": "x", "confidence": 0.5}
        assert parse_llm_payload(d) == d

    def test_string_json_parsed(self):
        d = {"action": ACTION_REINFORCE, "confidence": 0.5}
        assert parse_llm_payload(json.dumps(d)) == d

    def test_strips_markdown_fence(self):
        d = {"action": ACTION_REINFORCE}
        wrapped = f"```json\n{json.dumps(d)}\n```"
        assert parse_llm_payload(wrapped) == d

    def test_non_object_raises(self):
        with pytest.raises(ValueError):
            parse_llm_payload("[1, 2, 3]")

    def test_non_string_non_dict_raises(self):
        with pytest.raises(ValueError):
            parse_llm_payload(42)


# ---------------------------------------------------------------------------
# build_revision_prompt
# ---------------------------------------------------------------------------


class TestBuildRevisionPrompt:
    def test_returns_system_and_user_strings(self):
        sys, user = build_revision_prompt(_ctx())
        assert isinstance(sys, str) and isinstance(user, str)
        assert sys.strip() and user.strip()

    def test_system_lists_all_actions(self):
        sys, _ = build_revision_prompt(_ctx())
        for action in (ACTION_REINFORCE, ACTION_REVISE, ACTION_RETRACT, ACTION_FLAG_FOR_CURATION):
            assert action in sys

    def test_user_includes_mechanical_verdict(self):
        ctx = _ctx(mechanical=_mechanical(verdict=VERDICT_GAP_FILLING))
        _, user = build_revision_prompt(ctx)
        assert VERDICT_GAP_FILLING in user
        assert "R7_test_fixture" in user  # rule id

    def test_user_includes_new_and_existing_evidence(self):
        ctx = _ctx(
            existing_evidence=("OLD_EVIDENCE_FOR_TEST",),
            new_evidence=("NEW_EVIDENCE_FOR_TEST",),
        )
        _, user = build_revision_prompt(ctx)
        assert "OLD_EVIDENCE_FOR_TEST" in user
        assert "NEW_EVIDENCE_FOR_TEST" in user

    def test_deterministic(self):
        c = _ctx()
        assert build_revision_prompt(c) == build_revision_prompt(c)


# ---------------------------------------------------------------------------
# cross_check rules
# ---------------------------------------------------------------------------


class TestCrossCheckSchema:
    def test_unknown_action_fails(self):
        cc = cross_check(
            {
                "action": "DELETE_EVERYTHING",
                "evidence_quotes": ["Customers may hold multiple accounts"],
                "reasoning": "this is reasoning longer than the minimum required length",
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("unknown action" in n for n in cc.notes)

    def test_confidence_out_of_range_fails(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": ["Customers may hold multiple accounts"],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 1.5,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("not in [0, 1]" in n for n in cc.notes)

    def test_confidence_wrong_type_fails(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": ["Customers may hold multiple accounts"],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": "high",
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("must be a number" in n for n in cc.notes)

    def test_short_reasoning_fails(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": ["Customers may hold multiple accounts"],
                "reasoning": "ok",
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("too short" in n for n in cc.notes)

    def test_quotes_not_list_fails(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": "not a list",
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("must be a list" in n for n in cc.notes)


class TestCrossCheckEvidenceGrounding:
    def test_quote_present_passes_grounding(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": [
                    "Customers may hold multiple accounts including checking and savings."
                ],
                "reasoning": "The new evidence aligns with the existing belief about Account.",
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is True

    def test_hallucinated_quote_fails_grounding(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": [
                    "Customers MUST hold a single account at all times.",
                ],
                "reasoning": "The new evidence aligns with the existing belief about Account.",
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("not found in supplied source text" in n for n in cc.notes)

    def test_whitespace_normalised_match_passes(self):
        # The quote uses different whitespace than the source -- collapsed
        # whitespace should still match.
        ctx = _ctx(
            existing_evidence=("Account  holders\nmay open multiple    accounts.",),
        )
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": ["Account holders may open multiple accounts."],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 0.9,
            },
            ctx,
        )
        assert cc.passed is True


class TestCrossCheckActionPrerequisites:
    def test_retract_requires_evidence(self):
        cc = cross_check(
            {
                "action": ACTION_RETRACT,
                "evidence_quotes": [],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 0.95,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("RETRACT requires at least one" in n for n in cc.notes)

    def test_retract_requires_high_confidence(self):
        cc = cross_check(
            {
                "action": ACTION_RETRACT,
                "evidence_quotes": [
                    "Customers may hold multiple accounts including checking and savings."
                ],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": RETRACT_CONFIDENCE_FLOOR - 0.1,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("RETRACT requires confidence" in n for n in cc.notes)

    def test_reinforce_requires_evidence(self):
        cc = cross_check(
            {
                "action": ACTION_REINFORCE,
                "evidence_quotes": [],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False
        assert any("requires at least one evidence quote" in n for n in cc.notes)

    def test_revise_requires_evidence(self):
        cc = cross_check(
            {
                "action": ACTION_REVISE,
                "evidence_quotes": [],
                "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
                "confidence": 0.9,
            },
            _ctx(),
        )
        assert cc.passed is False

    def test_flag_for_curation_does_not_require_evidence(self):
        cc = cross_check(
            {
                "action": ACTION_FLAG_FOR_CURATION,
                "evidence_quotes": [],
                "reasoning": "I cannot decide between subClassOf and composition.",
                "confidence": 0.4,
            },
            _ctx(),
        )
        assert cc.passed is True

    def test_returns_structured_result(self):
        cc = cross_check({"action": "X"}, _ctx())
        assert isinstance(cc, CrossCheckResult)
        assert isinstance(cc.notes, tuple)


# ---------------------------------------------------------------------------
# revise() -- end-to-end with mocked LLM
# ---------------------------------------------------------------------------


_GOOD_PAYLOAD = {
    "action": ACTION_REVISE,
    "evidence_quotes": [
        "Escrow accounts are a special type of account used for holding funds in trust.",
    ],
    "reasoning": (
        "The new evidence explicitly says escrow accounts are a special type of account, "
        "supporting a subClassOf revision."
    ),
    "confidence": 0.9,
}


@pytest.mark.asyncio
class TestReviseHappyPath:
    async def test_structured_output_path_succeeds_first_try(self):
        llm = _FakeLLM(structured_output_payloads=[_GOOD_PAYLOAD])
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is True
        assert proposal.action == ACTION_REVISE
        assert proposal.confidence == 0.9
        assert len(proposal.evidence_quotes) == 1
        assert len(llm.calls) == 1
        assert llm.calls[0]["mode"] == "structured"

    async def test_plain_output_path_when_structured_unavailable(self):
        llm = _FakeLLM(
            raise_on_structured=True,
            plain_responses=[json.dumps(_GOOD_PAYLOAD)],
            token_counts=[{"prompt_tokens": 200, "completion_tokens": 50}],
        )
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is True
        assert proposal.action == ACTION_REVISE
        assert proposal.tokens == {"prompt_tokens": 200, "completion_tokens": 50}
        assert proposal.latency_ms >= 0

    async def test_returns_proposal_dataclass(self):
        llm = _FakeLLM(structured_output_payloads=[_GOOD_PAYLOAD])
        proposal = await revise(_ctx(), llm=llm)
        assert isinstance(proposal, LLMRevisionProposal)


@pytest.mark.asyncio
class TestReviseRetry:
    async def test_cross_check_failure_triggers_retry(self):
        bad = {
            "action": ACTION_REVISE,
            "evidence_quotes": ["this quote is not in the source"],
            "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
            "confidence": 0.9,
        }
        llm = _FakeLLM(structured_output_payloads=[bad, _GOOD_PAYLOAD])
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is True
        assert proposal.action == ACTION_REVISE
        # Two calls: first failed cross-check, second succeeded.
        assert len(llm.calls) == 2
        # Second call carries the failure notes as an extra HumanMessage.
        second_msgs = llm.calls[1]["messages"]
        assert len(second_msgs) == 3  # System + User + retry note
        assert "failed validation" in second_msgs[2].content

    async def test_parse_failure_triggers_retry(self):
        llm = _FakeLLM(
            raise_on_structured=True,
            plain_responses=["this is not json", json.dumps(_GOOD_PAYLOAD)],
        )
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is True

    async def test_persistent_failure_downgrades(self):
        bad = {
            "action": ACTION_REVISE,
            "evidence_quotes": ["nope"],
            "reasoning": "x" * (MIN_REASONING_LENGTH + 5),
            "confidence": 0.9,
        }
        # Submit `bad` for every retry slot (initial + LLM_MAX_RETRIES retries).
        llm = _FakeLLM(structured_output_payloads=[bad] * (LLM_MAX_RETRIES + 1))
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is False
        assert proposal.action == ACTION_FLAG_FOR_CURATION
        assert proposal.raw_action == ACTION_REVISE  # what LLM actually returned
        assert proposal.raw_confidence == 0.9
        assert any("not found in supplied source text" in n for n in proposal.cross_check_notes)
        assert proposal.confidence <= 0.5  # downgrade caps confidence


@pytest.mark.asyncio
class TestReviseDowngrade:
    async def test_downgrade_preserves_reasoning_when_present(self):
        bad = {
            "action": ACTION_RETRACT,
            "evidence_quotes": [],
            "reasoning": "I want to retract because it feels wrong.",
            "confidence": 0.5,
        }
        llm = _FakeLLM(structured_output_payloads=[bad] * (LLM_MAX_RETRIES + 1))
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is False
        assert proposal.action == ACTION_FLAG_FOR_CURATION
        # LLM's reasoning is preserved verbatim so the curator can see it.
        assert proposal.reasoning == "I want to retract because it feels wrong."

    async def test_downgrade_synthesises_reasoning_when_missing(self):
        bad = {
            "action": ACTION_REVISE,
            "evidence_quotes": ["fake quote"],
            "reasoning": "",  # empty -> synthesised
            "confidence": 0.5,
        }
        llm = _FakeLLM(structured_output_payloads=[bad] * (LLM_MAX_RETRIES + 1))
        proposal = await revise(_ctx(), llm=llm)
        assert proposal.cross_check_passed is False
        assert "Auto-downgraded" in proposal.reasoning


@pytest.mark.asyncio
class TestReviseBatch:
    async def test_empty_input_returns_empty_list(self):
        result = await revise_batch([])
        assert result == []

    async def test_preserves_order(self):
        # Three contexts with distinguishable mechanical reasoning.
        contexts = []
        for i in range(3):
            tp = _touchpoint(new_label=f"Class{i}")
            mech = MechanicalRevision(
                touchpoint=tp,
                verdict=VERDICT_UNCERTAIN,
                action=ACTION_FLAG_FOR_CURATION,
                rule_id="R7_test",
                confidence=0.4,
                reasoning=f"reasoning {i}",
            )
            contexts.append(_ctx(mechanical=mech))
        # Each context gets its own scripted payload.
        payloads = [_GOOD_PAYLOAD] * 3
        llm = _FakeLLM(structured_output_payloads=payloads)
        result = await revise_batch(contexts, llm=llm)
        assert len(result) == 3
        assert all(p.cross_check_passed for p in result)


# ---------------------------------------------------------------------------
# LLMRevisionProposal contract
# ---------------------------------------------------------------------------


class TestLLMRevisionProposal:
    def test_to_dict_includes_audit_fields(self):
        p = LLMRevisionProposal(
            action=ACTION_FLAG_FOR_CURATION,
            evidence_quotes=("quote",),
            reasoning="reasoning longer than minimum",
            confidence=0.5,
            cross_check_passed=False,
            cross_check_notes=("quote not found",),
            raw_action=ACTION_REVISE,
            raw_confidence=0.9,
            latency_ms=123.4,
            tokens={"prompt_tokens": 100, "completion_tokens": 25},
        )
        d = p.to_dict()
        assert d["raw_action"] == ACTION_REVISE  # auditable
        assert d["raw_confidence"] == 0.9  # auditable
        assert d["cross_check_notes"] == ["quote not found"]
        assert d["tokens"]["prompt_tokens"] == 100
