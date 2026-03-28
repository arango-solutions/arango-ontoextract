"""Integration tests for organization & user API endpoints — PRD Section 7.6.

Tests CRUD operations for organizations and users against a real ArangoDB
instance via the FastAPI TestClient.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.auth import AuthenticatedUser

ORGS_COLLECTION = "organizations"
USERS_COLLECTION = "users"

_ADMIN_USER = AuthenticatedUser(
    user_id="admin-001",
    org_id="test-org",
    roles=["admin"],
    email="admin@test.com",
    display_name="Test Admin",
)

_VIEWER_USER = AuthenticatedUser(
    user_id="viewer-001",
    org_id="test-org",
    roles=["viewer"],
    email="viewer@test.com",
    display_name="Test Viewer",
)


@pytest.fixture(autouse=True)
def _setup_collections(test_db):
    """Ensure organizations and users collections exist."""
    for name in (ORGS_COLLECTION, USERS_COLLECTION):
        if not test_db.has_collection(name):
            test_db.create_collection(name)
    yield
    test_db.collection(ORGS_COLLECTION).truncate()
    test_db.collection(USERS_COLLECTION).truncate()


def _patch_user(user: AuthenticatedUser):
    """Patch the auth middleware to inject a specific user."""
    return patch("app.api.auth.get_user_from_request", return_value=user)


@pytest.mark.integration
class TestOrgCrud:
    """Tests for organization CRUD endpoints."""

    def test_create_org(self, test_client, test_db):
        with _patch_user(_ADMIN_USER):
            resp = test_client.post(
                "/api/v1/orgs",
                json={"name": "acme-corp", "display_name": "Acme Corporation"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "acme-corp"
        assert data["display_name"] == "Acme Corporation"
        assert "_key" in data

    def test_list_orgs(self, test_client, test_db):
        col = test_db.collection(ORGS_COLLECTION)
        col.insert({"name": "org-a", "display_name": "A", "settings": {}})
        col.insert({"name": "org-b", "display_name": "B", "settings": {}})

        with _patch_user(_ADMIN_USER):
            resp = test_client.get("/api/v1/orgs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 2
        assert len(data["data"]) >= 2

    def test_get_org(self, test_client, test_db):
        col = test_db.collection(ORGS_COLLECTION)
        result = col.insert({"name": "test-org", "display_name": "Test", "settings": {}})

        with _patch_user(_ADMIN_USER):
            resp = test_client.get(f"/api/v1/orgs/{result['_key']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-org"

    def test_get_org_not_found(self, test_client):
        with _patch_user(_ADMIN_USER):
            resp = test_client.get("/api/v1/orgs/nonexistent-org")
        assert resp.status_code == 404

    def test_update_org(self, test_client, test_db):
        col = test_db.collection(ORGS_COLLECTION)
        result = col.insert({"name": "old-name", "display_name": "Old", "settings": {}})

        with _patch_user(_ADMIN_USER):
            resp = test_client.put(
                f"/api/v1/orgs/{result['_key']}",
                json={"display_name": "Updated Org"},
            )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Org"

    def test_viewer_cannot_create_org(self, test_client):
        with _patch_user(_VIEWER_USER):
            resp = test_client.post(
                "/api/v1/orgs",
                json={"name": "forbidden-org"},
            )
        assert resp.status_code == 403


@pytest.mark.integration
class TestOrgUsers:
    """Tests for user management within organizations."""

    @pytest.fixture()
    def org_key(self, test_db):
        col = test_db.collection(ORGS_COLLECTION)
        result = col.insert({"name": "user-test-org", "display_name": "UTO", "settings": {}})
        return result["_key"]

    def test_add_user_to_org(self, test_client, org_key):
        with _patch_user(_ADMIN_USER):
            resp = test_client.post(
                f"/api/v1/orgs/{org_key}/users",
                json={
                    "user_id": "new-user-001",
                    "role": "domain_expert",
                    "email": "expert@test.com",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "new-user-001"
        assert data["role"] == "domain_expert"

    def test_add_duplicate_user_conflict(self, test_client, test_db, org_key):
        with _patch_user(_ADMIN_USER):
            test_client.post(
                f"/api/v1/orgs/{org_key}/users",
                json={"user_id": "dup-user", "role": "viewer"},
            )
            resp = test_client.post(
                f"/api/v1/orgs/{org_key}/users",
                json={"user_id": "dup-user", "role": "admin"},
            )
        assert resp.status_code == 409

    def test_add_user_invalid_role(self, test_client, org_key):
        with _patch_user(_ADMIN_USER):
            resp = test_client.post(
                f"/api/v1/orgs/{org_key}/users",
                json={"user_id": "bad-role-user", "role": "superadmin"},
            )
        assert resp.status_code == 400

    def test_list_org_users(self, test_client, test_db, org_key):
        users_col = test_db.collection(USERS_COLLECTION)
        users_col.insert({"user_id": "u1", "org_id": org_key, "role": "viewer"})
        users_col.insert({"user_id": "u2", "org_id": org_key, "role": "admin"})

        with _patch_user(_ADMIN_USER):
            resp = test_client.get(f"/api/v1/orgs/{org_key}/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 2

    def test_update_user_role(self, test_client, test_db, org_key):
        users_col = test_db.collection(USERS_COLLECTION)
        users_col.insert({"user_id": "role-user", "org_id": org_key, "role": "viewer"})

        with _patch_user(_ADMIN_USER):
            resp = test_client.put(
                f"/api/v1/orgs/{org_key}/users/role-user/role",
                json={"role": "ontology_engineer"},
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "ontology_engineer"

    def test_update_user_role_not_found(self, test_client, org_key):
        with _patch_user(_ADMIN_USER):
            resp = test_client.put(
                f"/api/v1/orgs/{org_key}/users/nonexistent/role",
                json={"role": "admin"},
            )
        assert resp.status_code == 404

    def test_remove_user_from_org(self, test_client, test_db, org_key):
        users_col = test_db.collection(USERS_COLLECTION)
        users_col.insert({"user_id": "remove-me", "org_id": org_key, "role": "viewer"})

        with _patch_user(_ADMIN_USER):
            resp = test_client.delete(f"/api/v1/orgs/{org_key}/users/remove-me")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_remove_user_not_found(self, test_client, org_key):
        with _patch_user(_ADMIN_USER):
            resp = test_client.delete(f"/api/v1/orgs/{org_key}/users/ghost")
        assert resp.status_code == 404
