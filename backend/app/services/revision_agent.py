"""LLM revision agent for the belief-revision pipeline (Stream 11 IBR.8).

Phase 3 of the four-phase Incremental Belief Revision pipeline. When the
mechanical classifier (IBR.7) emits a contested verdict
(``CONTRADICTED`` / ``UNCERTAIN`` / ``FLAG_FOR_CURATION``), the LLM
revision agent reads the existing belief, its provenance, the new
concept, and the supporting chunks from the triggering document, and
proposes a final action grounded in evidence quotes.

Output is constrained by a JSON schema and gated by a deterministic
**cross-check** (the Evo-DKD pattern, ADR-008): the agent's output is
only accepted if every evidence quote is a substring of the supplied
evidence text and the reasoning is non-trivial. Any cross-check failure
downgrades the action to ``FLAG_FOR_CURATION`` with structured notes,
so the curator sees exactly which guardrail tripped.

This file is **deliberately thin on LLM-specific code**: it reuses
:func:`app.extraction.agents.extractor._get_llm` for provider abstraction
and the ``with_structured_output()`` + plain-parse fallback pattern from
:mod:`app.extraction.judges.qualitative_eval_node`. The pure helpers
(:func:`build_revision_prompt`, :func:`cross_check`,
:func:`parse_llm_payload`) are independently testable without an LLM.

Action contract
---------------

The LLM picks one of four actions
(:mod:`app.db.revision_meta_repo`):

* ``REINFORCE`` -- new evidence supports the existing belief; bump
  confidence and append evidence (no structural change).
* ``REVISE``    -- supersede the existing belief with a refined version
  (Levi identity = contraction + expansion, atomically performed by
  IBR.9).
* ``RETRACT``   -- remove the existing belief (contraction). Requires
  non-empty evidence and a high confidence; otherwise downgraded.
* ``FLAG_FOR_CURATION`` -- LLM is unsure or cross-check failed; let a
  human decide.

The agent is **never** allowed to invent new entities (Q.3b in
``docs/REMAINING_WORK_PLAN.md``) -- that's IBR.13's extension. If the
LLM proposes a non-existent target, the cross-check downgrades.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_REINFORCE,
    ACTION_RETRACT,
    ACTION_REVISE,
)
from app.extraction.agents.extractor import _get_llm
from app.services.revision_verdict import MechanicalRevision

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables (kept module-level for monkeypatching + future operator console)
# ---------------------------------------------------------------------------

# Maximum retries on parse / cross-check failure. The first try uses the
# strict prompt; subsequent retries append the failure notes so the LLM
# can self-correct.
LLM_MAX_RETRIES = 2

# Concurrency cap. Belief-revision calls are typically dozens per
# extraction run -- generous enough to finish quickly, conservative
# enough to avoid hitting per-key rate limits.
LLM_DEFAULT_CONCURRENCY = 8

# Reasoning sanity threshold. Strings shorter than this almost always
# indicate the LLM punted ("unsure", "skip"). We trip the cross-check.
MIN_REASONING_LENGTH = 30

# Confidence floor for irreversible actions. Even the LLM is not allowed
# to RETRACT below this confidence; downgraded to FLAG_FOR_CURATION.
RETRACT_CONFIDENCE_FLOOR = 0.80


# ---------------------------------------------------------------------------
# JSON schema for the structured output
# ---------------------------------------------------------------------------


_ACTION_ENUM = [
    ACTION_REINFORCE,
    ACTION_REVISE,
    ACTION_RETRACT,
    ACTION_FLAG_FOR_CURATION,
]

_RESPONSE_SCHEMA: dict[str, Any] = {
    "title": "belief_revision_decision",
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": _ACTION_ENUM,
            "description": "The action to take on the existing belief.",
        },
        "evidence_quotes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Verbatim quotes from the supplied evidence text that "
                "support the chosen action. Empty array is allowed only "
                "for FLAG_FOR_CURATION."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": (
                "1-3 sentences explaining the decision, referencing the "
                "evidence quotes. Must be at least "
                f"{MIN_REASONING_LENGTH} characters."
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "LLM's own confidence in the decision.",
        },
    },
    "required": ["action", "evidence_quotes", "reasoning", "confidence"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevisionContext:
    """Everything the LLM agent needs for one revision call.

    Construction is the IBR.10 LangGraph node's responsibility: it pulls
    the existing belief and provenance from Arango and passes them in
    here. This class is intentionally a plain dataclass with no DB
    coupling so it can be built from fixtures in tests.
    """

    mechanical_revision: MechanicalRevision
    existing_belief: dict[str, Any]
    existing_evidence: tuple[str, ...]
    new_concept_text: str
    new_evidence: tuple[str, ...]
    triggering_doc_id: str


@dataclass(frozen=True)
class LLMRevisionProposal:
    """The agent's final proposal for one revision.

    ``cross_check_passed`` is the gate the IBR.10 node uses to decide
    whether to invoke the supersede helper (IBR.9) or push to the
    Revisions Inbox. ``cross_check_notes`` is human-readable; it lands
    in ``revision_meta.decision_log`` so curators understand why the
    agent flagged something.
    """

    action: str
    evidence_quotes: tuple[str, ...]
    reasoning: str
    confidence: float
    cross_check_passed: bool
    cross_check_notes: tuple[str, ...]
    raw_action: str  # what the LLM actually returned (before downgrade)
    raw_confidence: float  # ditto
    latency_ms: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "evidence_quotes": list(self.evidence_quotes),
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "cross_check_passed": self.cross_check_passed,
            "cross_check_notes": list(self.cross_check_notes),
            "raw_action": self.raw_action,
            "raw_confidence": self.raw_confidence,
            "latency_ms": self.latency_ms,
            "tokens": dict(self.tokens),
        }


@dataclass(frozen=True)
class CrossCheckResult:
    passed: bool
    notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pure prompt builder
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are an ontology belief-revision agent. Your job is to decide "
    "what to do with an existing ontology belief in light of new "
    "evidence from a freshly-ingested document.\n\n"
    "You will be given:\n"
    "  * The existing belief (a class with label, description, "
    "properties), and the verbatim source text it was extracted from.\n"
    "  * A new concept and the verbatim source text it was extracted "
    "from in the new document.\n"
    "  * A mechanical verdict produced by deterministic rules, with the "
    "rule's name and reasoning.\n\n"
    "You must choose ONE action:\n"
    f"  * {ACTION_REINFORCE}        -- new evidence confirms the existing "
    "belief without changing it (bump confidence + append evidence).\n"
    f"  * {ACTION_REVISE}            -- replace the existing belief with a "
    "refined version (e.g. add a missing subClassOf edge).\n"
    f"  * {ACTION_RETRACT}           -- the existing belief is contradicted "
    "by the new evidence and should be removed.\n"
    f"  * {ACTION_FLAG_FOR_CURATION} -- you cannot decide confidently; "
    "let a human curator review.\n\n"
    "Hard rules:\n"
    "  1. Every quote in `evidence_quotes` MUST be copied verbatim from "
    "the supplied source text (existing provenance OR new evidence). "
    "Do not paraphrase, do not invent quotes.\n"
    f"  2. {ACTION_RETRACT} requires at least one evidence quote AND a "
    f"confidence >= {RETRACT_CONFIDENCE_FLOOR}.\n"
    "  3. Your `reasoning` must explicitly reference the quotes and the "
    "mechanical verdict.\n"
    f"  4. If unsure, choose {ACTION_FLAG_FOR_CURATION}; that is always "
    "the safe option.\n\n"
    "Return ONLY a JSON object matching the supplied schema."
)


def _format_evidence(quotes: tuple[str, ...]) -> str:
    """Render evidence as a numbered list -- helps the LLM cite cleanly."""
    if not quotes:
        return "(no evidence supplied)"
    return "\n".join(f"  [{i + 1}] {q.strip()}" for i, q in enumerate(quotes))


def _format_existing_belief(belief: dict[str, Any]) -> str:
    """Compact, deterministic rendering of the belief for the prompt."""
    label = belief.get("label") or belief.get("_key") or "<unknown>"
    uri = belief.get("uri") or belief.get("_id") or ""
    description = belief.get("description") or "(no description)"
    parts = [f"Label: {label}", f"URI:   {uri}", f"Description: {description}"]
    properties = belief.get("properties") or belief.get("attributes") or []
    if properties:
        prop_names = [
            str(p.get("label") or p.get("_key") or p.get("uri") or "?")
            for p in properties[:10]
        ]
        parts.append(f"Properties (first 10): {', '.join(prop_names)}")
    confidence = belief.get("confidence") or belief.get("current_confidence")
    if confidence is not None:
        parts.append(f"Current confidence: {confidence:.2f}")
    return "\n".join(parts)


def build_revision_prompt(ctx: RevisionContext) -> tuple[str, str]:
    """Build (system, user) message strings from a RevisionContext.

    Pure function -- no LLM, no DB. Same context always yields the same
    prompt, which makes prompt-engineering tests trivial.
    """
    mech = ctx.mechanical_revision
    existing_label = mech.touchpoint.existing_class_label
    new_label = mech.touchpoint.new_concept_label

    user = (
        f"## Mechanical verdict\n"
        f"  Verdict: {mech.verdict}\n"
        f"  Action proposed mechanically: {mech.action}\n"
        f"  Rule: {mech.rule_id}\n"
        f"  Mechanical confidence: {mech.confidence:.2f}\n"
        f"  Reasoning: {mech.reasoning}\n\n"
        f"## Existing belief\n"
        f"{_format_existing_belief(ctx.existing_belief)}\n\n"
        f"## Existing belief provenance (chunks from prior documents)\n"
        f"{_format_evidence(ctx.existing_evidence)}\n\n"
        f"## New concept (from triggering document {ctx.triggering_doc_id})\n"
        f"{ctx.new_concept_text.strip() or new_label}\n\n"
        f"## New evidence (chunks from the triggering document)\n"
        f"{_format_evidence(ctx.new_evidence)}\n\n"
        f"## Decide\n"
        f"Choose an action that updates the belief about "
        f"{existing_label!r} in light of the new evidence about "
        f"{new_label!r}. Quote the supplied source text verbatim in "
        f"`evidence_quotes`."
    )
    return _SYSTEM_PROMPT, user


# ---------------------------------------------------------------------------
# Pure cross-check (Evo-DKD pattern)
# ---------------------------------------------------------------------------


def _all_evidence_text(ctx: RevisionContext) -> str:
    """Concatenate every supplied evidence chunk for substring checking."""
    return "\n".join(list(ctx.existing_evidence) + list(ctx.new_evidence))


def cross_check(payload: dict[str, Any], ctx: RevisionContext) -> CrossCheckResult:
    """Validate that the LLM's payload is grounded and self-consistent.

    Returns a structured result rather than raising -- callers always
    write the result into ``cross_check_notes`` so the curator sees the
    full audit trail.

    Three families of check:

    1. **Schema sanity**: action is in the enum, confidence in [0, 1],
       reasoning long enough.
    2. **Evidence grounding**: every quote is a substring of the supplied
       evidence text. Whitespace-normalised match (collapses runs of
       whitespace) so the LLM doesn't have to reproduce odd line breaks.
    3. **Action prerequisites**: ``RETRACT`` requires evidence quotes
       and confidence >= ``RETRACT_CONFIDENCE_FLOOR``. Non-FLAG actions
       require at least one evidence quote.
    """
    notes: list[str] = []

    action = payload.get("action")
    confidence_raw = payload.get("confidence")
    reasoning = payload.get("reasoning") or ""
    quotes_raw = payload.get("evidence_quotes") or []

    # ---- Schema sanity -----------------------------------------------
    if action not in _ACTION_ENUM:
        notes.append(f"unknown action {action!r}; expected one of {_ACTION_ENUM}")

    if not isinstance(confidence_raw, int | float):
        notes.append(
            f"confidence must be a number, got {type(confidence_raw).__name__}"
        )
        confidence = 0.0
    else:
        confidence = float(confidence_raw)
        if not (0.0 <= confidence <= 1.0):
            notes.append(f"confidence {confidence!r} not in [0, 1]")

    if not isinstance(reasoning, str) or len(reasoning.strip()) < MIN_REASONING_LENGTH:
        notes.append(
            f"reasoning is too short (< {MIN_REASONING_LENGTH} chars); "
            "likely a non-answer"
        )

    if not isinstance(quotes_raw, list) or not all(
        isinstance(q, str) for q in quotes_raw
    ):
        notes.append("evidence_quotes must be a list of strings")
        quotes_raw = []

    # ---- Evidence grounding ------------------------------------------
    quotes = [q.strip() for q in quotes_raw if isinstance(q, str) and q.strip()]
    haystack = " ".join(_all_evidence_text(ctx).split())  # collapse whitespace
    for q in quotes:
        needle = " ".join(q.split())
        if not needle:
            continue
        if needle not in haystack:
            notes.append(
                f"evidence quote not found in supplied source text: {q[:80]!r}"
            )

    # ---- Action prerequisites ----------------------------------------
    if action == ACTION_RETRACT:
        if not quotes:
            notes.append("RETRACT requires at least one evidence quote")
        if confidence < RETRACT_CONFIDENCE_FLOOR:
            notes.append(
                f"RETRACT requires confidence >= {RETRACT_CONFIDENCE_FLOOR}, "
                f"got {confidence:.2f}"
            )
    elif action in (ACTION_REINFORCE, ACTION_REVISE) and not quotes:
        notes.append(f"{action} requires at least one evidence quote")

    return CrossCheckResult(passed=not notes, notes=tuple(notes))


# ---------------------------------------------------------------------------
# Pure parser
# ---------------------------------------------------------------------------


def parse_llm_payload(raw: Any) -> dict[str, Any]:
    """Coerce a raw LLM response into a dict, stripping markdown fences.

    Accepts either a dict (when ``with_structured_output`` succeeded) or
    a string (plain LLM response). Raises ``ValueError`` if the result
    is not a JSON object.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"expected dict or string, got {type(raw).__name__}")
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    return parsed


