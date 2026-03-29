"""Vector embedding service using OpenAI's embedding API.

Supports configurable model (via ``settings.embedding_model``) and batching.
"""

from __future__ import annotations

import logging
import time

from openai import OpenAI

from app.config import settings

log = logging.getLogger(__name__)

_BATCH_SIZE = 100
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0


def _get_client() -> OpenAI:
    kwargs: dict = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    batch_size: int = _BATCH_SIZE,
) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    Batches requests in groups of ``batch_size`` and retries with exponential
    backoff on rate-limit errors.
    """
    model = model or settings.embedding_model
    client = _get_client()
    all_embeddings: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings = _embed_batch(client, batch, model)
        all_embeddings.extend(embeddings)

    return all_embeddings


def _embed_batch(
    client: OpenAI,
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """Embed a single batch with retry + exponential backoff."""
    backoff = _INITIAL_BACKOFF
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.embeddings.create(input=texts, model=model)
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]
        except Exception as exc:
            is_rate_limit = "rate" in str(exc).lower() or "429" in str(exc)
            if attempt < _MAX_RETRIES - 1 and is_rate_limit:
                log.warning(
                    "rate limited, retrying",
                    extra={"attempt": attempt + 1, "backoff_s": backoff},
                )
                time.sleep(backoff)
                backoff *= 2
            else:
                raise

    raise RuntimeError("Exhausted retries for embedding batch")
