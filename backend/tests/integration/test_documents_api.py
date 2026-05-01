"""Integration tests for the documents API endpoints.

Uses FastAPI's TestClient with mocked async processing.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_doc(
    key: str = "doc1",
    filename: str = "test.pdf",
    status: str = "ready",
) -> dict:
    return {
        "_key": key,
        "_id": f"documents/{key}",
        "filename": filename,
        "mime_type": "application/pdf",
        "org_id": None,
        "status": status,
        "upload_date": "2026-03-27T12:00:00+00:00",
        "chunk_count": 5,
        "metadata": {},
        "file_hash": "abc123",
    }


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload
# ---------------------------------------------------------------------------


class TestUploadDocument:
    @patch("app.api.documents.process_document", new_callable=AsyncMock)
    @patch("app.api.documents.documents_repo")
    def test_upload_success(
        self,
        mock_repo: MagicMock,
        mock_process: AsyncMock,
        test_client,
    ):
        mock_repo.find_document_by_hash.return_value = None
        mock_repo.create_document.return_value = _make_mock_doc(status="uploading")

        pdf_content = b"%PDF-1.4 fake content"
        files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data["doc_id"] == "doc1"
        assert data["status"] == "uploading"
        mock_repo.create_document.assert_called_once()

    @patch("app.api.documents.documents_repo")
    def test_upload_duplicate_returns_409(self, mock_repo: MagicMock, test_client):
        mock_repo.find_document_by_hash.return_value = _make_mock_doc()

        pdf_content = b"%PDF-1.4 fake content"
        files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_upload_unsupported_type_returns_error(self, test_client):
        files = {"file": ("test.exe", io.BytesIO(b"binary"), "application/octet-stream")}
        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/documents/
# ---------------------------------------------------------------------------


class TestListDocuments:
    @patch("app.api.documents.documents_repo")
    def test_list_returns_paginated(self, mock_repo: MagicMock, test_client):
        from app.models.common import PaginatedResponse

        mock_repo.list_documents.return_value = PaginatedResponse(
            data=[_make_mock_doc()],
            cursor=None,
            has_more=False,
            total_count=1,
        )

        response = test_client.get("/api/v1/documents")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["total_count"] == 1
        assert len(data["data"]) == 1


# ---------------------------------------------------------------------------
# GET /api/v1/documents/{doc_id}
# ---------------------------------------------------------------------------


class TestGetDocument:
    @patch("app.api.documents.documents_repo")
    def test_get_existing(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = _make_mock_doc()

        response = test_client.get("/api/v1/documents/doc1")
        assert response.status_code == 200
        data = response.json()
        assert data["_key"] == "doc1"

    @patch("app.api.documents.documents_repo")
    def test_get_not_found(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = None

        response = test_client.get("/api/v1/documents/nonexistent")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ENTITY_NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /api/v1/documents/{doc_id}/chunks
# ---------------------------------------------------------------------------


class TestGetChunks:
    @patch("app.api.documents.documents_repo")
    def test_get_chunks_for_doc(self, mock_repo: MagicMock, test_client):
        from app.models.common import PaginatedResponse

        mock_repo.get_document.return_value = _make_mock_doc()
        mock_repo.get_chunks_for_document.return_value = PaginatedResponse(
            data=[
                {
                    "_key": "c1",
                    "doc_id": "doc1",
                    "text": "chunk text",
                    "chunk_index": 0,
                    "token_count": 5,
                }
            ],
            cursor=None,
            has_more=False,
            total_count=1,
        )

        response = test_client.get("/api/v1/documents/doc1/chunks")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1

    @patch("app.api.documents.documents_repo")
    def test_chunks_404_for_missing_doc(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = None

        response = test_client.get("/api/v1/documents/missing/chunks")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/documents/{doc_id}
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    @patch("app.api.documents.documents_repo")
    def test_delete_preview_requires_confirmation(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = _make_mock_doc()
        mock_repo.delete_document.return_value = {
            "doc_id": "doc1",
            "status": "pending_confirmation",
            "affected_ontologies": [{"_key": "onto1"}],
            "message": "Pass ?confirm=true to proceed with deletion.",
        }

        response = test_client.delete("/api/v1/documents/doc1")
        assert response.status_code == 200
        assert response.json()["status"] == "pending_confirmation"
        mock_repo.delete_document.assert_called_once_with("doc1", confirm=False)

    @patch("app.api.documents.documents_repo")
    def test_delete_confirm_executes_delete(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = _make_mock_doc()
        mock_repo.delete_document.return_value = {
            "doc_id": "doc1",
            "status": "deleted",
            "chunks_removed": 5,
            "affected_ontologies": [{"_key": "onto1"}],
        }

        response = test_client.delete("/api/v1/documents/doc1?confirm=true")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
        assert response.json()["chunks_removed"] == 5
        mock_repo.delete_document.assert_called_once_with("doc1", confirm=True)

    @patch("app.api.documents.documents_repo")
    def test_delete_not_found(self, mock_repo: MagicMock, test_client):
        mock_repo.get_document.return_value = None

        response = test_client.delete("/api/v1/documents/missing")
        assert response.status_code == 404
