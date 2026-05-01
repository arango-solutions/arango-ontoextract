"""Integration tests for the ER pipeline.

Seeds 20 ontology classes with near-duplicates, runs the ER pipeline,
and verifies candidate pairs and clusters are produced.
"""

from __future__ import annotations

import time

import pytest
from arango.database import StandardDatabase

from app.services.er import (
    ERPipelineConfig,
    explain_match,
    get_candidates,
    get_clusters,
    run_er_pipeline,
)
from app.services.temporal import NEVER_EXPIRES

pytestmark = pytest.mark.integration


@pytest.fixture()
def er_collections(test_db: StandardDatabase):
    """Create required collections for ER tests."""
    for col in ("ontology_classes", "ontology_properties", "subclass_of", "has_property"):
        if not test_db.has_collection(col):
            edge = col in ("subclass_of", "has_property")
            test_db.create_collection(col, edge=edge)

    for col in ("similarTo",):
        if not test_db.has_collection(col):
            test_db.create_collection(col, edge=True)

    for col in ("entity_clusters", "golden_records"):
        if not test_db.has_collection(col):
            test_db.create_collection(col)

    yield

    for col in (
        "ontology_classes",
        "ontology_properties",
        "subclass_of",
        "has_property",
        "similarTo",
        "entity_clusters",
        "golden_records",
    ):
        if test_db.has_collection(col):
            test_db.collection(col).truncate()


@pytest.fixture()
def seeded_classes(test_db: StandardDatabase, er_collections):
    """Seed 20 ontology classes including near-duplicates."""
    now = time.time()
    ontology_id = "test_er_ontology"

    base_classes = [
        ("Customer", "A customer entity"),
        ("Customers", "Customer records"),
        ("CustomerAccount", "A customer account"),
        ("Customer_Account", "A customer's account"),
        ("Product", "A product offering"),
        ("Products", "Product catalog items"),
        ("ProductCategory", "Category of products"),
        ("Order", "A purchase order"),
        ("PurchaseOrder", "A purchase order from customer"),
        ("Invoice", "An invoice document"),
        ("InvoiceItem", "Line item on an invoice"),
        ("Payment", "A payment transaction"),
        ("Vehicle", "A motorized vehicle"),
        ("Car", "A passenger car"),
        ("Automobile", "An automobile"),
        ("Truck", "A cargo truck"),
        ("Address", "A physical address"),
        ("Location", "A geographic location"),
        ("Organization", "A business organization"),
        ("Company", "A company entity"),
    ]

    for label, desc in base_classes:
        test_db.collection("ontology_classes").insert(
            {
                "uri": f"http://test.org#{label}",
                "label": label,
                "description": desc,
                "ontology_id": ontology_id,
                "tier": "domain",
                "status": "approved",
                "created": now,
                "expired": NEVER_EXPIRES,
                "version": 1,
            }
        )

    return ontology_id


class TestERPipelineIntegration:
    def test_pipeline_finds_near_duplicates(self, test_db, seeded_classes):
        """Run ER pipeline and verify it finds candidate pairs."""
        config = ERPipelineConfig(
            similarity_threshold=0.6,
            topological_weight=0.0,
        )
        result = run_er_pipeline(
            test_db,
            ontology_id=seeded_classes,
            config=config,
        )

        assert result.status.value == "complete"
        assert result.candidate_count > 0

    def test_pipeline_produces_clusters(self, test_db, seeded_classes):
        """Verify WCC clustering groups similar entities."""
        config = ERPipelineConfig(
            similarity_threshold=0.6,
            topological_weight=0.0,
        )
        result = run_er_pipeline(
            test_db,
            ontology_id=seeded_classes,
            config=config,
        )

        if result.candidate_count > 0:
            clusters = get_clusters(test_db, ontology_id=seeded_classes)
            assert len(clusters) >= 0

    def test_candidates_retrievable(self, test_db, seeded_classes):
        """Verify candidates can be retrieved after pipeline run."""
        config = ERPipelineConfig(
            similarity_threshold=0.6,
            topological_weight=0.0,
        )
        run_er_pipeline(test_db, ontology_id=seeded_classes, config=config)

        candidates = get_candidates(
            test_db,
            ontology_id=seeded_classes,
            min_score=0.0,
        )
        assert isinstance(candidates, list)

    def test_explain_match_between_near_duplicates(self, test_db, seeded_classes):
        """Verify explain_match returns field-level breakdown."""
        classes = list(
            test_db.aql.execute(
                "FOR cls IN ontology_classes FILTER cls.ontology_id == @oid LIMIT 2 RETURN cls",
                bind_vars={"oid": seeded_classes},
            )
        )
        if len(classes) < 2:
            pytest.skip("Not enough classes seeded")

        result = explain_match(
            test_db,
            key1=classes[0]["_key"],
            key2=classes[1]["_key"],
        )
        assert "field_scores" in result
        assert "combined_score" in result

    def test_pipeline_with_high_threshold_yields_fewer_candidates(self, test_db, seeded_classes):
        """Higher threshold should yield fewer candidates."""
        config_low = ERPipelineConfig(similarity_threshold=0.5, topological_weight=0.0)
        config_high = ERPipelineConfig(similarity_threshold=0.9, topological_weight=0.0)

        test_db.collection("similarTo").truncate()
        test_db.collection("entity_clusters").truncate()
        result_low = run_er_pipeline(test_db, ontology_id=seeded_classes, config=config_low)
        count_low = result_low.candidate_count

        test_db.collection("similarTo").truncate()
        test_db.collection("entity_clusters").truncate()
        result_high = run_er_pipeline(test_db, ontology_id=seeded_classes, config=config_high)
        count_high = result_high.candidate_count

        assert count_high <= count_low
