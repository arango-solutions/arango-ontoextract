"""Unit tests for app.services.ontology -- staging graph management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.ontology import ExtractionResult
from app.services.ontology import create_staging_graph, get_staging_graph, promote_staging

# ---------------------------------------------------------------------------
# create_staging_graph
# ---------------------------------------------------------------------------


class TestCreateStagingGraph:
    @patch("app.services.ontology.import_owl_to_graph")
    @patch("app.services.ontology.extraction_to_owl")
    def test_creates_graph_and_returns_stats(self, mock_to_owl, mock_import):
        mock_to_owl.return_value = "@prefix owl: <http://www.w3.org/2002/07/owl#> ."
        mock_import.return_value = {
            "graph_name": "staging_run1",
            "ontology_id": "extraction_run1",
            "triple_count": 10,
            "imported": True,
        }
        extraction = ExtractionResult(classes=[], pass_number=1, model="test")
        db = MagicMock()

        result = create_staging_graph(
            db, run_id="run1", extraction_result=extraction, ontology_uri="http://example.org"
        )

        mock_to_owl.assert_called_once_with(extraction, ontology_uri="http://example.org")
        mock_import.assert_called_once_with(
            db,
            ttl_content=mock_to_owl.return_value,
            graph_name="staging_run1",
            ontology_id="extraction_run1",
        )
        assert result["staging_graph_id"] == "staging_run1"
        assert result["ontology_id"] == "extraction_run1"
        assert result["imported"] is True

    @patch("app.services.ontology.import_owl_to_graph")
    @patch("app.services.ontology.extraction_to_owl")
    def test_uses_get_db_when_db_is_none(self, mock_to_owl, mock_import):
        mock_to_owl.return_value = "ttl"
        mock_import.return_value = {"graph_name": "g", "imported": True}
        extraction = ExtractionResult(classes=[], pass_number=1, model="test")

        with patch("app.services.ontology.get_db") as mock_get_db:
            mock_get_db.return_value = MagicMock()
            create_staging_graph(run_id="run2", extraction_result=extraction)

        mock_get_db.assert_called_once()


# ---------------------------------------------------------------------------
# get_staging_graph
# ---------------------------------------------------------------------------


class TestGetStagingGraph:
    @patch("app.services.ontology.run_aql")
    def test_returns_classes_properties_edges(self, mock_aql):
        db = MagicMock()
        db.has_collection.return_value = True

        class_doc = {"_key": "Person", "label": "Person", "ontology_id": "extraction_r1"}
        prop_doc = {"_key": "name", "label": "name", "ontology_id": "extraction_r1"}
        edge_doc = {"_from": "ontology_classes/Person", "_to": "ontology_classes/Animal"}

        # run_aql: classes, three property collections, then each edge collection
        mock_aql.side_effect = [
            [class_doc],
            [prop_doc],
            [],
            [],
            [edge_doc],
            [],
            [],
            [],
            [],
            [],
            [],
        ]

        result = get_staging_graph(db, run_id="r1")

        assert result["run_id"] == "r1"
        assert result["ontology_id"] == "extraction_r1"
        assert len(result["classes"]) == 1
        assert len(result["properties"]) == 1
        assert len(result["edges"]) == 1

    @patch("app.services.ontology.run_aql")
    def test_handles_missing_collections(self, mock_aql):
        db = MagicMock()
        db.has_collection.return_value = False

        result = get_staging_graph(db, run_id="r2")

        assert result["classes"] == []
        assert result["properties"] == []
        assert result["edges"] == []
        mock_aql.assert_not_called()


# ---------------------------------------------------------------------------
# promote_staging (stub)
# ---------------------------------------------------------------------------


class TestPromoteStaging:
    def test_returns_not_implemented_stub(self):
        db = MagicMock()
        result = promote_staging(db, run_id="r1")

        assert result["run_id"] == "r1"
        assert result["status"] == "not_implemented"
        assert result["promoted"] == 0
