"""Vector embedding service using OpenAI's embedding API.

Supports configurable model (via ``settings.embedding_model``) and batching.
Uses async client with concurrent requests capped by a semaphore.
Batches are constructed dynamically to stay under the 300K token-per-request limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import tiktoken
from openai import AsyncOpenAI

from app.config import settings

log = logging.getLogger(__name__)

# OpenAI enforces 300K total tokens per embedding request.
# OpenRouter silently returns empty data for large batches, so we also
# cap the number of inputs per batch as a safeguard.
_MAX_TOKENS_PER_REQUEST = 200_000
_MAX_INPUTS_PER_BATCH = 200
_MAX_CONCURRENCY = 100
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0
_TIKTOKEN_MODEL = "cl100k_base"


def _get_client() -> AsyncOpenAI:
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key, "timeout": 20.0}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return AsyncOpenAI(**kwargs)


def _build_batches(
    texts: list[str],
    max_tokens: int = _MAX_TOKENS_PER_REQUEST,
    max_inputs: int = _MAX_INPUTS_PER_BATCH,
) -> list[list[str]]:
    """Pack texts into batches dynamically, respecting both token and input limits."""
    enc = tiktoken.get_encoding(_TIKTOKEN_MODEL)
    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_tokens = 0

    for text in texts:
        token_count = len(enc.encode(text))
        if current_batch and (
            current_tokens + token_count > max_tokens or len(current_batch) >= max_inputs
        ):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(text)
        current_tokens += token_count

    if current_batch:
        batches.append(current_batch)

    return batches


async def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
) -> list[list[float]]:
    """Generate embeddings for a list of texts concurrently.

    Packs texts into token-aware batches (up to 300K tokens each),
    then fires up to ``_MAX_CONCURRENCY`` API calls in parallel.
    """
    if not texts:
        return []

    model = model or settings.embedding_model
    client = _get_client()
    batches = _build_batches(texts)
    log.info(
        "[embedding] starting: texts=%d, batches=%d, concurrency=%d, model=%s",
        len(texts),
        len(batches),
        _MAX_CONCURRENCY,
        model,
    )

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _do_batch(batch_num: int, batch: list[str]) -> list[list[float]]:
        async with semaphore:
            log.info("[embedding] batch %d/%d: %d texts", batch_num, len(batches), len(batch))
            result = await _embed_batch(client, batch, model)
            log.info("[embedding] batch %d/%d done", batch_num, len(batches))
            return result

    tasks = [_do_batch(i + 1, batch) for i, batch in enumerate(batches)]
    batch_results = await asyncio.gather(*tasks)

    all_embeddings: list[list[float]] = []
    for result in batch_results:
        all_embeddings.extend(result)

    log.info("[embedding] complete: %d embeddings", len(all_embeddings))
    return all_embeddings


async def _embed_batch(
    client: AsyncOpenAI,
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """Embed a single batch with retry on any error (up to 3 attempts)."""
    backoff = _INITIAL_BACKOFF
    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.embeddings.create(input=texts, model=model)
            if not response.data:
                raise ValueError(f"No embedding data received (texts={len(texts)}, model={model})")
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]
        except Exception as exc:
            log.error(
                "[embedding] API call failed attempt %d/%d: %s: %s",
                attempt + 1,
                _MAX_RETRIES,
                type(exc).__name__,
                exc,
            )
            if attempt < _MAX_RETRIES - 1:
                log.warning("[embedding] retrying in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                raise

    raise RuntimeError("Exhausted retries for embedding batch")
