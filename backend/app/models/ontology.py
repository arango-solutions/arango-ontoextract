from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Tier(StrEnum):
    DOMAIN = "domain"
    LOCAL = "local"


class EntityStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class OntologyClassResponse(BaseModel):
    key: str = Field(alias="_key")
    uri: str
    label: str
    description: str | None = None
    tier: Tier
    org_id: str | None = None
    status: EntityStatus
    version: int = 1
    created_at: datetime | None = None
    created_by: str | None = None
    supersedes: str | None = None


class OntologyPropertyResponse(BaseModel):
    key: str = Field(alias="_key")
    uri: str
    label: str
    domain_class: str
    range: str
    property_type: str  # "datatype" | "object"
    tier: Tier
    status: EntityStatus


class ExtractionClassification(StrEnum):
    EXISTING = "existing"
    EXTENSION = "extension"
    NEW = "new"


class ExtractedClass(BaseModel):
    """Pydantic model for LLM extraction output — a single ontology class."""

    uri: str
    label: str
    description: str
    parent_uri: str | None = None
    parent_domain_uri: str | None = None
    classification: ExtractionClassification = ExtractionClassification.NEW
    confidence: float = Field(ge=0.0, le=1.0)
    properties: list["ExtractedProperty"] = []


class ExtractedProperty(BaseModel):
    """Pydantic model for LLM extraction output — a single property."""

    uri: str
    label: str
    description: str
    property_type: str  # "datatype" | "object"
    range: str
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Full extraction output from a single LLM pass."""

    classes: list[ExtractedClass]
    pass_number: int
    model: str
    token_usage: int | None = None
