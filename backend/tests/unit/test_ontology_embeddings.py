"""Unit tests for the ontology embeddings service (SF.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.services import ontology_embeddings as oe


class TestBuildEntityText:
    def test_label_and_description(self) -> None:
        txt = oe.build_entity_text({"label": "Account", "description": "a bank account"})
        assert txt == "Account — a bank account"

    def test_label_only(self) -> None:
        assert oe.build_entity_text({"label": "Account"}) == "Account"

    def test_empty_entity_is_empty_string(self) -> None:
        assert oe.build_entity_text({}) == ""
        assert oe.build_entity_text({"label": "  ", "description": ""}) == ""

    def test_definition_included_only_when_flag_on(self) -> None:
        ent = {"label": "Account", "description": "d", "definition": "a financial account"}
        with patch.object(oe.settings, "ontology_embedding_enrich_definitions", False):
            assert "financial" not in oe.build_entity_text(ent)
        with patch.object(oe.settings, "ontology_embedding_enrich_definitions", True):
            assert oe.build_entity_text(ent).endswith("a financial account")


class TestEmbedOntologyEntities:
    async def test_embeds_missing_and_updates(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        db.collection.return_value = col

        rows = [
            {"_key": "C1", "label": "Account", "description": "x", "has_embedding": False},
            {"_key": "C2", "label": "Loan", "description": "y", "has_embedding": True},
            {"_key": "C3", "label": "", "description": "", "has_embedding": False},  # no text
        ]
        with (
            patch.object(oe, "run_aql", return_value=iter(rows)),
            patch.object(oe, "embed_texts", new=AsyncMock(return_value=[[0.1, 0.2]])),
        ):
            counts = await oe.embed_ontology_entities(db, "ont1", collections=("ontology_classes",))

        # Only C1 is embedded: C2 already has an embedding, C3 has no text.
        assert counts == {"ontology_classes": 1}
        col.update.assert_called_once_with({"_key": "C1", "embedding": [0.1, 0.2]})

    async def test_only_missing_false_reembeds_all_with_text(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        db.collection.return_value = col
        rows = [
            {"_key": "C1", "label": "A", "description": "", "has_embedding": True},
            {"_key": "C2", "label": "B", "description": "", "has_embedding": True},
        ]
        with (
            patch.object(oe, "run_aql", return_value=iter(rows)),
            patch.object(oe, "embed_texts", new=AsyncMock(return_value=[[1.0], [2.0]])),
        ):
            counts = await oe.embed_ontology_entities(
                db, "ont1", collections=("ontology_classes",), only_missing=False
            )
        assert counts == {"ontology_classes": 2}
        assert col.update.call_count == 2

    async def test_missing_collection_contributes_zero(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        with patch.object(oe, "embed_texts", new=AsyncMock(return_value=[])) as embed:
            counts = await oe.embed_ontology_entities(db, "ont1", collections=("ontology_classes",))
        assert counts == {"ontology_classes": 0}
        embed.assert_not_awaited()


class TestEnsureEntityVectorIndex:
    def test_returns_true_when_index_already_exists(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = [
            {"name": "idx_ontology_classes_embedding_vector", "type": "vector"}
        ]
        db.collection.return_value = col
        assert oe.ensure_entity_vector_index(db, "ontology_classes") is True
        db._conn.send_request.assert_not_called()

    def test_creates_index_when_absent_and_docs_present(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = []
        db.collection.return_value = col
        with patch.object(oe, "run_aql", return_value=iter([100])):
            assert oe.ensure_entity_vector_index(db, "ontology_classes") is True
        db._conn.send_request.assert_called_once()

    def test_no_embedded_docs_skips_creation(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.indexes.return_value = []
        db.collection.return_value = col
        with patch.object(oe, "run_aql", return_value=iter([0])):
            assert oe.ensure_entity_vector_index(db, "ontology_classes") is False
        db._conn.send_request.assert_not_called()

    def test_missing_collection_returns_false(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert oe.ensure_entity_vector_index(db, "ontology_classes") is False


class TestSearchSimilar:
    def test_missing_collection_or_empty_query_returns_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert oe.search_similar(db, "ontology_classes", [0.1, 0.2]) == []
        db.has_collection.return_value = True
        assert oe.search_similar(db, "ontology_classes", []) == []

    def test_returns_ranked_rows(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        hits = [
            {"_key": "C2", "ontology_id": "b", "label": "Acct", "score": 0.98},
            {"_key": "C9", "ontology_id": "b", "label": "Ledger", "score": 0.71},
        ]
        with patch.object(oe, "run_aql", return_value=iter(hits)) as raq:
            out = oe.search_similar(db, "ontology_classes", [0.1, 0.2], k=5)
        assert out == hits
        # k threaded into bind vars
        assert raq.call_args.kwargs["bind_vars"]["k"] == 5
