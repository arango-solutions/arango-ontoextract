"""Unit tests for visual extraction helpers (Stream 13)."""

from __future__ import annotations

from app.services.visual_extraction import (
    CaptionResult,
    NoOpCaptionProvider,
    VisualAsset,
    VisualCaptionProvider,
    VisualExtractionDiagnostics,
    aggregate_document_visual_diagnostics,
    build_orphan_risk_warning,
    format_section_chunk_text,
    get_caption_provider,
    register_caption_provider,
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


class TestCaptionProviderRegistry:
    def test_default_returns_noop(self):
        provider = get_caption_provider("none")
        assert isinstance(provider, NoOpCaptionProvider)
        result = provider.caption(b"\x89PNG", mime_type="image/png")
        assert result.success is False
        assert result.failure_reason == "provider_disabled"

    def test_unknown_provider_falls_back_to_noop(self, caplog):
        provider = get_caption_provider("does_not_exist")
        assert isinstance(provider, NoOpCaptionProvider)
        assert any("does_not_exist" in rec.message for rec in caplog.records)

    def test_register_custom_provider(self):
        class FakeProvider(VisualCaptionProvider):
            name = "fake"

            def caption(self, image_bytes, *, mime_type="image/png"):
                return CaptionResult(success=True, text="alt", confidence=0.9)

        register_caption_provider("fake", FakeProvider)
        try:
            provider = get_caption_provider("fake")
            assert isinstance(provider, FakeProvider)
            assert provider.caption(b"x").text == "alt"
        finally:
            from app.services.visual_extraction import _PROVIDERS

            _PROVIDERS.pop("fake", None)


class TestAggregateDocumentVisualDiagnostics:
    def test_empty_documents(self):
        summary = aggregate_document_visual_diagnostics([])
        assert summary["visual_asset_count"] == 0
        assert summary["documents"] == []

    def test_skips_docs_without_visual_metadata(self):
        docs = [{"_key": "d1", "filename": "a.pdf", "metadata": {}}]
        summary = aggregate_document_visual_diagnostics(docs)
        assert summary["documents"] == []

    def test_aggregates_per_doc_breakdown(self):
        docs = [
            {
                "_key": "d1",
                "filename": "deck.pptx",
                "metadata": {
                    "visual_extraction": {
                        "visual_asset_count": 3,
                        "placeholder_count": 2,
                        "alt_text_count": 1,
                        "scanned_page_count": 0,
                        "pages_with_visuals": [1, 4],
                    }
                },
            },
            {
                "_key": "d2",
                "filename": "scan.pdf",
                "metadata": {
                    "visual_extraction": {
                        "visual_asset_count": 0,
                        "scanned_page_count": 2,
                        "pages_with_visuals": [],
                    }
                },
            },
        ]
        summary = aggregate_document_visual_diagnostics(docs)
        assert summary["visual_asset_count"] == 3
        assert summary["placeholder_count"] == 2
        assert summary["alt_text_count"] == 1
        assert summary["scanned_page_count"] == 2
        assert {d["doc_id"] for d in summary["documents"]} == {"d1", "d2"}


class TestBuildOrphanRiskWarning:
    def _summary(self, *, assets=10, scanned=0):
        return {
            "visual_asset_count": assets,
            "scanned_page_count": scanned,
            "documents": [{"doc_id": "d1", "visual_asset_count": assets}],
        }

    def test_returns_none_when_no_classes(self):
        assert (
            build_orphan_risk_warning(
                orphan_class_count=0,
                total_classes=0,
                visual_summary=self._summary(),
                orphan_ratio_threshold=0.5,
                min_visual_assets=5,
            )
            is None
        )

    def test_returns_none_when_visuals_below_threshold(self):
        assert (
            build_orphan_risk_warning(
                orphan_class_count=4,
                total_classes=5,
                visual_summary=self._summary(assets=1, scanned=0),
                orphan_ratio_threshold=0.5,
                min_visual_assets=5,
            )
            is None
        )

    def test_returns_none_when_orphans_below_threshold(self):
        assert (
            build_orphan_risk_warning(
                orphan_class_count=1,
                total_classes=10,
                visual_summary=self._summary(assets=10),
                orphan_ratio_threshold=0.5,
                min_visual_assets=5,
            )
            is None
        )

    def test_triggers_when_both_thresholds_exceeded(self):
        warning = build_orphan_risk_warning(
            orphan_class_count=6,
            total_classes=10,
            visual_summary=self._summary(assets=12),
            orphan_ratio_threshold=0.5,
            min_visual_assets=5,
        )
        assert warning is not None
        assert warning["type"] == "visual_heavy_orphans"
        assert warning["severity"] == "warning"
        assert warning["orphan_class_count"] == 6
        assert warning["total_classes"] == 10
        assert warning["visual_asset_count"] == 12
        assert warning["documents"]

    def test_triggers_on_scanned_pages_alone(self):
        warning = build_orphan_risk_warning(
            orphan_class_count=1,
            total_classes=10,
            visual_summary=self._summary(assets=0, scanned=3),
            orphan_ratio_threshold=0.5,
            min_visual_assets=5,
        )
        assert warning is not None
        assert warning["scanned_page_count"] == 3
