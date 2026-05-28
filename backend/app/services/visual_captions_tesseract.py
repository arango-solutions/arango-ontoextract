"""Tesseract OCR caption adapter for Stream 13 visual extraction.

On-prem, zero-API-cost ``VisualCaptionProvider`` that turns one image
asset into a short caption via the open-source `Tesseract OCR engine
<https://github.com/tesseract-ocr/tesseract>`_. The sibling of
``visual_captions_openai`` — together they close the IMG.4 follow-up.

Activates when ``settings.visual_caption_provider == "tesseract"``.
Auto-loaded lazily by ``visual_extraction.get_caption_provider`` so the
default install never imports ``pytesseract`` or probes the host for
the ``tesseract`` binary.

Host dependency (per ``AGENTS.md`` host-deps table):

- macOS:           ``brew install tesseract``
- Debian/Ubuntu:   ``apt install tesseract-ocr``
- Python package:  ``pip install pytesseract`` (and Pillow, which is
  already a transitive dep).

Failure modes (all return ``CaptionResult(success=False, ...)`` so the
caller falls back to placeholder lines and never aborts a run):

- ``missing_package:pytesseract`` -- ``pytesseract`` is not installed.
- ``missing_binary``               -- ``tesseract`` is not on PATH. The
  provider also emits a one-shot ``log.warning`` with the install
  command for the current platform so ops sees the actionable hint.
- ``bad_image:<exception class>``  -- Pillow could not open the bytes
  (corrupted PNG, unsupported codec, etc).
- ``ocr_error:<detail>``           -- ``pytesseract`` raised. Includes
  the exception detail so curators can grep for systemic failures
  (locale problems, language-data missing, etc).
- ``no_text_detected``             -- OCR succeeded but produced zero
  non-empty words above the per-word confidence floor.
"""

from __future__ import annotations

import io
import logging
import platform
import shutil
from typing import Any

from app.services.visual_extraction import (
    CaptionResult,
    VisualCaptionProvider,
    register_caption_provider,
)

log = logging.getLogger(__name__)

#: Captions over this character length get truncated at the nearest
#: word boundary. Tesseract on a full slide can yield several KB of
#: text; we want a *caption*, not a page transcript.
_MAX_CAPTION_CHARS = 240

#: Per-word confidence floor. Tesseract reports confidences in
#: ``[-1, 100]``; ``-1`` means "no word here". We additionally drop
#: words below this threshold so the aggregate confidence is not
#: dragged down by clearly-misrecognised tokens (e.g., noise in
#: image margins).
_MIN_WORD_CONFIDENCE = 30.0


def _install_hint() -> str:
    """Return a platform-specific install command for ``tesseract``."""
    system = platform.system().lower()
    if system == "darwin":
        return "brew install tesseract"
    if system == "linux":
        return "apt install tesseract-ocr  # (or your distro's equivalent)"
    return "see https://github.com/tesseract-ocr/tesseract#installation"


class TesseractCaptionProvider(VisualCaptionProvider):
    """OCR caption adapter backed by Tesseract via ``pytesseract``.

    Probes ``pytesseract`` (Python package) and ``tesseract`` (host
    binary) at *call-time* rather than construction-time so the rest
    of the module still imports on a host that does not have either
    installed. A single missing-binary warning is logged per provider
    instance to keep the noise floor low even on a 25-image deck.
    """

    name = "tesseract"

    def __init__(self) -> None:
        #: One-shot log flag for the missing-binary case. The first
        #: caption call that hits it emits the install hint; later
        #: calls in the same ingestion just return the structured
        #: failure quietly.
        self._missing_binary_logged: bool = False

    def caption(self, image_bytes: bytes, *, mime_type: str = "image/png") -> CaptionResult:
        try:
            # ``pytesseract`` is an optional extra (``pip install -e .[ocr]``).
            # The except clause below tells mypy this import is handled, so
            # the strict-mode missing-stub diagnostic does not fire here.
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            return CaptionResult(
                success=False,
                failure_reason=f"missing_package:{exc.name or 'pytesseract'}",
            )

        binary = shutil.which("tesseract")
        if binary is None:
            if not self._missing_binary_logged:
                log.warning(
                    "tesseract OCR provider selected but the `tesseract` "
                    "binary is not on PATH. Install it with `%s` and "
                    "retry. Ingestion will fall back to placeholders in "
                    "the meantime.",
                    _install_hint(),
                )
                self._missing_binary_logged = True
            return CaptionResult(success=False, failure_reason="missing_binary")

        try:
            img = Image.open(io.BytesIO(image_bytes))
            img.load()
        except Exception as exc:
            return CaptionResult(
                success=False,
                failure_reason=f"bad_image:{type(exc).__name__}",
            )

        try:
            data: dict[str, Any] = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            return CaptionResult(
                success=False,
                failure_reason=f"ocr_error:{type(exc).__name__}: {exc}",
            )

        return _interpret_tesseract_data(data)


def _interpret_tesseract_data(data: dict[str, Any]) -> CaptionResult:
    """Build a caption + aggregate confidence from Tesseract's word-level dict.

    Kept module-private + pure so unit tests can drive it directly with
    stub dicts and never touch the OCR engine.

    Tesseract returns parallel lists keyed by ``"text"`` and ``"conf"``;
    ``conf == -1`` marks the position as "no word", which we drop along
    with words below ``_MIN_WORD_CONFIDENCE``. The remaining tokens
    are space-joined and truncated to a single caption-sized line; the
    confidence is the mean of accepted-word confidences scaled into
    ``[0.0, 1.0]``.
    """
    texts = data.get("text") or []
    confs = data.get("conf") or []

    words: list[str] = []
    accepted_confs: list[float] = []
    for raw_word, raw_conf in zip(texts, confs, strict=False):
        word = (raw_word or "").strip()
        if not word:
            continue
        try:
            ci = float(raw_conf)
        except (TypeError, ValueError):
            continue
        if ci < _MIN_WORD_CONFIDENCE:
            continue
        words.append(word)
        accepted_confs.append(ci)

    if not words:
        return CaptionResult(success=False, failure_reason="no_text_detected")

    text = " ".join(words).strip()
    if len(text) > _MAX_CAPTION_CHARS:
        # Truncate at the last whitespace inside the limit so we never
        # split a token mid-word. Ellipsis signals truncation to the
        # downstream prompt.
        head = text[:_MAX_CAPTION_CHARS]
        cut = head.rsplit(" ", 1)[0] if " " in head else head
        text = f"{cut}…"

    avg_conf = sum(accepted_confs) / len(accepted_confs) / 100.0
    return CaptionResult(success=True, text=text, confidence=avg_conf)


register_caption_provider("tesseract", TesseractCaptionProvider)
