"""OpenAI Vision caption adapter for Stream 13 visual extraction.

Concrete ``VisualCaptionProvider`` that turns a single image asset into
a short caption via OpenAI's chat-completions vision API. Closes the
IMG.4 follow-up that left the adapter boundary unwired.

Activated when ``settings.visual_caption_provider == "openai_vision"``.
Auto-loaded lazily by ``visual_extraction.get_caption_provider`` so the
default install does not import the OpenAI SDK on every ingestion.

Failure modes (all return ``CaptionResult(success=False, ...)`` so the
caller falls back to placeholder lines and never aborts a run):

- ``missing_api_key`` -- ``settings.openai_api_key`` is empty.
- ``api_error:<detail>`` -- network / quota / 5xx error after retries.
- ``malformed_response`` -- choices/message shape was unexpected.
- ``empty_caption`` -- model returned an empty string.
- ``no_recognizable_content`` -- model declined to caption (an opaque,
  text-free image such as a blank slide background).

The sync ``OpenAI`` client is used deliberately: ``parse_pptx`` runs
inside ``asyncio.to_thread`` in ``tasks.process_document``, so the
synchronous I/O here runs on a worker thread and does not stall the
asyncio event loop.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from openai import OpenAI

from app.config import settings
from app.services.visual_extraction import (
    CaptionResult,
    VisualCaptionProvider,
    register_caption_provider,
)

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0
_REQUEST_TIMEOUT = 30.0
_MAX_CAPTION_TOKENS = 150

#: Confidence reported on a successful caption. Vision chat-completions
#: do not expose calibrated confidence, so we pick a deliberately
#: middling value: high enough that the visual-aware prompt may cite
#: the caption as ``parent_evidence``, low enough that downstream
#: consensus weighting does not treat it like ground truth (the
#: visual-aware prompt also caps caption-only evidence at 0.7).
_DEFAULT_CONFIDENCE = 0.6

_PROMPT = (
    "You are captioning a single image extracted from a presentation deck or "
    "scanned report for an ontology-extraction system. Produce ONE concise "
    "caption (max 30 words) describing:\n"
    "1. Any text or labels visible in the image.\n"
    "2. Structural relationships (taxonomy, hierarchy, flow, list).\n"
    "3. Domain entities depicted (e.g., 'Customer', 'Account', 'Transaction').\n"
    "If the image contains no recognizable content, reply with exactly "
    "'no_recognizable_content'. Do not hallucinate."
)


class OpenAIVisionCaptionProvider(VisualCaptionProvider):
    """Vision-caption adapter backed by OpenAI chat-completions.

    Configuration (all read from :mod:`app.config.settings`):

    - ``openai_api_key`` -- required; provider returns ``missing_api_key``
      until set rather than raising at construction time.
    - ``openai_base_url`` -- optional; respected for OpenAI-compatible
      gateways (OpenRouter, etc).
    - ``visual_caption_openai_model`` -- vision-capable chat model id;
      defaults to ``gpt-4o-mini``.

    Retries on any transport-level exception with exponential backoff
    (``_MAX_RETRIES`` attempts, ``_INITIAL_BACKOFF``-doubled). A single
    failed image never aborts ingestion -- the upstream caller treats
    ``success=False`` as a fallback signal.
    """

    name = "openai_vision"

    def __init__(self) -> None:
        self._model: str = getattr(settings, "visual_caption_openai_model", _DEFAULT_MODEL)
        self._client: OpenAI | None = None
        if not settings.openai_api_key:
            log.warning(
                "openai_vision provider selected but openai_api_key is empty; "
                "every caption call will report missing_api_key and ingestion "
                "will fall back to placeholders"
            )
            return
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "timeout": _REQUEST_TIMEOUT,
        }
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self._client = OpenAI(**kwargs)

    def caption(self, image_bytes: bytes, *, mime_type: str = "image/png") -> CaptionResult:
        if self._client is None:
            return CaptionResult(success=False, failure_reason="missing_api_key")

        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"

        backoff = _INITIAL_BACKOFF
        last_error: str | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": _PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url},
                                },
                            ],
                        }
                    ],
                    max_tokens=_MAX_CAPTION_TOKENS,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "openai_vision caption attempt %d/%d failed: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    last_error,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
                continue

            return _interpret_response(response)

        return CaptionResult(
            success=False,
            failure_reason=f"api_error:{last_error or 'unknown'}",
        )


def _interpret_response(response: Any) -> CaptionResult:
    """Pull the caption text out of a chat-completions response.

    Kept module-private + side-effect-free so the test suite can drive
    it directly with stub response objects without touching the OpenAI
    client at all.
    """
    try:
        content = (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        return CaptionResult(success=False, failure_reason="malformed_response")

    if not content:
        return CaptionResult(success=False, failure_reason="empty_caption")
    if content.lower() == "no_recognizable_content":
        return CaptionResult(success=False, failure_reason="no_recognizable_content")
    return CaptionResult(success=True, text=content, confidence=_DEFAULT_CONFIDENCE)


register_caption_provider("openai_vision", OpenAIVisionCaptionProvider)
