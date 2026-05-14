"""Additional unit tests for document API route handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.documents import (
    _to_doc_response,
    _validate_mime,
    delete_document,
    get_chunks,
    get_document,
    get_document_ontologies,
    list_documents,
    update_document,
    upload_document,
)
from app.api.errors import ConflictError, ValidationError


def _upload_file(
    *,
    filename: str = "doc.pdf",
    content_type: str = "application/pdf",
    content: bytes = b"data",
) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        read=AsyncMock(return_value=content),
    )


class TestDocumentHelpers:
    def test_validate_mime_allows_markdown_by_extension(self):
        file = _upload_file(filename="note.md", content_type="")
        assert _validate_mime(file) == "text/markdown"

    def test_validate_mime_rejects_unsupported_type(self):
        file = _upload_file(filename="note.txt", content_type="text/plain")
        with pytest.raises(ValidationError):
            _validate_mime(file)

    def test_validate_mime_allows_pptx_by_declared_type(self):
        file = _upload_file(
            filename="deck.pptx",
            content_type=(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
        )
        assert _validate_mime(file).endswith("presentationml.presentation")

    def test_validate_mime_allows_pptx_by_extension_when_browser_lies(self):
        # Some browsers send octet-stream for Office files; the
        # extension fallback should still let the upload through.
        file = _upload_file(filename="deck.pptx", content_type="application/octet-stream")
        assert _validate_mime(file).endswith("presentationml.presentation")

    def test_validate_mime_allows_legacy_doc_by_declared_type(self):
        file = _upload_file(filename="memo.doc", content_type="application/msword")
        assert _validate_mime(file) == "application/msword"

    def test_validate_mime_allows_legacy_doc_by_extension(self):
        file = _upload_file(filename="memo.doc", content_type="")
        assert _validate_mime(file) == "application/msword"

    def test_validate_mime_extension_match_is_case_insensitive(self):
        file = _upload_file(filename="REPORT.PDF", content_type="application/octet-stream")
        assert _validate_mime(file) == "application/pdf"

    def test_to_doc_response_fills_defaults(self):
        result = _to_doc_response({"_key": "d1"})
        assert result["filename"] == ""
        assert result["status"] == "uploading"
        assert result["chunk_count"] == 0


class TestUploadDocument:
    @pytest.mark.asyncio
    async def test_upload_document_raises_on_duplicate_hash_when_prior_is_ready(self):
        # A duplicate of a fully-ingested doc (status=ready) should still
        # 409 -- we don't want users to accidentally clobber a working doc
        # by re-uploading identical content.
        file = _upload_file()
        with (
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch(
                "app.api.documents.documents_repo.find_document_by_hash",
                return_value={"_key": "d0", "status": "ready"},
            ),
            pytest.raises(ConflictError),
        ):
            await upload_document(file)

    @pytest.mark.asyncio
    async def test_upload_document_raises_on_duplicate_hash_when_status_unknown(self):
        # Defensive: a record without an explicit status (legacy / partial
        # write) is treated as a duplicate, not a retry. We only allow the
        # retry path when status is explicitly FAILED.
        file = _upload_file()
        with (
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch(
                "app.api.documents.documents_repo.find_document_by_hash",
                return_value={"_key": "d0"},  # no status field
            ),
            pytest.raises(ConflictError),
        ):
            await upload_document(file)

    @pytest.mark.asyncio
    async def test_upload_replaces_prior_failed_document(self):
        # Re-uploading the same file after a FAILED ingestion is the user's
        # natural recovery action -- discard the prior FAILED record and
        # its orphaned chunks, then proceed as a fresh upload. Without this
        # users hit an inscrutable 409 with no obvious next step.
        file = _upload_file()
        task = MagicMock()
        mock_create_task = MagicMock(side_effect=lambda coro: (coro.close(), task)[1])

        with (
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch(
                "app.api.documents.documents_repo.find_document_by_hash",
                return_value={"_key": "old_doc", "status": "failed"},
            ),
            patch(
                "app.api.documents.documents_repo.delete_chunks_for_document",
                return_value=16,
            ) as mock_delete_chunks,
            patch(
                "app.api.documents.documents_repo.hard_delete_document",
                return_value=True,
            ) as mock_hard_delete,
            patch(
                "app.api.documents.documents_repo.create_document",
                return_value={"_key": "new_doc", "filename": "doc.pdf", "status": "uploading"},
            ),
            patch("app.api.documents.asyncio.create_task", mock_create_task),
        ):
            result = await upload_document(file)

        # The prior FAILED record + chunks were cleaned up before the new
        # ingestion started -- so the user gets a fresh doc_id rather than
        # silently inheriting a half-broken state.
        mock_delete_chunks.assert_called_once_with("old_doc")
        mock_hard_delete.assert_called_once_with("old_doc")
        mock_create_task.assert_called_once()
        assert result == {"doc_id": "new_doc", "filename": "doc.pdf", "status": "uploading"}

    @pytest.mark.asyncio
    async def test_upload_document_creates_record_and_task(self):
        file = _upload_file()
        task = MagicMock()
        mock_create_task = MagicMock(side_effect=lambda coro: (coro.close(), task)[1])

        with (
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch("app.api.documents.documents_repo.find_document_by_hash", return_value=None),
            patch(
                "app.api.documents.documents_repo.create_document",
                return_value={"_key": "d1", "filename": "doc.pdf", "status": "uploading"},
            ),
            patch("app.api.documents.asyncio.create_task", mock_create_task),
        ):
            result = await upload_document(file, org_id="org1")

        mock_create_task.assert_called_once()
        task.add_done_callback.assert_called_once()
        assert result == {"doc_id": "d1", "filename": "doc.pdf", "status": "uploading"}


class TestDocumentRoutes:
    @pytest.mark.asyncio
    async def test_list_documents_delegates(self):
        expected = {"data": [{"_key": "d1"}], "cursor": None, "has_more": False, "total_count": 1}
        with patch(
            "app.api.documents.documents_repo.list_documents", return_value=expected
        ) as mock_list:
            result = await list_documents(
                limit=10,
                cursor=None,
                sort="filename",
                order="asc",
                org_id="org1",
                status="ready",
            )
        mock_list.assert_called_once_with(
            limit=10,
            cursor=None,
            sort_field="filename",
            sort_order="asc",
            org_id="org1",
            status="ready",
        )
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_document_maps_repo_result(self):
        doc = {"_key": "d1", "filename": "doc.md", "status": "ready"}
        with patch("app.api.documents.documents_repo.get_document", return_value=doc):
            result = await get_document("d1")
        assert result["_key"] == "d1"
        assert result["filename"] == "doc.md"

    @pytest.mark.asyncio
    async def test_get_chunks_checks_doc_and_delegates(self):
        expected = {"data": [{"_key": "c1"}], "cursor": None, "has_more": False, "total_count": 1}
        with (
            patch("app.api.documents.documents_repo.get_document", return_value={"_key": "d1"}),
            patch(
                "app.api.documents.documents_repo.get_chunks_for_document", return_value=expected
            ) as mock_chunks,
        ):
            result = await get_chunks("d1", limit=5, cursor="cur")
        mock_chunks.assert_called_once_with("d1", limit=5, cursor="cur")
        assert result is expected

    @pytest.mark.asyncio
    async def test_update_document_rejects_duplicate_hash_on_other_doc(self):
        file = _upload_file()
        with (
            patch(
                "app.api.documents.documents_repo.get_document",
                return_value={"_key": "d1", "filename": "old.pdf"},
            ),
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch(
                "app.api.documents.documents_repo.find_document_by_hash",
                return_value={"_key": "d2"},
            ),
            pytest.raises(ConflictError),
        ):
            await update_document("d1", file)

    @pytest.mark.asyncio
    async def test_update_document_restarts_processing(self):
        file = _upload_file(filename="new.pdf")
        task = MagicMock()
        mock_create_task = MagicMock(side_effect=lambda coro: (coro.close(), task)[1])
        with (
            patch(
                "app.api.documents.documents_repo.get_document",
                return_value={"_key": "d1", "filename": "old.pdf"},
            ),
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch("app.api.documents.documents_repo.find_document_by_hash", return_value=None),
            patch(
                "app.api.documents.documents_repo.get_document",
                side_effect=[
                    {"_key": "d1", "filename": "old.pdf"},
                    {"_key": "d1", "filename": "new.pdf", "status": "uploading"},
                ],
            ),
            patch(
                "app.api.documents.documents_repo.delete_chunks_for_document"
            ) as mock_delete_chunks,
            patch("app.api.documents.documents_repo.update_document_metadata") as mock_update_meta,
            patch("app.api.documents.documents_repo.update_document_status") as mock_update_status,
            patch("app.api.documents.asyncio.create_task", mock_create_task),
        ):
            result = await update_document("d1", file, org_id="org1")
        mock_delete_chunks.assert_called_once_with("d1")
        mock_update_meta.assert_called_once()
        mock_update_status.assert_called_once()
        assert result["filename"] == "new.pdf"

    @pytest.mark.asyncio
    async def test_get_document_ontologies_returns_query_results(self):
        db = MagicMock()
        db.has_collection.return_value = True
        ontologies = [{"_key": "onto1", "name": "Ontology"}]
        with (
            patch("app.api.documents.documents_repo.get_document", return_value={"_key": "d1"}),
            patch("app.api.documents.get_db", return_value=db),
            patch("app.api.documents.run_aql", return_value=ontologies),
        ):
            result = await get_document_ontologies("d1")
        assert result == {"doc_id": "d1", "ontologies": ontologies}

    @pytest.mark.asyncio
    async def test_delete_document_preview_returns_affected_ontologies(self):
        with (
            patch("app.api.documents.documents_repo.get_document", return_value={"_key": "d1"}),
            patch(
                "app.api.documents.documents_repo.delete_document",
                return_value={
                    "doc_id": "d1",
                    "status": "pending_confirmation",
                    "affected_ontologies": [{"_key": "onto1"}],
                    "message": "Pass ?confirm=true to proceed with deletion.",
                },
            ) as mock_delete,
        ):
            result = await delete_document("d1", confirm=False)
        assert result["status"] == "pending_confirmation"
        assert result["affected_ontologies"] == [{"_key": "onto1"}]
        mock_delete.assert_called_once_with("d1", confirm=False)

    @pytest.mark.asyncio
    async def test_delete_document_confirm_delegates_with_confirm_flag(self):
        with (
            patch("app.api.documents.documents_repo.get_document", return_value={"_key": "d1"}),
            patch(
                "app.api.documents.documents_repo.delete_document",
                return_value={"doc_id": "d1", "status": "deleted", "chunks_removed": 3},
            ) as mock_delete,
        ):
            result = await delete_document("d1", confirm=True)
        assert result["status"] == "deleted"
        assert result["doc_id"] == "d1"
        assert result["chunks_removed"] == 3
        mock_delete.assert_called_once_with("d1", confirm=True)
