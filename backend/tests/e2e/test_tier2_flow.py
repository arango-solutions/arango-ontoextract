"""E2E test: Full Tier 2 extraction + ER flow.

Simulates: upload org doc -> extract with domain context -> ER finds duplicates -> verify.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.models.ontology import (
    ExtractedClass,
    ExtractionClassification,
)

pytestmark = pytest.mark.e2e


class TestTier2ExtractionFlow:
    """End-to-end test for Tier 2 context-aware extraction with ER."""

    def test_org_ontology_selection(self, test_client: TestClient):
        """Org can select base ontologies for Tier 2 context."""
        response = test_client.get("/api/v1/ontology/orgs/test_org/ontologies")
        assert response.status_code == 200
        data = response.json()
        assert "selected_ontologies" in data

    def test_er_config_endpoint(self, test_client: TestClient):
        """ER config can be retrieved and updated."""
        response = test_client.get("/api/v1/er/config")
        assert response.status_code == 200
        config = response.json()
        assert "collection" in config
        assert "similarity_threshold" in config

    def test_er_config_update(self, test_client: TestClient):
        """ER config can be updated."""
        response = test_client.put(
            "/api/v1/er/config",
            json={"similarity_threshold": 0.8},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["similarity_threshold"] == 0.8

        test_client.put(
            "/api/v1/er/config",
            json={"similarity_threshold": 0.7},
        )

    def test_er_explain_endpoint(self, test_client: TestClient):
        """ER explain match endpoint returns field scores."""
        response = test_client.post(
            "/api/v1/er/explain",
            json={"key1": "nonexistent1", "key2": "nonexistent2"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "key1" in data

    def test_tier2_prompt_template_available(self):
        """Verify the Tier 2 prompt template is registered."""
        from app.extraction.prompts import get_template

        template = get_template("tier2_standard")
        assert template is not None
        assert "DOMAIN ONTOLOGY CONTEXT" in template.system_prompt
        assert "EXISTING" in template.system_prompt
        assert "EXTENSION" in template.system_prompt
        assert "NEW" in template.system_prompt

    def test_tier2_prompt_renders_with_context(self):
        """Verify Tier 2 prompt injects domain context."""
        from app.extraction.prompts import get_template

        template = get_template("tier2_standard")
        system_msg, user_msg = template.render(
            chunks_text="Some document text about vehicles.",
            domain_context="Domain: Automotive\nClasses:\n- Vehicle\n  - Car\n  - Truck",
            extra_vars={"pass_number": 1, "model_name": "test-model"},
        )
        assert "Automotive" in system_msg
        assert "Vehicle" in system_msg
        assert "Some document text" in user_msg

    def test_extraction_classification_model(self):
        """Verify ExtractedClass supports parent_domain_uri for EXTENSION."""
        cls = ExtractedClass(
            uri="http://local.org#ElectricCar",
            label="Electric Car",
            description="A battery-powered car",
            parent_uri="http://domain.org#Car",
            parent_domain_uri="http://domain.org#Car",
            classification=ExtractionClassification.EXTENSION,
            confidence=0.9,
        )
        assert cls.classification == ExtractionClassification.EXTENSION
        assert cls.parent_domain_uri == "http://domain.org#Car"

    def test_domain_context_serialization(self):
        """Verify domain context serializer produces compact text."""
        from app.services.ontology_context import serialize_domain_context

        db = MagicMock()
        db.has_collection.return_value = True

        call_count = {"n": 0}

        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://auto.org#Vehicle",
                "label": "Vehicle",
                "ontology_id": "auto",
            },
            {
                "_id": "ontology_classes/2",
                "_key": "2",
                "uri": "http://auto.org#Car",
                "label": "Car",
                "ontology_id": "auto",
            },
        ]
        edges = [{"_from": "ontology_classes/2", "_to": "ontology_classes/1"}]

        def execute_side(query, bind_vars=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return iter(["Automotive Ontology"])
            if call_count["n"] == 2:
                return iter(classes)
            if call_count["n"] == 3:
                return iter(edges)
            return iter([])

        db.aql.execute.side_effect = execute_side

        context = serialize_domain_context(db, ontology_id="auto")
        assert "Automotive Ontology" in context
        assert "Vehicle" in context
        assert "Car" in context

    def test_full_pipeline_has_er_and_filter_nodes(self):
        """Verify the extended pipeline includes ER and filter nodes."""
        from app.extraction.pipeline import build_pipeline

        graph = build_pipeline()
        node_names = set(graph.nodes.keys())
        assert "er_agent" in node_names
        assert "filter" in node_names
        assert "strategy_selector" in node_names
        assert "extractor" in node_names
        assert "consistency_checker" in node_names
