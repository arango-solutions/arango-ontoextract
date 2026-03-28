from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CurationAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MERGE = "merge"
    EDIT = "edit"


class CurationDecisionCreate(BaseModel):
    entity_id: str
    entity_type: str  # "class" | "property" | "edge"
    action: CurationAction
    before: dict | None = None
    after: dict | None = None
    notes: str | None = None


class CurationDecisionResponse(BaseModel):
    key: str = Field(alias="_key")
    entity_id: str
    entity_type: str
    action: CurationAction
    user_id: str
    timestamp: datetime
    before: dict | None = None
    after: dict | None = None
    notes: str | None = None


class MergeCandidateResponse(BaseModel):
    source_key: str
    source_label: str
    target_key: str
    target_label: str
    vector_similarity: float
    topo_similarity: float
    combined_score: float
