"""Unit tests for ontology CRUD API endpoints (K.3-K.6b).

All database operations are mocked via monkeypatching of ontology_repo.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

NEVER_EXPIRES = sys.maxsize


@pytest.fixture()
def _mock_db():
    """Patch ``get_db`` so endpoints never touch a real database."""
    db = MagicMock()
    db.has_collection.return_value = True

    def _execute(query, bind_vars=None):
        return iter([])

    db.aql.execute = MagicMock(side_effect=_execute)
    return db


@pytest.fixture()
def client(_mock_db):
    """TestClient with all DB / repo functions patched."""
    with (
        patch("app.db.client.get_db", return_value=_mock_db),
        patch("app.api.ontology.get_db", return_value=_mock_db),
    ):
        from app.main import app

        yield TestClient(app)


def _class_doc(key="Person", label="Person", ontology_id="test_onto"):
    return {
        "_key": key,
        "_id": f"ontology_classes/{key}",
        "uri": f"http://example.org/ontology/{ontology_id}#{key.lower()}",
        "label": label,
        "description": "",
        "ontology_id": ontology_id,
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
        "rdf_type": "owl:Class",
        "created": 1000.0,
        "expired": NEVER_EXPIRES,
        "version": 1,
    }


def _prop_doc(key="Person_name", label="name", ontology_id="test_onto"):
    return {
        "_key": key,
        "_id": f"ontology_properties/{key}",
        "uri": f"http://example.org/ontology/{ontology_id}#{key}",
        "label": label,
        "description": "",
        "ontology_id": ontology_id,
        "domain_class": "Person",
        "range": "xsd:string",
        "property_type": "datatype",
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
        "created": 1000.0,
        "expired": NEVER_EXPIRES,
        "version": 1,
    }


class TestDeleteOntology:
    def test_confirm_deprecates_registry_entry_by_default(self, client):
        with (
            patch("app.api.ontology.registry_repo") as registry_repo,
            patch("app.services.ontology_graphs.delete_ontology_graph", return_value=True),
        ):
            registry_repo.get_registry_entry.return_value = {
                "_key": "test_onto",
                "name": "Test Ontology",
                "status": "active",
            }

            resp = client.delete("/api/v1/ontology/library/test_onto?confirm=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deprecated"
        assert data["registry_deleted"] is False
        registry_repo.deprecate_registry_entry.assert_called_once_with("test_onto")
        registry_repo.delete_registry_entry.assert_not_called()

    def test_hard_delete_removes_registry_entry(self, client):
        with (
            patch("app.api.ontology.registry_repo") as registry_repo,
            patch("app.services.ontology_graphs.delete_ontology_graph", return_value=True),
        ):
            registry_repo.get_registry_entry.return_value = {
                "_key": "test_onto",
                "name": "Test Ontology",
                "status": "active",
            }
            registry_repo.delete_registry_entry.return_value = True

            resp = client.delete("/api/v1/ontology/library/test_onto?confirm=true&hard_delete=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["registry_deleted"] is True
        registry_repo.delete_registry_entry.assert_called_once_with("test_onto")
        registry_repo.deprecate_registry_entry.assert_not_called()

    def test_hard_delete_removes_already_deprecated_registry_entry(self, client):
        with (
            patch("app.api.ontology.registry_repo") as registry_repo,
            patch("app.services.ontology_graphs.delete_ontology_graph", return_value=False),
        ):
            registry_repo.get_registry_entry.return_value = {
                "_key": "test_onto",
                "name": "Test Ontology",
                "status": "deprecated",
            }
            registry_repo.delete_registry_entry.return_value = True

            resp = client.delete("/api/v1/ontology/library/test_onto?confirm=true&hard_delete=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["registry_deleted"] is True
        registry_repo.delete_registry_entry.assert_called_once_with("test_onto")
        registry_repo.deprecate_registry_entry.assert_not_called()

    def test_soft_delete_already_deprecated_still_returns_400(self, client):
        with patch("app.api.ontology.registry_repo") as registry_repo:
            registry_repo.get_registry_entry.return_value = {
                "_key": "test_onto",
                "name": "Test Ontology",
                "status": "deprecated",
            }

            resp = client.delete("/api/v1/ontology/library/test_onto?confirm=true")

        assert resp.status_code == 400
        assert "already deprecated" in resp.text


class TestGetClassDetail:
    def test_returns_class_with_attributes_and_relationships(self, client, _mock_db):
        cls = _class_doc()
        attr = {
            "_key": "Person_name",
            "_id": "ontology_datatype_properties/Person_name",
            "label": "name",
            "range_datatype": "xsd:string",
            "expired": NEVER_EXPIRES,
        }
        rel = {
            "_key": "Person_knows",
            "_id": "ontology_object_properties/Person_knows",
            "label": "knows",
            "expired": NEVER_EXPIRES,
            "target_class": {"_key": "Org", "label": "Organization", "_id": "ontology_classes/Org"},
        }

        call_counter = {"n": 0}

        def _mock_aql(db, query, bind_vars=None):
            call_counter["n"] += 1
            if "ontology_datatype_properties" in query:
                return iter([attr])
            if "ontology_object_properties" in query:
                return iter([rel])
            return iter([])

        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            with patch("app.api.ontology.run_aql", side_effect=_mock_aql):
                resp = client.get("/api/v1/ontology/test_onto/classes/Person")

        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Person"
        assert len(data["attributes"]) == 1
        assert data["attributes"][0]["label"] == "name"
        assert len(data["relationships"]) == 1
        assert data["relationships"][0]["label"] == "knows"

    def test_class_not_found_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = None
            resp = client.get("/api/v1/ontology/test_onto/classes/missing")
        assert resp.status_code == 404

    def test_class_wrong_ontology_returns_404(self, client, _mock_db):
        cls = _class_doc(ontology_id="other_onto")
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            resp = client.get("/api/v1/ontology/test_onto/classes/Person")
        assert resp.status_code == 404

    def test_legacy_fallback_when_no_pgt_data(self, client, _mock_db):
        cls = _class_doc()
        _mock_db.has_collection.side_effect = lambda name: (
            name
            in {
                "ontology_classes",
                "has_property",
                "ontology_properties",
            }
        )
        legacy_prop = {
            "_key": "Person_email",
            "_id": "ontology_properties/Person_email",
            "label": "email",
            "expired": NEVER_EXPIRES,
        }

        def _mock_aql(db, query, bind_vars=None):
            if "has_property" in query:
                return iter([legacy_prop])
            return iter([])

        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            with patch("app.api.ontology.run_aql", side_effect=_mock_aql):
                resp = client.get("/api/v1/ontology/test_onto/classes/Person")

        assert resp.status_code == 200
        data = resp.json()
        assert data["attributes"] == []
        assert data["relationships"] == []
        assert len(data["legacy_properties"]) == 1
        assert data["legacy_properties"][0]["label"] == "email"


class TestCreateClass:
    def test_creates_class_returns_201(self, client, _mock_db):
        created = _class_doc()
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.create_class.return_value = created
            resp = client.post(
                "/api/v1/ontology/test_onto/classes",
                json={"label": "Person"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Person"
        assert data["source_type"] == "manual"
        assert data["confidence"] == 1.0

    def test_creates_class_with_parent(self, client, _mock_db):
        created = _class_doc(key="Animal", label="Animal")
        parent = _class_doc(key="LivingThing", label="LivingThing")
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.create_class.return_value = created
            repo.get_class.return_value = parent
            repo.create_edge.return_value = {"_key": "edge1"}
            resp = client.post(
                "/api/v1/ontology/test_onto/classes",
                json={"label": "Animal", "parent_class_key": "LivingThing"},
            )
        assert resp.status_code == 201
        repo.create_edge.assert_called_once()
        edge_call = repo.create_edge.call_args
        assert edge_call.kwargs["edge_collection"] == "subclass_of"

    def test_duplicate_uri_returns_409(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter(["existing_key"]))
        resp = client.post(
            "/api/v1/ontology/test_onto/classes",
            json={"label": "Person", "uri": "http://example.org#Person"},
        )
        assert resp.status_code == 409

    def test_parent_not_found_returns_404(self, client, _mock_db):
        created = _class_doc()
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.create_class.return_value = created
            repo.get_class.return_value = None
            resp = client.post(
                "/api/v1/ontology/test_onto/classes",
                json={"label": "Child", "parent_class_key": "missing"},
            )
        assert resp.status_code == 404
        assert "Parent class" in resp.json()["error"]["message"]


class TestCreateProperty:
    def test_creates_property_returns_201(self, client, _mock_db):
        domain = _class_doc()
        created = _prop_doc()
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = domain
            repo.create_property.return_value = created
            repo.create_edge.return_value = {"_key": "edge_rd"}
            resp = client.post(
                "/api/v1/ontology/test_onto/properties",
                json={
                    "label": "name",
                    "domain_class_key": "Person",
                    "range": "xsd:string",
                    "property_type": "datatype",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["label"] == "name"
        repo.create_edge.assert_called_once()
        assert repo.create_edge.call_args.kwargs["edge_collection"] == "rdfs_domain"

    def test_missing_domain_class_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = None
            resp = client.post(
                "/api/v1/ontology/test_onto/properties",
                json={
                    "label": "name",
                    "domain_class_key": "missing",
                    "range": "xsd:string",
                    "property_type": "datatype",
                },
            )
        assert resp.status_code == 404
        assert "Domain class" in resp.json()["error"]["message"]

    def test_cross_ontology_domain_returns_400(self, client, _mock_db):
        other = _class_doc(ontology_id="other_onto")
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = other
            resp = client.post(
                "/api/v1/ontology/test_onto/properties",
                json={
                    "label": "name",
                    "domain_class_key": "Person",
                    "range": "xsd:string",
                    "property_type": "datatype",
                },
            )
        assert resp.status_code == 400


class TestCreateEdge:
    def test_creates_edge_returns_201(self, client, _mock_db):
        cls_a = _class_doc(key="A", label="A")
        cls_b = _class_doc(key="B", label="B")
        edge = {"_key": "e1", "_from": cls_a["_id"], "_to": cls_b["_id"]}
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.side_effect = [cls_a, cls_b]
            repo.create_edge.return_value = edge
            resp = client.post(
                "/api/v1/ontology/test_onto/edges",
                json={
                    "edge_type": "related_to",
                    "from_key": "A",
                    "to_key": "B",
                    "label": "relates",
                },
            )
        assert resp.status_code == 201
        repo.create_edge.assert_called_once()

    def test_source_class_not_found_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = None
            resp = client.post(
                "/api/v1/ontology/test_onto/edges",
                json={
                    "edge_type": "subclass_of",
                    "from_key": "missing",
                    "to_key": "B",
                },
            )
        assert resp.status_code == 404
        assert "Source class" in resp.json()["error"]["message"]

    def test_invalid_edge_type_returns_422(self, client, _mock_db):
        resp = client.post(
            "/api/v1/ontology/test_onto/edges",
            json={
                "edge_type": "invalid_type",
                "from_key": "A",
                "to_key": "B",
            },
        )
        assert resp.status_code == 422


class TestUpdateClass:
    def test_updates_class_returns_200(self, client, _mock_db):
        original = _class_doc()
        updated = {**original, "label": "UpdatedPerson", "version": 2}
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = original
            repo.update_class.return_value = updated
            resp = client.put(
                "/api/v1/ontology/test_onto/classes/Person",
                json={"label": "UpdatedPerson"},
            )
        assert resp.status_code == 200
        assert resp.json()["label"] == "UpdatedPerson"
        repo.update_class.assert_called_once()

    def test_class_not_found_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = None
            resp = client.put(
                "/api/v1/ontology/test_onto/classes/missing",
                json={"label": "Nope"},
            )
        assert resp.status_code == 404

    def test_empty_update_returns_400(self, client, _mock_db):
        original = _class_doc()
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = original
            resp = client.put(
                "/api/v1/ontology/test_onto/classes/Person",
                json={},
            )
        assert resp.status_code == 400
        assert "No fields" in resp.json()["error"]["message"]

    def test_cross_ontology_update_returns_400(self, client, _mock_db):
        cls = _class_doc(ontology_id="other_onto")
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            resp = client.put(
                "/api/v1/ontology/test_onto/classes/Person",
                json={"label": "Hack"},
            )
        assert resp.status_code == 400


class TestUpdateProperty:
    def test_updates_property_returns_200(self, client, _mock_db):
        original = _prop_doc()
        updated = {**original, "label": "fullName", "version": 2}
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_property.return_value = original
            repo.update_property.return_value = updated
            resp = client.put(
                "/api/v1/ontology/test_onto/properties/Person_name",
                json={"label": "fullName"},
            )
        assert resp.status_code == 200
        assert resp.json()["label"] == "fullName"

    def test_property_not_found_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_property.return_value = None
            resp = client.put(
                "/api/v1/ontology/test_onto/properties/missing",
                json={"label": "x"},
            )
        assert resp.status_code == 404


class TestDeleteClass:
    def test_deletes_class_returns_200(self, client, _mock_db):
        cls = _class_doc()
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            repo.expire_class_cascade.return_value = cls
            resp = client.delete("/api/v1/ontology/test_onto/classes/Person")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        repo.expire_class_cascade.assert_called_once()

    def test_delete_not_found_returns_404(self, client, _mock_db):
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = None
            resp = client.delete("/api/v1/ontology/test_onto/classes/missing")
        assert resp.status_code == 404

    def test_cross_ontology_delete_returns_400(self, client, _mock_db):
        cls = _class_doc(ontology_id="other_onto")
        with patch("app.api.ontology.ontology_repo") as repo:
            repo.get_class.return_value = cls
            resp = client.delete("/api/v1/ontology/test_onto/classes/Person")
        assert resp.status_code == 400
