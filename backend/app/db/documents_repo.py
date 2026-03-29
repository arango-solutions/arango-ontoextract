"""Repository layer for ``documents`` and ``chunks`` collections.

All AQL is encapsulated here — no raw queries in routes or services.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.pagination import paginate
from app.models.common import PaginatedResponse
from app.models.documents import DocumentStatus

log = logging.getLogger(__name__)

DOCUMENTS_COLLECTION = "documents"
CHUNKS_COLLECTION = "chunks"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_document(
    *,
    filename: str,
    mime_type: str,
    file_hash: str,
    org_id: str | None = None,
    metadata: dict | None = None,
    db: StandardDatabase | None = None,
) -> dict:
    """Insert a new document record.  Returns the full stored document."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    doc = {
        "filename": filename,
        "mime_type": mime_type,
        "file_hash": file_hash,
        "org_id": org_id,
        "status": DocumentStatus.UPLOADING,
        "upload_date": _now_iso(),
        "chunk_count": 0,
        "metadata": metadata or {},
    }
    result = col.insert(doc, return_new=True)
    return result["new"]


def get_document(doc_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Return a single document by ``_key``, or ``None``."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    try:
        return col.get(doc_id)
    except Exception:
        return None


def list_documents(
    *,
    limit: int = 25,
    cursor: str | None = None,
    sort_field: str = "upload_date",
    sort_order: str = "desc",
    org_id: str | None = None,
    status: str | None = None,
    db: StandardDatabase | None = None,
) -> PaginatedResponse[dict]:
    """Paginated document listing with optional filters."""
    db = db or get_db()
    filters: dict[str, Any] = {}
    if org_id:
        filters["org_id"] = org_id
    if status:
        filters["status"] = status
    # Exclude soft-deleted documents from listings
    return paginate(
        db,
        collection=DOCUMENTS_COLLECTION,
        sort_field=sort_field,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
        filters=filters,
        extra_aql='FILTER doc.status != "deleted"',
    )


def update_document_status(
    doc_id: str,
    status: DocumentStatus,
    *,
    error_message: str | None = None,
    db: StandardDatabase | None = None,
) -> dict | None:
    """Set the processing status on a document.  Returns updated doc."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    update: dict[str, Any] = {"status": status}
    if error_message is not None:
        update["error_message"] = error_message
    result = col.update({"_key": doc_id, **update}, return_new=True)
    return result["new"]


def update_document_chunk_count(
    doc_id: str,
    chunk_count: int,
    *,
    db: StandardDatabase | None = None,
) -> None:
    """Update the ``chunk_count`` field after chunking completes."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    col.update({"_key": doc_id, "chunk_count": chunk_count})


def delete_document(doc_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Soft-delete: set status to ``deleted``."""
    return update_document_status(doc_id, DocumentStatus.DELETED, db=db)


def find_document_by_hash(
    file_hash: str, *, db: StandardDatabase | None = None
) -> dict | None:
    """Look up an active document by its SHA-256 hash."""
    db = db or get_db()
    query = """\
FOR doc IN @@col
  FILTER doc.file_hash == @hash
  FILTER doc.status != "deleted"
  LIMIT 1
  RETURN doc"""
    rows = list(
        db.aql.execute(query, bind_vars={"@col": DOCUMENTS_COLLECTION, "hash": file_hash})
    )
    return rows[0] if rows else None


# ---------- chunks ----------


def create_chunks(
    chunks: list[dict],
    *,
    db: StandardDatabase | None = None,
) -> list[dict]:
    """Bulk-insert chunk documents.  Returns inserted docs with ``_key``."""
    db = db or get_db()

    if not db.has_collection(CHUNKS_COLLECTION):
        log.warning("chunks collection missing — creating it now")
        db.create_collection(CHUNKS_COLLECTION)

    col = db.collection(CHUNKS_COLLECTION)

    inserted = []
    first_error: Exception | None = None
    for i, chunk in enumerate(chunks):
        try:
            meta = col.insert(chunk, return_new=True)
            if isinstance(meta, dict) and "new" in meta:
                inserted.append(meta["new"])
            elif isinstance(meta, dict):
                inserted.append(meta)
        except Exception as exc:
            if first_error is None:
                first_error = exc
            log.warning("chunk %d insert failed: %s", i, exc)

    if not inserted and first_error is not None:
        raise first_error

    return inserted


def get_chunks_for_document(
    doc_id: str,
    *,
    limit: int = 25,
    cursor: str | None = None,
    db: StandardDatabase | None = None,
) -> PaginatedResponse[dict]:
    """Paginated chunk listing for a document, ordered by ``chunk_index``."""
    db = db or get_db()
    return paginate(
        db,
        collection=CHUNKS_COLLECTION,
        sort_field="chunk_index",
        sort_order="asc",
        limit=limit,
        cursor=cursor,
        filters={"doc_id": doc_id},
    )


def get_chunk_by_id(chunk_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Return a single chunk by ``_key``."""
    db = db or get_db()
    col = db.collection(CHUNKS_COLLECTION)
    try:
        return col.get(chunk_id)
    except Exception:
        return None
