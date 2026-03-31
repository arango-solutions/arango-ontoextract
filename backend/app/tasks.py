"""Async document processing pipeline.

Orchestrates: parse → chunk → embed → store.
Implemented as a plain async function for now; Celery/ARQ integration is a
future optimisation (IMPLEMENTATION_PLAN Week 2, task 2.5).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db import documents_repo
from app.db.client import get_db
from app.models.documents import DocumentStatus
from app.services import embedding as embedding_svc
from app.services.ingestion import (
    Chunk,
    ParsedDocument,
    chunk_document,
    parse_docx,
    parse_markdown,
    parse_pdf,
)

log = logging.getLogger(__name__)

_MIME_PARSERS: dict[str, Any] = {
    "application/pdf": parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    "text/markdown": parse_markdown,
}


async def process_document(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    """Full ingestion pipeline for a single document.

    Updates ``documents.status`` at each stage.  On failure the document is
    marked ``failed`` with the error message stored.
    """
    try:
        # --- parsing ---
        log.info("[ingest:%s] stage=parsing mime=%s bytes=%d", doc_id, mime_type, len(file_bytes))
        documents_repo.update_document_status(doc_id, DocumentStatus.PARSING)
        parsed = await _parse(file_bytes, mime_type)
        log.info("[ingest:%s] parsing done, sections=%d", doc_id, len(parsed.sections))

        # --- chunking ---
        log.info("[ingest:%s] stage=chunking", doc_id)
        documents_repo.update_document_status(doc_id, DocumentStatus.CHUNKING)
        chunks = chunk_document(parsed)
        if not chunks:
            log.warning("[ingest:%s] no chunks produced — marking ready with warning", doc_id)
            documents_repo.update_document_status(
                doc_id, DocumentStatus.READY, error_message="No content extracted"
            )
            return
        log.info("[ingest:%s] chunking done, num_chunks=%d", doc_id, len(chunks))

        # --- embedding ---
        log.info("[ingest:%s] stage=embedding, num_texts=%d", doc_id, len(chunks))
        documents_repo.update_document_status(doc_id, DocumentStatus.EMBEDDING)
        texts = [c.text for c in chunks]
        embeddings = await embedding_svc.embed_texts(texts)
        log.info("[ingest:%s] embedding done, num_embeddings=%d", doc_id, len(embeddings))

        # --- store chunks ---
        log.info("[ingest:%s] stage=storing chunks", doc_id)
        chunk_dicts = _build_chunk_dicts(doc_id, chunks, embeddings)
        stored = documents_repo.create_chunks(chunk_dicts)
        if not stored:
            raise RuntimeError(
                f"All {len(chunk_dicts)} chunk inserts failed — check ArangoDB logs"
            )
        documents_repo.update_document_chunk_count(doc_id, len(stored))
        log.info(
            "[ingest:%s] chunks stored, requested=%d stored=%d",
            doc_id, len(chunk_dicts), len(stored),
        )

        # --- vector index ---
        _ensure_vector_index()

        documents_repo.update_document_status(doc_id, DocumentStatus.READY)
        log.info("[ingest:%s] COMPLETE — document ready", doc_id)

    except Exception as exc:
        log.exception("[ingest:%s] FAILED at current stage", doc_id)
        documents_repo.update_document_status(
            doc_id, DocumentStatus.FAILED, error_message=str(exc)
        )


_VECTOR_INDEX_NAME = "idx_chunks_embedding_vector"
_EMBEDDING_DIMENSION = 1536


def _ensure_vector_index() -> None:
    """Create the Faiss IVF vector index on chunks.embedding if it doesn't exist.

    Must be called after chunks with embeddings have been inserted,
    since ArangoDB's vector index requires training data.
    """
    db = get_db()
    if not db.has_collection("chunks"):
        return

    col = db.collection("chunks")
    for idx in col.indexes():
        if idx.get("name") == _VECTOR_INDEX_NAME:
            return  # already exists

    from arango.request import Request
    import math

    chunk_count = col.count()
    n_lists = max(1, int(math.sqrt(chunk_count) * 15))
    # nLists cannot exceed the number of training points
    n_lists = min(n_lists, chunk_count)
    n_probe = max(1, int(math.sqrt(n_lists)))

    log.info("[ingest] vector index params: chunks=%d, nLists=%d, nProbe=%d",
             chunk_count, n_lists, n_probe)

    body = {
        "type": "vector",
        "name": _VECTOR_INDEX_NAME,
        "fields": ["embedding"],
        "params": {
            "metric": "cosine",
            "dimension": _EMBEDDING_DIMENSION,
            "nLists": n_lists,
            "defaultNProbe": n_probe,
            "trainingIterations": 25,
        },
    }
    req = Request(
        method="post",
        endpoint="/_api/index",
        params={"collection": "chunks"},
        data=body,
    )
    resp = db._conn.send_request(req)
    if resp.status_code in (200, 201):
        log.info("[ingest] created vector index %s on chunks.embedding", _VECTOR_INDEX_NAME)
    else:
        raise RuntimeError(
            f"Vector index creation failed ({resp.status_code}): {resp.body}"
        )


async def _parse(file_bytes: bytes, mime_type: str) -> ParsedDocument:
    """Dispatch to the correct parser based on MIME type."""
    if mime_type == "text/markdown":
        text = file_bytes.decode("utf-8", errors="replace")
        return parse_markdown(text)

    parser = _MIME_PARSERS.get(mime_type)
    if parser is None:
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    return await asyncio.to_thread(parser, file_bytes)


def _build_chunk_dicts(
    doc_id: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> list[dict]:
    """Convert Chunk dataclasses + embeddings into dicts for storage."""
    result: list[dict] = []
    for chunk, emb in zip(chunks, embeddings, strict=True):
        result.append(
            {
                "doc_id": doc_id,
                "text": chunk.text,
                "chunk_index": chunk.chunk_index,
                "source_page": chunk.source_page,
                "section_heading": chunk.section_heading,
                "token_count": chunk.token_count,
                "embedding": emb,
            }
        )
    return result
