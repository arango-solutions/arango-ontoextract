from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/extraction", tags=["extraction"])


@router.post("/run")
async def start_extraction(doc_id: str) -> dict:
    """Trigger ontology extraction on a document."""
    # TODO: implement extraction pipeline dispatch
    return {"run_id": "placeholder", "doc_id": doc_id, "status": "queued"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get extraction run status and stats."""
    # TODO: implement run status lookup
    return {"run_id": run_id, "status": "not_implemented"}


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict:
    """Get extracted entities from a run."""
    # TODO: implement result retrieval
    return {"run_id": run_id, "classes": [], "properties": []}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str) -> dict:
    """Retry a failed extraction run."""
    # TODO: implement retry logic
    return {"run_id": run_id, "status": "queued"}
