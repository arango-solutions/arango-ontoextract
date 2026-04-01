"""Unit tests for the ER pipeline configuration and orchestration."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from app.services.er import (
    ERFieldConfig,
    ERPipelineConfig,
    ERRunStatus,
    _blocking_tokens,
    _execute_blocking,
    _execute_scoring,
    _jaro_winkler_sim,
    _token_overlap,
    configure_blocking,
    configure_scoring,
    explain_match,
    get_config,
    run_er_pipeline,
    update_config,
)

NEVER_EXPIRES = sys.maxsize


class TestERPipelineConfig:
    def test_default_config(self):
        config = ERPipelineConfig()
        assert config.collection == "ontology_classes"
        assert len(config.field_configs) == 3
        assert config.topological_weight == 0.1

    def test_to_dict_roundtrip(self):
        config = ERPipelineConfig(
            ontology_id="test_onto",
            similarity_threshold=0.8,
        )
        d = config.to_dict()
        restored = ERPipelineConfig.from_dict(d)
        assert restored.ontology_id == "test_onto"
        assert restored.similarity_threshold == 0.8

    def test_from_dict_with_defaults(self):
        config = ERPipelineConfig.from_dict({})
        assert config.collection == "ontology_classes"
        assert len(config.blocking_strategies) == 2

    def test_custom_field_configs(self):
        config = ERPipelineConfig(
            field_configs=[
                ERFieldConfig("label", 0.5, "jaro_winkler"),
                ERFieldConfig("uri", 0.5, "exact"),
            ]
        )
        assert len(config.field_configs) == 2
        total_weight = sum(fc.weight for fc in config.field_configs)
        assert total_weight == 1.0


class TestConfigureBlocking:
    def test_bm25_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["bm25"])
        result = configure_blocking(config)
        assert len(result["strategies"]) == 1
        assert result["strategies"][0]["type"] == "BM25BlockingStrategy"

    def test_vector_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["vector"])
        result = configure_blocking(config)
        assert result["strategies"][0]["type"] == "VectorBlockingStrategy"

    def test_multi_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["bm25", "vector"])
        result = configure_blocking(config)
        assert len(result["strategies"]) == 2
        assert result["orchestrator"] == "MultiStrategyOrchestrator"


class TestConfigureScoring:
    def test_default_scoring(self):
        config = ERPipelineConfig()
        result = configure_scoring(config)
        assert result["type"] == "WeightedFieldSimilarity"
        assert len(result["fields"]) == 3
        assert result["topological_weight"] == 0.1

    def test_custom_threshold(self):
        config = ERPipelineConfig(similarity_threshold=0.9)
        result = configure_scoring(config)
        assert result["threshold"] == 0.9


class TestJaroWinklerSim:
    def test_identical_strings(self):
        assert _jaro_winkler_sim("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _jaro_winkler_sim("", "") == 0.0
        assert _jaro_winkler_sim("hello", "") == 0.0

    def test_similar_strings(self):
        sim = _jaro_winkler_sim("Customer", "Customers")
        assert sim > 0.9

    def test_different_strings(self):
        sim = _jaro_winkler_sim("apple", "orange")
        assert sim < 0.7

    def test_case_insensitive(self):
        assert _jaro_winkler_sim("Vehicle", "vehicle") == 1.0


class TestTokenOverlap:
    def test_identical_texts(self):
        assert _token_overlap("hello world", "hello world") == 1.0

    def test_empty_texts(self):
        assert _token_overlap("", "") == 0.0

    def test_partial_overlap(self):
        sim = _token_overlap("red car fast", "red truck slow")
        assert 0.0 < sim < 1.0

    def test_no_overlap(self):
        sim = _token_overlap("apple banana", "orange grape")
        assert sim == 0.0


class TestRunERPipeline:
    def test_pipeline_with_no_collection(self):
        db = MagicMock()
        db.has_collection.return_value = False

        result = run_er_pipeline(db, ontology_id="test")
        assert result.status == ERRunStatus.COMPLETE
        assert result.candidate_count == 0

    def test_pipeline_stores_run_status(self):
        db = MagicMock()
        db.has_collection.return_value = False

        result = run_er_pipeline(db, ontology_id="test")
        from app.services.er import get_run_status

        stored = get_run_status(result.run_id)
        assert stored is not None
        assert stored.run_id == result.run_id

    @patch("app.services.er.run_aql")
    def test_blocking_normalizes_plural_and_camelcase(self, mock_run_aql):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = [
            {"key": "c1", "label": "Customer", "uri": "http://ex#Customer"},
            {"key": "c2", "label": "Customers", "uri": "http://ex#Customers"},
            {"key": "c3", "label": "CustomerAccount", "uri": "http://ex#CustomerAccount"},
            {"key": "c4", "label": "Customer_Account", "uri": "http://ex#Customer_Account"},
        ]

        pairs = _execute_blocking(db, "onto1", ERPipelineConfig())

        assert ("c1", "c2") in pairs
        assert ("c3", "c4") in pairs

    @patch("app.services.er.compute_topological_similarity", return_value=0.0)
    @patch("app.services.er._get_class_doc")
    def test_scoring_does_not_penalize_nonmatching_exact_uri(
        self,
        mock_get_class_doc,
        mock_topology,
    ):
        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_class_doc.side_effect = [
            {
                "_key": "c1",
                "label": "Customer",
                "description": "A customer account",
                "uri": "http://ex#Customer",
            },
            {
                "_key": "c2",
                "label": "Customers",
                "description": "Customer account records",
                "uri": "http://ex#Customers",
            },
        ]

        scored = _execute_scoring(
            db,
            [("c1", "c2")],
            ERPipelineConfig(similarity_threshold=0.6, topological_weight=0.0),
        )

        assert len(scored) == 1
        assert scored[0]["combined_score"] >= 0.6


class TestBlockingTokens:
    def test_splits_camelcase_and_singularizes(self):
        tokens = _blocking_tokens("CustomerAccounts")

        assert "customer" in tokens
        assert "accounts" in tokens
        assert "account" in tokens


class TestExplainMatch:
    def test_missing_classes(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([])

        result = explain_match(db, key1="k1", key2="k2")
        assert "error" in result

    def test_explain_with_classes(self):
        db = MagicMock()
        db.has_collection.return_value = True

        call_count = {"n": 0}

        def execute_side(query, bind_vars=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return iter([{
                    "_key": f"k{call_count['n']}",
                    "_id": f"ontology_classes/k{call_count['n']}",
                    "label": f"Label{call_count['n']}",
                    "description": f"Description of entity {call_count['n']}",
                    "uri": f"http://ex.org#Entity{call_count['n']}",
                }])
            return iter([])

        db.aql.execute.side_effect = execute_side

        with patch("app.services.er.compute_topological_similarity", return_value=0.5):
            result = explain_match(db, key1="k1", key2="k2")

        assert "field_scores" in result
        assert "combined_score" in result
        assert result["combined_score"] > 0


class TestUpdateConfig:
    def test_update_preserves_defaults(self):
        updated = update_config({"similarity_threshold": 0.9})
        assert updated.similarity_threshold == 0.9
        assert updated.collection == "ontology_classes"

    def test_get_config_returns_current(self):
        update_config({"similarity_threshold": 0.75})
        config = get_config()
        assert config.similarity_threshold == 0.75
        update_config({"similarity_threshold": 0.7})
