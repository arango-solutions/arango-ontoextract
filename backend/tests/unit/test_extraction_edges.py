"""Unit tests for extraction graph edge creation (has_chunk, produced_by)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

NEVER_EXPIRES: int = sys.maxsize


class TestCreateProducedByEdge:
    """Tests for _create_produced_by_edge."""

    def test_creates_edge_between_ontology_and_run(self):
        from app.services.extraction import _create_produced_by_edge

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_col = MagicMock()
        mock_db.collection.return_value = mock_col

        _create_produced_by_edge(mock_db, ontology_id="onto_1", run_id="run_abc")

        mock_col.insert.assert_called_once()
        call_args = mock_col.insert.call_args
        edge_doc = call_args[0][0]

        assert edge_doc["_from"] == "ontology_registry/onto_1"
        assert edge_doc["_to"] == "extraction_runs/run_abc"
        assert edge_doc["expired"] == NEVER_EXPIRES
        assert "created" in edge_doc

    def test_creates_collection_if_missing(self):
        from app.services.extraction import _create_produced_by_edge

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False
        mock_col = MagicMock()
        mock_db.collection.return_value = mock_col

        _create_produced_by_edge(mock_db, ontology_id="onto_1", run_id="run_abc")

        mock_db.create_collection.assert_called_once_with("produced_by", edge=True)

    def test_does_not_crash_on_insert_failure(self):
        from app.services.extraction import _create_produced_by_edge

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_col = MagicMock()
        mock_col.insert.side_effect = Exception("duplicate key")
        mock_db.collection.return_value = mock_col

        _create_produced_by_edge(mock_db, ontology_id="onto_1", run_id="run_abc")


class TestHasChunkEdges:
    """Tests for has_chunk edge creation within _materialize_to_graph."""

    def _make_mock_db(self, chunk_keys: list[str] | None = None):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        collections = {}
        for name in (
            "ontology_classes",
            "ontology_properties",
            "has_property",
            "subclass_of",
            "related_to",
            "extracted_from",
            "has_chunk",
            "produced_by",
        ):
            col = MagicMock()
            col.insert.return_value = {}
            collections[name] = col

        mock_db.collection.side_effect = lambda name: collections.get(name, MagicMock())

        if chunk_keys is not None:
            mock_db.aql.execute.return_value = iter(chunk_keys)
        else:
            mock_db.aql.execute.return_value = iter([])

        return mock_db, collections

    def test_creates_has_chunk_edges_for_each_chunk(self):
        from app.services.extraction import _materialize_to_graph

        mock_db, cols = self._make_mock_db(chunk_keys=["chunk_0", "chunk_1", "chunk_2"])

        mock_result = MagicMock()
        mock_result.classes = []

        _materialize_to_graph(
            mock_db,
            run_id="run_1",
            document_id="doc_1",
            ontology_id="onto_1",
            result=mock_result,
        )

        has_chunk_col = cols["has_chunk"]
        assert has_chunk_col.insert.call_count == 3

        inserted_edges = [call[0][0] for call in has_chunk_col.insert.call_args_list]
        for edge in inserted_edges:
            assert edge["_from"] == "documents/doc_1"
            assert edge["expired"] == NEVER_EXPIRES
            assert "created" in edge

        to_values = {e["_to"] for e in inserted_edges}
        assert to_values == {"chunks/chunk_0", "chunks/chunk_1", "chunks/chunk_2"}

    def test_no_has_chunk_edges_when_no_chunks_collection(self):
        from app.services.extraction import _materialize_to_graph

        mock_db = MagicMock()
        existing = {
            "ontology_classes",
            "ontology_properties",
            "has_property",
            "subclass_of",
            "related_to",
            "extracted_from",
            "has_chunk",
            "produced_by",
        }
        mock_db.has_collection.side_effect = lambda name: name in existing

        cols = {}
        for name in existing:
            cols[name] = MagicMock()
        mock_db.collection.side_effect = lambda name: cols.get(name, MagicMock())

        mock_db.has_collection.side_effect = lambda name: name != "chunks"

        mock_result = MagicMock()
        mock_result.classes = []

        _materialize_to_graph(
            mock_db,
            run_id="run_1",
            document_id="doc_1",
            ontology_id="onto_1",
            result=mock_result,
        )

        cols["has_chunk"].insert.assert_not_called()
