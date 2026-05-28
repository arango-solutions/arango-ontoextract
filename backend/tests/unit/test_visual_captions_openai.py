"""Unit tests for the OpenAI Vision caption adapter (Stream 13 IMG.4 follow-up).

The OpenAI SDK is fully mocked here -- no network calls. Tests cover:

- Successful caption returned and trimmed.
- ``no_recognizable_content`` sentinel mapped to a structured failure.
- Empty content mapped to ``empty_caption``.
- Malformed response object mapped to ``malformed_response``.
- Transport-level exception retries N times, then surfaces ``api_error:...``.
- Missing ``openai_api_key`` short-circuits with ``missing_api_key``.
- Lazy-loading via ``get_caption_provider("openai_vision")`` works even
  when the adapter module has not been imported yet.
- ``settings.visual_caption_openai_model`` flows into the API call.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.visual_extraction import (
    _LAZY_PROVIDERS,
    _PROVIDERS,
    NoOpCaptionProvider,
    get_caption_provider,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _make_completion(text: str | None) -> SimpleNamespace:
    """Build a stub object shaped like an OpenAI ChatCompletion."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture
def fresh_adapter_module():
    """Ensure the adapter module is freshly imported per test.

    The module registers itself in ``_PROVIDERS`` on import; we drop both
    the module and the registry entry after each test so we can assert on
    the lazy-loading code path repeatedly.
    """
    module_name = "app.services.visual_captions_openai"
    sys.modules.pop(module_name, None)
    _PROVIDERS.pop("openai_vision", None)
    yield
    sys.modules.pop(module_name, None)
    _PROVIDERS.pop("openai_vision", None)


