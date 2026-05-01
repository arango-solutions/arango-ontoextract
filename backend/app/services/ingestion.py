"""Document parsing, semantic chunking, and duplicate detection.

Supports PDF (via pymupdf), DOCX (via python-docx), and Markdown.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field

import fitz
import tiktoken
from docx import Document

log = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 512
_TIKTOKEN_MODEL = "cl100k_base"


@dataclass
class Section:
    heading: str
    text: str
    page_number: int | None = None


@dataclass
class ParsedDocument:
    sections: list[Section] = field(default_factory=list)
    title: str = ""
    author: str = ""
    page_count: int = 0


@dataclass
class Chunk:
    text: str
    chunk_index: int
    source_page: int | None
    section_heading: str
    token_count: int


def compute_file_hash(content: bytes) -> str:
    """SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(content).hexdigest()


def _token_count(text: str) -> int:
    enc = tiktoken.get_encoding(_TIKTOKEN_MODEL)
    return len(enc.encode(text))


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_pdf(file_bytes: bytes) -> ParsedDocument:
    """Extract sections from a PDF using pymupdf (fitz)."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    parsed = ParsedDocument(page_count=len(doc))

    metadata = doc.metadata or {}
    parsed.title = metadata.get("title", "") or ""
    parsed.author = metadata.get("author", "") or ""

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        current_heading = ""
        current_text_parts: list[str] = []

        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text = "".join(span["text"] for span in line.get("spans", []))
                if not line_text.strip():
                    continue

                max_size = max(
                    (span.get("size", 0) for span in line.get("spans", [])),
                    default=0,
                )
                is_bold = any(
                    "bold" in (span.get("font", "").lower()) for span in line.get("spans", [])
                )

                if max_size >= 14 or (is_bold and max_size >= 12):
                    if current_text_parts:
                        parsed.sections.append(
                            Section(
                                heading=current_heading,
                                text="\n".join(current_text_parts).strip(),
                                page_number=page_num,
                            )
                        )
                        current_text_parts = []
                    current_heading = line_text.strip()
                else:
                    current_text_parts.append(line_text)

        if current_text_parts:
            parsed.sections.append(
                Section(
                    heading=current_heading,
                    text="\n".join(current_text_parts).strip(),
                    page_number=page_num,
                )
            )

    doc.close()

    if not parsed.sections:
        full_text = ""
        reopened = fitz.open(stream=file_bytes, filetype="pdf")
        for page in reopened:
            full_text += page.get_text() + "\n"
        reopened.close()
        if full_text.strip():
            parsed.sections.append(Section(heading="", text=full_text.strip(), page_number=1))

    return parsed


def parse_docx(file_bytes: bytes) -> ParsedDocument:
    """Extract sections from a DOCX using python-docx."""
    doc = Document(io.BytesIO(file_bytes))

    parsed = ParsedDocument()
    core = doc.core_properties
    parsed.title = core.title or ""
    parsed.author = core.author or ""

    current_heading = ""
    current_text_parts: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        if para.style and para.style.name and para.style.name.startswith("Heading"):
            if current_text_parts:
                parsed.sections.append(
                    Section(heading=current_heading, text="\n".join(current_text_parts))
                )
                current_text_parts = []
            current_heading = text
        else:
            current_text_parts.append(text)

    if current_text_parts:
        parsed.sections.append(Section(heading=current_heading, text="\n".join(current_text_parts)))

    return parsed


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)


def parse_markdown(text: str) -> ParsedDocument:
    """Extract sections from Markdown text using heading boundaries."""
    parsed = ParsedDocument()

    lines = text.split("\n")
    first_heading = ""
    for line in lines:
        m = _MD_HEADING_RE.match(line)
        if m:
            first_heading = m.group(2).strip()
            break
    parsed.title = first_heading

    current_heading = ""
    current_text_parts: list[str] = []

    for line in lines:
        m = _MD_HEADING_RE.match(line)
        if m:
            if current_text_parts:
                parsed.sections.append(
                    Section(heading=current_heading, text="\n".join(current_text_parts).strip())
                )
                current_text_parts = []
            current_heading = m.group(2).strip()
        else:
            current_text_parts.append(line)

    if current_text_parts:
        body = "\n".join(current_text_parts).strip()
        if body:
            parsed.sections.append(Section(heading=current_heading, text=body))

    return parsed


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text at blank-line boundaries, keeping non-empty paragraphs."""
    paragraphs = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paragraphs if p.strip()]


def chunk_document(
    parsed: ParsedDocument,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> list[Chunk]:
    """Chunk a parsed document at section / paragraph boundaries.

    Each chunk respects ``max_tokens`` (counted via tiktoken ``cl100k_base``).
    Chunks preserve source page and section heading metadata.
    """
    chunks: list[Chunk] = []
    idx = 0

    for section in parsed.sections:
        paragraphs = _split_into_paragraphs(section.text)
        if not paragraphs:
            continue

        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = _token_count(para)

            if para_tokens > max_tokens:
                if current_parts:
                    merged = "\n\n".join(current_parts)
                    chunks.append(
                        Chunk(
                            text=merged,
                            chunk_index=idx,
                            source_page=section.page_number,
                            section_heading=section.heading,
                            token_count=_token_count(merged),
                        )
                    )
                    idx += 1
                    current_parts = []
                    current_tokens = 0

                words = para.split()
                sub_parts: list[str] = []
                sub_tokens = 0
                for word in words:
                    word_tokens = _token_count(word + " ")
                    if sub_tokens + word_tokens > max_tokens and sub_parts:
                        sub_text = " ".join(sub_parts)
                        chunks.append(
                            Chunk(
                                text=sub_text,
                                chunk_index=idx,
                                source_page=section.page_number,
                                section_heading=section.heading,
                                token_count=_token_count(sub_text),
                            )
                        )
                        idx += 1
                        sub_parts = []
                        sub_tokens = 0
                    sub_parts.append(word)
                    sub_tokens += word_tokens

                if sub_parts:
                    sub_text = " ".join(sub_parts)
                    chunks.append(
                        Chunk(
                            text=sub_text,
                            chunk_index=idx,
                            source_page=section.page_number,
                            section_heading=section.heading,
                            token_count=_token_count(sub_text),
                        )
                    )
                    idx += 1
                continue

            if current_tokens + para_tokens > max_tokens and current_parts:
                merged = "\n\n".join(current_parts)
                chunks.append(
                    Chunk(
                        text=merged,
                        chunk_index=idx,
                        source_page=section.page_number,
                        section_heading=section.heading,
                        token_count=_token_count(merged),
                    )
                )
                idx += 1
                current_parts = []
                current_tokens = 0

            current_parts.append(para)
            current_tokens += para_tokens

        if current_parts:
            merged = "\n\n".join(current_parts)
            chunks.append(
                Chunk(
                    text=merged,
                    chunk_index=idx,
                    source_page=section.page_number,
                    section_heading=section.heading,
                    token_count=_token_count(merged),
                )
            )
            idx += 1

    return chunks
