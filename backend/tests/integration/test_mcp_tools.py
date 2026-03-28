"""Integration tests for MCP tools.

Tests each MCP tool returns correct data format using seeded test data.
Covers ontology query tools, pipeline tools, temporal tools, export tools,
ER tools, and org isolation.
"""

from __future__ import annotations

import sys
import time
from unittest.mock import patch

import pytest
from arango.database import StandardDatabase

from app.services.temporal import NEVER_EXPIRES

pytestmark = pytest.mark.integration

_TEST_ONTOLOGY_ID = "mcp_test_ontology"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mcp_collections(test_db: StandardDatabase):
    """Create all collections needed for MCP tool tests."""
    doc_collections = [
        "ontology_classes", "ontology_properties", "ontology_registry",
        "extraction_runs", "documents", "chunks", "curation_decisions",
        "entity_clusters", "api_keys",
    ]
    edge_collections = [
        "subclass_of", "has_property", "equivalent_class",
        "extends_domain", "related_to", "similarTo",
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
def seeded_ontology(test_db: StandardDatabase, mcp_collections):
    """Seed a test ontology with classes, properties, and edges."""
    now = time.time()

    test_db.collection("ontology_registry").insert({
        "_key": _TEST_ONTOLOGY_ID,
        "name": "Test Ontology",
        "tier": "domain",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
    })

    class_data = [
        ("cls_animal", "Animal", "http://test.org#Animal", "Top-level animal class"),
        ("cls_dog", "Dog", "http://test.org#Dog", "A domesticated canine"),
        ("cls_cat", "Cat", "http://test.org#Cat", "A small feline"),
        ("cls_bird", "Bird", "http://test.org#Bird", "A feathered vertebrate"),
    ]

    class_ids = {}
    for key, label, uri, desc in class_data:
        result = test_db.collection("ontology_classes").insert({
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
            "created_by": "test",
            "tier": "domain",
            "status": "approved",
            "ttlExpireAt": None,
        }, return_new=True)
        class_ids[key] = result["new"]["_id"]

    # Historical version of Dog (expired)
    test_db.collection("ontology_classes").insert({
        "_key": "cls_dog_v0",
        "label": "Dog (draft)",
        "uri": "http://test.org#Dog",
        "description": "A dog",
        "ontology_id": _TEST_ONTOLOGY_ID,
        "created": now - 1000,
        "expired": now - 500,
        "version": 0,
        "change_type": "initial",
        "change_summary": "Draft version",
        "created_by": "test",
        "tier": "domain",
        "ttlExpireAt": None,
    })

    prop_result = test_db.collection("ontology_properties").insert({
        "_key": "prop_name",
        "label": "name",
        "uri": "http://test.org#name",
        "description": "The name of the entity",
        "ontology_id": _TEST_ONTOLOGY_ID,
        "property_type": "datatype",
        "range": "xsd:string",
        "domain_class": "http://test.org#Animal",
        "created": now,
        "expired": NEVER_EXPIRES,
        "version": 1,
        "ttlExpireAt": None,
    }, return_new=True)
    prop_id = prop_result["new"]["_id"]

    for child_key in ("cls_dog", "cls_cat", "cls_bird"):
        test_db.collection("subclass_of").insert({
            "_from": class_ids[child_key],
            "_to": class_ids["cls_animal"],
            "created": now,
            "expired": NEVER_EXPIRES,
            "ttlExpireAt": None,
        })

    test_db.collection("has_property").insert({
        "_from": class_ids["cls_animal"],
        "_to": prop_id,
        "created": now,
        "expired": NEVER_EXPIRES,
        "ttlExpireAt": None,
    })

    test_db.collection("extraction_runs").insert({
        "_key": "run_test001",
        "doc_id": "doc_test001",
        "model": "claude-sonnet-4-20250514",
        "status": "completed",
        "started_at": now - 60,
        "completed_at": now,
        "stats": {
            "token_usage": {"total_tokens": 1000},
            "classes_extracted": 4,
            "errors": [],
            "step_logs": [],
        },
    })

    return {
        "ontology_id": _TEST_ONTOLOGY_ID,
        "class_ids": class_ids,
        "prop_id": prop_id,
        "timestamp": now,
    }


@pytest.fixture()
def patched_db(test_db: StandardDatabase):
    """Patch get_db to return the test database."""
    with patch("app.db.client.get_db", return_value=test_db):
        with patch("app.db.client._db", test_db):
            yield test_db


# ---------------------------------------------------------------------------
# Ontology Query Tools
# ---------------------------------------------------------------------------


class TestOntologyQueryTools:
    """Tests for the 4 ontology query MCP tools."""

    def test_query_domain_ontology(self, seeded_ontology, patched_db):
        from app.mcp.tools.ontology import register_ontology_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_ontology_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "query_domain_ontology":
                tool_fn = fn.fn
                break

        assert tool_fn is not None, "query_domain_ontology tool not registered"
        result = tool_fn(_TEST_ONTOLOGY_ID)

        assert result["ontology_id"] == _TEST_ONTOLOGY_ID
        assert result["class_count"] == 4
        assert result["property_count"] == 1
        assert "recent_changes" in result
        assert result["registry"] is not None
        assert result["registry"]["name"] == "Test Ontology"

    def test_get_class_hierarchy(self, seeded_ontology, patched_db):
        from app.mcp.tools.ontology import register_ontology_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_ontology_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_class_hierarchy":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID)
        assert "roots" in result
        roots = result["roots"]
        assert len(roots) >= 1

        animal_root = next((r for r in roots if r["label"] == "Animal"), None)
        assert animal_root is not None
        assert len(animal_root["children"]) == 3

    def test_get_class_hierarchy_subtree(self, seeded_ontology, patched_db):
        from app.mcp.tools.ontology import register_ontology_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_ontology_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_class_hierarchy":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID, root_class_key="cls_animal")
        assert result["label"] == "Animal"
        assert len(result["children"]) == 3

    def test_get_class_properties(self, seeded_ontology, patched_db):
        from app.mcp.tools.ontology import register_ontology_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_ontology_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_class_properties":
                tool_fn = fn.fn
                break

        result = tool_fn("cls_animal")
        assert result["class_key"] == "cls_animal"
        assert result["class_label"] == "Animal"
        assert result["property_count"] == 1
        assert result["properties"][0]["label"] == "name"

    def test_search_similar_classes_fallback(self, seeded_ontology, patched_db):
        from app.mcp.tools.ontology import register_ontology_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_ontology_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "search_similar_classes":
                tool_fn = fn.fn
                break

        results = tool_fn("Dog", ontology_id=_TEST_ONTOLOGY_ID)
        assert isinstance(results, list)
        assert any(r.get("label") == "Dog" for r in results)


# ---------------------------------------------------------------------------
# Pipeline Tools
# ---------------------------------------------------------------------------


class TestPipelineTools:
    """Tests for the 3 pipeline MCP tools."""

    def test_get_extraction_status(self, seeded_ontology, patched_db):
        from app.mcp.tools.pipeline import register_pipeline_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_pipeline_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_extraction_status":
                tool_fn = fn.fn
                break

        result = tool_fn("run_test001")
        assert result["run_id"] == "run_test001"
        assert result["status"] == "completed"
        assert result["classes_extracted"] == 4
        assert result["elapsed_seconds"] is not None

    def test_get_extraction_status_not_found(self, seeded_ontology, patched_db):
        from app.mcp.tools.pipeline import register_pipeline_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_pipeline_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_extraction_status":
                tool_fn = fn.fn
                break

        result = tool_fn("run_nonexistent")
        assert "error" in result

    def test_get_merge_candidates_empty(self, seeded_ontology, patched_db):
        from app.mcp.tools.pipeline import register_pipeline_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_pipeline_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_merge_candidates":
                tool_fn = fn.fn
                break

        results = tool_fn(_TEST_ONTOLOGY_ID)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Temporal Tools
# ---------------------------------------------------------------------------


class TestTemporalTools:
    """Tests for the 3 temporal MCP tools."""

    def test_get_ontology_snapshot(self, seeded_ontology, patched_db):
        from app.mcp.tools.temporal import register_temporal_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_temporal_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_ontology_snapshot":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID)
        assert result["ontology_id"] == _TEST_ONTOLOGY_ID
        assert result["class_count"] == 4
        assert result["property_count"] == 1
        assert len(result["sample_classes"]) <= 10

    def test_get_class_history(self, seeded_ontology, patched_db):
        from app.mcp.tools.temporal import register_temporal_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_temporal_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_class_history":
                tool_fn = fn.fn
                break

        results = tool_fn("cls_dog")
        assert isinstance(results, list)
        assert len(results) >= 2
        assert any(v["is_current"] for v in results)
        assert any(not v["is_current"] for v in results)

    def test_get_ontology_diff(self, seeded_ontology, patched_db):
        from app.mcp.tools.temporal import register_temporal_tools
        from mcp.server.fastmcp import FastMCP

        ts = seeded_ontology["timestamp"]

        mcp = FastMCP("test")
        register_temporal_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_ontology_diff":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID, t1=ts - 2000, t2=ts + 1)
        assert result["ontology_id"] == _TEST_ONTOLOGY_ID
        assert result["added_count"] >= 0
        assert "added" in result
        assert "removed" in result
        assert "changed" in result


# ---------------------------------------------------------------------------
# Export / Provenance Tools
# ---------------------------------------------------------------------------


class TestExportTools:
    """Tests for the 2 export/provenance MCP tools."""

    def test_get_provenance(self, seeded_ontology, patched_db):
        from app.mcp.tools.export import register_export_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_export_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_provenance":
                tool_fn = fn.fn
                break

        result = tool_fn("cls_dog")
        assert result["entity_key"] == "cls_dog"
        assert result["entity_label"] == "Dog"
        assert result["ontology_id"] == _TEST_ONTOLOGY_ID

    def test_get_provenance_not_found(self, seeded_ontology, patched_db):
        from app.mcp.tools.export import register_export_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_export_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_provenance":
                tool_fn = fn.fn
                break

        result = tool_fn("nonexistent_key")
        assert "error" in result

    def test_export_ontology_turtle(self, seeded_ontology, patched_db):
        from app.mcp.tools.export import register_export_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_export_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "export_ontology":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID, format="turtle")
        assert isinstance(result, str)
        assert "owl:Class" in result or "Class" in result
        assert "Animal" in result

    def test_export_ontology_invalid_format(self, seeded_ontology, patched_db):
        from app.mcp.tools.export import register_export_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_export_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "export_ontology":
                tool_fn = fn.fn
                break

        result = tool_fn(_TEST_ONTOLOGY_ID, format="xml")
        assert "Unsupported format" in result


