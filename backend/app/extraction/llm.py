"""Shared LLM client factory for extraction-pipeline nodes.

Both the multi-pass extractor and the Stream 16 domain-segmenter need a
provider-agnostic chat model built from ``Settings``. Keeping the factory
here (rather than private to ``extractor.py``) means new nodes reuse the
same provider selection, timeout, and base-url handling instead of
copy-pasting it -- the single source of truth for "how this project talks
to an LLM during extraction".
"""

from __future__ import annotations

from typing import Any

from app.config import settings


def get_chat_model(model_name: str, *, max_tokens: int = 4096) -> Any:
    """Instantiate a LangChain chat model for ``model_name``.

    Anthropic models (name contains ``claude``/``anthropic``) build a
    ``ChatAnthropic``; everything else builds a ``ChatOpenAI`` (honoring
    ``settings.openai_base_url`` for OpenAI-compatible gateways). Both
    receive ``timeout=settings.llm_request_timeout_seconds`` so a hung
    provider connection raises after the configured ceiling instead of
    pinning an asyncio task forever (see the timeout incident history on
    ``Settings.llm_request_timeout_seconds``).
    """
    timeout = settings.llm_request_timeout_seconds
    lowered = model_name.lower()
    if "claude" in lowered or "anthropic" in lowered:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,  # type: ignore[call-arg]
            api_key=settings.anthropic_api_key,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            timeout=timeout,
        )
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": settings.openai_api_key,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)
