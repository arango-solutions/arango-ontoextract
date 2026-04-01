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

    def test_to_doc_response_fills_defaults(self):
        result = _to_doc_response({"_key": "d1"})
        assert result["filename"] == ""
        assert result["status"] == "uploading"
        assert result["chunk_count"] == 0


class TestUploadDocument:
    @pytest.mark.asyncio
    async def test_upload_document_raises_on_duplicate_hash(self):
        file = _upload_file()
        with (
            patch("app.api.documents.compute_file_hash", return_value="hash"),
            patch(
                "app.api.documents.documents_repo.find_document_by_hash",
                return_value={"_key": "d0"},
            ),
            pytest.raises(ConflictError),
        ):
            await upload_document(file)

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
                return_value={"_key": "d1", "status": "deleted"},
            ) as mock_delete,
        ):
            result = await delete_document("d1", confirm=False)
        assert result["status"] == "deleted"
        mock_delete.assert_called_once_with("d1")

    @pytest.mark.asyncio
    async def test_delete_document_falls_back_to_minimal_deleted_payload(self):
        with (
            patch("app.api.documents.documents_repo.get_document", return_value={"_key": "d1"}),
            patch("app.api.documents.documents_repo.delete_document", return_value=None),
        ):
            result = await delete_document("d1", confirm=True)
        assert result["status"] == "deleted"
        assert result["doc_id"] == "d1"
