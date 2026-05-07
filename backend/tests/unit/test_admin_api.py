"""Tests for admin API endpoints (admin.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import _remove_ontology_graphs, _require_reset_enabled
from app.config import settings


class TestRequireResetEnabled:
    """Verify the reset gate respects ``settings.allow_system_reset``.

    The setting is loaded once at process start by pydantic-settings (env var
    ``ALLOW_SYSTEM_RESET``); individual test cases can flip it at runtime via
    ``patch.object(settings, ...)``.
    """

    def test_raises_403_when_disabled(self):
        with patch.object(settings, "allow_system_reset", False):
            with pytest.raises(HTTPException) as exc_info:
                _require_reset_enabled()
            assert exc_info.value.status_code == 403

    def test_passes_when_enabled(self):
        with patch.object(settings, "allow_system_reset", True):
            _require_reset_enabled()


class TestResetEndpoints:
    def test_remove_ontology_graphs_removes_only_prefixed_graphs(self):
        mock_db = MagicMock()
        mock_db.graphs.return_value = [
            {"name": "ontology_customer"},
            {"name": "other_graph"},
            "ontology_supplier",
        ]

        removed = _remove_ontology_graphs(mock_db)

        assert removed == ["ontology_customer", "ontology_supplier"]
        assert mock_db.delete_graph.call_count == 2

    def test_remove_ontology_graphs_handles_graph_listing_error(self):
        mock_db = MagicMock()
        mock_db.graphs.side_effect = RuntimeError("boom")

        removed = _remove_ontology_graphs(mock_db)

        assert removed == []
        mock_db.delete_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_ontology_truncates_collections(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert len(result["collections_truncated"]) > 0
        # Should NOT include documents/chunks
        assert "documents" not in result["collections_truncated"]
        assert "chunks" not in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_full_reset_includes_documents(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_all_data

            result = await reset_all_data()

        assert result["reset"] is True
        assert "documents" in result["collections_truncated"]
        assert "chunks" in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_reset_skips_missing_collections(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert result["collections_truncated"] == []
        mock_db.collection.assert_not_called()

    def test_settings_field_default_is_false(self, tmp_path, monkeypatch):
        """Regression: a fresh Settings with no env var and no .env must default
        to ``allow_system_reset=False`` so a new deployment isn't silently exposed
        to ``/admin/reset``.
        """
        monkeypatch.delenv("ALLOW_SYSTEM_RESET", raising=False)
        # Point pydantic-settings at an empty .env so the developer's repo-root
        # ``.env`` doesn't bleed into this assertion.
        empty_env = tmp_path / ".env.empty"
        empty_env.write_text("")

        from app.config import Settings

        fresh = Settings(_env_file=str(empty_env))
        assert fresh.allow_system_reset is False


class TestFeedbackLearningArtifacts:
    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_delegates_to_service(self):
        payload = {
            "status": "ready",
            "auto_apply": False,
            "summary": {"total_examples": 1},
            "examples": [{"decision_key": "d1"}],
            "regression_candidates": [],
        }

        with (
            patch("app.api.admin.get_db", return_value=MagicMock(name="db")) as mock_get_db,
            patch(
                "app.api.admin.build_feedback_learning_examples",
                return_value=payload,
            ) as mock_build,
        ):
            from app.api.admin import feedback_learning_artifacts

            result = await feedback_learning_artifacts(ontology_id="onto_1", limit=25)

        assert result == payload
        mock_build.assert_called_once_with(
            mock_get_db.return_value,
            ontology_id="onto_1",
            limit=25,
        )

    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_wraps_service_error(self):
        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch(
                "app.api.admin.build_feedback_learning_examples",
                side_effect=RuntimeError("boom"),
            ),
        ):
            from app.api.admin import feedback_learning_artifacts

            with pytest.raises(HTTPException) as exc:
                await feedback_learning_artifacts(ontology_id=None, limit=100)

        assert exc.value.status_code == 500
