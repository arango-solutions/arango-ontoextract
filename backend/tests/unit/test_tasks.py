"""Unit tests for app.tasks -- document ingestion pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ingestion import Chunk, ParsedDocument, Section
from app.tasks import _build_chunk_dicts, _ensure_vector_index, process_document

# ---------------------------------------------------------------------------
# _build_chunk_dicts
# ---------------------------------------------------------------------------


class TestBuildChunkDicts:
    def test_basic_mapping(self):
        chunks = [
            Chunk(
                text="hello",
                chunk_index=0,
                source_page=1,
                section_heading="Intro",
                token_count=3,
                doc_format="pptx",
            ),
            Chunk(
                text="world",
                chunk_index=1,
                source_page=2,
                section_heading="Body",
                token_count=4,
                doc_format="pptx",
            ),
        ]
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        result = _build_chunk_dicts("doc1", chunks, embeddings)

        assert len(result) == 2
        assert result[0]["doc_id"] == "doc1"
        assert result[0]["text"] == "hello"
        assert result[0]["chunk_index"] == 0
        assert result[0]["source_page"] == 1
        assert result[0]["section_heading"] == "Intro"
        assert result[0]["token_count"] == 3
        assert result[0]["embedding"] == [0.1, 0.2]
        # CH.1: doc_format is persisted so the strategy selector can detect decks.
        assert result[0]["doc_format"] == "pptx"

        assert result[1]["chunk_index"] == 1
        assert result[1]["text"] == "world"
        assert result[1]["doc_format"] == "pptx"

    def test_doc_format_omitted_when_empty(self):
        # CH.1: an unknown/empty doc_format is not written, so legacy
        # consumers and pre-CH.1 chunks stay byte-for-byte identical.
        chunks = [
            Chunk(
                text="hello",
                chunk_index=0,
                source_page=None,
                section_heading="",
                token_count=3,
            )
        ]
        result = _build_chunk_dicts("doc1", chunks, [[0.1, 0.2]])
        assert "doc_format" not in result[0]

    def test_deck_metadata_omitted_at_defaults(self):
        # CH.2/CH.3: a default (prose / non-deck) chunk writes none of the
        # deck-only fields, so non-deck storage is byte-identical.
        chunks = [
            Chunk(
                text="hello",
                chunk_index=0,
                source_page=None,
                section_heading="",
                token_count=3,
            )
        ]
        result = _build_chunk_dicts("doc1", chunks, [[0.1, 0.2]])
        assert "chunk_role" not in result[0]
        assert "slide_part" not in result[0]
        assert "slide_parts" not in result[0]
        assert "topic_unit" not in result[0]

    def test_deck_metadata_persisted_when_present(self):
        # CH.2/CH.3: deck-aware chunk metadata is persisted so the extractor
        # can batch by topic unit and curators can see slide provenance.
        chunks = [
            Chunk(
                text="[Notes] talk track",
                chunk_index=0,
                source_page=4,
                section_heading="Findings",
                token_count=5,
                doc_format="pptx",
                chunk_role="notes",
                slide_part=1,
                slide_parts=2,
                topic_unit=3,
            )
        ]
        result = _build_chunk_dicts("doc1", chunks, [[0.1, 0.2]])
        assert result[0]["chunk_role"] == "notes"
        assert result[0]["slide_part"] == 1
        assert result[0]["slide_parts"] == 2
        assert result[0]["topic_unit"] == 3

    def test_unsplit_slide_omits_slide_part_fields(self):
        # slide_parts == 1 is the default (not split) -> not persisted, but a
        # deck chunk still carries topic_unit.
        chunks = [
            Chunk(
                text="Body.",
                chunk_index=0,
                source_page=1,
                section_heading="Intro",
                token_count=2,
                doc_format="pptx",
                topic_unit=0,
            )
        ]
        result = _build_chunk_dicts("doc1", chunks, [[0.1, 0.2]])
        assert "slide_part" not in result[0]
        assert "slide_parts" not in result[0]
        assert result[0]["topic_unit"] == 0

    def test_empty_chunks(self):
        result = _build_chunk_dicts("doc1", [], [])
        assert result == []

    def test_mismatched_lengths_raises(self):
        chunks = [
            Chunk(text="a", chunk_index=0, source_page=None, section_heading="", token_count=1)
        ]
        with pytest.raises(ValueError):
            _build_chunk_dicts("doc1", chunks, [])


# ---------------------------------------------------------------------------
# _ensure_vector_index
# ---------------------------------------------------------------------------


class TestEnsureVectorIndex:
    @patch("app.tasks.get_db")
    def test_skips_when_no_chunks_collection(self, mock_get_db):
        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        _ensure_vector_index()

        db.has_collection.assert_called_once_with("chunks")
        # Should not try to access the collection
        db.collection.assert_not_called()

    @patch("app.tasks.get_db")
    def test_skips_when_index_already_exists(self, mock_get_db):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = [{"name": "idx_chunks_embedding_vector"}]
        db.collection.return_value = col
        mock_get_db.return_value = db

        _ensure_vector_index()

        # Should not attempt to create the index
        db._conn.send_request.assert_not_called()

    @patch("app.tasks.get_db")
    def test_creates_index_when_missing(self, mock_get_db):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = [{"name": "primary"}]
        col.count.return_value = 100
        db.collection.return_value = col

        resp = MagicMock()
        resp.status_code = 201
        db._conn.send_request.return_value = resp
        mock_get_db.return_value = db

        _ensure_vector_index()

        db._conn.send_request.assert_called_once()
        req = db._conn.send_request.call_args[0][0]
        assert req.method == "post"
        assert req.params == {"collection": "chunks"}
        assert req.data["type"] == "vector"
        assert req.data["name"] == "idx_chunks_embedding_vector"

    @patch("app.tasks.get_db")
    def test_raises_on_failed_creation(self, mock_get_db):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = []
        col.count.return_value = 10
        db.collection.return_value = col

        resp = MagicMock()
        resp.status_code = 500
        resp.body = "internal error"
        db._conn.send_request.return_value = resp
        mock_get_db.return_value = db

        with pytest.raises(RuntimeError, match="Vector index creation failed"):
            _ensure_vector_index()

    @patch("app.tasks.get_db")
    def test_timeout_then_index_present_is_treated_as_success(self, mock_get_db):
        # Reproduces the live failure mode observed against a fresh
        # ArangoDB Enterprise cluster: the cluster runs k-means training
        # synchronously for the very first vector index and exceeds the
        # python-arango client's read timeout, but persists the index
        # seconds later. Without recovery the document gets marked FAILED
        # despite chunks + embeddings + index all being present on disk.
        from requests.exceptions import ReadTimeout as RequestsReadTimeout

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        # First .indexes() call (existence pre-check) -- index NOT present
        # yet. Second .indexes() call (post-timeout re-check) -- index now
        # present because the cluster finished the work in the background.
        col.indexes.side_effect = [
            [{"name": "primary"}],
            [{"name": "primary"}, {"name": "idx_chunks_embedding_vector"}],
        ]
        col.count.return_value = 16
        db.collection.return_value = col
        db._conn.send_request.side_effect = RequestsReadTimeout("Read timed out. (read timeout=60)")
        mock_get_db.return_value = db

        # Should NOT raise -- the recovery branch must convert the timeout
        # into a success once the index is observed on the cluster.
        _ensure_vector_index()

        # Both .indexes() calls happened: the original existence check and
        # the recovery re-check.
        assert col.indexes.call_count == 2

    @patch("app.tasks.get_db")
    def test_timeout_then_index_still_missing_raises_runtime_error(self, mock_get_db):
        # If the timeout is real (cluster never wrote the index), we must
        # still raise so the document is correctly marked FAILED -- the
        # recovery path is for the "client gave up but cluster finished"
        # case only, not a license to swallow genuine errors.
        from requests.exceptions import ReadTimeout as RequestsReadTimeout

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.side_effect = [
            [{"name": "primary"}],  # initial existence check -- absent
            [{"name": "primary"}],  # recovery re-check -- still absent
        ]
        col.count.return_value = 16
        db.collection.return_value = col
        db._conn.send_request.side_effect = RequestsReadTimeout("Read timed out. (read timeout=60)")
        mock_get_db.return_value = db

        with pytest.raises(RuntimeError, match="timed out and the index is not present"):
            _ensure_vector_index()

    @patch("app.tasks.get_db")
    def test_connection_error_also_recoverable_when_index_present(self, mock_get_db):
        # Same recovery shape for transient connection drops: the cluster
        # may have completed before the connection died.
        from requests.exceptions import ConnectionError as RequestsConnectionError

        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.side_effect = [
            [{"name": "primary"}],
            [{"name": "idx_chunks_embedding_vector"}],
        ]
        col.count.return_value = 16
        db.collection.return_value = col
        db._conn.send_request.side_effect = RequestsConnectionError("connection reset")
        mock_get_db.return_value = db

        _ensure_vector_index()  # must not raise


# ---------------------------------------------------------------------------
# process_document
# ---------------------------------------------------------------------------


class TestProcessDocument:
    @pytest.mark.asyncio
    @patch("app.tasks._ensure_vector_index")
    @patch("app.tasks.embedding_svc")
    @patch("app.tasks.documents_repo")
    @patch("app.tasks.chunk_document")
    @patch("app.tasks.parse_markdown")
    async def test_markdown_happy_path(
        self, mock_parse_md, mock_chunk, mock_docs_repo, mock_embed_svc, mock_vec_idx
    ):
        parsed = ParsedDocument(
            sections=[Section(heading="Title", text="Hello world")],
            title="Test",
        )
        mock_parse_md.return_value = parsed

        chunks = [
            Chunk(
                text="Hello world",
                chunk_index=0,
                source_page=None,
                section_heading="Title",
                token_count=5,
            ),
        ]
        mock_chunk.return_value = chunks
        mock_embed_svc.embed_texts = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_docs_repo.create_chunks.return_value = [{"_key": "c1"}]

        await process_document("doc1", b"# Hello world", "text/markdown")

        mock_parse_md.assert_called_once()
        # CH.4: chunk_document is called with the pre-computed category.
        mock_chunk.assert_called_once_with(parsed, category="narrative")
        mock_embed_svc.embed_texts.assert_awaited_once_with(["Hello world"])
        mock_docs_repo.create_chunks.assert_called_once()
        mock_docs_repo.update_document_status.assert_any_call("doc1", "ready")
        mock_vec_idx.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tasks._ensure_vector_index")
    @patch("app.tasks.embedding_svc")
    @patch("app.tasks.documents_repo")
    @patch("app.tasks.chunk_document")
    @patch("app.tasks.parse_pdf")
    async def test_visual_diagnostics_persisted_after_parse(
        self, mock_parse_pdf, mock_chunk, mock_docs_repo, mock_embed_svc, mock_vec_idx
    ):
        from app.services.visual_extraction import VisualAsset, VisualExtractionDiagnostics

        diag = VisualExtractionDiagnostics()
        diag.register_asset(
            VisualAsset(page_number=1, asset_index=1, asset_type="picture", method="placeholder")
        )
        parsed = ParsedDocument(
            format="pdf",
            sections=[Section(heading="S", text="content", page_number=1)],
            visual_diagnostics=diag,
        )
        mock_parse_pdf.return_value = parsed
        mock_chunk.return_value = [
            Chunk(text="content", chunk_index=0, source_page=1, section_heading="S", token_count=3),
        ]
        mock_embed_svc.embed_texts = AsyncMock(return_value=[[0.5]])
        mock_docs_repo.create_chunks.return_value = [{"_key": "c1"}]

        await process_document("doc1", b"pdf-bytes", "application/pdf")

        mock_docs_repo.merge_document_user_metadata.assert_called_once_with(
            "doc1",
            {"visual_extraction": diag.to_metadata_dict()},
        )

    @pytest.mark.asyncio
    @patch("app.tasks._ensure_vector_index")
    @patch("app.tasks.embedding_svc")
    @patch("app.tasks.documents_repo")
    @patch("app.tasks.chunk_document")
    @patch("app.tasks.parse_markdown")
    async def test_empty_chunks_marks_ready_with_warning(
        self, mock_parse_md, mock_chunk, mock_docs_repo, mock_embed_svc, mock_vec_idx
    ):
        parsed = ParsedDocument(sections=[], title="Empty")
        mock_parse_md.return_value = parsed
        mock_chunk.return_value = []

        await process_document("doc1", b"", "text/markdown")

        mock_docs_repo.update_document_status.assert_any_call(
            "doc1", "ready", error_message="No content extracted"
        )
        mock_embed_svc.embed_texts.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.tasks.documents_repo")
    async def test_unsupported_mime_marks_failed(self, mock_docs_repo):
        await process_document("doc1", b"data", "application/octet-stream")

        mock_docs_repo.update_document_status.assert_any_call(
            "doc1", "failed", error_message="Unsupported MIME type: application/octet-stream"
        )

    @pytest.mark.asyncio
    @patch("app.tasks._ensure_vector_index")
    @patch("app.tasks.embedding_svc")
    @patch("app.tasks.documents_repo")
    @patch("app.tasks.chunk_document")
    @patch("app.tasks.parse_pdf")
    async def test_pdf_dispatches_to_parse_pdf(
        self, mock_parse_pdf, mock_chunk, mock_docs_repo, mock_embed_svc, mock_vec_idx
    ):
        parsed = ParsedDocument(sections=[Section(heading="S", text="content")])
        mock_parse_pdf.return_value = parsed
        mock_chunk.return_value = [
            Chunk(text="content", chunk_index=0, source_page=1, section_heading="S", token_count=3),
        ]
        mock_embed_svc.embed_texts = AsyncMock(return_value=[[0.5]])
        mock_docs_repo.create_chunks.return_value = [{"_key": "c1"}]

        await process_document("doc1", b"pdf-bytes", "application/pdf")

        # parse_pdf is called in a thread, so check chunk_document got the
        # parsed result plus the pre-computed category (CH.4).
        mock_chunk.assert_called_once_with(parsed, category="narrative")

    @pytest.mark.asyncio
    @patch("app.tasks._ensure_vector_index")
    @patch("app.tasks.embedding_svc")
    @patch("app.tasks.documents_repo")
    @patch("app.tasks.chunk_document")
    @patch("app.tasks.parse_markdown")
    async def test_all_chunk_inserts_fail_marks_failed(
        self, mock_parse_md, mock_chunk, mock_docs_repo, mock_embed_svc, mock_vec_idx
    ):
        parsed = ParsedDocument(sections=[Section(heading="S", text="text")])
        mock_parse_md.return_value = parsed
        mock_chunk.return_value = [
            Chunk(text="text", chunk_index=0, source_page=None, section_heading="S", token_count=2),
        ]
        mock_embed_svc.embed_texts = AsyncMock(return_value=[[0.1]])
        mock_docs_repo.create_chunks.return_value = []  # all inserts failed

        await process_document("doc1", b"# text", "text/markdown")

        # Should have been marked as failed
        calls = mock_docs_repo.update_document_status.call_args_list
        last_call = calls[-1]
        assert last_call[0][1] == "failed"
