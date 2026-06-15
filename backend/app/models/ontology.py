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
# CRUD request models (K.3-K.6b)
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

    edge_type: Literal[
        "subclass_of",
        "related_to",
        "extends_domain",
        "rdfs_domain",
        "rdfs_range_class",
    ]
    from_key: str
    to_key: str
    label: str | None = None


class UpdateClassRequest(BaseModel):
    """Partial update for an ontology class (K.6)."""

    label: str | None = None
    description: str | None = None
    uri: str | None = None
    status: str | None = None


class UpdatePropertyRequest(BaseModel):
    """Partial update for an ontology property (K.6)."""

    label: str | None = None
    description: str | None = None
    uri: str | None = None
    range: str | None = None


class UpdateEdgeRequest(BaseModel):
    """Partial update for a versioned ontology edge (subclass_of, related_to, etc.)."""

    status: Literal["pending", "approved", "rejected"]


class UpdateConstraintRequest(BaseModel):
    """Curator edit for a constraint (Stream 3 I.7).

    Only the curator-editable fields are accepted. ``restriction_value`` is
    overloaded by the constraint's ``restriction_type`` exactly as in
    ``ExtractedConstraint`` (int for cardinality kinds, class URI for value
    restrictions, literal for hasValue). At least one field must be set.
    """

    restriction_value: int | float | bool | str | None = None
    description: str | None = None


class ExtractionClassification(StrEnum):
    EXISTING = "existing"
    EXTENSION = "extension"
    NEW = "new"


class SourceEvidence(BaseModel):
    """Source-text evidence supporting an extracted ontology assertion."""

    source_chunk_ids: list[str] = []
    source_spans: list[str] = []
    evidence_text: str = ""
    evidence_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    extraction_rationale: str = ""


class ExtractedAttribute(BaseModel):
    """A datatype property (class attribute) extracted by the LLM."""

    uri: str
    label: str
    description: str = ""
    range_datatype: str = "xsd:string"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: list[SourceEvidence] = []


class ExtractedRelationship(BaseModel):
    """An object property (inter-class relationship) extracted by the LLM."""

    uri: str
    label: str
    description: str = ""
    target_class_uri: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: list[SourceEvidence] = []


class RestrictionType(StrEnum):
    """OWL restriction kinds the LLM may emit (PRD §6.14).

    Stream 3 PR 1 covers the cardinality + value-restriction kinds.
    Qualified cardinality variants (``owl:minQualifiedCardinality`` etc.)
    are documented in PRD §6.14 but deferred to a follow-up PR -- they
    require a ``qualified_on_class`` field that's not part of the
    minimal extraction contract.
    """

    MIN_CARDINALITY = "minCardinality"
    MAX_CARDINALITY = "maxCardinality"
    CARDINALITY = "cardinality"  # exactly N -- semantically: min==max
    ALL_VALUES_FROM = "allValuesFrom"
    SOME_VALUES_FROM = "someValuesFrom"
    HAS_VALUE = "hasValue"


class ExtractedConstraint(BaseModel):
    """A single OWL restriction extracted by the LLM for one class.

    One ``ExtractedConstraint`` becomes one row in ``ontology_constraints``
    on materialization (one restriction per row -- the OWL-native shape).
    Cardinality bounds that have BOTH a min and a max therefore emit two
    rows; the rule engine groups them back together at evaluation time.

    The ``property_uri`` references the constrained property by URI rather
    than by Arango key because the property may not exist yet when the
    LLM speaks (the same response may also be extracting the property).
    Materialization resolves URI -> Arango ``property_id`` opportunisticly;
    when no match is found, ``property_id`` is left ``null`` and the
    rule engine falls back to URI matching.
    """

    restriction_type: RestrictionType
    property_uri: str = Field(
        description="URI of the constrained property (an extracted attribute or relationship)."
    )
    # ``restriction_value`` is overloaded by ``restriction_type``:
    #   minCardinality / maxCardinality / cardinality  -> int (non-negative)
    #   allValuesFrom / someValuesFrom                  -> str (class URI)
    #   hasValue                                        -> str | int | float | bool (literal)
    #
    # Pydantic's union+strict-bool means we lean on the consumer (the
    # rule engine + UI) to interpret based on ``restriction_type``. The
    # alternative -- typed-per-restriction subclasses -- would explode
    # the JSON schema the LLM has to satisfy with no measured win.
    restriction_value: int | float | bool | str = Field(
        description=(
            "Integer for cardinality kinds; URI string for value restrictions; "
            "literal for hasValue."
        ),
    )
    description: str = Field(
        default="",
        description="Curator-readable rationale, e.g. 'each Account must have exactly one holder'.",
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: list[SourceEvidence] = []


class ExtractedClass(BaseModel):
    """Pydantic model for LLM extraction output — a single ontology class."""

    uri: str
    label: str
    description: str
    parent_uri: str | None = None
    parent_evidence: list[SourceEvidence] = []
    parent_domain_uri: str | None = None
    classification: ExtractionClassification = ExtractionClassification.NEW
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[SourceEvidence] = []
    # Legacy field — kept for backward compat during migration
    properties: list["ExtractedProperty"] = []
    # PGT-aligned fields (ADR-006)
    attributes: list[ExtractedAttribute] = []
    relationships: list[ExtractedRelationship] = []
    # Stream 3 PR 1 -- OWL restrictions on this class (cardinality,
    # value restrictions, hasValue). Empty by default so prompts that
    # don't ask for constraints continue to validate unchanged.
    constraints: list[ExtractedConstraint] = []
    # Quality signals
    llm_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    faithfulness_score: float = Field(default=0.5, ge=0.0, le=1.0)
    semantic_validity_score: float = Field(default=0.8, ge=0.0, le=1.0)
    property_agreement: float = Field(default=1.0, ge=0.0, le=1.0)
    attribute_agreement: float = Field(default=1.0, ge=0.0, le=1.0)
    relationship_agreement: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractedProperty(BaseModel):
    """Pydantic model for LLM extraction output — a single property."""

    uri: str
    label: str
    description: str
    property_type: str  # "datatype" | "object"
    range: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[SourceEvidence] = []


class ExtractionResult(BaseModel):
    """Full extraction output from a single LLM pass."""

    classes: list[ExtractedClass]
    pass_number: int
    model: str
    token_usage: int | None = None
