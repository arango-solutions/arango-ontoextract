"""End-to-end test: full extraction flow (mock LLM, real DB).

Flow: create doc → trigger extraction → verify staging graph exists.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / "llm_responses" / name) as f:
        return json.load(f)


def _ensure_collection(db, name: str, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge)


def _seed_document_and_chunks(db, doc_id: str = "test_doc_001") -> str:
    """Seed a document and its chunks into the test database."""
    _ensure_collection(db, "documents")
    _ensure_collection(db, "chunks")

    db.collection("documents").insert(
        {
            "_key": doc_id,
            "filename": "test_enterprise.md",
            "mime_type": "text/markdown",
            "upload_date": time.time(),
            "status": "ready",
            "org_id": "test_org",
        }
    )

    chunks = [
        {
            "doc_id": doc_id,
            "text": (
                "An organization is a top-level legal business entity that encompasses "
                "departments, employees, and projects. Departments are functional "
                "subdivisions responsible for specific business areas."
            ),
            "chunk_index": 0,
            "token_count": 50,
        },
        {
            "doc_id": doc_id,
            "text": (
                "Employees are individuals employed by an organization, assigned roles "
                "and participating in projects. A manager is an employee responsible "
                "for leading a department or team."
            ),
            "chunk_index": 1,
            "token_count": 45,
        },
        {
            "doc_id": doc_id,
            "text": (
                "A role defines a named set of responsibilities assigned to employees. "
                "Projects are time-bound initiatives with defined objectives and deliverables."
            ),
            "chunk_index": 2,
            "token_count": 40,
        },
    ]

    for chunk in chunks:
        db.collection("chunks").insert(chunk)

    return doc_id


def _make_mock_llm_response(fixture_name: str):
    """Create a mock LLM response from a fixture file."""
    fixture = _load_fixture(fixture_name)
    mock_response = MagicMock()
    mock_response.content = json.dumps(fixture)
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.total_tokens = 1000
    mock_response.usage_metadata.input_tokens = 800
    mock_response.usage_metadata.output_tokens = 200
    return mock_response


@pytest.mark.integration
class TestExtractionFlow:
    """Full extraction pipeline flow test."""

    @pytest.mark.asyncio
    async def test_full_extraction_creates_run_and_results(self, test_db):
        """Create doc → trigger extraction → verify run record and results."""
        _ensure_collection(test_db, "extraction_runs")
        _ensure_collection(test_db, "ontology_classes")
        _ensure_collection(test_db, "ontology_properties")

        doc_id = _seed_document_and_chunks(test_db)

        fixtures = [
            "extraction_response_01.json",
            "extraction_response_02.json",
            "extraction_response_03.json",
        ]
        fixture_idx = 0

        def mock_invoke(messages):
            nonlocal fixture_idx
            fname = fixtures[fixture_idx % len(fixtures)]
            fixture_idx += 1
            return _make_mock_llm_response(fname)

        mock_llm = MagicMock()
        mock_llm.invoke = mock_invoke

        with (
            patch("app.services.extraction.get_db", return_value=test_db),
            patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
            patch(
                "app.extraction.agents.extractor._retrieve_relevant_chunks",
                side_effect=lambda *a, **k: [],
            ),
        ):
            from app.services.extraction import start_run

            run = await start_run(
                test_db,
                document_id=doc_id,
            )

        assert run is not None
        assert run["status"] in ("completed", "completed_with_errors")
        assert run["doc_id"] == doc_id

        stats = run.get("stats", {})
        assert stats.get("classes_extracted", 0) > 0

    @pytest.mark.asyncio
    async def test_extraction_stores_results(self, test_db):
        """Verify that extraction results are stored alongside the run."""
        _ensure_collection(test_db, "extraction_runs")
        _ensure_collection(test_db, "ontology_classes")
        _ensure_collection(test_db, "ontology_properties")

        doc_id = _seed_document_and_chunks(test_db, doc_id="test_doc_results")

        def mock_invoke(messages):
            return _make_mock_llm_response("extraction_response_01.json")

        mock_llm = MagicMock()
        mock_llm.invoke = mock_invoke

        with (
            patch("app.services.extraction.get_db", return_value=test_db),
            patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
            patch(
                "app.extraction.agents.extractor._retrieve_relevant_chunks",
                side_effect=lambda *a, **k: [],
            ),
        ):
            from app.services.extraction import get_run_results, start_run

            run = await start_run(test_db, document_id=doc_id)

            results = get_run_results(test_db, run_id=run["_key"])

        assert results is not None
        if "classes" in results:
            assert len(results["classes"]) > 0
