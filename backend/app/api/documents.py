from fastapi import APIRouter, UploadFile

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(file: UploadFile) -> dict:
    """Upload a document and start async processing pipeline."""
    # TODO: implement ingestion service — parse, chunk, embed
    return {
        "doc_id": "placeholder",
        "filename": file.filename,
        "status": "uploading",
    }


@router.get("/{doc_id}")
async def get_document(doc_id: str) -> dict:
    """Get document metadata and processing status."""
    # TODO: implement document lookup
    return {"doc_id": doc_id, "status": "not_implemented"}


@router.get("/{doc_id}/chunks")
async def get_chunks(doc_id: str, offset: int = 0, limit: int = 50) -> dict:
    """List chunks for a document."""
    # TODO: implement chunk retrieval with pagination
    return {"doc_id": doc_id, "chunks": [], "offset": offset, "limit": limit}


@router.get("")
async def list_documents(offset: int = 0, limit: int = 50) -> dict:
    """List all documents, paginated."""
    # TODO: implement document listing
    return {"documents": [], "offset": offset, "limit": limit}
