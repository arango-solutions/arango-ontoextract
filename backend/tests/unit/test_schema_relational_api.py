"""Unit tests for relational schema extraction API routes.

Pins the wire contract for:
  * POST /api/v1/ontology/schema/relational/tables   (preview)
  * POST /api/v1/ontology/schema/relational/extract  (commit)

Patches at the service layer *as bound in the route module* so the routes are
exercised end-to-end without a live relational database or the optional
``relational-schema-analyzer`` library. See the mock-fidelity rule -- patch at
the usage site (``app.api.ontology.schema_relational``), not at the service
definition site.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

ROUTE_MODULE = "app.api.ontology.schema_relational"

client = TestClient(app)


def _conn_body(**overrides) -> dict:
    body = {
        "source_type": "postgresql",
        "url": "postgresql://root:secret@target/shop",
        "schema_name": "public",
    }
    body.update(overrides)
    return body


class TestPreviewRoute:
    def test_returns_service_payload(self):
        with patch(
            f"{ROUTE_MODULE}.list_relational_tables",
            return_value={
                "source_type": "postgresql",
                "schema_name": "public",
                "db_label": "shop",
                "server_version": "16.1",
                "dialect": "postgresql",
                "tables": [
                    {
                        "name": "users",
                        "is_view": False,
                        "comment": "people",
                        "column_count": 2,
                        "primary_key": ["id"],
                        "columns": [],
                        "foreign_keys": [],
                    }
                ],
                "table_count": 1,
                "view_count": 0,
                "foreign_key_count": 0,
            },
        ) as mock_list:
            resp = client.post("/api/v1/ontology/schema/relational/tables", json=_conn_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["db_label"] == "shop"
        assert body["table_count"] == 1
        assert body["tables"][0]["name"] == "users"
        mock_list.assert_called_once()
        called_cfg = mock_list.call_args.args[0]
        assert called_cfg.source_type == "postgresql"
        assert called_cfg.url == "postgresql://root:secret@target/shop"

    def test_missing_library_returns_501(self):
        with patch(
            f"{ROUTE_MODULE}.list_relational_tables",
            side_effect=RuntimeError("relational-schema-analyzer is not installed"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/tables", json=_conn_body())
        assert resp.status_code == 501
        assert "relational-schema-analyzer" in resp.json()["detail"]

    def test_value_error_returns_400(self):
        with patch(
            f"{ROUTE_MODULE}.list_relational_tables",
            side_effect=ValueError("bad source_type"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/tables", json=_conn_body())
        assert resp.status_code == 400

    def test_connection_error_returns_502(self):
        with patch(
            f"{ROUTE_MODULE}.list_relational_tables",
            side_effect=ConnectionError("target unreachable"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/tables", json=_conn_body())
        assert resp.status_code == 502

    def test_rejects_invalid_body(self):
        resp = client.post(
            "/api/v1/ontology/schema/relational/tables",
            json={"source_type": "postgresql"},  # missing url
        )
        assert resp.status_code == 422


class TestExtractRoute:
    def test_success_returns_service_payload(self):
        with patch(
            f"{ROUTE_MODULE}.extract_relational_schema",
            return_value={
                "run_id": "abc123",
                "status": "completed",
                "ontology_id": "relschema_shop_abc123",
                "import_stats": {"triple_count": 42},
                "provenance": {"mode": "relational"},
                "provenance_stamped": 7,
            },
        ) as mock_extract:
            resp = client.post(
                "/api/v1/ontology/schema/relational/extract",
                json=_conn_body(imports=["foaf"], ontology_label="Shop DB"),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "abc123"
        assert body["ontology_id"] == "relschema_shop_abc123"
        assert body["provenance_stamped"] == 7
        called_cfg = mock_extract.call_args.args[0]
        assert called_cfg.imports == ["foaf"]
        assert called_cfg.ontology_label == "Shop DB"

    def test_missing_library_returns_501(self):
        with patch(
            f"{ROUTE_MODULE}.extract_relational_schema",
            side_effect=RuntimeError("relational-schema-analyzer is not installed"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/extract", json=_conn_body())
        assert resp.status_code == 501

    def test_value_error_returns_400(self):
        with patch(
            f"{ROUTE_MODULE}.extract_relational_schema",
            side_effect=ValueError("bad cfg"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/extract", json=_conn_body())
        assert resp.status_code == 400

    def test_connection_error_returns_502(self):
        with patch(
            f"{ROUTE_MODULE}.extract_relational_schema",
            side_effect=ConnectionError("driver failed"),
        ):
            resp = client.post("/api/v1/ontology/schema/relational/extract", json=_conn_body())
        assert resp.status_code == 502
