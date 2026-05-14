"""Pydantic models for curation decisions, promotion reports, and temporal responses."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CurationAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MERGE = "merge"
    EDIT = "edit"


class CurationIssueReason(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    WRONG_CLASS = "wrong_class"
    WRONG_PARENT = "wrong_parent"
    WRONG_RELATIONSHIP = "wrong_relationship"
    DUPLICATE = "duplicate"
    TOO_GENERIC = "too_generic"
    TOO_SPECIFIC = "too_specific"
    HALLUCINATED = "hallucinated"
    BAD_LABEL = "bad_label"
    BAD_DESCRIPTION = "bad_description"
    MISSING_PROPERTY = "missing_property"
    DOMAIN_MISMATCH = "domain_mismatch"


class EntityType(StrEnum):
    CLASS = "class"
    PROPERTY = "property"
    EDGE = "edge"


# ---------------------------------------------------------------------------
# Curation Decision models
# ---------------------------------------------------------------------------


class CurationDecisionCreate(BaseModel):
    """Request body for recording a single curation decision."""

    run_id: str
    entity_key: str
    entity_type: EntityType
    action: CurationAction
    curator_id: str
    notes: str | None = None
    issue_reasons: list[CurationIssueReason] = Field(default_factory=list)
    edited_data: dict[str, Any] | None = Field(
        None,
        description="New data when action is 'edit'; ignored for approve/reject.",
    )
    decision_latency_ms: int | None = Field(
        None,
        ge=0,
        description=(
            "Q.5 — client-measured milliseconds from the previous decision "
            "(or session start) to this one. Used to compute curator "
            "throughput without trusting the wall clock between two "
            "server-side ``created_at`` values, which would conflate "
            "active curation time with idle / coffee time."
        ),
    )


class CurationDecisionResponse(BaseModel):
    """Response model for a persisted curation decision."""

    key: str = Field(alias="_key")
    id: str = Field(alias="_id")
    run_id: str
    entity_key: str
    entity_type: EntityType
    action: CurationAction
    curator_id: str
    notes: str | None = None
    issue_reasons: list[CurationIssueReason] = Field(default_factory=list)
    edited_data: dict[str, Any] | None = None
    edit_diff: dict[str, Any] | None = None
    created_at: float
    decision_latency_ms: int | None = None

    model_config = {"populate_by_name": True}


class BatchDecisionRequest(BaseModel):
    """Request body for batch curation decisions."""

    run_id: str
    decisions: list[BatchDecisionItem]


class BatchDecisionItem(BaseModel):
    """A single item within a batch decision request."""

    entity_key: str
    entity_type: EntityType
    action: CurationAction
    curator_id: str
    notes: str | None = None
    issue_reasons: list[CurationIssueReason] = Field(default_factory=list)
    edited_data: dict[str, Any] | None = None
    decision_latency_ms: int | None = Field(None, ge=0)


class BatchDecisionResponse(BaseModel):
    """Response from a batch curation operation."""

    processed: int
    succeeded: int
    failed: int
    results: list[CurationDecisionResponse]
    errors: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Merge models
# ---------------------------------------------------------------------------


class MergeRequest(BaseModel):
    """Request body for merging duplicate entities."""

    source_keys: list[str] = Field(min_length=1)
    target_key: str
    merged_data: dict[str, Any] = Field(default_factory=dict)
    curator_id: str
    notes: str | None = None


class MergeResponse(BaseModel):
    """Response from a merge operation."""

    target_key: str
    merged_version: dict[str, Any]
    expired_sources: list[str]
    edges_recreated: int


class MergeCandidateResponse(BaseModel):
    """Entity resolution merge candidate pair."""

    source_key: str
    source_label: str
    target_key: str
    target_label: str
    vector_similarity: float
    topo_similarity: float
    combined_score: float


# ---------------------------------------------------------------------------
# Promotion models
# ---------------------------------------------------------------------------


class PromotionRequest(BaseModel):
    """Optional parameters for a promotion request."""

    ontology_id: str | None = None


class PromotionReport(BaseModel):
    """Report from a staging-to-production promotion."""

    run_id: str
    ontology_id: str
    promoted_count: int
    skipped_count: int
    error_count: int
    promoted_at: float
    errors: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "completed"


class PromotionStatusResponse(BaseModel):
    """Current promotion status for a run."""

    run_id: str
    status: str
    report: PromotionReport | None = None


# ---------------------------------------------------------------------------
# Temporal response models
# ---------------------------------------------------------------------------


class TemporalSnapshot(BaseModel):
    """Point-in-time graph state."""

    ontology_id: str
    timestamp: float
    classes: list[dict[str, Any]]
    properties: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class TemporalDiffEntry(BaseModel):
    """A single entity that appears in a temporal diff."""

    key: str = Field(alias="_key", default="")
    uri: str = ""
    label: str = ""
    collection: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class TemporalDiff(BaseModel):
    """Comparison between two timestamps."""

    ontology_id: str
    t1: float
    t2: float
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    changed: list[dict[str, Any]]


class TimelineEvent(BaseModel):
    """A discrete change event for the VCR timeline slider."""

    timestamp: float
    event_type: str
    entity_key: str = ""
    entity_label: str = ""
    collection: str = ""
    change_summary: str = ""


class VersionHistoryEntry(BaseModel):
    """A single version of a class in its history."""

    version: int
    label: str
    created: float
    expired: float
    is_current: bool
    change_type: str = ""
    change_summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
