"""Unit tests for MCP (Model Context Protocol) modules.

Covers auth, server, resources, and all tool modules with mocked DB calls.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants reused across tests
# ---------------------------------------------------------------------------
NEVER_EXPIRES: int = sys.maxsize


# ===========================================================================
# auth.py
# ===========================================================================


class TestOrgContext:
    """Tests for the OrgContext dataclass and permission helpers."""

    def test_has_permission_true(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="org1", permissions=frozenset({"ontology:read"}))
        assert ctx.has_permission("ontology:read") is True

    def test_has_permission_false(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="org1", permissions=frozenset())
        assert ctx.has_permission("ontology:read") is False

    def test_can_read_ontology(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="o", permissions=frozenset({"ontology:read"}))
        assert ctx.can_read_ontology() is True

    def test_can_write_ontology(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="o", permissions=frozenset({"ontology:write"}))
        assert ctx.can_write_ontology() is True

    def test_can_trigger_extraction(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="o", permissions=frozenset({"extraction:trigger"}))
        assert ctx.can_trigger_extraction() is True

    def test_can_trigger_er(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="o", permissions=frozenset({"er:trigger"}))
        assert ctx.can_trigger_er() is True

    def test_frozen_dataclass(self):
        from app.mcp.auth import OrgContext

        ctx = OrgContext(org_id="o", permissions=frozenset())
        with pytest.raises(AttributeError):
            ctx.org_id = "other"  # type: ignore[misc]


class TestGetDevContext:
    def test_returns_dev_context(self):
        from app.mcp.auth import DEFAULT_ORG_ID, DEFAULT_PERMISSIONS, get_dev_context

        ctx = get_dev_context()
        assert ctx.org_id == DEFAULT_ORG_ID
        assert ctx.permissions == DEFAULT_PERMISSIONS
        assert ctx.api_key_id == "dev"


class TestValidateApiKey:
    @patch("app.mcp.auth.get_db")
    def test_no_api_keys_collection(self, mock_get_db):
        from app.mcp.auth import validate_api_key

        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        result = validate_api_key("some-key")
        assert result["valid"] is False
        assert "not configured" in result["error"]

    @patch("app.mcp.auth.run_aql")
    @patch("app.mcp.auth.get_db")
    def test_invalid_key(self, mock_get_db, mock_run_aql):
        from app.mcp.auth import validate_api_key

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter([])  # no results

        result = validate_api_key("bad-key")
        assert result["valid"] is False
        assert "Invalid" in result["error"]

    @patch("app.mcp.auth.run_aql")
    @patch("app.mcp.auth.get_db")
    def test_expired_key(self, mock_get_db, mock_run_aql):
        from app.mcp.auth import validate_api_key

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter(
            [
                {
                    "_key": "k1",
                    "org_id": "org1",
                    "expires_at": 1.0,  # expired long ago
                    "permissions": ["ontology:read"],
                    "status": "active",
                }
            ]
        )

        result = validate_api_key("expired-key")
        assert result["valid"] is False
        assert "expired" in result["error"]

    @patch("app.mcp.auth.run_aql")
    @patch("app.mcp.auth.get_db")
    def test_valid_key(self, mock_get_db, mock_run_aql):
        from app.mcp.auth import validate_api_key

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter(
            [
                {
                    "_key": "k1",
                    "org_id": "org1",
                    "expires_at": time.time() + 9999,
                    "permissions": ["ontology:read"],
                    "status": "active",
                }
            ]
        )

        result = validate_api_key("good-key")
        assert result["valid"] is True
        assert result["org_id"] == "org1"
        assert result["api_key_id"] == "k1"

    @patch("app.mcp.auth.run_aql")
    @patch("app.mcp.auth.get_db")
    def test_valid_key_no_expiry(self, mock_get_db, mock_run_aql):
        from app.mcp.auth import validate_api_key

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter(
            [
                {
                    "_key": "k2",
                    "org_id": "org2",
                    "permissions": ["ontology:read", "ontology:write"],
                    "status": "active",
                }
            ]
        )

        result = validate_api_key("no-expiry-key")
        assert result["valid"] is True

    @patch("app.mcp.auth.get_db", side_effect=Exception("db down"))
    def test_db_error(self, mock_get_db):
        from app.mcp.auth import validate_api_key

        result = validate_api_key("any-key")
        assert result["valid"] is False
        assert "Validation error" in result["error"]


class TestResolveOrgContext:
    def test_stdio_transport(self):
        from app.mcp.auth import DEFAULT_ORG_ID, resolve_org_context

        ctx = resolve_org_context(transport="stdio")
        assert ctx.org_id == DEFAULT_ORG_ID

    def test_sse_no_api_key(self):
        from app.mcp.auth import DEFAULT_ORG_ID, resolve_org_context

        ctx = resolve_org_context(transport="sse", api_key=None)
        assert ctx.org_id == DEFAULT_ORG_ID

    @patch("app.mcp.auth.validate_api_key")
    def test_sse_invalid_key_falls_back(self, mock_validate):
        from app.mcp.auth import DEFAULT_ORG_ID, resolve_org_context

        mock_validate.return_value = {"valid": False, "error": "bad"}
        ctx = resolve_org_context(transport="sse", api_key="bad-key")
        assert ctx.org_id == DEFAULT_ORG_ID

    @patch("app.mcp.auth.validate_api_key")
    def test_sse_valid_key(self, mock_validate):
        from app.mcp.auth import resolve_org_context

        mock_validate.return_value = {
            "valid": True,
            "org_id": "acme",
            "api_key_id": "k99",
            "permissions": ["ontology:read"],
        }
        ctx = resolve_org_context(transport="sse", api_key="good-key")
        assert ctx.org_id == "acme"
        assert ctx.api_key_id == "k99"
        assert ctx.has_permission("ontology:read")


class TestFilterByOrg:
    def test_default_org_sees_everything(self):
        from app.mcp.auth import DEFAULT_ORG_ID, OrgContext, filter_by_org

        ctx = OrgContext(org_id=DEFAULT_ORG_ID, permissions=frozenset())
        data = [{"org_id": "a"}, {"org_id": "b"}]
        assert filter_by_org(data, ctx) == data

    def test_filters_to_own_org(self):
        from app.mcp.auth import OrgContext, filter_by_org

        ctx = OrgContext(org_id="a", permissions=frozenset())
        data = [{"org_id": "a"}, {"org_id": "b"}, {"name": "global"}]
        result = filter_by_org(data, ctx)
        assert len(result) == 2  # a's item + global (no org_id)

    def test_includes_items_without_org_field(self):
        from app.mcp.auth import OrgContext, filter_by_org

        ctx = OrgContext(org_id="x", permissions=frozenset())
        data = [{"name": "shared"}]
        assert filter_by_org(data, ctx) == data


class TestHashApiKey:
    def test_deterministic(self):
        from app.mcp.auth import _hash_api_key

        h1 = _hash_api_key("test-key")
        h2 = _hash_api_key("test-key")
        assert h1 == h2
        assert h1 == hashlib.sha256(b"test-key").hexdigest()


# ===========================================================================
# server.py
# ===========================================================================


class TestCreateMcpServer:
    @patch("app.mcp.server.register_ontology_resources")
    @patch("app.mcp.server.register_er_tools")
    @patch("app.mcp.server.register_export_tools")
    @patch("app.mcp.server.register_temporal_tools")
    @patch("app.mcp.server.register_pipeline_tools")
    @patch("app.mcp.server.register_ontology_tools")
    @patch("app.mcp.server.register_introspection_tools")
    def test_stdio_server(self, *mocks):
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="stdio")
        assert server is not None
        assert server.name == "aoe-dev"
        for m in mocks:
            m.assert_called_once()

    @patch("app.mcp.server.register_ontology_resources")
    @patch("app.mcp.server.register_er_tools")
    @patch("app.mcp.server.register_export_tools")
    @patch("app.mcp.server.register_temporal_tools")
    @patch("app.mcp.server.register_pipeline_tools")
    @patch("app.mcp.server.register_ontology_tools")
    @patch("app.mcp.server.register_introspection_tools")
    def test_sse_server(self, *mocks):
        from app.mcp.server import create_mcp_server

        server = create_mcp_server(transport="sse", host="127.0.0.1", port=9000)
        assert server is not None
        assert server.name == "aoe-runtime"


class TestParseArgs:
    def test_defaults(self):
        from app.mcp.server import parse_args

        args = parse_args([])
        assert args.transport == "stdio"
        assert args.host == "0.0.0.0"
        assert args.port == 8001

    def test_sse_args(self):
        from app.mcp.server import parse_args

        args = parse_args(["--transport", "sse", "--host", "127.0.0.1", "--port", "9000"])
        assert args.transport == "sse"
        assert args.host == "127.0.0.1"
        assert args.port == 9000


# ===========================================================================
# resources/ontology.py
# ===========================================================================


class TestOntologyDomainSummary:
    """Tests for the ontology_domain_summary resource."""

    @patch("app.mcp.resources.ontology.run_aql")
    @patch("app.mcp.resources.ontology.get_db")
    def test_happy_path(self, mock_get_db, mock_run_aql):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        # First call: registry entries. Second call: class count for entry.
        mock_run_aql.side_effect = [
            iter(
                [
                    {
                        "ontology_id": "o1",
                        "name": "Test",
                        "tier": "local",
                        "status": "active",
                        "created_at": 1.0,
                    }
                ]
            ),
            iter([5]),
        ]

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://ontology/domain/summary"]())
        assert result["total_ontologies"] == 1
        assert result["ontologies"][0]["class_count"] == 5

    @patch("app.mcp.resources.ontology.get_db")
    def test_no_registry_collection(self, mock_get_db):
        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://ontology/domain/summary"]())
        assert result["total_ontologies"] == 0

    @patch("app.mcp.resources.ontology.get_db", side_effect=Exception("db fail"))
    def test_error_handling(self, mock_get_db):
        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://ontology/domain/summary"]())
        assert "error" in result


class TestExtractionRunsRecent:
    @patch("app.mcp.resources.ontology.run_aql")
    @patch("app.mcp.resources.ontology.get_db")
    def test_happy_path(self, mock_get_db, mock_run_aql):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter(
            [
                {"run_id": "r1", "status": "completed", "doc_id": "d1"},
            ]
        )

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://extraction/runs/recent"]())
        assert result["count"] == 1


class TestSystemHealth:
    @patch("app.mcp.resources.ontology.get_db")
    def test_healthy(self, mock_get_db):
        db = MagicMock()
        col_mock = MagicMock()
        col_mock.count.return_value = 42
        db.collections.return_value = [
            {"name": "ontology_classes", "system": False, "type": 2},
        ]
        db.collection.return_value = col_mock
        mock_get_db.return_value = db

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://system/health"]())
        assert result["status"] == "healthy"
        assert result["arango_connected"] is True
        assert result["collection_count"] == 1

    @patch("app.mcp.resources.ontology.get_db")
    def test_degraded_when_db_query_fails(self, mock_get_db):
        db = MagicMock()
        db.collections.side_effect = Exception("connection refused")
        mock_get_db.return_value = db

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://system/health"]())
        assert result["status"] == "degraded"
        assert result["arango_connected"] is False

    @patch("app.mcp.resources.ontology.get_db")
    def test_skips_system_collections(self, mock_get_db):
        db = MagicMock()
        db.collections.return_value = [
            {"name": "_system", "system": True, "type": 2},
            {"name": "user_col", "system": False, "type": 2},
        ]
        col_mock = MagicMock()
        col_mock.count.return_value = 10
        db.collection.return_value = col_mock
        mock_get_db.return_value = db

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://system/health"]())
        assert result["collection_count"] == 1  # only user_col

    @patch("app.mcp.resources.ontology.get_db")
    def test_edge_collection_type(self, mock_get_db):
        db = MagicMock()
        db.collections.return_value = [
            {"name": "subclass_of", "system": False, "type": 3},
        ]
        col_mock = MagicMock()
        col_mock.count.return_value = 7
        db.collection.return_value = col_mock
        mock_get_db.return_value = db

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://system/health"]())
        assert result["collections"][0]["type"] == "edge"


class TestOntologyStats:
    @patch("app.mcp.resources.ontology.doc_get")
    @patch("app.mcp.resources.ontology.run_aql")
    @patch("app.mcp.resources.ontology.get_db")
    def test_happy_path(self, mock_get_db, mock_run_aql, mock_doc_get):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        # class_count, prop counts x3, class_ids, prop _id queries x3, edges x7, versions
        mock_run_aql.side_effect = [
            iter([3]),
            iter([1]),
            iter([0]),
            iter([1]),
            iter(["ontology_classes/c1", "ontology_classes/c2", "ontology_classes/c3"]),
            iter([]),
            iter([]),
            iter([]),
            iter([{"f": "ontology_classes/c1", "t": "ontology_classes/c2"}]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([5]),
        ]
        mock_doc_get.return_value = {"name": "Test Onto", "status": "active", "tier": "local"}

        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://ontology/{ontology_id}/stats"]("test-onto"))
        assert result["class_count"] == 3
        assert result["property_count"] == 2
        assert result["total_versions"] == 5
        assert result["registry"]["name"] == "Test Onto"

    @patch("app.mcp.resources.ontology.get_db", side_effect=Exception("boom"))
    def test_error(self, mock_get_db):
        mcp = MagicMock()
        captured = {}

        def fake_resource(uri):
            def decorator(fn):
                captured[uri] = fn
                return fn

            return decorator

        mcp.resource = fake_resource
        from app.mcp.resources.ontology import register_ontology_resources

        register_ontology_resources(mcp)

        result = json.loads(captured["aoe://ontology/{ontology_id}/stats"]("o1"))
        assert "error" in result


# ===========================================================================
# Helper to capture MCP tool registrations
# ===========================================================================


def _capture_tools(register_fn):
    """Call a register_*_tools function with a mock MCP and return a dict
    mapping tool function names to the actual functions."""
    mcp = MagicMock()
    captured = {}

    def fake_tool():
        def decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return decorator

    mcp.tool = fake_tool
    # Some register fns also use mcp.resource
    mcp.resource = lambda uri: lambda fn: fn
    register_fn(mcp)
    return captured


# ===========================================================================
# tools/introspection.py
# ===========================================================================


class TestQueryCollections:
    @patch("app.mcp.tools.introspection.get_db")
    def test_lists_collections(self, mock_get_db):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        col_mock = MagicMock()
        col_mock.count.return_value = 10
        db.collections.return_value = [
            {"name": "ontology_classes", "system": False, "type": 2},
            {"name": "_graphs", "system": True, "type": 2},
        ]
        db.collection.return_value = col_mock
        mock_get_db.return_value = db

        tools = _capture_tools(register_introspection_tools)
        result = tools["query_collections"]()
        assert len(result) == 1
        assert result[0]["name"] == "ontology_classes"
        assert result[0]["count"] == 10
        assert result[0]["type"] == "document"

    @patch("app.mcp.tools.introspection.get_db")
    def test_edge_type(self, mock_get_db):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        col_mock = MagicMock()
        col_mock.count.return_value = 5
        db.collections.return_value = [
            {"name": "subclass_of", "system": False, "type": 3},
        ]
        db.collection.return_value = col_mock
        mock_get_db.return_value = db

        tools = _capture_tools(register_introspection_tools)
        result = tools["query_collections"]()
        assert result[0]["type"] == "edge"

    @patch("app.mcp.tools.introspection.get_db", side_effect=Exception("down"))
    def test_error(self, mock_get_db):
        from app.mcp.tools.introspection import register_introspection_tools

        tools = _capture_tools(register_introspection_tools)
        result = tools["query_collections"]()
        assert result[0]["error"]


class TestRunAql:
    @patch("app.mcp.tools.introspection._run_aql")
    @patch("app.mcp.tools.introspection.get_db")
    def test_runs_query(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter([{"_key": "k1"}, {"_key": "k2"}])

        tools = _capture_tools(register_introspection_tools)
        result = tools["run_aql"]("RETURN 1")
        assert len(result) == 2

    @patch("app.mcp.tools.introspection._run_aql")
    @patch("app.mcp.tools.introspection.get_db")
    def test_caps_at_100(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter({"n": i} for i in range(200))

        tools = _capture_tools(register_introspection_tools)
        result = tools["run_aql"]("FOR i IN 1..200 RETURN i")
        assert len(result) == 100

    @patch("app.mcp.tools.introspection.get_db", side_effect=Exception("fail"))
    def test_error(self, mock_get_db):
        from app.mcp.tools.introspection import register_introspection_tools

        tools = _capture_tools(register_introspection_tools)
        result = tools["run_aql"]("BAD QUERY")
        assert "error" in result[0]


class TestSampleCollection:
    @patch("app.mcp.tools.introspection._run_aql")
    @patch("app.mcp.tools.introspection.get_db")
    def test_returns_samples(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter([{"_key": "d1"}, {"_key": "d2"}])

        tools = _capture_tools(register_introspection_tools)
        result = tools["sample_collection"]("my_col", limit=2)
        assert len(result) == 2

    @patch("app.mcp.tools.introspection.get_db")
    def test_collection_not_found(self, mock_get_db):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        tools = _capture_tools(register_introspection_tools)
        result = tools["sample_collection"]("no_such")
        assert "error" in result[0]
        assert "does not exist" in result[0]["error"]

    @patch("app.mcp.tools.introspection._run_aql")
    @patch("app.mcp.tools.introspection.get_db")
    def test_limit_clamped(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.introspection import register_introspection_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter([])

        tools = _capture_tools(register_introspection_tools)
        # limit=50 should be clamped to 20
        tools["sample_collection"]("col", limit=50)
        call_args = mock_run_aql.call_args
        assert call_args[1]["bind_vars"]["lim"] == 20


# ===========================================================================
# tools/ontology.py
# ===========================================================================


class TestQueryDomainOntology:
    @patch("app.mcp.tools.ontology.doc_get")
    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_happy_path(self, mock_get_db, mock_run_aql, mock_doc_get):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        # class_count, recent_changes, prop counts x3, hierarchy_depth
        mock_run_aql.side_effect = [
            iter([10]),  # class count
            iter([{"key": "c1", "label": "Cls1"}]),  # recent changes
            iter([1]),
            iter([1]),
            iter([2]),  # property_count sum == 4
            iter([2]),  # hierarchy depth
        ]
        mock_doc_get.return_value = {
            "name": "My Onto",
            "status": "active",
            "tier": "local",
            "created_at": 1.0,
        }

        tools = _capture_tools(register_ontology_tools)
        result = tools["query_domain_ontology"]("onto-1")
        assert result["class_count"] == 10
        assert result["property_count"] == 4
        assert result["registry"]["name"] == "My Onto"

    @patch("app.mcp.tools.ontology.get_db", side_effect=Exception("fail"))
    def test_error(self, mock_get_db):
        from app.mcp.tools.ontology import register_ontology_tools

        tools = _capture_tools(register_ontology_tools)
        result = tools["query_domain_ontology"]("x")
        assert "error" in result


class TestGetClassHierarchy:
    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_builds_tree(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "key": "root",
                "id": "ontology_classes/root",
                "label": "Root",
                "uri": "u:root",
                "description": "",
            },
            {
                "key": "child",
                "id": "ontology_classes/child",
                "label": "Child",
                "uri": "u:child",
                "description": "",
            },
        ]
        edges = [
            {"from_id": "ontology_classes/child", "to_id": "ontology_classes/root"},
        ]
        mock_run_aql.side_effect = [iter(classes), iter(edges)]

        tools = _capture_tools(register_ontology_tools)
        result = tools["get_class_hierarchy"]("onto-1")
        assert result["ontology_id"] == "onto-1"
        assert len(result["roots"]) == 1
        assert result["roots"][0]["key"] == "root"
        assert len(result["roots"][0]["children"]) == 1

    @patch("app.mcp.tools.ontology.get_db")
    def test_no_classes_collection(self, mock_get_db):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        tools = _capture_tools(register_ontology_tools)
        result = tools["get_class_hierarchy"]("x")
        assert "error" in result

    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_root_class_key_not_found(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "key": "c1",
                "id": "ontology_classes/c1",
                "label": "C1",
                "uri": "u:c1",
                "description": "",
            },
        ]
        mock_run_aql.side_effect = [iter(classes), iter([])]

        tools = _capture_tools(register_ontology_tools)
        result = tools["get_class_hierarchy"]("o1", root_class_key="missing")
        assert "error" in result
        assert "not found" in result["error"]


class TestGetClassProperties:
    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_returns_properties(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        cls_doc = {"_key": "c1", "_id": "ontology_classes/c1", "label": "MyClass", "uri": "u:c1"}
        legacy_prop = {"_key": "p1", "label": "prop1", "property_type": "datatype"}
        mock_run_aql.side_effect = [
            iter([cls_doc]),
            iter([]),  # PGT datatype via rdfs_domain
            iter([]),  # PGT object via rdfs_domain
            iter([legacy_prop]),  # legacy has_property
        ]

        tools = _capture_tools(register_ontology_tools)
        result = tools["get_class_properties"]("c1")
        assert result["class_key"] == "c1"
        assert result["property_count"] == 1

    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_class_not_found(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.return_value = iter([])  # no class found

        tools = _capture_tools(register_ontology_tools)
        result = tools["get_class_properties"]("missing")
        assert "error" in result
        assert "not found" in result["error"]


class TestSearchSimilarClasses:
    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_fallback_search(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        db.views.return_value = []  # no search view
        mock_get_db.return_value = db

        search_results = [{"key": "c1", "label": "Animal"}]
        mock_run_aql.return_value = iter(search_results)

        tools = _capture_tools(register_ontology_tools)
        result = tools["search_similar_classes"]("Animal")
        assert len(result) == 1
        assert result[0]["label"] == "Animal"

    @patch("app.mcp.tools.ontology.run_aql")
    @patch("app.mcp.tools.ontology.get_db")
    def test_bm25_search(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = True
        db.views.return_value = [{"name": "ontology_classes_search"}]
        mock_get_db.return_value = db

        mock_run_aql.return_value = iter([{"key": "c1", "label": "Dog", "score": 2.5}])

        tools = _capture_tools(register_ontology_tools)
        result = tools["search_similar_classes"]("Dog", ontology_id="o1")
        assert len(result) == 1

    @patch("app.mcp.tools.ontology.get_db")
    def test_no_classes_collection(self, mock_get_db):
        from app.mcp.tools.ontology import register_ontology_tools

        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_db.return_value = db

        tools = _capture_tools(register_ontology_tools)
        result = tools["search_similar_classes"]("query")
        assert "error" in result[0]


# ===========================================================================
# tools/export.py
# ===========================================================================


class TestGetProvenance:
    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.doc_get")
    @patch("app.mcp.tools.export.get_db")
    def test_entity_not_found(self, mock_get_db, mock_doc_get, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        mock_run_aql.side_effect = [iter([]), iter([]), iter([]), iter([])]

        tools = _capture_tools(register_export_tools)
        result = tools["get_provenance"]("missing-key")
        assert "error" in result
        assert "not found" in result["error"]

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.doc_get")
    @patch("app.mcp.tools.export.get_db")
    def test_full_provenance_chain(self, mock_get_db, mock_doc_get, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        entity = {
            "_key": "e1",
            "label": "Animal",
            "uri": "u:animal",
            "ontology_id": "extraction_run123",
            "created": 1.0,
            "created_by": "extractor",
            "version": 1,
        }
        extraction_doc = {
            "doc_id": "doc1",
            "model": "gpt-4",
            "status": "completed",
            "started_at": 1.0,
            "completed_at": 2.0,
        }
        source_doc = {
            "filename": "test.pdf",
            "content_type": "application/pdf",
            "uploaded_at": 0.5,
        }

        # _find_entity: first collection query returns result
        # _get_related_chunks: returns chunks
        # _get_curation_decisions: returns decisions
        mock_run_aql.side_effect = [
            iter([entity]),  # _find_entity - ontology_classes
            iter([{"chunk_index": 0, "text_preview": "Animals are..."}]),  # _get_related_chunks
            iter([{"decision": "accept", "decided_at": 3.0}]),  # _get_curation_decisions
        ]
        # _get_extraction_run and _get_document_info use doc_get
        mock_doc_get.side_effect = [extraction_doc, source_doc]

        tools = _capture_tools(register_export_tools)
        result = tools["get_provenance"]("e1")
        assert result["entity_key"] == "e1"
        assert result["entity_label"] == "Animal"
        assert result["extraction_run"]["run_id"] == "run123"
        assert result["source_document"]["filename"] == "test.pdf"
        assert len(result["source_chunks"]) == 1
        assert len(result["curation_decisions"]) == 1

    @patch("app.mcp.tools.export.get_db", side_effect=Exception("boom"))
    def test_error(self, mock_get_db):
        from app.mcp.tools.export import register_export_tools

        tools = _capture_tools(register_export_tools)
        result = tools["get_provenance"]("x")
        assert "error" in result


class TestExportOntology:
    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_no_entities(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db
        # classes, 3 property collections, rdfs_range_class, rdfs_domain (then early return)
        mock_run_aql.side_effect = [
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("empty-onto")
        assert "No entities found" in result

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_unsupported_format(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        mock_get_db.return_value = db

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="xml")
        assert "Unsupported format" in result

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_turtle_export(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "_key": "c1",
                "_id": "ontology_classes/c1",
                "label": "Animal",
                "uri": "http://example.org/Animal",
                "description": "An animal",
            }
        ]
        properties = [
            {
                "_key": "p1",
                "_id": "ontology_properties/p1",
                "label": "hasName",
                "uri": "http://example.org/hasName",
                "description": "Name property",
                "property_type": "datatype",
            }
        ]
        mock_run_aql.side_effect = [
            iter(classes),
            iter(properties),
            iter([]),
            iter([]),
            iter([]),  # rdfs_range_class
            iter([]),  # rdfs_domain
            iter([]),  # subclass_of
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="turtle")
        assert "Animal" in result
        assert "hasName" in result

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_jsonld_export(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "_key": "c1",
                "_id": "ontology_classes/c1",
                "label": "Thing",
                "uri": "http://example.org/Thing",
                "description": None,
            }
        ]
        mock_run_aql.side_effect = [
            iter(classes),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="json-ld")
        # Should be valid JSON-LD
        parsed = json.loads(result)
        assert isinstance(parsed, (dict, list))

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_object_property(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {"_key": "c1", "_id": "ontology_classes/c1", "label": "A", "uri": "http://ex.org/A"}
        ]
        properties = [
            {
                "_key": "p1",
                "_id": "ontology_properties/p1",
                "label": "relatesTo",
                "uri": "http://ex.org/relatesTo",
                "property_type": "object",
            }
        ]
        mock_run_aql.side_effect = [
            iter(classes),
            iter(properties),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="turtle")
        assert "ObjectProperty" in result

    @patch("app.mcp.tools.export.get_db", side_effect=Exception("crash"))
    def test_error(self, mock_get_db):
        from app.mcp.tools.export import register_export_tools

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1")
        assert "Export failed" in result

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_subclass_edges_in_export(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "_key": "parent",
                "_id": "ontology_classes/parent",
                "label": "Parent",
                "uri": "http://ex.org/Parent",
            },
            {
                "_key": "child",
                "_id": "ontology_classes/child",
                "label": "Child",
                "uri": "http://ex.org/Child",
            },
        ]
        edges = [{"from_id": "ontology_classes/child", "to_id": "ontology_classes/parent"}]
        mock_run_aql.side_effect = [
            iter(classes),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter([]),
            iter(edges),
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="turtle")
        assert "subClassOf" in result

    @patch("app.mcp.tools.export.run_aql")
    @patch("app.mcp.tools.export.get_db")
    def test_pgt_object_property_domain_and_range_in_turtle(self, mock_get_db, mock_run_aql):
        from app.mcp.tools.export import register_export_tools

        db = MagicMock()
        db.has_collection.return_value = True
        mock_get_db.return_value = db

        classes = [
            {
                "_key": "c1",
                "_id": "ontology_classes/c1",
                "label": "DomainCls",
                "uri": "http://ex.org/DomainCls",
                "description": None,
            }
        ]
        obj_prop = {
            "_key": "c1_rel",
            "_id": "ontology_object_properties/c1_rel",
            "label": "pointsTo",
            "uri": "http://ex.org/pointsTo",
            "description": "",
        }
        range_rows = [
            {
                "from_id": "ontology_object_properties/c1_rel",
                "uri": "http://ex.org/TargetCls",
            }
        ]
        domain_rows = [
            {
                "from_id": "ontology_object_properties/c1_rel",
                "to_id": "ontology_classes/c1",
            }
        ]
        mock_run_aql.side_effect = [
            iter(classes),
            iter([]),
            iter([obj_prop]),
            iter([]),
            iter(range_rows),
            iter(domain_rows),
            iter([]),
        ]

        tools = _capture_tools(register_export_tools)
        result = tools["export_ontology"]("o1", format="turtle")
        assert "ObjectProperty" in result
        assert "rdfs:domain" in result
        assert "rdfs:range" in result
        assert "TargetCls" in result


# ===========================================================================
# tools/export.py helper functions
# ===========================================================================


class TestExportHelpers:
    @patch("app.mcp.tools.export.run_aql")
    def test_find_entity_in_classes(self, mock_run_aql):
        from app.mcp.tools.export import _find_entity

        db = MagicMock()
        db.has_collection.return_value = True
        entity = {"_key": "e1", "label": "Foo"}
        mock_run_aql.return_value = iter([entity])

        result = _find_entity(db, "e1")
        assert result == entity

    @patch("app.mcp.tools.export.run_aql")
    def test_find_entity_not_found(self, mock_run_aql):
        from app.mcp.tools.export import _find_entity

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.side_effect = [iter([]), iter([]), iter([]), iter([])]

        result = _find_entity(db, "missing")
        assert result is None

    @patch("app.mcp.tools.export.doc_get")
    def test_get_extraction_run_found(self, mock_doc_get):
        from app.mcp.tools.export import _get_extraction_run

        db = MagicMock()
        db.has_collection.return_value = True
        mock_doc_get.return_value = {
            "doc_id": "d1",
            "model": "gpt-4",
            "status": "completed",
            "started_at": 1.0,
            "completed_at": 2.0,
        }

        result = _get_extraction_run(db, "r1")
        assert result["run_id"] == "r1"
        assert result["doc_id"] == "d1"

    @patch("app.mcp.tools.export.doc_get")
    def test_get_extraction_run_not_found(self, mock_doc_get):
        from app.mcp.tools.export import _get_extraction_run

        db = MagicMock()
        db.has_collection.return_value = True
        mock_doc_get.return_value = None

        result = _get_extraction_run(db, "r1")
        assert result is None

    def test_get_extraction_run_no_collection(self):
        from app.mcp.tools.export import _get_extraction_run

        db = MagicMock()
        db.has_collection.return_value = False

        result = _get_extraction_run(db, "r1")
        assert result is None

    @patch("app.mcp.tools.export.doc_get")
    def test_get_document_info(self, mock_doc_get):
        from app.mcp.tools.export import _get_document_info

        db = MagicMock()
        db.has_collection.return_value = True
        mock_doc_get.return_value = {
            "filename": "test.pdf",
            "content_type": "application/pdf",
            "uploaded_at": 1.0,
        }

        result = _get_document_info(db, "d1")
        assert result["filename"] == "test.pdf"

    def test_get_document_info_no_collection(self):
        from app.mcp.tools.export import _get_document_info

        db = MagicMock()
        db.has_collection.return_value = False

        result = _get_document_info(db, "d1")
        assert result is None

    @patch("app.mcp.tools.export.run_aql")
    def test_get_related_chunks(self, mock_run_aql):
        from app.mcp.tools.export import _get_related_chunks

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = iter([{"chunk_index": 0, "text_preview": "..."}])

        result = _get_related_chunks(db, "d1", "Animal")
        assert len(result) == 1

    def test_get_related_chunks_no_collection(self):
        from app.mcp.tools.export import _get_related_chunks

        db = MagicMock()
        db.has_collection.return_value = False

        result = _get_related_chunks(db, "d1", "Animal")
        assert result == []

    def test_get_related_chunks_no_label(self):
        from app.mcp.tools.export import _get_related_chunks

        db = MagicMock()
        db.has_collection.return_value = True

        result = _get_related_chunks(db, "d1", "")
        assert result == []

    @patch("app.mcp.tools.export.run_aql")
    def test_get_curation_decisions(self, mock_run_aql):
        from app.mcp.tools.export import _get_curation_decisions

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = iter([{"decision": "accept"}])

        result = _get_curation_decisions(db, "e1")
        assert len(result) == 1

    def test_get_curation_decisions_no_collection(self):
        from app.mcp.tools.export import _get_curation_decisions

        db = MagicMock()
        db.has_collection.return_value = False

        result = _get_curation_decisions(db, "e1")
        assert result == []


# ===========================================================================
# tools/pipeline.py
# ===========================================================================


class TestTriggerExtraction:
    @patch("app.mcp.tools.pipeline.asyncio")
    @patch("app.services.extraction.start_run")
    def test_trigger_basic(self, mock_start_run, mock_asyncio):
        from app.mcp.tools.pipeline import register_pipeline_tools

        loop = MagicMock()
        mock_asyncio.get_running_loop.side_effect = RuntimeError
        mock_asyncio.new_event_loop.return_value = loop
        mock_asyncio.set_event_loop = MagicMock()

        loop.run_until_complete.return_value = {
            "_key": "run1",
            "status": "running",
            "started_at": 1.0,
        }

        tools = _capture_tools(register_pipeline_tools)
        result = tools["trigger_extraction"]("doc1")
        assert result["run_id"] == "run1"
        assert result["status"] == "running"
        assert result["document_id"] == "doc1"

    @patch("app.mcp.tools.pipeline.asyncio")
    @patch("app.services.extraction.start_run")
    def test_trigger_with_ontology_id(self, mock_start_run, mock_asyncio):
        from app.mcp.tools.pipeline import register_pipeline_tools

        loop = MagicMock()
        mock_asyncio.get_running_loop.side_effect = RuntimeError
        mock_asyncio.new_event_loop.return_value = loop
        mock_asyncio.set_event_loop = MagicMock()

        loop.run_until_complete.return_value = {
            "_key": "run2",
            "status": "running",
            "started_at": 1.0,
        }

        tools = _capture_tools(register_pipeline_tools)
        result = tools["trigger_extraction"]("doc1", ontology_id="onto-1")
        assert result["ontology_id"] == "onto-1"

    def test_trigger_error(self):
        from app.mcp.tools.pipeline import register_pipeline_tools

        tools = _capture_tools(register_pipeline_tools)

        with (
            patch("app.services.extraction.start_run", side_effect=Exception("fail")),
            patch("app.mcp.tools.pipeline.asyncio") as mock_asyncio,
        ):
            loop = MagicMock()
            mock_asyncio.get_running_loop.side_effect = RuntimeError
            mock_asyncio.new_event_loop.return_value = loop
            loop.run_until_complete.side_effect = Exception("fail")

            result = tools["trigger_extraction"]("doc1")
            assert "error" in result


class TestGetExtractionStatus:
    @patch("app.db.client.get_db")
    @patch("app.services.extraction.get_run")
    def test_completed_run(self, mock_get_run, mock_get_db):
        from app.mcp.tools.pipeline import register_pipeline_tools

        mock_get_db.return_value = MagicMock()
        mock_get_run.return_value = {
            "status": "completed",
            "doc_id": "d1",
            "model": "gpt-4",
            "started_at": 100.0,
            "completed_at": 110.0,
            "stats": {
                "token_usage": {"total": 500},
                "classes_extracted": 5,
                "errors": [],
                "step_logs": ["s1", "s2"],
            },
        }

        tools = _capture_tools(register_pipeline_tools)
        result = tools["get_extraction_status"]("r1")
        assert result["status"] == "completed"
        assert result["elapsed_seconds"] == 10.0
        assert result["classes_extracted"] == 5
        assert result["step_count"] == 2

    @patch("app.db.client.get_db")
    @patch("app.services.extraction.get_run")
    def test_running_run(self, mock_get_run, mock_get_db):
        from app.mcp.tools.pipeline import register_pipeline_tools

        mock_get_db.return_value = MagicMock()
        mock_get_run.return_value = {
            "status": "running",
            "doc_id": "d1",
            "model": "gpt-4",
            "started_at": time.time() - 5.0,
            "stats": {},
        }

        tools = _capture_tools(register_pipeline_tools)
        result = tools["get_extraction_status"]("r1")
        assert result["status"] == "running"
        assert result["elapsed_seconds"] is not None
        assert result["elapsed_seconds"] >= 4.0

    @patch("app.db.client.get_db")
    @patch("app.services.extraction.get_run", side_effect=Exception("not found"))
    def test_error(self, mock_get_run, mock_get_db):
        from app.mcp.tools.pipeline import register_pipeline_tools

        mock_get_db.return_value = MagicMock()
        tools = _capture_tools(register_pipeline_tools)
        result = tools["get_extraction_status"]("bad")
        assert "error" in result


class TestGetMergeCandidates:
    @patch("app.services.er.get_candidates")
    def test_returns_candidates(self, mock_get_candidates):
        from app.mcp.tools.pipeline import register_pipeline_tools

        mock_get_candidates.return_value = [
            {"key1": "c1", "key2": "c2", "score": 0.9},
        ]

        tools = _capture_tools(register_pipeline_tools)
        result = tools["get_merge_candidates"]("o1")
        assert len(result) == 1
        assert result[0]["score"] == 0.9

    @patch("app.services.er.get_candidates", side_effect=Exception("no er"))
    def test_error(self, mock_get_candidates):
        from app.mcp.tools.pipeline import register_pipeline_tools

        tools = _capture_tools(register_pipeline_tools)
        result = tools["get_merge_candidates"]("o1")
        assert "error" in result[0]


# ===========================================================================
# tools/temporal.py
# ===========================================================================


class TestGetOntologySnapshot:
    @patch("app.services.temporal.get_snapshot")
    def test_returns_snapshot(self, mock_get_snapshot):
        from app.mcp.tools.temporal import register_temporal_tools

        mock_get_snapshot.return_value = {
            "classes": [
                {"_key": "c1", "label": "Animal", "uri": "u:c1", "version": 1},
                {"_key": "c2", "label": "Plant", "uri": "u:c2", "version": 1},
            ],
            "properties": [{"_key": "p1"}],
            "edges": [{"_key": "e1"}, {"_key": "e2"}],
        }

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_ontology_snapshot"]("o1", timestamp=500.0)
        assert result["class_count"] == 2
        assert result["property_count"] == 1
        assert result["edge_count"] == 2
        assert result["timestamp"] == 500.0
        assert len(result["sample_classes"]) == 2

    @patch("app.services.temporal.get_snapshot")
    def test_default_timestamp(self, mock_get_snapshot):
        from app.mcp.tools.temporal import register_temporal_tools

        mock_get_snapshot.return_value = {"classes": [], "properties": [], "edges": []}

        tools = _capture_tools(register_temporal_tools)
        before = time.time()
        result = tools["get_ontology_snapshot"]("o1")
        after = time.time()
        assert before <= result["timestamp"] <= after

    @patch("app.services.temporal.get_snapshot", side_effect=Exception("fail"))
    def test_error(self, mock_get_snapshot):
        from app.mcp.tools.temporal import register_temporal_tools

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_ontology_snapshot"]("o1")
        assert "error" in result


class TestGetClassHistory:
    @patch("app.services.temporal.get_entity_history")
    def test_returns_versions(self, mock_history):
        from app.mcp.tools.temporal import register_temporal_tools

        mock_history.return_value = [
            {
                "_key": "c1_v2",
                "label": "Animal",
                "uri": "u:animal",
                "version": 2,
                "created": 2.0,
                "expired": NEVER_EXPIRES,
                "change_type": "update",
                "change_summary": "desc changed",
                "created_by": "curator",
            },
            {
                "_key": "c1_v1",
                "label": "Animal",
                "uri": "u:animal",
                "version": 1,
                "created": 1.0,
                "expired": 2.0,
                "change_type": "create",
                "change_summary": None,
                "created_by": "extractor",
            },
        ]

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_class_history"]("c1")
        assert len(result) == 2
        assert result[0]["is_current"] is True
        assert result[1]["is_current"] is False

    @patch("app.services.temporal.get_entity_history", side_effect=Exception("no"))
    def test_error(self, mock_history):
        from app.mcp.tools.temporal import register_temporal_tools

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_class_history"]("c1")
        assert "error" in result[0]


class TestGetOntologyDiff:
    @patch("app.services.temporal.get_diff")
    def test_returns_diff(self, mock_diff):
        from app.mcp.tools.temporal import register_temporal_tools

        mock_diff.return_value = {
            "added": [{"_key": "c3", "label": "Fish", "uri": "u:fish"}],
            "removed": [{"_key": "c2", "label": "Plant", "uri": "u:plant"}],
            "changed": [
                {
                    "collection": "ontology_classes",
                    "before": {"_key": "c1", "version": 1},
                    "after": {"_key": "c1", "label": "Animal", "version": 2},
                }
            ],
        }

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_ontology_diff"]("o1", t1=1.0, t2=2.0)
        assert result["added_count"] == 1
        assert result["removed_count"] == 1
        assert result["changed_count"] == 1
        assert result["t1"] == 1.0
        assert result["t2"] == 2.0
        assert result["added"][0]["label"] == "Fish"
        assert result["changed"][0]["before_version"] == 1
        assert result["changed"][0]["after_version"] == 2

    @patch("app.services.temporal.get_diff", side_effect=Exception("fail"))
    def test_error(self, mock_diff):
        from app.mcp.tools.temporal import register_temporal_tools

        tools = _capture_tools(register_temporal_tools)
        result = tools["get_ontology_diff"]("o1", t1=1.0, t2=2.0)
        assert "error" in result


# ===========================================================================
# tools/er.py
# ===========================================================================


class TestRunEntityResolution:
    @patch("app.services.er.run_er_pipeline")
    @patch("app.services.er.ERPipelineConfig")
    def test_runs_pipeline(self, mock_config_cls, mock_run):
        from app.mcp.tools.er import register_er_tools

        mock_result = MagicMock()
        mock_result.run_id = "er-1"
        mock_result.status.value = "completed"
        mock_result.candidate_count = 3
        mock_result.cluster_count = 1
        mock_result.duration_seconds = 5.5
        mock_result.error = None
        mock_run.return_value = mock_result

        tools = _capture_tools(register_er_tools)
        result = tools["run_entity_resolution"]("o1")
        assert result["run_id"] == "er-1"
        assert result["status"] == "completed"
        assert result["candidate_count"] == 3

    @patch("app.services.er.run_er_pipeline")
    @patch("app.services.er.ERPipelineConfig")
    def test_with_config(self, mock_config_cls, mock_run):
        from app.mcp.tools.er import register_er_tools

        mock_config_cls.from_dict.return_value = MagicMock()
        mock_result = MagicMock()
        mock_result.run_id = "er-2"
        mock_result.status.value = "completed"
        mock_result.candidate_count = 0
        mock_result.cluster_count = 0
        mock_result.duration_seconds = 1.0
        mock_result.error = None
        mock_run.return_value = mock_result

        tools = _capture_tools(register_er_tools)
        result = tools["run_entity_resolution"]("o1", config={"threshold": 0.8})
        assert result["run_id"] == "er-2"
        mock_config_cls.from_dict.assert_called_once_with({"threshold": 0.8})

    def test_error(self):
        from app.mcp.tools.er import register_er_tools

        tools = _capture_tools(register_er_tools)
        with (
            patch("app.services.er.run_er_pipeline", side_effect=Exception("boom")),
            patch("app.services.er.ERPipelineConfig"),
        ):
            result = tools["run_entity_resolution"]("o1")
            assert "error" in result


class TestExplainEntityMatch:
    @patch("app.services.er.explain_match")
    def test_returns_explanation(self, mock_explain):
        from app.mcp.tools.er import register_er_tools

        mock_explain.return_value = {
            "key1": "c1",
            "key2": "c2",
            "label_similarity": 0.95,
            "combined_score": 0.88,
        }

        tools = _capture_tools(register_er_tools)
        result = tools["explain_entity_match"]("c1", "c2")
        assert result["combined_score"] == 0.88

    @patch("app.services.er.explain_match", side_effect=Exception("fail"))
    def test_error(self, mock_explain):
        from app.mcp.tools.er import register_er_tools

        tools = _capture_tools(register_er_tools)
        result = tools["explain_entity_match"]("c1", "c2")
        assert "error" in result


class TestGetEntityClusters:
    @patch("app.services.er.get_clusters")
    def test_returns_clusters(self, mock_clusters):
        from app.mcp.tools.er import register_er_tools

        mock_clusters.return_value = [
            {"cluster_id": "cl1", "members": ["c1", "c2"]},
        ]

        tools = _capture_tools(register_er_tools)
        result = tools["get_entity_clusters"]("o1")
        assert len(result) == 1
        assert result[0]["cluster_id"] == "cl1"

    @patch("app.services.er.get_clusters", side_effect=Exception("no"))
    def test_error(self, mock_clusters):
        from app.mcp.tools.er import register_er_tools

        tools = _capture_tools(register_er_tools)
        result = tools["get_entity_clusters"]("o1")
        assert "error" in result[0]


# ===========================================================================
# tools/ontology.py private helpers
# ===========================================================================


class TestComputeHierarchyDepth:
    @patch("app.mcp.tools.ontology.run_aql")
    def test_returns_max_depth(self, mock_run_aql):
        from app.mcp.tools.ontology import _compute_hierarchy_depth

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = iter([2, 3, 1])

        result = _compute_hierarchy_depth(db, "o1")
        assert result == 3

    def test_no_collections(self):
        from app.mcp.tools.ontology import _compute_hierarchy_depth

        db = MagicMock()
        db.has_collection.return_value = False

        assert _compute_hierarchy_depth(db, "o1") == 0

    @patch("app.mcp.tools.ontology.run_aql", side_effect=Exception("fail"))
    def test_error_returns_zero(self, mock_run_aql):
        from app.mcp.tools.ontology import _compute_hierarchy_depth

        db = MagicMock()
        db.has_collection.return_value = True

        assert _compute_hierarchy_depth(db, "o1") == 0

    @patch("app.mcp.tools.ontology.run_aql")
    def test_empty_result(self, mock_run_aql):
        from app.mcp.tools.ontology import _compute_hierarchy_depth

        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = iter([])

        assert _compute_hierarchy_depth(db, "o1") == 0


class TestHasSearchView:
    def test_view_exists(self):
        from app.mcp.tools.ontology import _has_search_view

        db = MagicMock()
        db.views.return_value = [{"name": "ontology_classes_search"}]
        assert _has_search_view(db, "ontology_classes_search") is True

    def test_view_missing(self):
        from app.mcp.tools.ontology import _has_search_view

        db = MagicMock()
        db.views.return_value = []
        assert _has_search_view(db, "ontology_classes_search") is False

    def test_error_returns_false(self):
        from app.mcp.tools.ontology import _has_search_view

        db = MagicMock()
        db.views.side_effect = Exception("fail")
        assert _has_search_view(db, "ontology_classes_search") is False


# ===========================================================================
# tools/pipeline.py helper
# ===========================================================================


class TestGetOrCreateEventLoop:
    def test_creates_new_loop_when_none_running(self):
        from app.mcp.tools.pipeline import _get_or_create_event_loop

        with patch("app.mcp.tools.pipeline.asyncio") as mock_asyncio:
            mock_asyncio.get_running_loop.side_effect = RuntimeError
            new_loop = MagicMock()
            mock_asyncio.new_event_loop.return_value = new_loop

            result = _get_or_create_event_loop()
            assert result is new_loop
            mock_asyncio.set_event_loop.assert_called_once_with(new_loop)

    def test_returns_running_loop(self):
        from app.mcp.tools.pipeline import _get_or_create_event_loop

        with patch("app.mcp.tools.pipeline.asyncio") as mock_asyncio:
            existing_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = existing_loop

            result = _get_or_create_event_loop()
            assert result is existing_loop
