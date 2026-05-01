"""Unit tests for app.services.ingestion — parsing, chunking, hashing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.ingestion import (
    ParsedDocument,
    Section,
    chunk_document,
    compute_file_hash,
    parse_markdown,
)

# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------


class TestComputeFileHash:
    def test_deterministic(self):
        content = b"hello world"
        h1 = compute_file_hash(content)
        h2 = compute_file_hash(content)
        assert h1 == h2

    def test_different_content_different_hash(self):
        assert compute_file_hash(b"a") != compute_file_hash(b"b")

    def test_empty_bytes(self):
        h = compute_file_hash(b"")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_sha256_known_value(self):
        expected = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        assert compute_file_hash(b"test") == expected


# ---------------------------------------------------------------------------
# parse_markdown
# ---------------------------------------------------------------------------


class TestParseMarkdown:
    def test_single_section(self):
        md = "# Title\n\nSome body text here."
        parsed = parse_markdown(md)
        assert parsed.title == "Title"
        assert len(parsed.sections) == 1
        assert parsed.sections[0].heading == "Title"
        assert "body text" in parsed.sections[0].text

    def test_multiple_sections(self):
        md = "# Intro\n\nIntro text.\n\n## Details\n\nDetail text."
        parsed = parse_markdown(md)
        assert len(parsed.sections) == 2
        assert parsed.sections[0].heading == "Intro"
        assert parsed.sections[1].heading == "Details"

    def test_empty_markdown(self):
        parsed = parse_markdown("")
        assert parsed.sections == []
        assert parsed.title == ""

    def test_no_headings(self):
        md = "Just a paragraph of text without any headings."
        parsed = parse_markdown(md)
        assert len(parsed.sections) == 1
        assert parsed.sections[0].heading == ""

    def test_heading_levels(self):
        md = "# H1\n\nh1 text\n\n### H3\n\nh3 text"
        parsed = parse_markdown(md)
        assert parsed.sections[0].heading == "H1"
        assert parsed.sections[1].heading == "H3"


# ---------------------------------------------------------------------------
# parse_pdf (mocked)
# ---------------------------------------------------------------------------


class TestParsePdf:
    @patch("app.services.ingestion.fitz")
    def test_basic_extraction(self, mock_fitz: MagicMock):
        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {"spans": [{"text": "A normal paragraph.", "size": 11, "font": "Regular"}]}
                    ],
                }
            ]
        }

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.metadata = {"title": "Test", "author": "Auth"}

        mock_fitz.open.return_value = mock_doc
        mock_fitz.TEXT_PRESERVE_WHITESPACE = 1

        from app.services.ingestion import parse_pdf

        parsed = parse_pdf(b"fake-pdf-bytes")

        assert parsed.title == "Test"
        assert parsed.author == "Auth"
        assert len(parsed.sections) >= 1

    @patch("app.services.ingestion.fitz")
    def test_empty_pdf(self, mock_fitz: MagicMock):
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([]))
        mock_doc.__len__ = MagicMock(return_value=0)
        mock_doc.metadata = {}

        reopened_doc = MagicMock()
        reopened_page = MagicMock()
        reopened_page.get_text.return_value = ""
        reopened_doc.__iter__ = MagicMock(return_value=iter([reopened_page]))

        mock_fitz.open.side_effect = [mock_doc, reopened_doc]
        mock_fitz.TEXT_PRESERVE_WHITESPACE = 1

        from app.services.ingestion import parse_pdf

        parsed = parse_pdf(b"fake-empty-pdf")
        assert parsed.page_count == 0


# ---------------------------------------------------------------------------
# parse_docx (mocked)
# ---------------------------------------------------------------------------


class TestParseDocx:
    @patch("app.services.ingestion.Document")
    def test_basic_extraction(self, mock_document_cls: MagicMock):
        mock_heading_style = MagicMock()
        mock_heading_style.name = "Heading 1"

        mock_normal_style = MagicMock()
        mock_normal_style.name = "Normal"

        heading_para = MagicMock()
        heading_para.text = "My Heading"
        heading_para.style = mock_heading_style

        body_para = MagicMock()
        body_para.text = "Some body content here."
        body_para.style = mock_normal_style

        mock_core = MagicMock()
        mock_core.title = "Doc Title"
        mock_core.author = "Author Name"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [heading_para, body_para]
        mock_doc.core_properties = mock_core
        mock_document_cls.return_value = mock_doc

        from app.services.ingestion import parse_docx

        parsed = parse_docx(b"fake-docx")

        assert parsed.title == "Doc Title"
        assert parsed.author == "Author Name"
        assert len(parsed.sections) == 1
        assert parsed.sections[0].heading == "My Heading"
        assert "body content" in parsed.sections[0].text


# ---------------------------------------------------------------------------
# chunk_document (tiktoken mocked)
# ---------------------------------------------------------------------------


def _fake_token_count(text: str) -> int:
    """Approximate token count for tests: ~1 token per 4 chars."""
    return max(1, len(text) // 4)


@patch("app.services.ingestion._token_count", side_effect=_fake_token_count)
class TestChunkDocument:
    def test_single_short_section(self, _mock_tc: MagicMock):
        parsed = ParsedDocument(
            sections=[Section(heading="Intro", text="Short text.", page_number=1)]
        )
        chunks = chunk_document(parsed, max_tokens=512)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].section_heading == "Intro"
        assert chunks[0].source_page == 1

    def test_respects_max_tokens(self, _mock_tc: MagicMock):
        long_text = " ".join(["word"] * 2000)
        parsed = ParsedDocument(sections=[Section(heading="Long", text=long_text, page_number=1)])
        chunks = chunk_document(parsed, max_tokens=50)
        assert len(chunks) > 1

    def test_empty_document(self, _mock_tc: MagicMock):
        parsed = ParsedDocument(sections=[])
        chunks = chunk_document(parsed)
        assert chunks == []

    def test_multiple_sections(self, _mock_tc: MagicMock):
        parsed = ParsedDocument(
            sections=[
                Section(heading="A", text="Text A", page_number=1),
                Section(heading="B", text="Text B", page_number=2),
            ]
        )
        chunks = chunk_document(parsed)
        assert len(chunks) == 2
        assert chunks[0].section_heading == "A"
        assert chunks[1].section_heading == "B"

    def test_chunk_indexes_sequential(self, _mock_tc: MagicMock):
        parsed = ParsedDocument(
            sections=[
                Section(heading="A", text="Text A", page_number=1),
                Section(heading="B", text="Text B", page_number=2),
            ]
        )
        chunks = chunk_document(parsed)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_paragraph_boundary_splitting(self, _mock_tc: MagicMock):
        text = (
            "First paragraph with enough words to matter.\n\n"
            "Second paragraph also with content.\n\n"
            "Third paragraph here too."
        )
        parsed = ParsedDocument(sections=[Section(heading="S", text=text, page_number=1)])
        chunks = chunk_document(parsed, max_tokens=15)
        assert len(chunks) >= 2
