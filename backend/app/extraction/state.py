"""LangGraph pipeline state schema per PRD Section 6.11."""

from __future__ import annotations

from typing import Any, TypedDict

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
    errors: list[str]
    token_usage: TokenUsage
    step_logs: list[StepLog]
    metadata: dict[str, Any]

    er_results: dict[str, Any]
    filter_results: dict[str, Any]
    merge_candidates: list[dict[str, Any]]

    domain_context: str
