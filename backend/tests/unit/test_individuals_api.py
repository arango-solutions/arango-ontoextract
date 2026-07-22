"""Unit tests for the A-box individuals read API (Stream 21 / AB-PR6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.db import individuals_repo
from app.main import app
from app.services import abox_canonicalize, abox_validation, quality_metrics

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


class TestCanonicalize:
    def test_canonicalize_threads_params(self) -> None:
        report = {"ontology_id": "o1", "candidates": [{"keep_key": "a"}], "merged": 0}
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(abox_canonicalize, "canonicalize_ontology", return_value=report) as mk,
        ):
            resp = client.post(
                "/api/v1/ontology/o1/individuals/canonicalize?min_score=0.9&auto_merge=true"
            )
        assert resp.status_code == 200
        assert resp.json()["merged"] == 0
        assert mk.call_args.kwargs["min_score"] == 0.9
        assert mk.call_args.kwargs["auto_merge"] is True


class TestMetrics:
    def test_metrics_returns_grounding_rates(self) -> None:
        metrics = {
            "total_individuals": 3,
            "grounded_individuals": 2,
            "individual_grounding_rate": 0.6667,
            "typed_rate": 0.6667,
        }
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(quality_metrics, "compute_abox_metrics", return_value=metrics) as mk,
        ):
            resp = client.get("/api/v1/ontology/o1/individuals/metrics")
        assert resp.status_code == 200
        assert resp.json()["individual_grounding_rate"] == 0.6667
        assert mk.call_args.args[1] == "o1"


class TestValidate:
    def test_validate_returns_report(self) -> None:
        report = MagicMock()
        report.to_dict.return_value = {"ontology_id": "o1", "violation_count": 2, "violations": []}
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(abox_validation, "validate_abox", return_value=report) as mk,
        ):
            resp = client.post("/api/v1/ontology/o1/individuals/validate")
        assert resp.status_code == 200
        assert resp.json()["violation_count"] == 2
        assert mk.call_args.args[1] == "o1"


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
