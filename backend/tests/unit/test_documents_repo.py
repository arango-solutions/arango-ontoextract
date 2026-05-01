"""Unit tests for document repository delete flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import documents_repo


def _db_with_collections(*names: str) -> MagicMock:
    db = MagicMock()
    available = set(names)
    db.has_collection.side_effect = lambda name: name in available
    return db


class TestDeleteDocumentRepo:
    def test_delete_document_preview_returns_affected_ontologies(self):
        db = _db_with_collections("extracted_from", "ontology_registry")

        with patch(
            "app.db.documents_repo.run_aql",
            side_effect=[
                ["onto1"],
                [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
            ],
        ) as mock_run_aql:
            result = documents_repo.delete_document("d1", confirm=False, db=db)

        assert result == {
            "doc_id": "d1",
            "status": "pending_confirmation",
            "affected_ontologies": [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
            "message": "Pass ?confirm=true to proceed with deletion.",
        }
        assert mock_run_aql.call_count == 2

    def test_delete_document_confirm_expires_edges_and_deletes_document(self):
        db = _db_with_collections("extracted_from", "ontology_registry")

        with (
            patch(
                "app.db.documents_repo.run_aql",
                side_effect=[
                    ["onto1"],
                    [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
                    ["edge1", "edge2"],
                ],
            ) as mock_run_aql,
            patch(
                "app.db.documents_repo.delete_chunks_for_document", return_value=3
            ) as mock_delete_chunks,
            patch("app.db.documents_repo.hard_delete_document", return_value=True) as mock_delete,
        ):
            result = documents_repo.delete_document("d1", confirm=True, db=db)

        assert result == {
            "doc_id": "d1",
            "status": "deleted",
            "chunks_removed": 3,
            "affected_ontologies": [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
        }
        assert mock_run_aql.call_count == 3
        mock_delete_chunks.assert_called_once_with("d1", db=db)
        mock_delete.assert_called_once_with("d1", db=db)
