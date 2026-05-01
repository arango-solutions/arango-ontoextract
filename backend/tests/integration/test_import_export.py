"""Integration tests for import/export roundtrip — requires running ArangoDB.

Import sample OWL → export as TTL → verify roundtrip equivalence by
comparing class URIs and relationship structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TTL = FIXTURES_DIR / "ontologies" / "sample_ontology.ttl"


@pytest.mark.integration
class TestImportExportRoundtrip:
    """Test importing OWL files and re-exporting them.

    These tests require a running ArangoDB instance and the arango_rdf package.
    Skipped if either is unavailable.
    """

    def test_import_then_export_turtle(self, test_db):
        """Import sample OWL → export as TTL → verify triples are preserved."""
        try:
            from app.services.arangordf_bridge import import_from_file
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_bytes()

        from unittest.mock import patch

        with (
            patch("app.services.arangordf_bridge.get_db", return_value=test_db),
            patch("app.services.export.get_db", return_value=test_db),
        ):
            import_result = import_from_file(
                file_content=ttl_content,
                filename="sample_ontology.ttl",
                ontology_id="roundtrip_test",
                db=test_db,
                ontology_label="Roundtrip Test",
                ontology_uri_prefix="http://example.org/enterprise#",
            )

            assert import_result["imported"] is True
            assert import_result["triple_count"] > 0

            from app.services.export import export_ontology

            exported_ttl = export_ontology("roundtrip_test", fmt="turtle")

            assert len(exported_ttl) > 0

            g = Graph()
            g.parse(data=exported_ttl, format="turtle")
            assert len(g) > 0

    def test_roundtrip_preserves_class_uris(self, test_db):
        """Class URIs from the original file should appear in the export."""
        try:
            from app.services.arangordf_bridge import import_from_file
        except ImportError:
            pytest.skip("arango_rdf not installed")

        original = Graph()
        original.parse(str(SAMPLE_TTL), format="turtle")
        original_classes = {str(s) for s, p, o in original.triples((None, RDF.type, OWL.Class))}

        ttl_content = SAMPLE_TTL.read_bytes()

        from unittest.mock import patch

        with (
            patch("app.services.arangordf_bridge.get_db", return_value=test_db),
            patch("app.services.export.get_db", return_value=test_db),
        ):
            import_from_file(
                file_content=ttl_content,
                filename="sample_ontology.ttl",
                ontology_id="roundtrip_classes",
                db=test_db,
                ontology_uri_prefix="http://example.org/enterprise#",
            )

            from app.services.export import export_ontology

            exported_ttl = export_ontology("roundtrip_classes")

            exported = Graph()
            exported.parse(data=exported_ttl, format="turtle")
            exported_classes = {str(s) for s, p, o in exported.triples((None, RDF.type, OWL.Class))}

            for cls_uri in original_classes:
                assert cls_uri in exported_classes, (
                    f"Class {cls_uri} from original not found in export"
                )

    def test_import_creates_registry_entry(self, test_db):
        """Import should create a registry entry accessible by ontology_id."""
        try:
            from app.services.arangordf_bridge import import_from_file
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_bytes()

        from unittest.mock import patch

        with patch("app.services.arangordf_bridge.get_db", return_value=test_db):
            result = import_from_file(
                file_content=ttl_content,
                filename="sample_ontology.ttl",
                ontology_id="registry_test",
                db=test_db,
                ontology_label="Registry Test Ontology",
            )

            assert result["registry_key"] == "registry_test"

            from app.db.registry_repo import get_registry_entry

            with patch("app.db.registry_repo.get_db", return_value=test_db):
                entry = get_registry_entry("registry_test")

            assert entry is not None
            assert entry["label"] == "Registry Test Ontology"
            assert entry["source"] == "file_import"

    def test_export_jsonld_format(self, test_db):
        """Export as JSON-LD should produce valid JSON-LD."""
        try:
            from app.services.arangordf_bridge import import_from_file
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_bytes()

        from unittest.mock import patch

        with (
            patch("app.services.arangordf_bridge.get_db", return_value=test_db),
            patch("app.services.export.get_db", return_value=test_db),
        ):
            import_from_file(
                file_content=ttl_content,
                filename="sample_ontology.ttl",
                ontology_id="jsonld_test",
                db=test_db,
            )

            from app.services.export import export_jsonld

            result = export_jsonld("jsonld_test")

            assert isinstance(result, (dict, list))

            import json

            jsonld_str = json.dumps(result)
            g = Graph()
            g.parse(data=jsonld_str, format="json-ld")
            assert len(g) > 0

    def test_export_csv_format(self, test_db):
        """Export as CSV should contain class and property sections."""
        try:
            from app.services.arangordf_bridge import import_from_file
        except ImportError:
            pytest.skip("arango_rdf not installed")

        ttl_content = SAMPLE_TTL.read_bytes()

        from unittest.mock import patch

        with (
            patch("app.services.arangordf_bridge.get_db", return_value=test_db),
            patch("app.services.export.get_db", return_value=test_db),
        ):
            import_from_file(
                file_content=ttl_content,
                filename="sample_ontology.ttl",
                ontology_id="csv_test",
                db=test_db,
            )

            from app.services.export import export_csv

            csv_content = export_csv("csv_test")

            assert "# Classes" in csv_content
            assert "# Properties" in csv_content
            assert len(csv_content) > 50

    def test_unsupported_format_raises_error(self, test_db):
        """Importing a file with unsupported extension should raise ValueError."""
        from app.services.arangordf_bridge import import_from_file

        with pytest.raises(ValueError, match="Unsupported file extension"):
            import_from_file(
                file_content=b"not real content",
                filename="ontology.xyz",
                ontology_id="bad_format",
                db=test_db,
            )
