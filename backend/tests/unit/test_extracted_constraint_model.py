"""Unit tests for the ``ExtractedConstraint`` + ``RestrictionType`` models.

Stream 3 PR 1. These are pure Pydantic-validation tests -- no DB, no
service. They guard the contract between the LLM JSON schema (the
``tier1_*`` prompts) and the materialization layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.ontology import (
    ExtractedClass,
    ExtractedConstraint,
    RestrictionType,
)


def test_min_cardinality_round_trip() -> None:
    c = ExtractedConstraint(
        restriction_type=RestrictionType.MIN_CARDINALITY,
        property_uri="http://ex.org/onto#holder",
        restriction_value=1,
        description="each Account must have at least one holder",
        confidence=0.95,
    )
    assert c.restriction_type == "minCardinality"
    assert c.restriction_value == 1


def test_all_values_from_takes_uri_string() -> None:
    c = ExtractedConstraint(
        restriction_type=RestrictionType.ALL_VALUES_FROM,
        property_uri="http://ex.org/onto#nationality",
        restriction_value="http://ex.org/onto#Country",
    )
    assert c.restriction_value == "http://ex.org/onto#Country"


def test_has_value_takes_string_literal() -> None:
    c = ExtractedConstraint(
        restriction_type=RestrictionType.HAS_VALUE,
        property_uri="http://ex.org/onto#status",
        restriction_value="Open",
    )
    assert c.restriction_value == "Open"


def test_unknown_restriction_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedConstraint(
            restriction_type="notARealRestrictionKind",  # type: ignore[arg-type]
            property_uri="http://ex.org/onto#x",
            restriction_value=1,
        )


def test_confidence_clamped_via_validation() -> None:
    with pytest.raises(ValidationError):
        ExtractedConstraint(
            restriction_type=RestrictionType.MIN_CARDINALITY,
            property_uri="http://ex.org/onto#holder",
            restriction_value=1,
            confidence=1.5,
        )


def test_extracted_class_constraints_default_empty() -> None:
    """Existing prompts that don't emit "constraints" continue to validate."""
    cls = ExtractedClass(
        uri="http://ex.org/onto#Account",
        label="Account",
        description="A financial account",
        confidence=0.9,
    )
    assert cls.constraints == []


def test_extracted_class_with_constraints() -> None:
    cls = ExtractedClass(
        uri="http://ex.org/onto#Account",
        label="Account",
        description="A financial account",
        confidence=0.9,
        constraints=[
            {
                "restriction_type": "minCardinality",
                "property_uri": "http://ex.org/onto#holder",
                "restriction_value": 1,
                "description": "at least one",
            },
            {
                "restriction_type": "maxCardinality",
                "property_uri": "http://ex.org/onto#holder",
                "restriction_value": 1,
                "description": "and at most one",
            },
        ],
    )
    assert len(cls.constraints) == 2
    kinds = sorted(c.restriction_type for c in cls.constraints)
    assert kinds == ["maxCardinality", "minCardinality"]


def test_restriction_type_enum_values_match_prd() -> None:
    """Lock the wire values -- PRD §6.14 fixes these strings."""
    assert RestrictionType.MIN_CARDINALITY.value == "minCardinality"
    assert RestrictionType.MAX_CARDINALITY.value == "maxCardinality"
    assert RestrictionType.CARDINALITY.value == "cardinality"
    assert RestrictionType.ALL_VALUES_FROM.value == "allValuesFrom"
    assert RestrictionType.SOME_VALUES_FROM.value == "someValuesFrom"
    assert RestrictionType.HAS_VALUE.value == "hasValue"
