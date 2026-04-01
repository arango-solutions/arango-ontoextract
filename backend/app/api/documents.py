"""Document REST endpoints — PRD Section 7.1.

Thin route handlers that validate input, delegate to services/repo, and return
Pydantic-shaped responses.  Routes never import from ``db/`` directly; all data
access goes through the repository and service layers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from fastapi import APIRouter, Query, UploadFile

from app.api.dependencies import get_or_404
from app.api.errors import ConflictError, ValidationError
from app.db import documents_repo
from app.db.client import get_db
from app.db.utils import run_aql
from app.models.common import PaginatedResponse
from app.services.ingestion import compute_file_hash
from app.tasks import process_document

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_background_tasks: set[asyncio.Task] = set()  # prevent GC of fire-and-forget tasks

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
}


def _validate_mime(file: UploadFile) -> str:
    """Return the validated MIME type, raising ValidationError if unsupported."""
    mime = file.content_type or ""
    if mime not in _ALLOWED_MIME_TYPES:
        if file.filename and file.filename.endswith(".md"):
            return "text/markdown"
        raise ValidationError(
            f"Unsupported file type: {mime}",
            details={"allowed": sorted(_ALLOWED_MIME_TYPES)},
        )
    return mime


def _to_doc_response(doc: dict) -> dict:
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
) -> dict:
    """Upload a document and start async processing pipeline."""
    content = await file.read()
    mime = _validate_mime(file)

    file_hash = compute_file_hash(content)
    existing = documents_repo.find_document_by_hash(file_hash)
    if existing:
        raise ConflictError(
            "Duplicate document — a file with identical content already exists",
            details={"existing_doc_id": existing["_key"], "file_hash": file_hash},
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
) -> PaginatedResponse[dict]:
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
async def get_document(doc_id: str) -> dict:
    """Get document metadata and processing status."""
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return _to_doc_response(doc)


@router.get("/{doc_id}/chunks")
async def get_chunks(
    doc_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[dict]:
    """List chunks for a document (paginated)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return documents_repo.get_chunks_for_document(doc_id, limit=limit, cursor=cursor)


@router.put("/{doc_id}")
async def update_document(
    doc_id: str,
    file: UploadFile,
    org_id: str | None = Query(default=None),
) -> dict:
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
    from app.models.documents import DocumentStatus

    documents_repo.update_document_status(doc_id, DocumentStatus.UPLOADING)

    task = asyncio.create_task(process_document(doc_id, content, mime))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    updated = documents_repo.get_document(doc_id)
    return _to_doc_response(updated or {"_key": doc_id})


@router.get("/{doc_id}/ontologies")
async def get_document_ontologies(doc_id: str) -> dict:
    """List ontologies extracted from a document (via ``extracted_from`` edges)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    db = get_db()
    ontologies: list[dict] = []
    if db.has_collection("extracted_from") and db.has_collection("ontology_registry"):
        ontologies = list(run_aql(db,
            "FOR e IN extracted_from "
            "FILTER e._to == @doc_id "
            "LET oid = e.ontology_id "
            "COLLECT ontology_id = oid INTO group "
            "FOR o IN ontology_registry "
            "FILTER o._key == ontology_id "
            "RETURN {_key: o._key, name: o.name, tier: o.tier, "
            "class_count: o.class_count, status: o.status, edge_count: LENGTH(group)}",
            bind_vars={"doc_id": f"documents/{doc_id}"},
        ))

    return {"doc_id": doc_id, "ontologies": ontologies}


NEVER_EXPIRES: int = sys.maxsize


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    confirm: bool = Query(default=False, description="Set to true to actually delete"),
) -> dict:
    """Delete a document with cascade analysis (J.2).

    Without ``?confirm=true``, returns the list of affected ontologies
    without making changes.  With confirmation, removes the document,
    its chunks, and expires ``extracted_from`` edges.
    """
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    db = get_db()
    affected_ontologies: list[dict] = []
    doc_full_id = f"documents/{doc_id}"

    if db.has_collection("extracted_from"):
        edges = list(
            run_aql(db,
                "FOR e IN extracted_from "
                "FILTER e._to == @doc_id AND e.expired == @never "
                "RETURN e",
                bind_vars={"doc_id": doc_full_id, "never": NEVER_EXPIRES},
            )
        )

        ontology_ids = {e.get("ontology_id") for e in edges if e.get("ontology_id")}
        if ontology_ids and db.has_collection("ontology_registry"):
            affected_ontologies = list(
                run_aql(db,
                    "FOR o IN ontology_registry FILTER o._key IN @ids "
                    "RETURN {_key: o._key, name: o.name, status: o.status}",
                    bind_vars={"ids": list(ontology_ids)},
                )
            )

    if not confirm:
        return {
            "doc_id": doc_id,
            "status": "pending_confirmation",
            "affected_ontologies": affected_ontologies,
            "message": "Pass ?confirm=true to proceed with deletion.",
        }

    if db.has_collection("extracted_from"):
        run_aql(db,
            "FOR e IN extracted_from "
            "FILTER e._to == @doc_id AND e.expired == @never "
            "UPDATE e WITH {expired: @now} IN extracted_from",
            bind_vars={"doc_id": doc_full_id, "never": NEVER_EXPIRES, "now": time.time()},
        )

    chunks_removed = documents_repo.delete_chunks_for_document(doc_id)
    documents_repo.hard_delete_document(doc_id)

    return {
        "doc_id": doc_id,
        "status": "deleted",
        "chunks_removed": chunks_removed,
        "affected_ontologies": affected_ontologies,
    }
