"""Unit tests for ontology release persistence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import releases_repo


def test_list_releases_empty_when_collection_missing() -> None:
    db = MagicMock()
    db.has_collection.return_value = False
    assert releases_repo.list_releases_for_ontology("o1", db=db) == []


def test_release_exists_false_when_collection_missing() -> None:
    db = MagicMock()
    db.has_collection.return_value = False
    assert releases_repo.release_exists("o1", "1.0.0", db=db) is False


def test_create_release_duplicate_version_raises() -> None:
    db = MagicMock()
    db.has_collection.return_value = True
    with (
        patch.object(releases_repo, "release_exists", return_value=True),
        pytest.raises(ValueError, match="already exists"),
    ):
        releases_repo.create_release(
            "o1",
            version="1.0.0",
            description="",
            release_notes="",
            released_by=None,
            db=db,
        )


def test_create_release_inserts_and_updates_registry() -> None:
    db = MagicMock()
    db.has_collection.return_value = True
    mock_col = MagicMock()
    db.collection.return_value = mock_col
    mock_col.insert.return_value = {
        "new": {
            "_key": "rel1",
            "ontology_id": "o1",
            "version": "2.1.0",
            "description": "Stable",
            "release_notes": "Fixes",
        }
    }

    with (
        patch.object(releases_repo, "release_exists", return_value=False),
        patch.object(
            releases_repo.registry_repo,
            "update_registry_entry",
        ) as mock_update,
    ):
        out = releases_repo.create_release(
            "o1",
            version="2.1.0",
            description="Stable",
            release_notes="Fixes",
            released_by="user-9",
            db=db,
        )

    assert out["version"] == "2.1.0"
    mock_col.insert.assert_called_once()
    inserted = mock_col.insert.call_args[0][0]
    assert inserted["ontology_id"] == "o1"
    assert inserted["released_by"] == "user-9"
    mock_update.assert_called_once()
    call_kw = mock_update.call_args[0][1]
    assert call_kw["current_release_version"] == "2.1.0"
    assert call_kw["release_state"] == "released"
    assert call_kw["current_release_description"] == "Stable"
