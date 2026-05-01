"""Repository layer for ``documents`` and ``chunks`` collections.

All AQL is encapsulated here — no raw queries in routes or services.
"""

from __future__ import annotations

import logging
from time import time
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get, run_aql
from app.db.utils import now_iso as _now_iso
from app.models.common import PaginatedResponse
from app.models.documents import DocumentStatus
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)

DOCUMENTS_COLLECTION = "documents"
CHUNKS_COLLECTION = "chunks"


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
    result = cast("dict[str, Any]", col.insert(doc, return_new=True))
    return result["new"]


def get_document(doc_id: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Return a single document by ``_key``, or ``None``."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    try:
        return doc_get(col, doc_id)
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
    result = cast("dict[str, Any]", col.update({"_key": doc_id, **update}, return_new=True))
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


def update_document_metadata(
    doc_id: str,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    file_hash: str | None = None,
    chunk_count: int | None = None,
    db: StandardDatabase | None = None,
) -> dict | None:
    """Merge-update editable metadata fields on a document."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    updates: dict[str, Any] = {}
    if filename is not None:
        updates["filename"] = filename
    if mime_type is not None:
        updates["mime_type"] = mime_type
    if file_hash is not None:
        updates["file_hash"] = file_hash
    if chunk_count is not None:
        updates["chunk_count"] = chunk_count
    if not updates:
        return doc_get(col, doc_id)
    result = cast("dict[str, Any]", col.update({"_key": doc_id, **updates}, return_new=True))
    return result["new"]


def delete_chunks_for_document(doc_id: str, *, db: StandardDatabase | None = None) -> int:
    """Hard-delete all chunks belonging to a document. Returns count removed."""
    db = db or get_db()
    if not db.has_collection(CHUNKS_COLLECTION):
        return 0
    result = list(
        run_aql(
            db,
            "FOR c IN @@col FILTER c.doc_id == @doc_id REMOVE c IN @@col RETURN OLD._key",
            bind_vars={"@col": CHUNKS_COLLECTION, "doc_id": doc_id},
        )
    )
    return len(result)


def hard_delete_document(doc_id: str, *, db: StandardDatabase | None = None) -> bool:
    """Hard-delete a document record. Returns True if deleted."""
    db = db or get_db()
    col = db.collection(DOCUMENTS_COLLECTION)
    try:
        col.delete(doc_id)
        return True
    except Exception:
        return False


def get_document_affected_ontologies(
    doc_id: str, *, db: StandardDatabase | None = None
) -> list[dict]:
    """Return ontologies with active provenance edges from a document."""
    db = db or get_db()
    if not db.has_collection("extracted_from"):
        return []

    ontology_ids = list(
        run_aql(
            db,
            "FOR e IN extracted_from "
            "FILTER e._to == @doc_id AND e.expired == @never "
            "COLLECT ontology_id = e.ontology_id "
            "FILTER ontology_id != null "
            "RETURN ontology_id",
            bind_vars={"doc_id": f"documents/{doc_id}", "never": NEVER_EXPIRES},
        )
    )

    if not ontology_ids or not db.has_collection("ontology_registry"):
        return []

    return list(
        run_aql(
            db,
            "FOR o IN ontology_registry FILTER o._key IN @ids "
            "RETURN {_key: o._key, name: o.name, status: o.status}",
            bind_vars={"ids": ontology_ids},
        )
    )


def expire_document_provenance_edges(doc_id: str, *, db: StandardDatabase | None = None) -> int:
    """Expire active ``extracted_from`` edges pointing at a document."""
    db = db or get_db()
    if not db.has_collection("extracted_from"):
        return 0

    expired = list(
        run_aql(
            db,
            "FOR e IN extracted_from "
            "FILTER e._to == @doc_id AND e.expired == @never "
            "UPDATE e WITH {expired: @now} IN extracted_from "
            "RETURN NEW._key",
            bind_vars={
                "doc_id": f"documents/{doc_id}",
                "never": NEVER_EXPIRES,
                "now": time(),
            },
        )
    )
    return len(expired)


def delete_document(
    doc_id: str,
    *,
    confirm: bool = False,
    db: StandardDatabase | None = None,
) -> dict:
    """Delete a document with cascade analysis and provenance expiration."""
    db = db or get_db()
    affected_ontologies = get_document_affected_ontologies(doc_id, db=db)

    if not confirm:
        return {
            "doc_id": doc_id,
            "status": "pending_confirmation",
            "affected_ontologies": affected_ontologies,
            "message": "Pass ?confirm=true to proceed with deletion.",
        }

    expire_document_provenance_edges(doc_id, db=db)
    chunks_removed = delete_chunks_for_document(doc_id, db=db)
    hard_delete_document(doc_id, db=db)

    return {
        "doc_id": doc_id,
        "status": "deleted",
        "chunks_removed": chunks_removed,
        "affected_ontologies": affected_ontologies,
    }


def find_document_by_hash(file_hash: str, *, db: StandardDatabase | None = None) -> dict | None:
    """Look up an active document by its SHA-256 hash."""
    db = db or get_db()
    query = """\
FOR doc IN @@col
  FILTER doc.file_hash == @hash
  FILTER doc.status != "deleted"
  LIMIT 1
  RETURN doc"""
    rows = list(run_aql(db, query, bind_vars={"@col": DOCUMENTS_COLLECTION, "hash": file_hash}))
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
        return doc_get(col, chunk_id)
    except Exception:
        return None
