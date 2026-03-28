"""Integration tests for ArangoRDF import — requires running ArangoDB."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TTL = FIXTURES_DIR / "ontologies" / "sample_ontology.ttl"


@pytest.mark.integration
class TestArangoRDFImport:
    """Test importing OWL files via the ArangoRDF bridge.

    These tests require a running ArangoDB instance and the arango_rdf package.
    They are skipped if either is unavailable.
    """

    def test_import_sample_ontology(self, test_db):
        """Import sample OWL file and verify collections are populated."""
        try:
            from app.services.arangordf_bridge import import_owl_to_graph
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_text()

        stats = import_owl_to_graph(
            test_db,
            ttl_content=ttl_content,
            graph_name="test_import",
            ontology_id="test_ontology_001",
            ontology_uri_prefix="http://example.org/enterprise#",
        )

        assert stats["imported"] is True
        assert stats["triple_count"] > 0
        assert stats["graph_name"] == "test_import"

    def test_import_tags_documents_with_ontology_id(self, test_db):
        """After import, all documents should be tagged with ontology_id."""
        try:
            from app.services.arangordf_bridge import import_owl_to_graph
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_text()

        import_owl_to_graph(
            test_db,
            ttl_content=ttl_content,
            graph_name="test_tagged",
            ontology_id="tagged_ontology",
            ontology_uri_prefix="http://example.org/enterprise#",
        )

        for col_name in ["ontology_classes", "ontology_properties"]:
            if test_db.has_collection(col_name):
                untagged = list(
                    test_db.aql.execute(
                        f"FOR doc IN {col_name} "
                        "FILTER doc.ontology_id == null OR doc.ontology_id == '' "
                        "RETURN doc._key"
                    )
                )
                assert len(untagged) == 0, f"Untagged documents in {col_name}: {untagged}"

    def test_import_creates_named_graph(self, test_db):
        """Import should create a per-ontology named graph."""
        try:
            from app.services.arangordf_bridge import import_owl_to_graph
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_text()

        import_owl_to_graph(
            test_db,
            ttl_content=ttl_content,
            graph_name="test_graph_creation",
            ontology_id="graph_test",
        )

        assert test_db.has_graph("ontology_test_graph_creation")

    def test_import_is_idempotent(self, test_db):
        """Importing the same ontology twice should not fail."""
        try:
            from app.services.arangordf_bridge import import_owl_to_graph
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_text()

        stats1 = import_owl_to_graph(
            test_db,
            ttl_content=ttl_content,
            graph_name="test_idempotent",
            ontology_id="idem_test",
        )
        stats2 = import_owl_to_graph(
            test_db,
            ttl_content=ttl_content,
            graph_name="test_idempotent",
            ontology_id="idem_test",
        )

        assert stats1["imported"] is True
        assert stats2["imported"] is True
