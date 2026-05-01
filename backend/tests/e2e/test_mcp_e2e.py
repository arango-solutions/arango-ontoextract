"""E2E test: simulated external agent workflow via MCP.

Simulates: connect → query ontology → check status → get results.
Uses the MCP server's tool functions directly (simulating what an MCP client
SDK would invoke), since stdio/SSE transport requires process-level setup.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from arango.database import StandardDatabase

from app.services.temporal import NEVER_EXPIRES

pytestmark = pytest.mark.e2e

_TEST_ONTOLOGY_ID = "e2e_mcp_ontology"


@pytest.fixture()
def e2e_collections(test_db: StandardDatabase):
    """Create all collections needed for the E2E MCP test."""
    doc_collections = [
        "ontology_classes",
        "ontology_properties",
        "ontology_registry",
        "extraction_runs",
        "documents",
        "chunks",
    ]
    edge_collections = [
        "subclass_of",
        "has_property",
        "equivalent_class",
        "extends_domain",
        "related_to",
        "similarTo",
    ]

    for col in doc_collections:
        if not test_db.has_collection(col):
            test_db.create_collection(col)

    for col in edge_collections:
        if not test_db.has_collection(col):
            test_db.create_collection(col, edge=True)

    yield

    for col in doc_collections + edge_collections:
        if test_db.has_collection(col):
            test_db.collection(col).truncate()


@pytest.fixture()
def e2e_seeded_data(test_db: StandardDatabase, e2e_collections):
    """Seed a complete ontology with extraction run for E2E testing."""
    now = time.time()

    test_db.collection("ontology_registry").insert(
        {
            "_key": _TEST_ONTOLOGY_ID,
            "name": "E2E Test Ontology",
            "tier": "domain",
            "status": "active",
            "created_at": "2026-03-01T00:00:00Z",
        }
    )

    classes = [
        ("e2e_person", "Person", "http://test.org#Person", "A human being"),
        ("e2e_org", "Organization", "http://test.org#Organization", "A company or institution"),
        ("e2e_employee", "Employee", "http://test.org#Employee", "A person employed by an org"),
    ]

    class_ids = {}
    for key, label, uri, desc in classes:
        result = test_db.collection("ontology_classes").insert(
            {
                "_key": key,
                "label": label,
                "uri": uri,
                "description": desc,
                "ontology_id": _TEST_ONTOLOGY_ID,
                "created": now,
                "expired": NEVER_EXPIRES,
                "version": 1,
                "change_type": "initial",
                "change_summary": f"Created {label}",
                "created_by": "e2e_test",
                "tier": "domain",
                "status": "approved",
                "ttlExpireAt": None,
            },
            return_new=True,
        )
        class_ids[key] = result["new"]["_id"]

    test_db.collection("subclass_of").insert(
        {
            "_from": class_ids["e2e_employee"],
            "_to": class_ids["e2e_person"],
            "created": now,
            "expired": NEVER_EXPIRES,
            "ttlExpireAt": None,
        }
    )

    test_db.collection("extraction_runs").insert(
        {
            "_key": "run_e2e001",
            "doc_id": "doc_e2e001",
            "model": "claude-sonnet-4-20250514",
            "status": "completed",
            "started_at": now - 120,
            "completed_at": now - 60,
            "stats": {
                "token_usage": {"total_tokens": 2500},
                "classes_extracted": 3,
                "errors": [],
                "step_logs": [],
            },
        }
    )

    test_db.collection("documents").insert(
        {
            "_key": "doc_e2e001",
            "filename": "org_policy.pdf",
            "content_type": "application/pdf",
            "uploaded_at": now - 200,
        }
    )

    return {"ontology_id": _TEST_ONTOLOGY_ID, "timestamp": now}


@pytest.fixture()
def patched_db(test_db: StandardDatabase):
    """Patch get_db to return the test database."""
    with (
        patch("app.db.client.get_db", return_value=test_db),
        patch("app.db.client._db", test_db),
    ):
        yield test_db


class TestMCPExternalAgentWorkflow:
    """Simulates an external agent connecting and using MCP tools."""

    def test_full_agent_workflow(self, e2e_seeded_data, patched_db):
        """Complete workflow: query ontology → check hierarchy → get status → export."""
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="sse")
        tools = server._tool_manager._tools

        # Step 1: Query the ontology summary
        query_fn = tools["query_domain_ontology"].fn
        summary = query_fn(_TEST_ONTOLOGY_ID)

        assert summary["class_count"] == 3
        assert summary["property_count"] == 0
        assert summary["registry"]["name"] == "E2E Test Ontology"

        # Step 2: Get the class hierarchy
        hierarchy_fn = tools["get_class_hierarchy"].fn
        hierarchy = hierarchy_fn(_TEST_ONTOLOGY_ID)

        assert "roots" in hierarchy
        root_labels = {r["label"] for r in hierarchy["roots"]}
        assert "Person" in root_labels or "Organization" in root_labels

        # Step 3: Check extraction run status
        status_fn = tools["get_extraction_status"].fn
        status = status_fn("run_e2e001")

        assert status["status"] == "completed"
        assert status["classes_extracted"] == 3
        assert status["elapsed_seconds"] is not None

        # Step 4: Get provenance for a class
        provenance_fn = tools["get_provenance"].fn
        prov = provenance_fn("e2e_person")

        assert prov["entity_label"] == "Person"
        assert prov["ontology_id"] == _TEST_ONTOLOGY_ID

        # Step 5: Get a temporal snapshot
        snapshot_fn = tools["get_ontology_snapshot"].fn
        snapshot = snapshot_fn(_TEST_ONTOLOGY_ID)

        assert snapshot["class_count"] == 3

        # Step 6: Export the ontology
        export_fn = tools["export_ontology"].fn
        turtle = export_fn(_TEST_ONTOLOGY_ID, format="turtle")

        assert isinstance(turtle, str)
        assert "Person" in turtle

    def test_search_and_drill_down(self, e2e_seeded_data, patched_db):
        """Agent searches for classes then drills into properties and history."""
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="stdio")
        tools = server._tool_manager._tools

        # Search for "Employee"
        search_fn = tools["search_similar_classes"].fn
        results = search_fn("Employee", ontology_id=_TEST_ONTOLOGY_ID)
        assert isinstance(results, list)
        assert any(r.get("label") == "Employee" for r in results)

        # Get class properties (none seeded, but should return empty list)
        props_fn = tools["get_class_properties"].fn
        props = props_fn("e2e_employee")
        assert props["class_label"] == "Employee"
        assert props["property_count"] == 0

        # Get class history
        history_fn = tools["get_class_history"].fn
        history = history_fn("e2e_employee")
        assert isinstance(history, list)
        assert len(history) >= 1
        assert history[0]["is_current"] is True

    def test_temporal_diff_workflow(self, e2e_seeded_data, patched_db):
        """Agent checks what changed between two timestamps."""
        from app.mcp.server import create_mcp_server

        ts = e2e_seeded_data["timestamp"]
        server = create_mcp_server(transport="sse")
        tools = server._tool_manager._tools

        diff_fn = tools["get_ontology_diff"].fn
        diff = diff_fn(_TEST_ONTOLOGY_ID, t1=ts - 3600, t2=ts + 1)

        assert diff["ontology_id"] == _TEST_ONTOLOGY_ID
        assert diff["added_count"] >= 0

    def test_server_creates_with_all_tools(self):
        """Verify all expected tools are registered."""
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="sse")
        tool_names = set(server._tool_manager._tools.keys())

        expected_tools = {
            "query_collections",
            "run_aql",
            "sample_collection",
            "query_domain_ontology",
            "get_class_hierarchy",
            "get_class_properties",
            "search_similar_classes",
            "trigger_extraction",
            "get_extraction_status",
            "get_merge_candidates",
            "get_ontology_snapshot",
            "get_class_history",
            "get_ontology_diff",
            "get_provenance",
            "export_ontology",
            "run_entity_resolution",
            "explain_entity_match",
            "get_entity_clusters",
        }

        missing = expected_tools - tool_names
        assert not missing, f"Missing tools: {missing}"
