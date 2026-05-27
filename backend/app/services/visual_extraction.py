"""Visual asset inventory and placeholder helpers for document ingestion.

Stream 13 (IMG.1-IMG.3): track embedded images/charts in PPTX and PDF,
emit labeled placeholders when OCR/vision is not configured, and expose
diagnostics for document metadata and downstream orphan-risk warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
        if asset.page_number not in self.pages_with_visuals:
            self.pages_with_visuals.append(asset.page_number)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "visual_asset_count": self.visual_asset_count,
            "placeholder_count": self.placeholder_count,
            "alt_text_count": self.alt_text_count,
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


def collect_pptx_visual_assets(
    shapes: Any,
    *,
    slide_index: int,
    diagnostics: VisualExtractionDiagnostics,
    emit_placeholders: bool,
) -> list[str]:
    """Walk PPTX shapes (including groups) and return body placeholder lines."""
    lines: list[str] = []

    def _walk(shape_collection: Any) -> None:
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
            if alt_text:
                method: VisualExtractionMethod = "alt_text"
                line = visual_alt_text_line(alt_text)
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
                )
            )
            lines.append(line)

    _walk(shapes)
    return lines
