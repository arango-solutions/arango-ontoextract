"""008 — Vector index on ``chunks.embedding`` for similarity search.

Used for RAG context retrieval and entity resolution vector blocking.
Dimension defaults to 1536 (OpenAI ``text-embedding-3-small``).

Creates an inverted index with HNSW vector support via the raw ArangoDB API,
since python-arango's high-level methods don't expose vector params yet.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.request import Request

log = logging.getLogger(__name__)

INDEX_NAME = "idx_chunks_embedding_hnsw"
EMBEDDING_DIMENSION = 1536


def up(db: StandardDatabase) -> None:
    col = db.collection("chunks")

    for idx in col.indexes():
        if idx.get("name") == INDEX_NAME:
            log.debug("vector index %s already exists", INDEX_NAME)
            return

    body = {
        "type": "inverted",
        "name": INDEX_NAME,
        "fields": [
            {
                "name": "embedding",
                "aql": False,
            },
        ],
        "params": {
            "vector": {
                "type": "hnsw",
                "dimension": EMBEDDING_DIMENSION,
                "similarity": "cosine",
            },
        },
    }

    try:
        req = Request(
            method="post",
            endpoint="/_api/index",
            params={"collection": "chunks"},
            data=body,
        )
        resp = db._conn.send_request(req)
        if resp.status_code in (200, 201):
            log.info("created vector index %s on chunks.embedding", INDEX_NAME)
        else:
            log.warning(
                "vector index returned %d — RAG will use full-scan fallback",
                resp.status_code,
            )
    except Exception as exc:
        log.warning(
            "vector index not created — RAG will use full-scan fallback: %s", exc,
        )
