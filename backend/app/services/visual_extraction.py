"""Visual asset inventory and placeholder helpers for document ingestion.

Stream 13 (IMG.1-IMG.4): track embedded images/charts in PPTX and PDF,
emit labeled placeholders when OCR/vision is not configured, expose
diagnostics for document metadata and downstream orphan-risk warnings,
and define a provider boundary for OCR / multimodal caption adapters.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

VisualAssetType = Literal["picture", "chart", "image_block"]
VisualExtractionMethod = Literal["placeholder", "alt_text", "ocr", "vision_caption"]

# python-pptx MSO_SHAPE_TYPE values we care about (avoid importing enum at module load).
_PPTX_SHAPE_GROUP = 6
_PPTX_SHAPE_CHART = 3
_PPTX_SHAPE_PICTURE = 13


@dataclass
class VisualAsset:
    page_number: int
    asset_index: int
    asset_type: VisualAssetType
    method: VisualExtractionMethod = "placeholder"
    alt_text: str | None = None
    confidence: float | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "page_number": self.page_number,
            "asset_index": self.asset_index,
            "asset_type": self.asset_type,
            "method": self.method,
        }
        if self.alt_text:
            out["alt_text"] = self.alt_text
        if self.confidence is not None:
            out["confidence"] = self.confidence
        if self.failure_reason:
            out["failure_reason"] = self.failure_reason
        return out


@dataclass
class VisualExtractionDiagnostics:
    visual_asset_count: int = 0
    placeholder_count: int = 0
    alt_text_count: int = 0
    caption_count: int = 0
    scanned_page_count: int = 0
    pages_with_visuals: list[int] = field(default_factory=list)
    assets: list[VisualAsset] = field(default_factory=list)

    def register_asset(self, asset: VisualAsset) -> None:
        self.assets.append(asset)
        self.visual_asset_count = len(self.assets)
        if asset.method == "placeholder":
            self.placeholder_count += 1
        elif asset.method == "alt_text":
            self.alt_text_count += 1
        elif asset.method in ("vision_caption", "ocr"):
            self.caption_count += 1
        if asset.page_number not in self.pages_with_visuals:
            self.pages_with_visuals.append(asset.page_number)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "visual_asset_count": self.visual_asset_count,
            "placeholder_count": self.placeholder_count,
            "alt_text_count": self.alt_text_count,
            "caption_count": self.caption_count,
            "scanned_page_count": self.scanned_page_count,
            "pages_with_visuals": sorted(self.pages_with_visuals),
            "assets": [a.to_dict() for a in self.assets],
        }


def visual_placeholder_line(
    *,
    page_number: int,
    asset_index: int,
    asset_type: VisualAssetType,
    doc_format: str,
) -> str:
    """Human-readable placeholder when OCR/vision is disabled."""
    page_label = "slide" if doc_format == "pptx" else "page"
    type_label = "chart" if asset_type == "chart" else "image"
    return f"[Visual omitted: {page_label} {page_number} {type_label} {asset_index}]"


def visual_alt_text_line(alt_text: str) -> str:
    return f"[Visual (alt text): {alt_text.strip()}]"


def section_context_prefix(
    *,
    page_number: int | None,
    heading: str,
    doc_format: str,
) -> str:
    """Prefix chunk text so slide/page titles reach the LLM (IMG.2 / IMG.5)."""
    if page_number is None:
        return f"[Section: {heading}]" if heading else ""
    if doc_format == "pptx":
        label = f"Slide {page_number}"
    elif doc_format == "pdf":
        label = f"Page {page_number}"
    else:
        label = f"Section {page_number}"
    if heading:
        return f"[{label}: {heading}]"
    return f"[{label}]"


def format_section_chunk_text(
    *,
    heading: str,
    body: str,
    page_number: int | None,
    doc_format: str,
) -> str:
    """Build chunk-visible text from a parsed section."""
    parts: list[str] = []
    if doc_format in ("pptx", "pdf") and page_number is not None:
        prefix = section_context_prefix(
            page_number=page_number,
            heading=heading,
            doc_format=doc_format,
        )
        if prefix:
            parts.append(prefix)
    if body.strip():
        parts.append(body.strip())
    elif heading and not parts:
        parts.append(heading.strip())
    return "\n\n".join(parts)


def pptx_shape_alt_text(shape: Any) -> str:
    """Read OpenXML ``descr`` / ``title`` from a shape when present."""
    try:
        elements = shape._element.xpath(".//p:cNvPr")
        if not elements:
            return ""
        el = elements[0]
        return (el.get("descr") or el.get("title") or "").strip()
    except Exception:
        return ""


@dataclass
class CaptionResult:
    success: bool
    text: str = ""
    confidence: float | None = None
    failure_reason: str | None = None


class VisualCaptionProvider(ABC):
    """Boundary for OCR / multimodal-caption providers.

    Implementations turn a single image asset into a short text caption.
    Failures must surface as ``CaptionResult(success=False, ...)`` rather
    than raising — a single bad asset must never fail an ingestion run.
    """

    name: str = "base"

    @abstractmethod
    def caption(self, image_bytes: bytes, *, mime_type: str = "image/png") -> CaptionResult:
        """Return a caption for one image asset."""


class NoOpCaptionProvider(VisualCaptionProvider):
    """Default provider — never produces captions, never fails.

    Selected when ``settings.visual_caption_provider == 'none'`` so the
    default install has zero host dependencies (no OCR engine, no extra
    LLM calls per asset).
    """

    name = "none"

    def caption(self, image_bytes: bytes, *, mime_type: str = "image/png") -> CaptionResult:
        return CaptionResult(success=False, failure_reason="provider_disabled")


_PROVIDERS: dict[str, type[VisualCaptionProvider]] = {
    "none": NoOpCaptionProvider,
}


def register_caption_provider(name: str, provider_cls: type[VisualCaptionProvider]) -> None:
    """Register an additional caption provider (e.g. tesseract, openai_vision).

    Kept open so optional adapters can be registered at app start by
    plugins or by future ingestion-side modules without modifying this
    file.
    """
    _PROVIDERS[name] = provider_cls


def get_caption_provider(name: str) -> VisualCaptionProvider:
    """Return an instance of the requested provider, falling back to no-op.

    Unknown provider names log a warning and fall back to NoOp rather
    than raising — invalid config should not crash ingestion.
    """
    cls = _PROVIDERS.get(name)
    if cls is None:
        log.warning("unknown visual caption provider %r; falling back to no-op", name)
        cls = NoOpCaptionProvider
    return cls()


def aggregate_document_visual_diagnostics(
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate ``metadata.visual_extraction`` across a run's documents.

    Returns a flat summary plus a per-document breakdown so the orphan-
    risk warning can link curators back to the specific slides/pages
    that need review.
    """
    total_assets = 0
    total_placeholders = 0
    total_alt_text = 0
    total_scanned_pages = 0
    per_doc: list[dict[str, Any]] = []

    for doc in documents:
        meta = (doc or {}).get("metadata") or {}
        vis = meta.get("visual_extraction") or {}
        if not vis:
            continue
        count = int(vis.get("visual_asset_count") or 0)
        if count == 0 and not vis.get("scanned_page_count"):
            continue
        total_assets += count
        total_placeholders += int(vis.get("placeholder_count") or 0)
        total_alt_text += int(vis.get("alt_text_count") or 0)
        total_scanned_pages += int(vis.get("scanned_page_count") or 0)
        per_doc.append(
            {
                "doc_id": doc.get("_key"),
                "filename": doc.get("filename"),
                "visual_asset_count": count,
                "pages_with_visuals": list(vis.get("pages_with_visuals") or []),
                "scanned_page_count": int(vis.get("scanned_page_count") or 0),
            }
        )

    return {
        "visual_asset_count": total_assets,
        "placeholder_count": total_placeholders,
        "alt_text_count": total_alt_text,
        "scanned_page_count": total_scanned_pages,
        "documents": per_doc,
    }


