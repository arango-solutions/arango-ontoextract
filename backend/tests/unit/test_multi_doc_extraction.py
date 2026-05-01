"""Unit tests for multi-document extraction and incremental extraction (G.1/G.2)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

NEVER_EXPIRES: int = sys.maxsize


class TestNormalizeDocIds:
    """Tests for _normalize_doc_ids helper."""

    def test_single_document_id(self):
        from app.services.extraction import _normalize_doc_ids

        result = _normalize_doc_ids(document_id="doc_a")
        assert result == ["doc_a"]

    def test_multiple_document_ids(self):
        from app.services.extraction import _normalize_doc_ids

        result = _normalize_doc_ids(document_ids=["doc_a", "doc_b"])
        assert result == ["doc_a", "doc_b"]

    def test_both_singular_and_plural(self):
        from app.services.extraction import _normalize_doc_ids

        result = _normalize_doc_ids(document_id="doc_x", document_ids=["doc_a", "doc_b"])
        assert result == ["doc_x", "doc_a", "doc_b"]

    def test_dedup_when_singular_in_plural(self):
        from app.services.extraction import _normalize_doc_ids

        result = _normalize_doc_ids(document_id="doc_a", document_ids=["doc_a", "doc_b"])
        assert result == ["doc_a", "doc_b"]

    def test_returns_empty_when_neither(self):
        from app.services.extraction import _normalize_doc_ids

        result = _normalize_doc_ids()
        assert result == []


class TestCreateRunRecordMultiDoc:
    """Tests for multi-doc create_run_record."""

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_stores_doc_ids_list(self, mock_get_db, mock_get_col, mock_load):
        from app.services.extraction import create_run_record

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col

        record = create_run_record(
            mock_db,
            document_ids=["doc1", "doc2", "doc3"],
        )

        assert record["doc_ids"] == ["doc1", "doc2", "doc3"]
        assert record["doc_id"] == "doc1"
        mock_col.insert.assert_called_once()

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_backward_compat_single_doc(self, mock_get_db, mock_get_col, mock_load):
        from app.services.extraction import create_run_record

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col

        record = create_run_record(mock_db, document_id="doc_abc")

        assert record["doc_ids"] == ["doc_abc"]
        assert record["doc_id"] == "doc_abc"

    @patch("app.services.extraction._load_document_chunks", return_value=[])
    @patch("app.services.extraction._get_collection")
    @patch("app.services.extraction.get_db")
    def test_stores_target_ontology_id(self, mock_get_db, mock_get_col, mock_load):
        from app.services.extraction import create_run_record

        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col

        record = create_run_record(
            mock_db,
            document_id="doc1",
            target_ontology_id="onto_existing",
        )

        assert record["target_ontology_id"] == "onto_existing"

    def test_raises_when_no_docs(self):
        from app.services.extraction import create_run_record

        with pytest.raises(ValueError, match="At least one document ID"):
            create_run_record(MagicMock())


class TestUpdateExistingOntology:
    """Tests for _update_existing_ontology (G.2 incremental extraction)."""

    @patch("app.db.registry_repo.get_registry_entry")
    @patch("app.db.registry_repo.update_registry_entry")
    def test_updates_counts_and_run_id(self, mock_update, mock_get):
        from app.services.extraction import _update_existing_ontology

        mock_get.return_value = {
            "_key": "onto_1",
            "class_count": 5,
            "property_count": 10,
        }
        mock_update.return_value = {}

        result_mock = MagicMock()
        result_mock.classes = [
            MagicMock(properties=["p1", "p2"]),
            MagicMock(properties=["p3"]),
        ]

        oid = _update_existing_ontology(
            MagicMock(),
            ontology_id="onto_1",
            run_id="run_new",
            result=result_mock,
        )

        assert oid == "onto_1"
        mock_update.assert_called_once_with(
            "onto_1",
            {
                "class_count": 7,
                "property_count": 13,
                "extraction_run_id": "run_new",
            },
        )

    @patch("app.db.registry_repo.get_registry_entry")
    def test_returns_none_when_ontology_not_found(self, mock_get):
        from app.services.extraction import _update_existing_ontology

        mock_get.return_value = None

        oid = _update_existing_ontology(
            MagicMock(),
            ontology_id="missing",
            run_id="run_x",
            result=MagicMock(),
        )

        assert oid is None


class TestResolveDocIds:
    """Tests for API-level _resolve_doc_ids."""

    @patch("app.api.extraction.get_db")
    def test_single_doc_field(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db

        from app.api.extraction import StartRunRequest, _resolve_doc_ids

        req = StartRunRequest(document_id="abc")
        assert _resolve_doc_ids(req) == ["abc"]

    @patch("app.api.extraction.get_db")
    def test_multi_doc_field(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db

        from app.api.extraction import StartRunRequest, _resolve_doc_ids

        req = StartRunRequest(document_ids=["a", "b"])
        assert _resolve_doc_ids(req) == ["a", "b"]

    @patch("app.api.extraction.get_db")
    def test_both_fields_merged(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_get_db.return_value = mock_db

        from app.api.extraction import StartRunRequest, _resolve_doc_ids

        req = StartRunRequest(document_id="x", document_ids=["y", "z"])
        assert _resolve_doc_ids(req) == ["x", "y", "z"]

    def test_raises_when_empty(self):
        from fastapi import HTTPException

        from app.api.extraction import StartRunRequest, _resolve_doc_ids

        req = StartRunRequest()
        with pytest.raises(HTTPException) as exc_info:
            _resolve_doc_ids(req)
        assert exc_info.value.status_code == 422
