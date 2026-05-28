"""Unit tests for the Tesseract OCR caption adapter (Stream 13 IMG.4 follow-up).

Both ``pytesseract`` and the ``tesseract`` host binary are fully
isolated here -- no real OCR is invoked. Tests cover:

- Pure ``_interpret_tesseract_data`` helper: empty / all-noise input,
  successful word join, sub-threshold word filtering, truncation,
  confidence aggregation.
- Provider: missing-binary path emits a one-shot install-hint warning,
  missing-package path returns structured failure, end-to-end caption
  with mocked ``pytesseract``, malformed image / OCR error paths.
- Lazy registration via ``get_caption_provider("tesseract")``.
- ``_install_hint`` picks a platform-specific command.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from app.services.visual_extraction import (
    _LAZY_PROVIDERS,
    _PROVIDERS,
    NoOpCaptionProvider,
    get_caption_provider,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_adapter_module():
    """Drop the adapter module + registry entry between tests."""
    module_name = "app.services.visual_captions_tesseract"
    sys.modules.pop(module_name, None)
    _PROVIDERS.pop("tesseract", None)
    yield
    sys.modules.pop(module_name, None)
    _PROVIDERS.pop("tesseract", None)


# Minimal real PNG (1x1 transparent) -- bytes go to mocked Pillow, which
# we patch out, so the content does not actually have to decode.
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# ---------------------------------------------------------------------------
# _interpret_tesseract_data: pure-function tests
# ---------------------------------------------------------------------------
class TestInterpretTesseractData:
    def test_returns_no_text_detected_on_empty_dict(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        result = _interpret_tesseract_data({})
        assert result.success is False
        assert result.failure_reason == "no_text_detected"

    def test_returns_no_text_detected_on_all_neg_conf(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        data = {"text": ["", "", ""], "conf": [-1, -1, -1]}
        assert _interpret_tesseract_data(data).failure_reason == "no_text_detected"

    def test_drops_sub_threshold_words(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        data = {
            "text": ["Vehicle", "noisy", "Taxonomy"],
            "conf": [95, 5, 88],  # 5 < _MIN_WORD_CONFIDENCE (30)
        }
        result = _interpret_tesseract_data(data)
        assert result.success is True
        assert result.text == "Vehicle Taxonomy"
        # Aggregate confidence comes from accepted words only.
        assert result.confidence == pytest.approx((95 + 88) / 2 / 100.0)

    def test_drops_negative_one_sentinel(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        data = {
            "text": ["Car", "", "Truck"],
            "conf": [80, -1, 70],
        }
        result = _interpret_tesseract_data(data)
        assert result.success is True
        assert result.text == "Car Truck"

    def test_ignores_unparseable_confidence(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        data = {
            "text": ["Hello", "World"],
            "conf": ["??", 90],
        }
        result = _interpret_tesseract_data(data)
        assert result.success is True
        assert result.text == "World"

    def test_truncates_long_text_at_word_boundary(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import (
            _MAX_CAPTION_CHARS,
            _interpret_tesseract_data,
        )

        words = ["alpha"] * 200  # 200 * 5 + 199 spaces = 1199 chars
        data = {"text": words, "conf": [80] * 200}
        result = _interpret_tesseract_data(data)
        assert result.success is True
        # Truncated and ends with the ellipsis sentinel.
        assert result.text.endswith("…")
        # Never exceeds the budget (the head is bounded; only the
        # ellipsis adds a single char).
        assert len(result.text) <= _MAX_CAPTION_CHARS + 1
        # Last token is not a partial word.
        assert " alph…" not in result.text  # cut at last space

    def test_zip_handles_mismatched_lengths(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import _interpret_tesseract_data

        # Tesseract should never do this, but the helper should be
        # defensive -- using zip(..., strict=False) per design.
        data = {"text": ["only-text"], "conf": []}
        # No conf -> zip yields nothing -> no_text_detected.
        assert _interpret_tesseract_data(data).failure_reason == "no_text_detected"


# ---------------------------------------------------------------------------
# _install_hint: platform-specific install string
# ---------------------------------------------------------------------------
class TestInstallHint:
    def test_macos_returns_brew(self, fresh_adapter_module):
        from app.services import visual_captions_tesseract as mod

        with patch.object(mod.platform, "system", return_value="Darwin"):
            assert mod._install_hint() == "brew install tesseract"

    def test_linux_returns_apt(self, fresh_adapter_module):
        from app.services import visual_captions_tesseract as mod

        with patch.object(mod.platform, "system", return_value="Linux"):
            assert "apt install tesseract-ocr" in mod._install_hint()

    def test_other_platform_returns_url(self, fresh_adapter_module):
        from app.services import visual_captions_tesseract as mod

        with patch.object(mod.platform, "system", return_value="Windows"):
            assert "github.com/tesseract-ocr" in mod._install_hint()


# ---------------------------------------------------------------------------
# Provider end-to-end with mocked pytesseract + Pillow
# ---------------------------------------------------------------------------
class TestProviderCaption:
    def test_missing_binary_returns_structured_failure_and_logs_once(
        self, fresh_adapter_module, caplog
    ):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        # Stub pytesseract + PIL so the package-import probe inside
        # ``caption()`` passes; the missing-binary check is what we are
        # actually exercising here.
        with (
            patch(
                "app.services.visual_captions_tesseract.shutil.which",
                return_value=None,
            ),
            patch.dict(
                sys.modules,
                {
                    "pytesseract": _build_fake_pytesseract(text=[], conf=[]),
                    "PIL": _build_fake_pil(),
                },
            ),
        ):
            provider = TesseractCaptionProvider()
            r1 = provider.caption(_FAKE_PNG)
            r2 = provider.caption(_FAKE_PNG)

        assert r1.success is False
        assert r1.failure_reason == "missing_binary"
        assert r2.failure_reason == "missing_binary"
        # The actionable install hint is logged exactly once per
        # provider instance even though we called caption() twice.
        install_warnings = [rec for rec in caplog.records if "tesseract" in rec.message.lower()]
        assert any("install" in rec.message.lower() for rec in install_warnings)
        # And only once (not duplicated on the second call).
        assert len(install_warnings) == 1
        assert provider._missing_binary_logged is True

    def test_missing_package_returns_structured_failure(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        provider = TesseractCaptionProvider()

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pytesseract":
                raise ImportError("No module named 'pytesseract'", name="pytesseract")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = provider.caption(_FAKE_PNG)

        assert result.success is False
        assert result.failure_reason == "missing_package:pytesseract"

    def test_successful_caption_round_trip(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        with (
            patch(
                "app.services.visual_captions_tesseract.shutil.which",
                return_value="/usr/local/bin/tesseract",
            ),
            patch.dict(
                sys.modules,
                {
                    "pytesseract": _build_fake_pytesseract(
                        text=["Vehicle", "Taxonomy"], conf=[92, 88]
                    ),
                    "PIL": _build_fake_pil(),
                },
            ),
        ):
            provider = TesseractCaptionProvider()
            result = provider.caption(_FAKE_PNG, mime_type="image/png")

        assert result.success is True
        assert result.text == "Vehicle Taxonomy"
        assert result.confidence == pytest.approx(0.90)

    def test_bad_image_returns_structured_failure(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        with (
            patch(
                "app.services.visual_captions_tesseract.shutil.which",
                return_value="/usr/local/bin/tesseract",
            ),
            patch.dict(
                sys.modules,
                {
                    "pytesseract": _build_fake_pytesseract(text=[], conf=[]),
                    "PIL": _build_fake_pil(open_exception=OSError("cannot identify image file")),
                },
            ),
        ):
            result = TesseractCaptionProvider().caption(b"not-a-real-image")

        assert result.success is False
        assert result.failure_reason.startswith("bad_image:")
        assert "OSError" in result.failure_reason

    def test_ocr_error_returns_structured_failure(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        with (
            patch(
                "app.services.visual_captions_tesseract.shutil.which",
                return_value="/usr/local/bin/tesseract",
            ),
            patch.dict(
                sys.modules,
                {
                    "pytesseract": _build_fake_pytesseract(
                        ocr_exception=RuntimeError("language data missing")
                    ),
                    "PIL": _build_fake_pil(),
                },
            ),
        ):
            result = TesseractCaptionProvider().caption(_FAKE_PNG)

        assert result.success is False
        assert result.failure_reason.startswith("ocr_error:")
        assert "language data missing" in result.failure_reason

    def test_no_text_detected_when_ocr_returns_empty(self, fresh_adapter_module):
        from app.services.visual_captions_tesseract import TesseractCaptionProvider

        with (
            patch(
                "app.services.visual_captions_tesseract.shutil.which",
                return_value="/usr/local/bin/tesseract",
            ),
            patch.dict(
                sys.modules,
                {
                    "pytesseract": _build_fake_pytesseract(text=[""], conf=[-1]),
                    "PIL": _build_fake_pil(),
                },
            ),
        ):
            result = TesseractCaptionProvider().caption(_FAKE_PNG)

        assert result.success is False
        assert result.failure_reason == "no_text_detected"


# ---------------------------------------------------------------------------
# Lazy registration
# ---------------------------------------------------------------------------
class TestLazyRegistration:
    def test_tesseract_is_known_lazy_provider(self):
        assert "tesseract" in _LAZY_PROVIDERS

    def test_lazy_load_registers_and_returns_instance(self, fresh_adapter_module):
        assert "tesseract" not in _PROVIDERS
        provider = get_caption_provider("tesseract")
        assert "tesseract" in _PROVIDERS
        assert provider.__class__.__name__ == "TesseractCaptionProvider"

    def test_lazy_load_failure_falls_back_to_noop(self, fresh_adapter_module, monkeypatch, caplog):
        monkeypatch.setitem(_LAZY_PROVIDERS, "tesseract", "app.services.does_not_exist")
        provider = get_caption_provider("tesseract")
        assert isinstance(provider, NoOpCaptionProvider)


# ---------------------------------------------------------------------------
# Helpers: build stubs that look enough like pytesseract / PIL.Image
# ---------------------------------------------------------------------------
def _build_fake_pytesseract(
    *,
    text: list[str] | None = None,
    conf: list[float] | None = None,
    ocr_exception: Exception | None = None,
):
    """Construct a stub ``pytesseract`` module for ``sys.modules`` patching."""
    import types

    mod = types.ModuleType("pytesseract")
    output = types.SimpleNamespace(DICT="dict")
    mod.Output = output  # type: ignore[attr-defined]

    def image_to_data(_img, output_type=None):
        if ocr_exception is not None:
            raise ocr_exception
        return {"text": text or [], "conf": conf or []}

    mod.image_to_data = image_to_data  # type: ignore[attr-defined]
    return mod


def _build_fake_pil(*, open_exception: Exception | None = None):
    """Construct a stub ``PIL`` package (with ``Image.open``)."""
    import types

    pil_pkg = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")

    class _FakeImage:
        def load(self) -> None:
            return None

    def open_(_buf):
        if open_exception is not None:
            raise open_exception
        return _FakeImage()

    image_mod.open = open_  # type: ignore[attr-defined]
    pil_pkg.Image = image_mod  # type: ignore[attr-defined]
    # Register the submodule so ``from PIL import Image`` works.
    sys.modules["PIL.Image"] = image_mod
    return pil_pkg
