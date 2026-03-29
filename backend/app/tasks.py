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
        documents_repo.update_document_status(doc_id, DocumentStatus.PARSING)
        parsed = await _parse(file_bytes, mime_type)

        # --- chunking ---
        documents_repo.update_document_status(doc_id, DocumentStatus.CHUNKING)
        chunks = chunk_document(parsed)
        if not chunks:
            documents_repo.update_document_status(
                doc_id, DocumentStatus.READY, error_message="No content extracted"
            )
            return

        # --- embedding ---
        documents_repo.update_document_status(doc_id, DocumentStatus.EMBEDDING)
        texts = [c.text for c in chunks]
        embeddings = await asyncio.to_thread(embedding_svc.embed_texts, texts)

        # --- store chunks ---
        chunk_dicts = _build_chunk_dicts(doc_id, chunks, embeddings)
        stored = documents_repo.create_chunks(chunk_dicts)
        if not stored:
            raise RuntimeError(
                f"All {len(chunk_dicts)} chunk inserts failed — check ArangoDB logs"
            )
        documents_repo.update_document_chunk_count(doc_id, len(stored))
        log.info(
            "chunks stored",
            extra={"doc_id": doc_id, "requested": len(chunk_dicts), "stored": len(stored)},
        )

        documents_repo.update_document_status(doc_id, DocumentStatus.READY)
        log.info("document processing complete", extra={"doc_id": doc_id, "chunks": len(chunks)})

    except Exception as exc:
        log.exception("document processing failed", extra={"doc_id": doc_id})
        documents_repo.update_document_status(
            doc_id, DocumentStatus.FAILED, error_message=str(exc)
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