# ---------------------------------------------------------------------------
# Downgrade helper
# ---------------------------------------------------------------------------


def _downgrade(
    ctx: RevisionContext,
    payload: dict[str, Any],
    notes: tuple[str, ...],
    *,
    latency_ms: float,
    tokens: dict[str, int],
) -> LLMRevisionProposal:
    """Build the FLAG_FOR_CURATION downgrade proposal.

    Preserves ``raw_action`` / ``raw_confidence`` / ``reasoning`` so the
    curator sees what the LLM actually said, not just the downgrade.
    """
    raw_action = payload.get("action") if isinstance(payload, dict) else None
    raw_confidence_val = payload.get("confidence") if isinstance(payload, dict) else None
    try:
        raw_confidence = float(raw_confidence_val) if raw_confidence_val is not None else 0.0
    except (TypeError, ValueError):
        raw_confidence = 0.0
    reasoning = payload.get("reasoning") if isinstance(payload, dict) else None
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = (
            f"Auto-downgraded to FLAG_FOR_CURATION because the LLM "
            f"agent's response failed cross-check: {'; '.join(notes)}"
        )

    quotes_raw = payload.get("evidence_quotes") if isinstance(payload, dict) else []
    if isinstance(quotes_raw, list):
        quotes = tuple(q for q in quotes_raw if isinstance(q, str))
    else:
        quotes = ()

    return LLMRevisionProposal(
        action=ACTION_FLAG_FOR_CURATION,
        evidence_quotes=quotes,
        reasoning=reasoning,
        confidence=min(raw_confidence, 0.5),  # cap downgraded confidence
        cross_check_passed=False,
        cross_check_notes=notes,
        raw_action=str(raw_action) if raw_action else "",
        raw_confidence=raw_confidence,
        latency_ms=latency_ms,
        tokens=dict(tokens),
    )


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------


