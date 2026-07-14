"""Ontology entity embeddings + vector search (Stream SF.1).

Shared foundation for alignment (Stream 20 candidate retrieval), the A-box
schema retriever (Stream 21), and competency-question term matching (Stream 22).
Embeds ontology classes / properties (``label`` + ``description``, optionally an
LLM-generated natural-language ``definition`` behind
``settings.ontology_embedding_enrich_definitions``) and stores the vector on the
entity so ArangoDB vector search can retrieve nearest neighbours across
ontologies.

The embedding is a **derived** field: it is written directly with
``collection.update`` (NOT via the temporal versioning path), because it is
index-support metadata, not curatable content — re-embedding must not spawn a
temporal version.

Following the ``chunks.embedding`` precedent (``tasks._ensure_vector_index``),
the FAISS-IVF vector index is created **at runtime after embeddings exist**
(the index needs training points), not at migration time. :func:`embed_ontology_entities`
populates embeddings; :func:`ensure_entity_vector_index` creates the index; keep
them separate so population is unit-testable without a live vector index.
"""

from __future__ import annotations

import logging
import math
from typing import Any, cast

from arango.database import StandardDatabase

from app.config import settings
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.embedding import embed_texts

log = logging.getLogger(__name__)

# Matches the chunk embedding dimension (text-embedding-3-small).
EMBEDDING_DIMENSION = 1536

# The ontology entity collections we embed + index, in the ADR-006 PGT split.
DEFAULT_EMBED_COLLECTIONS: tuple[str, ...] = (
    "ontology_classes",
    "ontology_object_properties",
    "ontology_datatype_properties",
)


def build_entity_text(entity: dict[str, Any]) -> str:
    """Build the text to embed for one ontology entity.

    ``label`` carries the most signal; ``description`` disambiguates;
    ``definition`` (an optional LLM-generated natural-language gloss, GenOM-style)
    is appended when present. Returns ``""`` when the entity has no usable text
    so the caller can skip it (embedding an empty string is meaningless).
    """
    parts = [
        str(entity.get("label") or "").strip(),
        str(entity.get("description") or "").strip(),
    ]
    if settings.ontology_embedding_enrich_definitions:
        parts.append(str(entity.get("definition") or "").strip())
    return " — ".join(p for p in parts if p)


async def embed_ontology_entities(
    db: StandardDatabase,
    ontology_id: str,
    *,
    collections: tuple[str, ...] = DEFAULT_EMBED_COLLECTIONS,
    model: str | None = None,
    only_missing: bool = True,
) -> dict[str, int]:
    """Embed an ontology's live entities and store the vectors on them.

    Returns a per-collection count of entities embedded. ``only_missing`` (the
    default) skips entities that already carry an embedding, so re-running is
    cheap and idempotent. Missing collections contribute 0 (fresh databases).
    Does NOT create the vector index — call :func:`ensure_entity_vector_index`
    afterwards once embeddings exist.
    """
    counts: dict[str, int] = {}
    for name in collections:
        if not db.has_collection(name):
            counts[name] = 0
            continue

        rows = list(
            run_aql(
                db,
                f"""
                FOR e IN {name}
                  FILTER e.ontology_id == @oid AND e.expired == @never
                  RETURN {{
                    _key: e._key,
                    label: e.label,
                    description: e.description,
                    definition: e.definition,
                    has_embedding: (e.embedding != null AND e.embedding != [])
                  }}
                """,
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

        targets: list[dict[str, Any]] = []
        texts: list[str] = []
        for row in rows:
            if only_missing and row.get("has_embedding"):
                continue
            text = build_entity_text(row)
            if not text:
                continue
            targets.append(row)
            texts.append(text)

        if not texts:
            counts[name] = 0
            continue

        embeddings = await embed_texts(texts, model=model)
        col = db.collection(name)
        n = 0
        for row, emb in zip(targets, embeddings, strict=False):
            if not emb:
                continue
            col.update({"_key": row["_key"], "embedding": emb})
            n += 1
        counts[name] = n
        log.info("[ontology_embeddings] %s: embedded %d entities (ont=%s)", name, n, ontology_id)

    return counts


def _vector_index_name(collection: str) -> str:
    return f"idx_{collection}_embedding_vector"


def ensure_entity_vector_index(db: StandardDatabase, collection: str) -> bool:
    """Create the FAISS-IVF vector index on ``<collection>.embedding`` if absent.

    Must run AFTER embeddings are populated (the index trains on existing
    vectors). Returns True if the index exists (created now or already present),
    False if the collection is missing or has no embedded documents to train on.
    Mirrors ``tasks._ensure_vector_index`` (chunks).
    """
    if not db.has_collection(collection):
        return False

    col = db.collection(collection)
    index_name = _vector_index_name(collection)
    for idx in cast("list[dict[str, Any]]", col.indexes()):
        if idx.get("name") == index_name:
            return True  # already exists

    # Count only embedded docs — the index trains on them, and nLists cannot
    # exceed the number of training points.
    trained = list(
        run_aql(
            db,
            f"FOR e IN {collection} FILTER e.embedding != null COLLECT WITH COUNT INTO n RETURN n",
        )
    )
    n_docs = int(trained[0]) if trained else 0
    if n_docs < 1:
        log.info("[ontology_embeddings] %s: no embedded docs; skip index", collection)
        return False

    from arango.request import Request

    n_lists = min(max(1, int(math.sqrt(n_docs) * 15)), n_docs)
    n_probe = max(1, int(math.sqrt(n_lists)))
    body = {
        "type": "vector",
        "name": index_name,
        "fields": ["embedding"],
        "params": {
            "metric": "cosine",
            "dimension": EMBEDDING_DIMENSION,
            "nLists": n_lists,
            "defaultNProbe": n_probe,
            "trainingIterations": 25,
        },
    }
    req = Request(
        method="post",
        endpoint="/_api/index",
        params={"collection": collection},
        data=body,
    )
    db._conn.send_request(req)
    log.info(
        "[ontology_embeddings] %s: created vector index (docs=%d, nLists=%d)",
        collection,
        n_docs,
        n_lists,
    )
    return True


def search_similar(
    db: StandardDatabase,
    collection: str,
    query_embedding: list[float],
    *,
    k: int = 10,
) -> list[dict[str, Any]]:
    """Return up to ``k`` nearest entities in ``collection`` by cosine.

    Uses ArangoDB's ``APPROX_NEAR_COSINE`` over the vector index. Source-filtering
    (e.g. "exclude the query's own ontology" for cross-ontology alignment) is the
    caller's responsibility — fetch a larger ``k`` and filter — because the
    vector-search loop does not compose with an arbitrary pre-FILTER. Returns
    ``[]`` when the collection is missing or the query vector is empty.
    """
    if not query_embedding or not db.has_collection(collection):
        return []
    return list(
        run_aql(
            db,
            f"""
            FOR e IN {collection}
              SORT APPROX_NEAR_COSINE(e.embedding, @q) DESC
              LIMIT @k
              RETURN {{
                _key: e._key,
                ontology_id: e.ontology_id,
                label: e.label,
                score: APPROX_NEAR_COSINE(e.embedding, @q)
              }}
            """,
            bind_vars={"q": query_embedding, "k": int(k)},
        )
    )
