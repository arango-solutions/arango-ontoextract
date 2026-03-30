from datetime import datetime
from enum import StrEnum
from typing import Literal

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


# ---------------------------------------------------------------------------
# CRUD request models (K.3–K.6b)
# ---------------------------------------------------------------------------


class CreateClassRequest(BaseModel):
    """Request body for creating a new ontology class (K.3)."""

    label: str
    uri: str | None = None
    description: str | None = None
    parent_class_key: str | None = Field(
        None, description="If set, a subclass_of edge is created to this parent"
    )
    rdf_type: str = "owl:Class"


class CreatePropertyRequest(BaseModel):
    """Request body for creating a new ontology property (K.4)."""

    label: str
    uri: str | None = None
    description: str | None = None
    domain_class_key: str = Field(..., description="Class this property belongs to")
    range: str = Field(..., description="e.g. 'xsd:string', 'xsd:integer', or a class URI")
    property_type: str = Field(..., description="'datatype' or 'object'")


class CreateEdgeRequest(BaseModel):
    """Request body for creating or updating an edge between classes (K.5)."""

    edge_type: Literal["subclass_of", "related_to", "extends_domain"]
    from_key: str
    to_key: str
    label: str | None = None


class UpdateClassRequest(BaseModel):
    """Partial update for an ontology class (K.6)."""

    label: str | None = None
    description: str | None = None
    uri: str | None = None


class UpdatePropertyRequest(BaseModel):
    """Partial update for an ontology property (K.6)."""

    label: str | None = None
    description: str | None = None
    uri: str | None = None
    range: str | None = None


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
    llm_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    faithfulness_score: float = Field(default=0.5, ge=0.0, le=1.0)
    semantic_validity_score: float = Field(default=0.8, ge=0.0, le=1.0)
    property_agreement: float = Field(default=1.0, ge=0.0, le=1.0)
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
