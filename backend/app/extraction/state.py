"""LangGraph pipeline state schema per PRD Section 6.11."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.models.ontology import ExtractionResult


class TokenUsage(TypedDict, total=False):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class StepLog(TypedDict, total=False):
    step: str
    status: str  # "started" | "completed" | "failed"
    started_at: float
    completed_at: float
    duration_seconds: float
    tokens: TokenUsage
    error: str | None
    metadata: dict[str, Any]


class StrategyConfig(TypedDict, total=False):
    model_name: str
    prompt_template_key: str
    chunk_batch_size: int
    num_passes: int
    consistency_threshold: int
    document_type: str


class ExtractionPipelineState(TypedDict, total=False):
    """Typed state for the LangGraph extraction pipeline.

    All agents read from and write to this state object.
    """

    run_id: str
    document_id: str
    document_chunks: list[dict[str, Any]]
    strategy_config: StrategyConfig
    extraction_passes: list[ExtractionResult]
    consistency_result: ExtractionResult | None
    staging_graph_id: str | None
    current_step: str
    errors: Annotated[list[str], operator.add]
    token_usage: TokenUsage
    step_logs: Annotated[list[StepLog], operator.add]
    metadata: dict[str, Any]

    faithfulness_scores: dict[str, float]
    validity_scores: dict[str, float]

    er_results: dict[str, Any]
    filter_results: dict[str, Any]
    merge_candidates: list[dict[str, Any]]

    qualitative_evaluation: dict[str, Any]

    domain_context: str

    # Belief revision (PRD §6.16, Stream 11 IBR.10)
    # One entry per revision applied OR flagged during this run. Each entry
    # is a dict (not a dataclass) so the value composes cleanly through
    # LangGraph state-merge with operator.add.
    revision_actions: Annotated[list[dict[str, Any]], operator.add]

    # Belief revision summary (Stream 11 IBR.12).
    # The belief_revision agent runs once per pipeline invocation and
    # produces a single summary dict -- counts of touchpoints
    # discovered, verdict distribution, auto-applied vs flagged-for-
    # curation revisions, LLM invocation count, and the reason the
    # phase was skipped (if any). The persister copies this verbatim
    # to ``extraction_runs.stats.belief_revision`` so the Pipeline
    # Monitor can render it as run-level tiles without parsing
    # ``step_logs[].metadata`` (which is meant for audit, not for
    # programmatic consumption).
    #
    # No reducer: the field is replaced wholesale by the agent's
    # single write, not accumulated. Defaults to ``None`` when the
    # belief_revision node hasn't run yet (early pipeline state) or
    # when the agent's return is missing the field.
    belief_revision_summary: dict[str, Any] | None
