"""Unit tests for the A-box individuals read API (Stream 21 / AB-PR6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.db import individuals_repo
from app.main import app

client = TestClient(app)


class TestListIndividuals:
    def test_lists_with_types(self) -> None:
        rows = [
            {"_key": "i1", "label": "Acme", "type_label": "Organization", "type_key": "Org"},
            {"_key": "i2", "label": "Bob", "type_label": "Person", "type_key": "Per"},
        ]
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(individuals_repo, "list_individuals_with_types", return_value=rows) as mk,
        ):
            resp = client.get("/api/v1/ontology/o1/individuals?limit=50&offset=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["data"][0]["type_label"] == "Organization"
        assert mk.call_args.kwargs["limit"] == 50
        assert mk.call_args.kwargs["offset"] == 10


class TestGetIndividual:
    def test_returns_individual(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                individuals_repo, "get_individual", return_value={"_key": "i1", "label": "Acme"}
            ),
        ):
            resp = client.get("/api/v1/ontology/individuals/i1")
        assert resp.status_code == 200
        assert resp.json()["label"] == "Acme"

    def test_404_when_missing(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(individuals_repo, "get_individual", return_value=None),
        ):
            resp = client.get("/api/v1/ontology/individuals/nope")
        assert resp.status_code == 404
