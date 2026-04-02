"""Additional unit tests for organization and quality API route handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.api.orgs import (
    AddUserRequest,
    CreateOrgRequest,
    UpdateOrgRequest,
    UpdateRoleRequest,
    add_user_to_org,
    create_organization,
    get_organization,
    list_org_users,
    list_organizations,
    remove_user_from_org,
    update_organization,
    update_user_role,
)
from app.api.quality import quality_for_ontology


class TestOrgRoutes:
    @pytest.mark.asyncio
    async def test_create_list_get_and_update_org(self):
        with (
            patch(
                "app.api.orgs.orgs_repo.create_organization", return_value={"_key": "o1"}
            ) as mock_create,
            patch(
                "app.api.orgs.orgs_repo.list_organizations", return_value={"data": []}
            ) as mock_list,
            patch(
                "app.api.orgs.orgs_repo.get_organization",
                return_value={"_key": "o1", "display_name": "Org"},
            ) as mock_get,
            patch(
                "app.api.orgs.orgs_repo.update_organization",
                return_value={"_key": "o1", "display_name": "New"},
            ) as mock_update,
        ):
            created = await create_organization(CreateOrgRequest(name="org"))
            listing = await list_organizations(limit=5, cursor=None, sort="name", order="asc")
            current = await get_organization("o1")
            updated = await update_organization("o1", UpdateOrgRequest(display_name="New"))
        mock_create.assert_called_once()
        mock_list.assert_called_once_with(limit=5, cursor=None, sort_field="name", sort_order="asc")
        mock_get.assert_called()
        mock_update.assert_called_once()
        assert created == {"_key": "o1"}
        assert listing == {"data": []}
        assert current["_key"] == "o1"
        assert updated["display_name"] == "New"

    @pytest.mark.asyncio
    async def test_update_org_returns_existing_when_no_changes(self):
        with patch(
            "app.api.orgs.orgs_repo.get_organization",
            return_value={"_key": "o1", "display_name": "Org"},
        ):
            result = await update_organization("o1", UpdateOrgRequest())
        assert result["display_name"] == "Org"

    @pytest.mark.asyncio
    async def test_add_user_validates_and_conflicts(self):
        with (
            patch("app.api.orgs.orgs_repo.get_organization", return_value={"_key": "o1"}),
            pytest.raises(ValidationError),
        ):
            await add_user_to_org("o1", AddUserRequest(user_id="u1", role="bad"))

        with (
            patch("app.api.orgs.orgs_repo.get_organization", return_value={"_key": "o1"}),
            patch("app.api.orgs.orgs_repo.get_org_user", return_value={"user_id": "u1"}),
            pytest.raises(ConflictError),
        ):
            await add_user_to_org("o1", AddUserRequest(user_id="u1", role="viewer"))

    @pytest.mark.asyncio
    async def test_add_list_update_and_remove_user(self):
        with (
            patch("app.api.orgs.orgs_repo.get_organization", return_value={"_key": "o1"}),
            patch("app.api.orgs.orgs_repo.get_org_user", return_value=None),
            patch(
                "app.api.orgs.orgs_repo.add_user_to_org", return_value={"user_id": "u1"}
            ) as mock_add,
            patch(
                "app.api.orgs.orgs_repo.list_org_users", return_value={"data": [{"user_id": "u1"}]}
            ) as mock_list,
            patch(
                "app.api.orgs.orgs_repo.update_user_role",
                side_effect=[{"user_id": "u1", "role": "admin"}, None],
            ) as mock_update_role,
            patch(
                "app.api.orgs.orgs_repo.remove_user_from_org", side_effect=[True, False]
            ) as mock_remove,
        ):
            added = await add_user_to_org("o1", AddUserRequest(user_id="u1", role="viewer"))
            listing = await list_org_users("o1", limit=10, cursor="cur")
            updated = await update_user_role("o1", "u1", UpdateRoleRequest(role="admin"))
            removed = await remove_user_from_org("o1", "u1")
            with pytest.raises(NotFoundError):
                await remove_user_from_org("o1", "u2")
        mock_add.assert_called_once()
        mock_list.assert_called_once_with("o1", limit=10, cursor="cur")
        mock_update_role.assert_called_once_with("o1", "u1", "admin")
        assert added == {"user_id": "u1"}
        assert listing["data"][0]["user_id"] == "u1"
        assert updated["role"] == "admin"
        assert removed["status"] == "removed"
        assert mock_remove.call_count == 2

    @pytest.mark.asyncio
    async def test_update_user_role_validation_and_not_found(self):
        with pytest.raises(ValidationError):
            await update_user_role("o1", "u1", UpdateRoleRequest(role="bad"))

        with (
            patch("app.api.orgs.orgs_repo.update_user_role", return_value=None),
            pytest.raises(NotFoundError),
        ):
            await update_user_role("o1", "u1", UpdateRoleRequest(role="viewer"))


class TestQualityRoutes:
    @pytest.mark.asyncio
    async def test_quality_for_ontology_merges_results_and_handles_error(self):
        with (
            patch("app.api.quality.get_db", return_value=MagicMock()),
            patch(
                "app.api.quality.compute_ontology_quality",
                side_effect=[{"health": 90}, RuntimeError("boom")],
            ),
            patch(
                "app.api.quality.compute_extraction_quality", return_value={"acceptance_rate": 0.8}
            ),
        ):
            result = await quality_for_ontology("onto1")
            assert result == {"health": 90, "acceptance_rate": 0.8}
            with pytest.raises(HTTPException) as exc:
                await quality_for_ontology("onto1")
        assert exc.value.status_code == 500
