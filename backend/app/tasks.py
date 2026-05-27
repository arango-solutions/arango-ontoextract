"""Async document processing pipeline.

Orchestrates: parse → chunk → embed → store.
Implemented as a plain async function for now; Celery/ARQ integration is a
future optimisation (IMPLEMENTATION_PLAN Week 2, task 2.5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast

from app.db import documents_repo
from app.db.client import get_db
from app.models.documents import DocumentStatus
from app.observability import get_tracer
from app.services import embedding as embedding_svc
from app.services.ingestion import (
    Chunk,
    ParsedDocument,
    chunk_document,
    parse_doc,
    parse_docx,
    parse_markdown,
    parse_pdf,
    parse_pptx,
)

log = logging.getLogger(__name__)
tracer = get_tracer(__name__)

_MIME_PARSERS: dict[str, Callable[[bytes], ParsedDocument]] = {
    "application/pdf": lambda file_bytes: parse_pdf(file_bytes),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        lambda file_bytes: parse_docx(file_bytes)
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        lambda file_bytes: parse_pptx(file_bytes)
    ),
    # Legacy Word binary; requires LibreOffice on the host.
    # parse_doc raises a clear RuntimeError if soffice is missing.
    "application/msword": lambda file_bytes: parse_doc(file_bytes),
}


async def process_document(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    """Full ingestion pipeline for a single document.

    Updates ``documents.status`` at each stage.  On failure the document is
    marked ``failed`` with the error message stored.

    OpenTelemetry: wrapped in a top-level ``ingest.document`` span
    (Stream 7 PR 2 -- E.1) with sub-spans for each pipeline stage
    (parse / chunk / embed / store). The span carries
    ``doc.id``/``doc.mime``/``doc.byte_size`` attributes so an
    operator viewing the trace in Jaeger / Tempo can immediately
    see which document and which stage a slow trace belongs to.
    Spans are no-ops when ``settings.otel_enabled`` is False, so
    this costs nothing in the default deployment.
    """
    with tracer.start_as_current_span(
        "ingest.document",
        attributes={
            "doc.id": doc_id,
            "doc.mime": mime_type,
            "doc.byte_size": len(file_bytes),
        },
    ) as ingest_span:
        try:
            with tracer.start_as_current_span("ingest.parse") as parse_span:
                log.info(
                    "[ingest:%s] stage=parsing mime=%s bytes=%d",
                    doc_id,
                    mime_type,
                    len(file_bytes),
                )
                documents_repo.update_document_status(doc_id, DocumentStatus.PARSING)
                parsed = await _parse(file_bytes, mime_type)
                parse_span.set_attribute("sections", len(parsed.sections))
                parse_span.set_attribute(
                    "visual_assets", parsed.visual_diagnostics.visual_asset_count
                )
                if parsed.visual_diagnostics.visual_asset_count:
                    documents_repo.merge_document_user_metadata(
                        doc_id,
                        {"visual_extraction": parsed.visual_diagnostics.to_metadata_dict()},
                    )
                log.info("[ingest:%s] parsing done, sections=%d", doc_id, len(parsed.sections))

            with tracer.start_as_current_span("ingest.chunk") as chunk_span:
                log.info("[ingest:%s] stage=chunking", doc_id)
                documents_repo.update_document_status(doc_id, DocumentStatus.CHUNKING)
                chunks = chunk_document(parsed)
                chunk_span.set_attribute("num_chunks", len(chunks))
                if not chunks:
                    log.warning(
                        "[ingest:%s] no chunks produced — marking ready with warning",
                        doc_id,
                    )
                    documents_repo.update_document_status(
                        doc_id, DocumentStatus.READY, error_message="No content extracted"
                    )
                    ingest_span.set_attribute("result", "empty")
                    return
                log.info("[ingest:%s] chunking done, num_chunks=%d", doc_id, len(chunks))

            with tracer.start_as_current_span("ingest.embed") as embed_span:
                log.info("[ingest:%s] stage=embedding, num_texts=%d", doc_id, len(chunks))
                documents_repo.update_document_status(doc_id, DocumentStatus.EMBEDDING)
                texts = [c.text for c in chunks]
                embeddings = await embedding_svc.embed_texts(texts)
                embed_span.set_attribute("num_embeddings", len(embeddings))
                log.info(
                    "[ingest:%s] embedding done, num_embeddings=%d",
                    doc_id,
                    len(embeddings),
                )

            with tracer.start_as_current_span("ingest.store") as store_span:
                log.info("[ingest:%s] stage=storing chunks", doc_id)
                chunk_dicts = _build_chunk_dicts(doc_id, chunks, embeddings)
                stored = documents_repo.create_chunks(chunk_dicts)
                store_span.set_attribute("chunks.requested", len(chunk_dicts))
                store_span.set_attribute("chunks.stored", len(stored))
                if not stored:
                    raise RuntimeError(
                        f"All {len(chunk_dicts)} chunk inserts failed — check ArangoDB logs"
                    )
                documents_repo.update_document_chunk_count(doc_id, len(stored))
                log.info(
                    "[ingest:%s] chunks stored, requested=%d stored=%d",
                    doc_id,
                    len(chunk_dicts),
                    len(stored),
                )

            _ensure_vector_index()

            documents_repo.update_document_status(doc_id, DocumentStatus.READY)
            ingest_span.set_attribute("result", "ready")
            log.info("[ingest:%s] COMPLETE — document ready", doc_id)

        except Exception as exc:
            ingest_span.set_attribute("result", "failed")
            ingest_span.record_exception(exc)
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
    for idx in cast("list[dict[str, Any]]", col.indexes()):
        if idx.get("name") == _VECTOR_INDEX_NAME:
            return  # already exists

    import math

    from arango.request import Request

    chunk_count = cast(int, col.count())
    n_lists = max(1, int(math.sqrt(chunk_count) * 15))
    # nLists cannot exceed the number of training points
    n_lists = min(n_lists, chunk_count)
    n_probe = max(1, int(math.sqrt(n_lists)))

    log.info(
        "[ingest] vector index params: chunks=%d, nLists=%d, nProbe=%d",
        chunk_count,
        n_lists,
        n_probe,
    )

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

    # Vector index creation is synchronous on the cluster: the server runs
    # ``trainingIterations`` of k-means over the existing
    # ``_EMBEDDING_DIMENSION``-d vectors before responding. On a fresh DB the
    # very first call can exceed the python-arango client's default read
    # timeout (~60 s) -- the cluster keeps training and eventually persists
    # the index, but the client has already raised. The downstream effect is
    # the document gets marked FAILED even though chunks + embeddings are
    # present and the index landed seconds later. We catch that specific
    # failure mode and re-check; the index name is unique so this is safe.
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import ReadTimeout as RequestsReadTimeout

    try:
        resp = db._conn.send_request(req)
    except (RequestsReadTimeout, RequestsConnectionError) as exc:
        log.warning(
            "[ingest] vector index POST raised %s; re-checking the cluster "
            "to see if the cluster completed the build anyway",
            exc.__class__.__name__,
        )
        for idx in cast("list[dict[str, Any]]", col.indexes()):
            if idx.get("name") == _VECTOR_INDEX_NAME:
                log.info(
                    "[ingest] vector index %s present after client timeout -- treating as success",
                    _VECTOR_INDEX_NAME,
                )
                return
        raise RuntimeError(
            f"Vector index creation timed out and the index is not present on the cluster: {exc}"
        ) from exc

    if resp.status_code in (200, 201):
        log.info("[ingest] created vector index %s on chunks.embedding", _VECTOR_INDEX_NAME)
    else:
        raise RuntimeError(f"Vector index creation failed ({resp.status_code}): {resp.body}")


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
) -> list[dict[str, Any]]:
    """Convert Chunk dataclasses + embeddings into dicts for storage."""
    result: list[dict[str, Any]] = []
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