@pytest.fixture
def api_key_set(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_base_url", "")
    monkeypatch.setattr(settings, "visual_caption_openai_model", "gpt-4o-mini")
    yield settings


# ---------------------------------------------------------------------------
# _interpret_response: pure helper tests
# ---------------------------------------------------------------------------
class TestInterpretResponse:
    def test_returns_success_on_valid_caption(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(_make_completion("  A taxonomy of accounts.  "))
        assert result.success is True
        assert result.text == "A taxonomy of accounts."
        assert result.confidence is not None and 0.0 < result.confidence < 1.0

    def test_returns_failure_on_sentinel(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(_make_completion("no_recognizable_content"))
        assert result.success is False
        assert result.failure_reason == "no_recognizable_content"

    def test_sentinel_match_is_case_insensitive(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(_make_completion("No_Recognizable_Content"))
        assert result.success is False
        assert result.failure_reason == "no_recognizable_content"

    def test_returns_failure_on_empty(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(_make_completion(""))
        assert result.success is False
        assert result.failure_reason == "empty_caption"

    def test_returns_failure_on_none_content(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(_make_completion(None))
        assert result.success is False
        assert result.failure_reason == "empty_caption"

    def test_returns_failure_on_malformed_response(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        # Object missing the expected choices/message structure.
        bad = SimpleNamespace(choices=[])
        result = _interpret_response(bad)
        assert result.success is False
        assert result.failure_reason == "malformed_response"

    def test_returns_failure_when_response_is_completely_wrong_shape(self, fresh_adapter_module):
        from app.services.visual_captions_openai import _interpret_response

        result = _interpret_response(object())
        assert result.success is False
        assert result.failure_reason == "malformed_response"


# ---------------------------------------------------------------------------
# Provider construction + caption() integration with mocked OpenAI client
# ---------------------------------------------------------------------------
class TestProviderConstruction:
    def test_missing_api_key_returns_structured_failure(self, fresh_adapter_module, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "")

        from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

        provider = OpenAIVisionCaptionProvider()
        result = provider.caption(b"\x89PNG\r\n")
        assert result.success is False
        assert result.failure_reason == "missing_api_key"

    def test_base_url_is_passed_through(self, fresh_adapter_module, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "openai_base_url", "https://router.example/v1")

        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

            OpenAIVisionCaptionProvider()

        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["api_key"] == "sk-x"
        assert kwargs["base_url"] == "https://router.example/v1"
        assert kwargs["timeout"] > 0


class TestProviderCaption:
    def test_successful_caption_round_trip(self, fresh_adapter_module, api_key_set):
        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_completion(
                "Vehicle taxonomy diagram."
            )
            mock_client_cls.return_value = mock_client

            from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

            provider = OpenAIVisionCaptionProvider()
            result = provider.caption(b"fake-png-bytes", mime_type="image/png")

        assert result.success is True
        assert result.text == "Vehicle taxonomy diagram."
        assert result.confidence is not None

        # The request must include both a text part and an image_url part,
        # and the image_url must be a base64 data URL with the right mime.
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        parts = call_kwargs["messages"][0]["content"]
        assert any(p["type"] == "text" for p in parts)
        image_part = next(p for p in parts if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")

    def test_mime_type_threads_through_to_data_url(self, fresh_adapter_module, api_key_set):
        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_completion("x")
            mock_client_cls.return_value = mock_client

            from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

            OpenAIVisionCaptionProvider().caption(b"jpg-bytes", mime_type="image/jpeg")

        parts = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        image_part = next(p for p in parts if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_custom_model_is_used(self, fresh_adapter_module, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "openai_base_url", "")
        monkeypatch.setattr(settings, "visual_caption_openai_model", "gpt-4o")

        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _make_completion("ok")
            mock_client_cls.return_value = mock_client

            from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

            OpenAIVisionCaptionProvider().caption(b"img")

        assert mock_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"

    def test_transport_exception_retries_then_surfaces_api_error(
        self, fresh_adapter_module, api_key_set, monkeypatch
    ):
        # Eliminate sleep delay so the test is fast.
        monkeypatch.setattr("app.services.visual_captions_openai.time.sleep", lambda _s: None)

        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError(
                "simulated network error"
            )
            mock_client_cls.return_value = mock_client

            from app.services.visual_captions_openai import (
                _MAX_RETRIES,
                OpenAIVisionCaptionProvider,
            )

            provider = OpenAIVisionCaptionProvider()
            result = provider.caption(b"img")

        assert result.success is False
        assert result.failure_reason.startswith("api_error:")
        assert "simulated network error" in result.failure_reason
        # Each attempt must have been made.
        assert mock_client.chat.completions.create.call_count == _MAX_RETRIES

    def test_retry_then_success(self, fresh_adapter_module, api_key_set, monkeypatch):
        monkeypatch.setattr("app.services.visual_captions_openai.time.sleep", lambda _s: None)

        with patch("app.services.visual_captions_openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = [
                RuntimeError("flaky"),
                _make_completion("Recovered on retry."),
            ]
            mock_client_cls.return_value = mock_client

            from app.services.visual_captions_openai import OpenAIVisionCaptionProvider

            result = OpenAIVisionCaptionProvider().caption(b"img")

        assert result.success is True
        assert result.text == "Recovered on retry."
        assert mock_client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# Lazy registration via get_caption_provider
# ---------------------------------------------------------------------------
class TestLazyRegistration:
    def test_openai_vision_is_known_lazy_provider(self):
        assert "openai_vision" in _LAZY_PROVIDERS

    def test_lazy_load_registers_and_returns_instance(self, fresh_adapter_module, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-x")

        assert "openai_vision" not in _PROVIDERS

        provider = get_caption_provider("openai_vision")

        # After the lookup the module has been imported and the
        # provider is permanently registered for the remainder of the
        # fixture's lifetime.
        assert "openai_vision" in _PROVIDERS
        assert provider.__class__.__name__ == "OpenAIVisionCaptionProvider"

    def test_lazy_load_failure_falls_back_to_noop(self, fresh_adapter_module, monkeypatch, caplog):
        # Point the lazy entry at a non-existent module so importlib raises.
        monkeypatch.setitem(_LAZY_PROVIDERS, "openai_vision", "app.services.does_not_exist")

        provider = get_caption_provider("openai_vision")
        assert isinstance(provider, NoOpCaptionProvider)
        assert any(
            "failed to load visual caption provider" in rec.message for rec in caplog.records
        )

    def test_unknown_provider_still_warns(self, fresh_adapter_module, caplog):
        provider = get_caption_provider("tesseract")  # not registered, not lazy
        assert isinstance(provider, NoOpCaptionProvider)
        assert any("unknown visual caption provider" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Module-level registration side effect
# ---------------------------------------------------------------------------
class TestImportSideEffect:
    def test_importing_module_registers_provider(self, fresh_adapter_module):
        assert "openai_vision" not in _PROVIDERS
        importlib.import_module("app.services.visual_captions_openai")
        assert "openai_vision" in _PROVIDERS
