"""Unit tests for visual extraction helpers (Stream 13)."""

from __future__ import annotations

from app.services.visual_extraction import (
    VisualAsset,
    VisualExtractionDiagnostics,
    format_section_chunk_text,
    section_context_prefix,
    visual_alt_text_line,
    visual_placeholder_line,
)


class TestVisualPlaceholderLine:
    def test_pptx_uses_slide_label(self):
        line = visual_placeholder_line(
            page_number=3,
            asset_index=2,
            asset_type="picture",
            doc_format="pptx",
        )
        assert line == "[Visual omitted: slide 3 image 2]"

    def test_pdf_uses_page_label(self):
        line = visual_placeholder_line(
            page_number=5,
            asset_index=1,
            asset_type="image_block",
            doc_format="pdf",
        )
        assert line == "[Visual omitted: page 5 image 1]"


class TestSectionContextPrefix:
    def test_title_only_slide(self):
        assert section_context_prefix(page_number=2, heading="Benefits", doc_format="pptx") == (
            "[Slide 2: Benefits]"
        )

    def test_format_section_chunk_text_title_only(self):
        text = format_section_chunk_text(
            heading="Root Class",
            body="",
            page_number=4,
            doc_format="pptx",
        )
        assert text == "[Slide 4: Root Class]"


class TestVisualExtractionDiagnostics:
    def test_to_metadata_dict_counts_assets(self):
        diag = VisualExtractionDiagnostics()
        diag.register_asset(
            VisualAsset(page_number=1, asset_index=1, asset_type="picture", method="placeholder")
        )
        diag.register_asset(
            VisualAsset(
                page_number=1,
                asset_index=2,
                asset_type="chart",
                method="alt_text",
                alt_text="Org chart",
            )
        )
        meta = diag.to_metadata_dict()
        assert meta["visual_asset_count"] == 2
        assert meta["placeholder_count"] == 1
        assert meta["alt_text_count"] == 1
        assert meta["pages_with_visuals"] == [1]


class TestVisualAltTextLine:
    def test_wraps_alt_text(self):
        assert visual_alt_text_line("Taxonomy diagram") == "[Visual (alt text): Taxonomy diagram]"
