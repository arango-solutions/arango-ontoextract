from fastapi import APIRouter

from app.models.curation import CurationDecisionCreate

router = APIRouter(prefix="/api/v1/curation", tags=["curation"])


@router.post("/decide")
async def record_decision(decision: CurationDecisionCreate) -> dict:
    """Record a curation decision (approve/reject/merge/edit)."""
    # TODO: implement decision recording in curation_decisions collection
    return {"status": "recorded", "action": decision.action}


@router.get("/decisions")
async def list_decisions(offset: int = 0, limit: int = 50) -> dict:
    """List curation decisions (audit trail)."""
    # TODO: implement decision listing
    return {"decisions": [], "offset": offset, "limit": limit}


@router.get("/merge-candidates/{run_id}")
async def get_merge_candidates(run_id: str) -> dict:
    """Get entity resolution suggestions for a run."""
    # TODO: implement entity resolution query
    return {"run_id": run_id, "candidates": []}


@router.post("/merge")
async def execute_merge(source_key: str, target_key: str) -> dict:
    """Execute a merge between two entities."""
    # TODO: implement merge logic with provenance preservation
    return {"source": source_key, "target": target_key, "status": "not_implemented"}