def build_orphan_risk_warning(
    *,
    orphan_class_count: int,
    total_classes: int,
    visual_summary: dict[str, Any],
    orphan_ratio_threshold: float,
    min_visual_assets: int,
) -> dict[str, Any] | None:
    """Return a non-blocking warning when orphans correlate with visuals.

    The warning is written to ``extraction_runs.stats.warnings`` so the
    curator UI can surface a link back to the visual-heavy source
    pages/slides for review (IMG.7). Returns ``None`` when either
    threshold is not met -- callers should not append a warning in that
    case so the UI stays quiet on healthy runs.
    """
    if total_classes <= 0:
        return None
    visual_asset_count = int(visual_summary.get("visual_asset_count") or 0)
    scanned_pages = int(visual_summary.get("scanned_page_count") or 0)
    if visual_asset_count < min_visual_assets and scanned_pages == 0:
        return None

    orphan_ratio = orphan_class_count / total_classes
    if orphan_ratio < orphan_ratio_threshold and scanned_pages == 0:
        return None

    return {
        "type": "visual_heavy_orphans",
        "severity": "warning",
        "message": (
            f"{orphan_class_count} of {total_classes} extracted classes have no parent "
            f"({orphan_ratio:.0%}) on a run with {visual_asset_count} visual "
            f"asset(s) and {scanned_pages} scanned page(s). Visual hierarchy may "
            "not have reached the LLM -- review highlighted slides/pages or "
            "enable an OCR/vision provider."
        ),
        "orphan_class_count": orphan_class_count,
        "total_classes": total_classes,
        "orphan_ratio": orphan_ratio,
        "visual_asset_count": visual_asset_count,
        "scanned_page_count": scanned_pages,
        "documents": visual_summary.get("documents", []),
    }


