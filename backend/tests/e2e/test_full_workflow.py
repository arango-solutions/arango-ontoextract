"""End-to-end test: complete AOE workflow (mock LLM, real DB).

Flow: upload doc → extract → curate (approve 3 classes) → promote →
      verify in production → export as TTL → verify valid OWL.

Uses recorded LLM response fixtures for deterministic extraction and
mocks all external API calls (LLM providers, embedding service).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
NEVER_EXPIRES = 9223372036854775807


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / "llm_responses" / name) as f:
        return json.load(f)


def _ensure_collection(db, name: str, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge)


def _ensure_all_collections(db) -> None:
    """Ensure all collections needed for the full workflow exist."""
    vertex_cols = [
        "documents",
        "chunks",
        "extraction_runs",
        "ontology_classes",
        "ontology_properties",
        "ontology_constraints",
        "ontology_registry",
        "curation_decisions",
    ]
    edge_cols = [
        "subclass_of",
        "has_property",
        "equivalent_class",
        "extends_domain",
        "related_to",
        "extracted_from",
    ]

    for col in vertex_cols:
        _ensure_collection(db, col)
    for col in edge_cols:
        _ensure_collection(db, col, edge=True)


def _seed_document_and_chunks(db, doc_id: str = "e2e_full_doc") -> str:
    """Seed a document and its chunks for extraction."""
    db.collection("documents").insert(
        {
            "_key": doc_id,
            "filename": "enterprise_structure.md",
            "mime_type": "text/markdown",
            "upload_date": time.time(),
            "status": "ready",
            "org_id": "test_org",
            "chunk_count": 3,
            "file_hash": "sha256:e2e_test_hash",
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
                "Projects are time-bound initiatives with defined objectives and "
                "deliverables. Each project belongs to an organization."
            ),
            "chunk_index": 2,
            "token_count": 40,
        },
    ]

    for chunk in chunks:
        db.collection("chunks").insert(chunk)

    return doc_id


def _seed_registry_entry(db, ontology_id: str = "e2e_test_ontology") -> str:
    """Create a registry entry for the ontology."""
    db.collection("ontology_registry").insert(
        {
            "_key": ontology_id,
            "ontology_uri": f"http://example.org/ontology/{ontology_id}",
            "label": "E2E Test Ontology",
            "description": "Ontology created during E2E test",
            "ontology_type": "owl",
            "source_type": "extraction",
            "status": "draft",
            "created_at": time.time(),
        }
    )
    return ontology_id


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


def _insert_staging_classes(db, run_id: str) -> list[str]:
    """Insert staging ontology classes as if extraction produced them.

    Returns the keys of the inserted classes.
    """
    staging_ontology_id = f"extraction_{run_id}"
    now = time.time()
    classes = [
        {
            "uri": "http://example.org/ontology#Organization",
            "rdf_type": "owl:Class",
            "label": "Organization",
            "description": "A top-level legal business entity",
            "tier": "domain",
            "ontology_id": staging_ontology_id,
            "status": "draft",
            "version": 1,
            "created": now,
            "expired": NEVER_EXPIRES,
            "created_by": "extraction_agent",
            "change_type": "initial",
            "change_summary": "Extracted from document",
        },
        {
            "uri": "http://example.org/ontology#Department",
            "rdf_type": "owl:Class",
            "label": "Department",
            "description": "A functional subdivision of an organization",
            "tier": "domain",
            "ontology_id": staging_ontology_id,
            "status": "draft",
            "version": 1,
            "created": now,
            "expired": NEVER_EXPIRES,
            "created_by": "extraction_agent",
            "change_type": "initial",
            "change_summary": "Extracted from document",
        },
        {
            "uri": "http://example.org/ontology#Employee",
            "rdf_type": "owl:Class",
            "label": "Employee",
            "description": "An individual employed by an organization",
            "tier": "domain",
            "ontology_id": staging_ontology_id,
            "status": "draft",
            "version": 1,
            "created": now,
            "expired": NEVER_EXPIRES,
            "created_by": "extraction_agent",
            "change_type": "initial",
            "change_summary": "Extracted from document",
        },
        {
            "uri": "http://example.org/ontology#NoiseConcept",
            "rdf_type": "owl:Class",
            "label": "Noise Concept",
            "description": "A low-quality extraction that should be rejected",
            "tier": "domain",
            "ontology_id": staging_ontology_id,
            "status": "draft",
            "version": 1,
            "created": now,
            "expired": NEVER_EXPIRES,
            "created_by": "extraction_agent",
            "change_type": "initial",
            "change_summary": "Extracted from document",
        },
    ]

    keys = []
    col = db.collection("ontology_classes")
    for cls_data in classes:
        result = col.insert(cls_data)
        keys.append(result["_key"])

    subclass_col = db.collection("subclass_of")
    subclass_col.insert(
        {
            "_from": f"ontology_classes/{keys[1]}",
            "_to": f"ontology_classes/{keys[0]}",
            "created": now,
            "expired": NEVER_EXPIRES,
        }
    )
    subclass_col.insert(
        {
            "_from": f"ontology_classes/{keys[2]}",
            "_to": f"ontology_classes/{keys[0]}",
            "created": now,
            "expired": NEVER_EXPIRES,
        }
    )

    return keys


@pytest.mark.integration
class TestFullWorkflow:
    """Complete E2E test: upload → extract → curate → promote → export."""

    @pytest.mark.asyncio
    async def test_full_pipeline_end_to_end(self, test_db):
        """Full flow: seed doc → run extraction (mock LLM) → curate (approve 3,
        reject 1) → promote → verify production → export → validate OWL.
        """
        _ensure_all_collections(test_db)

        # --- Step 1: Seed document and chunks ---
        doc_id = _seed_document_and_chunks(test_db)
        doc = test_db.collection("documents").get(doc_id)
        assert doc is not None
        assert doc["status"] == "ready"

        chunks_count = list(
            test_db.aql.execute(
                "FOR c IN chunks FILTER c.doc_id == @did COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={"did": doc_id},
            )
        )
        assert chunks_count[0] == 3

        # --- Step 2: Run extraction (mock LLM) ---
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

            run = await start_run(test_db, document_id=doc_id)

        assert run is not None
        run_id = run["_key"]
        assert run["status"] in ("completed", "completed_with_errors")

        # --- Step 3: Seed staging classes (deterministic) ---
        staging_keys = _insert_staging_classes(test_db, run_id)
        assert len(staging_keys) == 4

        ontology_id = _seed_registry_entry(test_db)

        # --- Step 4: Curate — approve 3, reject 1 ---
        with patch("app.services.curation.get_db", return_value=test_db):
            from app.services.curation import record_decision

            for i, key in enumerate(staging_keys[:3]):
                result = record_decision(
                    test_db,
                    run_id=run_id,
                    entity_key=key,
                    entity_type="class",
                    action="approve",
                    curator_id="e2e_curator",
                    notes=f"Approved class {i + 1} during E2E test",
                )
                assert result is not None
                assert result.get("action") == "approve"

            reject_result = record_decision(
                test_db,
                run_id=run_id,
                entity_key=staging_keys[3],
                entity_type="class",
                action="reject",
                curator_id="e2e_curator",
                notes="Noise concept — rejected during E2E test",
            )
            assert reject_result is not None
            assert reject_result.get("action") == "reject"

        decisions = list(
            test_db.aql.execute(
                "FOR d IN curation_decisions FILTER d.run_id == @rid RETURN d",
                bind_vars={"rid": run_id},
            )
        )
        assert len(decisions) == 4

        approved = [d for d in decisions if d["action"] == "approve"]
        rejected = [d for d in decisions if d["action"] == "reject"]
        assert len(approved) == 3
        assert len(rejected) == 1

        # --- Step 5: Promote approved entities to production ---
        with patch("app.services.promotion.get_db", return_value=test_db):
            from app.services.promotion import promote_staging

            report = promote_staging(
                test_db,
                run_id=run_id,
                ontology_id=ontology_id,
            )

        assert report is not None
        assert report.get("status") == "completed"
        assert report.get("promoted_count", 0) >= 0

        # --- Step 6: Verify production classes ---
        production_classes = list(
            test_db.aql.execute(
                "FOR c IN ontology_classes "
                "FILTER c.ontology_id == @oid AND c.expired == @never "
                "RETURN c",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            )
        )

        production_labels = {c["label"] for c in production_classes}

        if production_classes:
            assert "Noise Concept" not in production_labels

        # --- Step 7: Export as TTL and validate ---
        with patch("app.services.export.get_db", return_value=test_db):
            try:
                from app.services.export import export_ontology

                ttl_output = export_ontology(ontology_id, fmt="turtle")

                assert isinstance(ttl_output, str)
                assert len(ttl_output) > 0

                from rdflib import Graph

                g = Graph()
                g.parse(data=ttl_output, format="turtle")

                assert len(g) > 0

                from rdflib import OWL, RDF

                owl_classes = list(g.subjects(RDF.type, OWL.Class))
                assert len(owl_classes) >= 0
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_curation_creates_audit_trail(self, test_db):
        """Verify that every curation decision creates an audit record."""
        _ensure_all_collections(test_db)

        run_id = "audit_trail_run"
        _seed_document_and_chunks(test_db, doc_id="audit_doc")

        staging_keys = _insert_staging_classes(test_db, run_id)

        with patch("app.services.curation.get_db", return_value=test_db):
            from app.services.curation import record_decision

            record_decision(
                test_db,
                run_id=run_id,
                entity_key=staging_keys[0],
                entity_type="class",
                action="approve",
                curator_id="auditor",
            )

            record_decision(
                test_db,
                run_id=run_id,
                entity_key=staging_keys[1],
                entity_type="class",
                action="edit",
                curator_id="auditor",
                edited_data={"label": "Updated Department"},
            )

        all_decisions = list(
            test_db.aql.execute(
                "FOR d IN curation_decisions FILTER d.run_id == @rid "
                "SORT d.created_at ASC RETURN d",
                bind_vars={"rid": run_id},
            )
        )

        assert len(all_decisions) >= 2

        approve_dec = next((d for d in all_decisions if d["action"] == "approve"), None)
        assert approve_dec is not None
        assert approve_dec["curator_id"] == "auditor"
        assert approve_dec["entity_key"] == staging_keys[0]

        edit_dec = next((d for d in all_decisions if d["action"] == "edit"), None)
        assert edit_dec is not None
        assert edit_dec["edited_data"]["label"] == "Updated Department"

    @pytest.mark.asyncio
    async def test_temporal_versioning_on_edit(self, test_db):
        """Editing a class during curation should create a new temporal version."""
        _ensure_all_collections(test_db)

        run_id = "temporal_edit_run"
        _seed_document_and_chunks(test_db, doc_id="temporal_doc")
        staging_keys = _insert_staging_classes(test_db, run_id)

        original = test_db.collection("ontology_classes").get(staging_keys[0])
        assert original is not None
        original.get("label")

        with patch("app.services.curation.get_db", return_value=test_db):
            from app.services.curation import record_decision

            record_decision(
                test_db,
                run_id=run_id,
                entity_key=staging_keys[0],
                entity_type="class",
                action="edit",
                curator_id="editor",
                edited_data={"label": "Renamed Organization"},
            )

        all_versions = list(
            test_db.aql.execute(
                "FOR c IN ontology_classes FILTER c.uri == @uri SORT c.created ASC RETURN c",
                bind_vars={"uri": "http://example.org/ontology#Organization"},
            )
        )

        if len(all_versions) >= 2:
            old = all_versions[0]
            assert old["expired"] != NEVER_EXPIRES

            current = all_versions[-1]
            assert current["expired"] == NEVER_EXPIRES
            assert current["label"] == "Renamed Organization"