# ---------------------------------------------------------------------------
# ER Tools
# ---------------------------------------------------------------------------


class TestERTools:
    """Tests for the 3 ER MCP tools."""

    def test_explain_entity_match(self, seeded_ontology, patched_db):
        from app.mcp.tools.er import register_er_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_er_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "explain_entity_match":
                tool_fn = fn.fn
                break

        result = tool_fn("cls_dog", "cls_cat")
        assert "field_scores" in result or "error" not in result
        assert result["key1"] == "cls_dog"
        assert result["key2"] == "cls_cat"

    def test_get_entity_clusters_empty(self, seeded_ontology, patched_db):
        from app.mcp.tools.er import register_er_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_er_tools(mcp)

        tool_fn = None
        for name, fn in mcp._tool_manager._tools.items():
            if name == "get_entity_clusters":
                tool_fn = fn.fn
                break

        results = tool_fn(_TEST_ONTOLOGY_ID)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Org Isolation
# ---------------------------------------------------------------------------


class TestOrgIsolation:
    """Tests for organization-scoped filtering."""

    def test_filter_by_org_default_sees_all(self):
        from app.mcp.auth import filter_by_org, get_dev_context

        ctx = get_dev_context()
        data = [
            {"name": "a", "org_id": "org1"},
            {"name": "b", "org_id": "org2"},
            {"name": "c"},
        ]
        filtered = filter_by_org(data, ctx)
        assert len(filtered) == 3

    def test_filter_by_org_scoped(self):
        from app.mcp.auth import OrgContext, filter_by_org

        ctx = OrgContext(
            org_id="org1",
            permissions=frozenset({"ontology:read"}),
        )
        data = [
            {"name": "a", "org_id": "org1"},
            {"name": "b", "org_id": "org2"},
            {"name": "c"},
        ]
        filtered = filter_by_org(data, ctx)
        assert len(filtered) == 2
        assert all(
            item.get("org_id") in (None, "org1") for item in filtered
        )

    def test_validate_api_key_no_collection(self, patched_db):
        from app.mcp.auth import validate_api_key

        result = validate_api_key("some-key")
        assert result["valid"] is False

    def test_resolve_org_context_stdio(self):
        from app.mcp.auth import resolve_org_context

        ctx = resolve_org_context(transport="stdio")
        assert ctx.org_id == "default"
        assert ctx.has_permission("ontology:read")

    def test_resolve_org_context_sse_no_key(self):
        from app.mcp.auth import resolve_org_context

        ctx = resolve_org_context(transport="sse")
        assert ctx.org_id == "default"


# ---------------------------------------------------------------------------
# Server Configuration
# ---------------------------------------------------------------------------


class TestServerConfiguration:
    """Tests for MCP server creation and argument parsing."""

    def test_create_mcp_server_stdio(self):
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="stdio")
        assert server is not None
        assert server.name == "aoe-dev"

    def test_create_mcp_server_sse(self):
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="sse")
        assert server is not None
        assert server.name == "aoe-runtime"

    def test_parse_args_defaults(self):
        from app.mcp.server import parse_args

        args = parse_args([])
        assert args.transport == "stdio"
        assert args.host == "0.0.0.0"
        assert args.port == 8001

    def test_parse_args_sse(self):
        from app.mcp.server import parse_args

        args = parse_args(["--transport", "sse", "--port", "9001"])
        assert args.transport == "sse"
        assert args.port == 9001
