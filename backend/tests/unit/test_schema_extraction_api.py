"""Unit tests for schema extraction API routes (Stream 5 PR 1).

Pins the wire contract for:
  * POST /api/v1/ontology/schema/extract   (pre-existing; smoke only)
  * GET  /api/v1/ontology/schema/extract/{run_id} (pre-existing; smoke only)
  * POST /api/v1/ontology/schema/graphs    (NEW Stream 5 PR 1 S.6)

Patches at the service layer so the routes are exercised end-to-end
without a live ArangoDB connection.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

# IMPORTANT: patch the symbols as they live in ``app.api.ontology``
# (where the route looks them up), NOT as they live in
# ``app.services.schema_extraction``. ``from ... import extract_schema``
# in the router module created an independent binding; patching the
# service binding would not intercept the call. See the mock-fidelity
# rule -- "patch at the usage site".
ROUTE_MODULE = "app.api.ontology.schema_temporal"

client = TestClient(app)


def _conn_body(**overrides) -> dict:
    body = {
        "target_host": "http://target:8529",
        "target_db": "social",
        "target_user": "root",
        "target_password": "secret",
    }
    body.update(overrides)
    return body


class TestSchemaGraphsRoute:
    def test_returns_service_payload(self):
        with patch(
            f"{ROUTE_MODULE}.list_named_graphs",
            return_value={
                "target_host": "http://target:8529",
                "target_db": "social",
                "graphs": [
                    {
                        "name": "social_graph",
                        "edge_definitions": [
                            {
                                "edge_collection": "follows",
                                "from_vertex_collections": ["users"],
                                "to_vertex_collections": ["users"],
                            }
                        ],
                        "vertex_collections": ["users"],
                        "orphan_collections": [],
                    }
                ],
                "loose_collections": [{"name": "audit_log", "type": "document", "count": 123}],
            },
        ) as mock_list:
            resp = client.post("/api/v1/ontology/schema/graphs", json=_conn_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["target_db"] == "social"
        assert len(body["graphs"]) == 1
        assert body["graphs"][0]["edge_definitions"][0]["edge_collection"] == "follows"
        assert body["loose_collections"][0]["name"] == "audit_log"
        mock_list.assert_called_once()
        called_cfg = mock_list.call_args.args[0]
        assert called_cfg.target_db == "social"
        assert called_cfg.target_password == "secret"

    def test_value_error_returns_400(self):
        with patch(
            f"{ROUTE_MODULE}.list_named_graphs",
            side_effect=ValueError("bad host"),
        ):
            resp = client.post("/api/v1/ontology/schema/graphs", json=_conn_body())
        assert resp.status_code == 400

    def test_connection_error_returns_502(self):
        with patch(
            f"{ROUTE_MODULE}.list_named_graphs",
            side_effect=ConnectionError("target unreachable"),
        ):
            resp = client.post("/api/v1/ontology/schema/graphs", json=_conn_body())
        assert resp.status_code == 502

    def test_rejects_invalid_body(self):
        resp = client.post(
            "/api/v1/ontology/schema/graphs",
            json={"target_host": "http://h"},  # missing target_db
        )
        assert resp.status_code == 422


class TestSchemaExtractRoute:
    def test_success_returns_service_payload(self):
        with patch(
            f"{ROUTE_MODULE}.extract_schema",
            return_value={
                "run_id": "abc123",
                "status": "completed",
                "ontology_id": "schema_social_abc123",
                "import_stats": {"triple_count": 42},
                "provenance": {"mode": "direct"},
                "provenance_stamped": 7,
            },
        ) as mock_extract:
            resp = client.post(
                "/api/v1/ontology/schema/extract",
                json=_conn_body(imports=["foaf"], graph_names=["g1"]),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "abc123"
        assert body["provenance_stamped"] == 7
        called_cfg = mock_extract.call_args.args[0]
        assert called_cfg.imports == ["foaf"]
        assert called_cfg.graph_names == ["g1"]

    def test_value_error_returns_400(self):
        with patch(
            f"{ROUTE_MODULE}.extract_schema",
            side_effect=ValueError("bad cfg"),
        ):
            resp = client.post("/api/v1/ontology/schema/extract", json=_conn_body())
        assert resp.status_code == 400

    def test_other_error_returns_500(self):
        with patch(
            f"{ROUTE_MODULE}.extract_schema",
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post("/api/v1/ontology/schema/extract", json=_conn_body())
        assert resp.status_code == 500