async def _invoke_llm(
    llm: Any,
    system_msg: str,
    user_msg: str,
    *,
    extra_user_msg: str | None = None,
) -> tuple[Any, dict[str, int]]:
    """One round-trip to the LLM.

    Tries ``with_structured_output`` first (so providers that support it
    enforce the schema in-protocol); falls back to plain invocation +
    JSON parsing for providers that don't.
    """
    messages: list[Any] = [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]
    if extra_user_msg:
        messages.append(HumanMessage(content=extra_user_msg))

    tokens = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        structured = llm.with_structured_output(_RESPONSE_SCHEMA)
        result = await structured.ainvoke(messages)
        return result, tokens
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        pass

    response = await llm.ainvoke(messages)
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
        tokens["prompt_tokens"] = usage.get("input_tokens", 0)
        tokens["completion_tokens"] = usage.get("output_tokens", 0)
    return response.content, tokens


async def revise(
    ctx: RevisionContext,
    *,
    llm: Any | None = None,
    model_name: str | None = None,
) -> LLMRevisionProposal:
    """Run the LLM revision agent on one context, with cross-check + retry.

    Parameters
    ----------
    ctx:
        The pre-built revision context.
    llm:
        Optional pre-built LLM client (lets tests inject a mock). When
        ``None``, a client is built from ``model_name`` (or the
        configured default).
    model_name:
        Override for the LLM model. Defaults to
        ``settings.llm_extraction_model``.

    Returns
    -------
    LLMRevisionProposal
        Always returned -- on persistent cross-check failure the
        proposal carries ``action=FLAG_FOR_CURATION`` and the failure
        notes, never raises.
    """
    started = time.time()
    model = model_name or settings.llm_extraction_model
    client = llm if llm is not None else _get_llm(model)
    system_msg, user_msg = build_revision_prompt(ctx)

    last_payload: dict[str, Any] = {}
    last_notes: tuple[str, ...] = ("LLM call did not complete",)
    accumulated_tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    extra: str | None = None

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            raw, tokens = await _invoke_llm(
                client, system_msg, user_msg, extra_user_msg=extra
            )
            accumulated_tokens["prompt_tokens"] += tokens.get("prompt_tokens", 0)
            accumulated_tokens["completion_tokens"] += tokens.get("completion_tokens", 0)
            last_payload = parse_llm_payload(raw)
        except Exception as exc:
            last_notes = (f"LLM invocation/parse failed on attempt {attempt + 1}: {exc}",)
            log.warning(
                "revision_agent: invocation/parse failure",
                extra={
                    "attempt": attempt + 1,
                    "model": model,
                    "existing_class_id": ctx.mechanical_revision.touchpoint.existing_class_id,
                    "error": str(exc),
                },
            )
            extra = (
                "Your previous response could not be parsed. Return ONLY a "
                "JSON object matching the schema, with no surrounding text."
            )
            continue

        cc = cross_check(last_payload, ctx)
        if cc.passed:
            confidence = float(last_payload.get("confidence", 0.0))
            quotes = tuple(
                q for q in (last_payload.get("evidence_quotes") or []) if isinstance(q, str)
            )
            action = str(last_payload["action"])
            reasoning = str(last_payload.get("reasoning", ""))
            return LLMRevisionProposal(
                action=action,
                evidence_quotes=quotes,
                reasoning=reasoning,
                confidence=confidence,
                cross_check_passed=True,
                cross_check_notes=(),
                raw_action=action,
                raw_confidence=confidence,
                latency_ms=(time.time() - started) * 1000.0,
                tokens=dict(accumulated_tokens),
            )

        last_notes = cc.notes
        log.info(
            "revision_agent: cross-check failed (attempt %d): %s",
            attempt + 1,
            "; ".join(cc.notes),
        )
        extra = (
            "Your previous response failed validation:\n"
            + "\n".join(f"  - {n}" for n in cc.notes)
            + "\nFix and return JSON matching the schema."
        )

    # All retries exhausted -- downgrade the last attempt.
    return _downgrade(
        ctx,
        last_payload,
        last_notes,
        latency_ms=(time.time() - started) * 1000.0,
        tokens=accumulated_tokens,
    )


async def revise_batch(
    contexts: list[RevisionContext],
    *,
    model_name: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
    llm: Any | None = None,
) -> list[LLMRevisionProposal]:
    """Revise a batch of contexts concurrently with a configurable cap.

    Order of the returned list matches the input. Concurrency defaults
    to :data:`LLM_DEFAULT_CONCURRENCY` -- override in tests / production
    via ``semaphore``.
    """
    if not contexts:
        return []
    sem = semaphore or asyncio.Semaphore(LLM_DEFAULT_CONCURRENCY)

    async def _one(ctx: RevisionContext) -> LLMRevisionProposal:
        async with sem:
            return await revise(ctx, llm=llm, model_name=model_name)

    return await asyncio.gather(*(_one(c) for c in contexts))
