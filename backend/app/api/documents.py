"""Document REST endpoints — PRD Section 7.1.

Thin route handlers that validate input, delegate to services/repo, and return
Pydantic-shaped responses.  Routes never import from ``db/`` directly; all data
access goes through the repository and service layers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, UploadFile

from app.api.dependencies import get_or_404
from app.api.errors import ConflictError, ValidationError
from app.db import documents_repo
from app.db.client import get_db
from app.db.utils import run_aql
from app.models.common import PaginatedResponse
from app.models.documents import DocumentStatus
from app.services.ingestion import compute_file_hash
from app.tasks import process_document

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_background_tasks: set[asyncio.Task[None]] = set()  # prevent GC of fire-and-forget tasks

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",  # legacy .doc (pre-2007); requires LibreOffice on host
    "text/markdown",
}

# Browsers occasionally upload Office files with a generic or vendor-
# specific MIME type. Map well-known cases by filename suffix when the
# declared MIME doesn't match. Keep this list short -- it's a fallback,
# not a primary path.
_EXTENSION_FALLBACK: dict[str, str] = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
}


def _validate_mime(file: UploadFile) -> str:
    """Return the validated MIME type, raising ValidationError if unsupported.

    Falls back to filename-extension sniffing for known Office formats so
    a misconfigured browser ("application/octet-stream") doesn't block a
    legitimate upload.
    """
    mime = file.content_type or ""
    if mime in _ALLOWED_MIME_TYPES:
        return mime

    if file.filename:
        lower = file.filename.lower()
        for suffix, fallback in _EXTENSION_FALLBACK.items():
            if lower.endswith(suffix):
                return fallback

    raise ValidationError(
        f"Unsupported file type: {mime}",
        details={"allowed": sorted(_ALLOWED_MIME_TYPES)},
    )


def _to_doc_response(doc: dict[str, Any]) -> dict[str, Any]:
    """Ensure the dict has the fields DocumentResponse expects."""
    return {
        "_key": doc["_key"],
        "filename": doc.get("filename", ""),
        "mime_type": doc.get("mime_type", ""),
        "org_id": doc.get("org_id"),
        "status": doc.get("status", "uploading"),
        "upload_date": doc.get("upload_date", ""),
        "chunk_count": doc.get("chunk_count", 0),
        "metadata": doc.get("metadata"),
        "file_hash": doc.get("file_hash"),
        "error_message": doc.get("error_message"),
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    org_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Upload a document and start async processing pipeline."""
    content = await file.read()
    mime = _validate_mime(file)

    file_hash = compute_file_hash(content)
    existing = documents_repo.find_document_by_hash(file_hash)
    if existing:
        # A FAILED record is a leftover from a previous failed ingestion
        # attempt at any pipeline stage (parse / chunk / embed / index).
        # The user's natural recovery is to retry the same file, so we
        # treat re-upload of identical content as an explicit retry: hard
        # delete the prior record + its chunks, then proceed with a fresh
        # ingestion. Any non-FAILED status (uploading / parsing / chunking
        # / embedding / ready / deleted) is still rejected -- those are
        # legitimate duplicates the user shouldn't accidentally clobber.
        prior_status = existing.get("status")
        if prior_status == DocumentStatus.FAILED:
            prior_id = existing["_key"]
            chunks_removed = documents_repo.delete_chunks_for_document(prior_id)
            documents_repo.hard_delete_document(prior_id)
            log.info(
                "discarded prior FAILED document %s (chunks_removed=%d) "
                "to allow re-upload of identical content (hash=%s)",
                prior_id,
                chunks_removed,
                file_hash,
            )
        else:
            raise ConflictError(
                "Duplicate document — a file with identical content already exists",
                details={
                    "existing_doc_id": existing["_key"],
                    "existing_status": prior_status,
                    "file_hash": file_hash,
                },
            )

    doc = documents_repo.create_document(
        filename=file.filename or "untitled",
        mime_type=mime,
        file_hash=file_hash,
        org_id=org_id,
    )

    task = asyncio.create_task(process_document(doc["_key"], content, mime))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "doc_id": doc["_key"],
        "filename": doc["filename"],
        "status": doc["status"],
    }


@router.get("")
async def list_documents(
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="upload_date"),
    order: str = Query(default="desc"),
    org_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[dict[str, Any]]:
    """List all documents (paginated)."""
    return documents_repo.list_documents(
        limit=limit,
        cursor=cursor,
        sort_field=sort,
        sort_order=order,
        org_id=org_id,
        status=status,
    )


@router.get("/{doc_id}")
async def get_document(doc_id: str) -> dict[str, Any]:
    """Get document metadata and processing status."""
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return _to_doc_response(doc)


@router.get("/{doc_id}/chunks")
async def get_chunks(
    doc_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[dict[str, Any]]:
    """List chunks for a document (paginated)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return documents_repo.get_chunks_for_document(doc_id, limit=limit, cursor=cursor)


@router.put("/{doc_id}")
async def update_document(
    doc_id: str,
    file: UploadFile,
    org_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Replace document content with a new file upload (J.1).

    Deletes existing chunks, re-chunks from the new file, and updates
    document metadata (filename, mime_type, file_hash, chunk_count).
    """
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    content = await file.read()
    mime = _validate_mime(file)

    file_hash = compute_file_hash(content)

    existing = documents_repo.find_document_by_hash(file_hash)
    if existing and existing["_key"] != doc_id:
        raise ConflictError(
            "A different document with identical content already exists",
            details={"existing_doc_id": existing["_key"], "file_hash": file_hash},
        )

    documents_repo.delete_chunks_for_document(doc_id)

    documents_repo.update_document_metadata(
        doc_id,
        filename=file.filename or doc.get("filename", "untitled"),
        mime_type=mime,
        file_hash=file_hash,
        chunk_count=0,
    )
    documents_repo.update_document_status(doc_id, DocumentStatus.UPLOADING)

    task = asyncio.create_task(process_document(doc_id, content, mime))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    updated = documents_repo.get_document(doc_id)
    return _to_doc_response(updated or {"_key": doc_id})


@router.get("/{doc_id}/ontologies")
async def get_document_ontologies(doc_id: str) -> dict[str, Any]:
    """List ontologies extracted from a document (via ``extracted_from`` edges)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    db = get_db()
    ontologies: list[dict[str, Any]] = []
    if db.has_collection("extracted_from") and db.has_collection("ontology_registry"):
        ontologies = list(
            run_aql(
                db,
                "FOR e IN extracted_from "
                "FILTER e._to == @doc_id "
                "LET oid = e.ontology_id "
                "COLLECT ontology_id = oid INTO group "
                "FOR o IN ontology_registry "
                "FILTER o._key == ontology_id "
                "RETURN {_key: o._key, name: o.name, tier: o.tier, "
                "class_count: o.class_count, status: o.status, edge_count: LENGTH(group)}",
                bind_vars={"doc_id": f"documents/{doc_id}"},
            )
        )

    return {"doc_id": doc_id, "ontologies": ontologies}


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    confirm: bool = Query(default=False, description="Set to true to actually delete"),
) -> dict[str, Any]:
    """Delete a document with cascade analysis and confirmation."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return documents_repo.delete_document(doc_id, confirm=confirm)