def visual_caption_line(text: str) -> str:
    return f"[Visual (caption): {text.strip()}]"


def _try_get_image_bytes(shape: Any) -> tuple[bytes, str] | None:
    """Best-effort extraction of (bytes, mime_type) from a PPTX picture shape.

    Returns ``None`` when the shape does not expose ``image.blob`` (e.g.,
    chart shapes, programmatically-built shapes in tests where the
    backing image isn't a normal PNG/JPEG).
    """
    try:
        blob = shape.image.blob
        mime = getattr(shape.image, "content_type", "") or "image/png"
        return blob, mime
    except Exception:
        return None


def collect_pptx_visual_assets(
    shapes: Any,
    *,
    slide_index: int,
    diagnostics: VisualExtractionDiagnostics,
    emit_placeholders: bool,
    caption_provider: VisualCaptionProvider | None = None,
    max_caption_calls: int | None = None,
) -> list[str]:
    """Walk PPTX shapes (including groups) and return body placeholder lines.

    When ``caption_provider`` is provided and not the no-op, the provider
    is invoked for each picture shape that lacks alt text. A successful
    caption replaces the placeholder line and the asset's ``method`` is
    recorded as ``"vision_caption"``. Provider failures fall back to the
    placeholder path and record ``failure_reason`` on the asset — they
    never abort ingestion.
    """
    lines: list[str] = []
    captions_used = 0

    def _walk(shape_collection: Any) -> None:
        nonlocal captions_used
        for shape in shape_collection:
            shape_type = getattr(shape, "shape_type", None)
            if shape_type == _PPTX_SHAPE_GROUP:
                _walk(shape.shapes)
                continue

            if shape_type == _PPTX_SHAPE_PICTURE:
                asset_type: VisualAssetType = "picture"
            elif shape_type == _PPTX_SHAPE_CHART:
                asset_type = "chart"
            else:
                continue

            asset_index = diagnostics.visual_asset_count + 1
            alt_text = pptx_shape_alt_text(shape)
            caption_text: str | None = None
            caption_confidence: float | None = None
            failure_reason: str | None = None

            if alt_text:
                method: VisualExtractionMethod = "alt_text"
                line = visual_alt_text_line(alt_text)
            else:
                # Try the caption provider before falling back to a
                # placeholder. Only PICTURE shapes have image bytes we
                # can hand to a provider; charts always go to placeholder.
                if (
                    caption_provider is not None
                    and not isinstance(caption_provider, NoOpCaptionProvider)
                    and asset_type == "picture"
                    and (max_caption_calls is None or captions_used < max_caption_calls)
                ):
                    img = _try_get_image_bytes(shape)
                    if img is not None:
                        bytes_, mime = img
                        try:
                            result = caption_provider.caption(bytes_, mime_type=mime)
                        except Exception as exc:
                            result = CaptionResult(
                                success=False, failure_reason=f"provider_error:{exc}"
                            )
                        captions_used += 1
                        if result.success and result.text.strip():
                            caption_text = result.text.strip()
                            caption_confidence = result.confidence
                        else:
                            failure_reason = result.failure_reason or "no_caption"
                    else:
                        failure_reason = "no_image_bytes"

                if caption_text:
                    method = "vision_caption"
                    line = visual_caption_line(caption_text)
                elif emit_placeholders:
                    method = "placeholder"
                    line = visual_placeholder_line(
                        page_number=slide_index,
                        asset_index=asset_index,
                        asset_type=asset_type,
                        doc_format="pptx",
                    )
                else:
                    continue

            diagnostics.register_asset(
                VisualAsset(
                    page_number=slide_index,
                    asset_index=asset_index,
                    asset_type=asset_type,
                    method=method,
                    alt_text=alt_text or None,
                    confidence=caption_confidence,
                    failure_reason=failure_reason,
                )
            )
            lines.append(line)

    _walk(shapes)
    return lines
