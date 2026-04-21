"""Unit tests for ontology creation and imports CRUD endpoints.

All database operations are mocked via monkeypatching.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

NEVER_EXPIRES = sys.maxsize


def _registry_doc(key: str = "test_ont", name: str = "Test Ontology", **extra):
    return {
        "_key": key,
        "_id": f"ontology_registry/{key}",
        "name": name,
        "label": name,
        "status": "active",
        "uri": f"http://example.org/ontology/{key}#",
        **extra,
    }


@pytest.fixture()
def _mock_db():
    db = MagicMock()
    db.has_collection.return_value = True
    db.aql.execute = MagicMock(side_effect=lambda *a, **kw: iter([]))
    return db


@pytest.fixture()
def client(_mock_db):
    with (
        patch("app.db.client.get_db", return_value=_mock_db),
        patch("app.api.ontology.get_db", return_value=_mock_db),
    ):
        from app.main import app

        yield TestClient(app)


# ── POST /create ──


class TestCreateOntology:
    def test_create_minimal(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="ont_abc123", name="My Ontology"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "My Ontology"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ontology_id"] == "ont_abc123"
        assert body["name"] == "My Ontology"
        assert body["imports_created"] == []
        assert body["warnings"] == []

    def test_create_with_custom_id(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="custom_id"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Custom", "ontology_id": "custom_id"},
            )

        assert resp.status_code == 201
        assert resp.json()["ontology_id"] == "custom_id"

    def test_create_conflict(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(key="existing"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Dup", "ontology_id": "existing"},
            )

        assert resp.status_code == 409

    def test_create_with_imports(self, client, _mock_db):
        call_count = {"n": 0}

        def mock_get_entry(key, *, db=None):
            if key == "target_ont":
                return _registry_doc(key="target_ont", name="Target")
            if call_count["n"] == 0:
                call_count["n"] += 1
                return None
            return _registry_doc()

        mock_edge = MagicMock(
            return_value={"_key": "e1", "_from": "a", "_to": "b"}
        )

        with patch(
            "app.db.registry_repo.get_registry_entry", side_effect=mock_get_entry
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="new_ont"),
        ), patch(
            "app.db.ontology_repo.create_edge", mock_edge
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Composed", "imports": ["target_ont"]},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert len(body["imports_created"]) == 1
        assert body["imports_created"][0]["target"] == "target_ont"

    def test_create_empty_name_rejected(self, client):
        resp = client.post("/api/v1/ontology/create", json={"name": ""})
        assert resp.status_code == 422


# ── GET /{id}/imports ──


class TestListImports:
    def test_list_imports_ok(self, client, _mock_db):
        imports_data = [
            {
                "edge_key": "e1",
                "target_id": "target_ont",
                "target_name": "Target",
                "target_uri": "http://example.org/",
                "import_iri": "http://example.org/",
                "created": 1000.0,
            }
        ]
        _mock_db.aql.execute = MagicMock(return_value=iter(imports_data))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(),
        ):
            resp = client.get("/api/v1/ontology/test_ont/imports")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["imports"]) == 1
        assert body["imports"][0]["target_id"] == "target_ont"

    def test_list_imports_not_found(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ):
            resp = client.get("/api/v1/ontology/nope/imports")

        assert resp.status_code == 404


# ── POST /{id}/imports ──


class TestAddImport:
    def test_add_import_ok(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter([]))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            side_effect=lambda k, **kw: _registry_doc(key=k),
        ), patch(
            "app.db.ontology_repo.create_edge",
            return_value={"_key": "edge1", "_from": "a", "_to": "b"},
        ):
            resp = client.post(
                "/api/v1/ontology/src_ont/imports",
                json={"target_ontology_id": "tgt_ont"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["from"] == "src_ont"
        assert body["to"] == "tgt_ont"

    def test_add_import_self_rejected(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(key="same"),
        ):
            resp = client.post(
                "/api/v1/ontology/same/imports",
                json={"target_ontology_id": "same"},
            )

        assert resp.status_code == 400

    def test_add_import_target_not_found(self, client, _mock_db):
        def mock_get(key, **kw):
            if key == "src":
                return _registry_doc(key="src")
            return None

        with patch(
            "app.db.registry_repo.get_registry_entry", side_effect=mock_get
        ):
            resp = client.post(
                "/api/v1/ontology/src/imports",
                json={"target_ontology_id": "missing"},
            )

        assert resp.status_code == 404

    def test_add_import_duplicate_rejected(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter(["existing_edge"]))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            side_effect=lambda k, **kw: _registry_doc(key=k),
        ):
            resp = client.post(
                "/api/v1/ontology/src/imports",
                json={"target_ontology_id": "tgt"},
            )

        assert resp.status_code == 409


# ── DELETE /{id}/imports/{target_id} ──


class TestRemoveImport:
    def test_remove_import_ok(self, client, _mock_db):
        edge_doc = {"_key": "e1", "_from": "a", "_to": "b", "expired": NEVER_EXPIRES}
        _mock_db.aql.execute = MagicMock(return_value=iter([edge_doc]))
        mock_col = MagicMock()
        _mock_db.collection.return_value = mock_col

        with patch("app.db.registry_repo.get_registry_entry", return_value=_registry_doc()):
            resp = client.delete("/api/v1/ontology/src/imports/tgt")

        assert resp.status_code == 200
        body = resp.json()
        assert body["removed"] == 1
        mock_col.update.assert_called_once()

    def test_remove_import_not_found(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter([]))

        resp = client.delete("/api/v1/ontology/src/imports/tgt")

        assert resp.status_code == 404


# ── POST /import (file upload) ──


class TestImportOntologyEndpoint:
    """Regression coverage for POST /api/v1/ontology/import.

    Real imports can take minutes (per-triple Arango writes against a remote
    cluster), so the endpoint now accepts the file, kicks the work off in a
    background task, and returns 202 with a ``job_status_url``. The matching
    GET /import/{id}/status endpoint is the client's polling target.
    """

    @pytest.fixture(autouse=True)
    def _clear_jobs(self):
        from app.api.ontology import _import_jobs

        _import_jobs.clear()
        yield
        _import_jobs.clear()

    def test_import_returns_202_and_registers_job(self, client):
        async def slow_to_thread(*_args, **_kwargs):
            import asyncio as _asyncio

            await _asyncio.sleep(0.05)
            return {"source": "file_import", "registry_key": "my_onto"}

        with patch(
            "app.api.ontology.registry_repo.get_registry_entry", return_value=None
        ), patch("app.api.ontology.asyncio.to_thread", side_effect=slow_to_thread):
            resp = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "my_onto", "ontology_label": "My"},
                files={"file": ("schema.ttl", b"@prefix : <http://x/> .\n", "text/turtle")},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["ontology_id"] == "my_onto"
        assert body["status"] == "running"
        assert body["job_status_url"] == "/api/v1/ontology/import/my_onto/status"
        assert body["filename"] == "schema.ttl"

    def test_import_then_status_reports_completion(self, client):
        captured = {}

        async def fake_to_thread(func, /, *args, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "source": "file_import",
                "registry_key": kwargs["ontology_id"],
                "filename": kwargs["filename"],
                "triple_count": 42,
            }

        with patch(
            "app.api.ontology.registry_repo.get_registry_entry", return_value=None
        ), patch("app.api.ontology.import_from_file"), patch(
            "app.api.ontology.asyncio.to_thread", side_effect=fake_to_thread
        ):
            resp = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "onto_a"},
                files={"file": ("a.ttl", b"data", "text/turtle")},
            )
            assert resp.status_code == 202

            status = client.get("/api/v1/ontology/import/onto_a/status")

        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert body["result"]["registry_key"] == "onto_a"
        assert body["result"]["triple_count"] == 42
        assert captured["kwargs"]["ontology_id"] == "onto_a"
        assert captured["kwargs"]["filename"] == "a.ttl"

    def test_import_status_reports_failure(self, client):
        async def boom(*_args, **_kwargs):
            raise ValueError("Unsupported file extension")

        with patch(
            "app.api.ontology.registry_repo.get_registry_entry", return_value=None
        ), patch("app.api.ontology.import_from_file"), patch(
            "app.api.ontology.asyncio.to_thread", side_effect=boom
        ):
            resp = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "bad_onto"},
                files={"file": ("bad.xyz", b"data", "application/octet-stream")},
            )
            assert resp.status_code == 202
            status = client.get("/api/v1/ontology/import/bad_onto/status")

        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "failed"
        assert body["error_kind"] == "validation"
        assert "Unsupported" in body["error"]

    def test_import_rejects_duplicate_while_running(self, client):
        async def pending(*_args, **_kwargs):
            import asyncio as _asyncio

            await _asyncio.sleep(5)
            return {"source": "file_import", "registry_key": "dup"}

        with patch(
            "app.api.ontology.registry_repo.get_registry_entry", return_value=None
        ), patch("app.api.ontology.import_from_file"), patch(
            "app.api.ontology.asyncio.to_thread", side_effect=pending
        ):
            first = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "dup"},
                files={"file": ("a.ttl", b"data", "text/turtle")},
            )
            second = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "dup"},
                files={"file": ("a.ttl", b"data", "text/turtle")},
            )

        assert first.status_code == 202
        assert second.status_code == 409

    def test_import_rejects_existing_registry_entry(self, client):
        with patch(
            "app.api.ontology.registry_repo.get_registry_entry",
            return_value=_registry_doc(key="existing"),
        ):
            resp = client.post(
                "/api/v1/ontology/import",
                params={"ontology_id": "existing"},
                files={"file": ("a.ttl", b"data", "text/turtle")},
            )
        assert resp.status_code == 409

    def test_import_status_fallback_to_registry(self, client):
        """If the job isn't in memory (e.g. after a restart) but the ontology
        exists in the registry, status should still report completed."""

        with patch(
            "app.api.ontology.registry_repo.get_registry_entry",
            return_value=_registry_doc(
                key="onto_restart",
                source_filename="schema.ttl",
                triple_count=17,
            ),
        ):
            resp = client.get("/api/v1/ontology/import/onto_restart/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["result"]["registry_key"] == "onto_restart"
        assert body["result"]["triple_count"] == 17
        assert body["result"]["filename"] == "schema.ttl"

    def test_import_status_unknown_id_returns_404(self, client):
        with patch(
            "app.api.ontology.registry_repo.get_registry_entry", return_value=None
        ):
            resp = client.get("/api/v1/ontology/import/nope/status")
        assert resp.status_code == 404
