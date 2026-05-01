"""Unit tests for app.services.schema_extraction -- schema extraction from external ArangoDB."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.schema_extraction import (
    ExtractionStatus,
    SchemaExtractionConfig,
    _runs,
    _stub_extract_schema,
    extract_schema,
    get_extraction_status,
)


@pytest.fixture(autouse=True)
def _clear_runs():
    """Clear the module-level _runs dict before each test."""
    _runs.clear()
    yield
    _runs.clear()


def _make_config(**overrides) -> SchemaExtractionConfig:
    defaults = {
        "target_host": "http://localhost:8529",
        "target_db": "test_db",
        "target_user": "root",
        "target_password": "pass",
    }
    defaults.update(overrides)
    return SchemaExtractionConfig(**defaults)


# ---------------------------------------------------------------------------
# SchemaExtractionConfig
# ---------------------------------------------------------------------------


class TestSchemaExtractionConfig:
    def test_defaults(self):
        cfg = SchemaExtractionConfig(target_host="http://h:8529", target_db="db1")
        assert cfg.target_user == "root"
        assert cfg.target_password == ""
        assert cfg.use_llm_inference is False
        assert cfg.ontology_id is None
        assert cfg.extraction_source == "arango_graph_schema"
        assert cfg.verify_tls is True

    def test_custom_values(self):
        cfg = _make_config(ontology_id="custom", ontology_label="My Schema")
        assert cfg.ontology_id == "custom"
        assert cfg.ontology_label == "My Schema"


# ---------------------------------------------------------------------------
# get_extraction_status
# ---------------------------------------------------------------------------


class TestGetExtractionStatus:
    def test_raises_for_unknown_run(self):
        with pytest.raises(ValueError, match="not found"):
            get_extraction_status("nonexistent")

    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._stub_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_completed_run_includes_stats(self, mock_get_db, mock_stub, mock_mapper, mock_import):
        mock_get_db.return_value = MagicMock()
        mock_stub.return_value = "@prefix owl: <> ."
        mock_import.return_value = {"triple_count": 5, "imported": True}

        config = _make_config()
        result = extract_schema(config)
        run_id = result["run_id"]

        status = get_extraction_status(run_id)
        assert status["status"] == "completed"
        assert "import_stats" in status
        assert status["target_db"] == "test_db"


# ---------------------------------------------------------------------------
# extract_schema
# ---------------------------------------------------------------------------


class TestExtractSchema:
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._stub_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_stub_path_success(self, mock_get_db, mock_stub, mock_mapper, mock_import):
        mock_get_db.return_value = MagicMock()
        mock_stub.return_value = "@prefix owl: <http://www.w3.org/2002/07/owl#> ."
        mock_import.return_value = {"triple_count": 10, "imported": True}

        config = _make_config()
        result = extract_schema(config)

        assert result["status"] == "completed"
        assert "run_id" in result
        assert result["ontology_id"].startswith("schema_test_db_")
        assert result["provenance"]["mode"] == "stub"
        mock_stub.assert_called_once_with(config)
        mock_import.assert_called_once()

    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._stub_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_custom_ontology_id(self, mock_get_db, mock_stub, mock_mapper, mock_import):
        mock_get_db.return_value = MagicMock()
        mock_stub.return_value = "ttl"
        mock_import.return_value = {"imported": True}

        config = _make_config(ontology_id="my_custom_id")
        result = extract_schema(config)

        assert result["ontology_id"] == "my_custom_id"

    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._run_schema_mapper_extract")
    @patch("app.services.schema_extraction._try_import_schema_mapper")
    @patch("app.services.schema_extraction.get_db")
    def test_mapper_path_calls_run_schema_mapper_extract(
        self, mock_get_db, mock_try_mapper, mock_run_extract, mock_import
    ):
        mock_get_db.return_value = MagicMock()
        mock_try_mapper.return_value = (object(), object(), object(), object())
        mock_run_extract.return_value = (
            "@prefix owl: <> .",
            {"physical_schema_fingerprint": "fp1"},
        )
        mock_import.return_value = {"imported": True}
        config = _make_config()
        result = extract_schema(config)

        mock_run_extract.assert_called_once()
        assert mock_run_extract.call_args[0][0] is config
        assert result["status"] == "completed"
        assert result["provenance"]["physical_schema_fingerprint"] == "fp1"

    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch(
        "app.services.schema_extraction._stub_extract_schema", side_effect=ConnectionError("nope")
    )
    @patch("app.services.schema_extraction.get_db")
    def test_failure_sets_error(self, mock_get_db, mock_stub, mock_mapper):
        mock_get_db.return_value = MagicMock()
        config = _make_config()

        with pytest.raises(ConnectionError):
            extract_schema(config)

        # Verify the run was recorded with FAILED status
        assert len(_runs) == 1
        run = next(iter(_runs.values()))
        assert run.status == ExtractionStatus.FAILED
        assert run.error == "nope"


# ---------------------------------------------------------------------------
# _stub_extract_schema
# ---------------------------------------------------------------------------


class TestStubExtractSchema:
    def test_produces_turtle_with_classes_and_properties(self):
        """Test that the stub queries the target DB and creates OWL triples.

        Patch ``ArangoClient`` at its usage site (the function-local
        ``from arango.client import ArangoClient``) rather than the
        ``arango`` package re-export.
        """
        with patch("arango.client.ArangoClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_client.db.return_value = mock_db
            mock_db.collections.return_value = [
                {"name": "users", "system": False, "type": 2},
                {"name": "edges", "system": False, "type": 3},
                {"name": "_system", "system": True, "type": 2},
            ]

            config = _make_config()
            ttl = _stub_extract_schema(config)

        assert isinstance(ttl, str)
        assert "users" in ttl
        assert "edges" in ttl
        assert "_system" not in ttl
        assert mock_client.close.call_count >= 1
