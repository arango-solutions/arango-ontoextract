"""Ontology requirements / competency-question CRUD (Stream 22 / CQ-PR1, PRD §6.19).

An ORSD-style spec attached to a target ontology: purpose, scope, intended uses,
and use cases with their competency questions. CQ authoring assistance (CQ-PR2),
CQ->AQL formalization (CQ-PR3), and coverage validation (CQ-PR4/5) build on this.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.ontology import _shared
from app.db import requirements_repo
from app.services import cq_coverage

log = logging.getLogger(__name__)
router = APIRouter()


class CompetencyQuestion(BaseModel):
    id: str | None = None
    text: str = Field(..., min_length=1)
    priority: str = Field("medium", pattern="^(low|medium|high)$")
    expected_answer_shape: str | None = None
    query: str | None = None  # CQ->AQL, filled by CQ-PR3
    status: str = Field("proposed", pattern="^(proposed|accepted|rejected)$")


class UseCase(BaseModel):
    name: str = Field(..., min_length=1)
    priority: str = Field("medium", pattern="^(low|medium|high)$")
    competency_questions: list[CompetencyQuestion] = Field(default_factory=list)


class RequirementsSpec(BaseModel):
    purpose: str | None = None
    scope: str | None = None
    intended_uses: list[str] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(default_factory=list)


def _require_ontology(ontology_id: str) -> None:
    db = _shared.get_db()
    if _shared.registry_repo.get_registry_entry(ontology_id, db=db) is None:
        raise HTTPException(status_code=404, detail=f"ontology '{ontology_id}' not found")


@router.get("/{ontology_id}/requirements")
async def get_requirements(ontology_id: str) -> dict[str, Any]:
    spec = requirements_repo.get_requirements(_shared.get_db(), ontology_id)
    if spec is None:
        raise HTTPException(
            status_code=404, detail=f"no requirements spec for ontology '{ontology_id}'"
        )
    return spec


@router.put("/{ontology_id}/requirements")
async def put_requirements(ontology_id: str, body: RequirementsSpec) -> dict[str, Any]:
    """Create or replace the requirements spec for an ontology."""
    _require_ontology(ontology_id)
    return requirements_repo.upsert_requirements(_shared.get_db(), ontology_id, body.model_dump())


@router.post("/{ontology_id}/coverage")
async def run_coverage(ontology_id: str) -> dict[str, Any]:
    """Evaluate the ontology's competency questions and return a coverage report."""
    try:
        return cq_coverage.run_coverage(_shared.get_db(), ontology_id=ontology_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{ontology_id}/requirements")
async def delete_requirements(ontology_id: str) -> dict[str, Any]:
    removed = requirements_repo.delete_requirements(_shared.get_db(), ontology_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"no requirements spec for ontology '{ontology_id}'"
        )
    return {"ontology_id": ontology_id, "deleted": True}
