# AOE MCP Server

The Arango-OntoExtract (AOE) MCP server exposes ontology operations to AI agents via the Model Context Protocol. It supports both development-time use (Cursor/Claude Desktop via stdio) and runtime integration (external agents via SSE).

## Architecture

```
┌──────────────────┐     stdio      ┌──────────────────┐
│  Cursor / Claude  │───────────────▶│                  │
│  Desktop          │                │                  │
└──────────────────┘                │   AOE MCP Server  │──────▶ ArangoDB
                                    │                  │
┌──────────────────┐     SSE        │  (FastMCP)       │
│  Custom MCP      │───────────────▶│                  │
│  Client / Agent   │  :8001        │                  │
└──────────────────┘                └──────────────────┘
```

The MCP server runs as a standalone process alongside the FastAPI backend, sharing the same ArangoDB instance and configuration.

## Quick Start

### Development (stdio — Cursor)

Add to your `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "aoe": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/arango-ontoextract/backend"
    }
  }
}
```

### Development (stdio — Claude Desktop)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aoe": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/arango-ontoextract/backend"
    }
  }
}
```

### Runtime (SSE — Custom Clients)

Start the server:

```bash
cd backend
python -m app.mcp.server --transport sse --port 8001
```

Connect from a Python client:

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8001/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(
            "query_domain_ontology",
            arguments={"ontology_id": "my_ontology"},
        )
```

## CLI Options

```
python -m app.mcp.server [OPTIONS]

Options:
  --transport {stdio,sse}   Transport protocol (default: stdio)
  --host HOST               SSE bind host (default: 0.0.0.0)
  --port PORT               SSE port (default: 8001)
```

## Tool Catalog

### Introspection Tools (Phase 1)

| Tool | Description | Parameters |
|------|-------------|------------|
| `query_collections` | List all ArangoDB collections with counts and types | — |
| `run_aql` | Execute a read-only AQL query (limit 100 results) | `query: str`, `bind_vars: dict \| None` |
| `sample_collection` | Return N sample documents from a collection | `collection_name: str`, `limit: int = 5` |

### Ontology Query Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `query_domain_ontology` | Summary of an ontology: class/property counts, hierarchy depth, recent changes | `ontology_id: str` |
| `get_class_hierarchy` | SubClassOf tree as nested dict; optionally rooted at a specific class | `ontology_id: str`, `root_class_key: str \| None` |
| `get_class_properties` | All properties for a class (via has_property edges, current versions) | `class_key: str` |
| `search_similar_classes` | BM25 search on class labels/descriptions (fallback to LIKE if no ArangoSearch view) | `query: str`, `ontology_id: str \| None`, `limit: int = 10` |

**Example — `query_domain_ontology`:**

```json
{
  "ontology_id": "financial_services",
  "class_count": 142,
  "property_count": 387,
  "hierarchy_depth": 6,
  "recent_changes": [
    {"key": "cls_abc", "label": "Transaction", "change_type": "edit", "version": 3}
  ],
  "registry": {"name": "Financial Services Ontology", "status": "active", "tier": "domain"}
}
```

### Pipeline Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `trigger_extraction` | Start an extraction run; returns run_id and status | `document_id: str`, `ontology_id: str \| None` |
| `get_extraction_status` | Run status, elapsed time, token usage, classes extracted | `run_id: str` |
| `get_merge_candidates` | ER merge candidates above a score threshold | `ontology_id: str`, `min_score: float = 0.5` |

**Example — `get_extraction_status`:**

```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "document_id": "doc_456",
  "model": "claude-sonnet-4-20250514",
  "elapsed_seconds": 42.5,
  "token_usage": {"total_tokens": 12450},
  "classes_extracted": 34,
  "errors": []
}
```

### Temporal Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_ontology_snapshot` | Full graph state at a timestamp (or current); counts + sample classes | `ontology_id: str`, `timestamp: float \| None` |
| `get_class_history` | All versions of a class sorted by created DESC | `class_key: str` |
| `get_ontology_diff` | Added/removed/changed entities between two timestamps | `ontology_id: str`, `t1: float`, `t2: float` |

**Example — `get_ontology_diff`:**

```json
{
  "ontology_id": "healthcare",
  "t1": 1711500000.0,
  "t2": 1711600000.0,
  "added_count": 3,
  "removed_count": 1,
  "changed_count": 2,
  "added": [{"key": "cls_new", "label": "Diagnosis", "uri": "http://..."}],
  "removed": [{"key": "cls_old", "label": "Deprecated", "uri": "http://..."}],
  "changed": [{"key": "cls_mod", "label": "Patient", "before_version": 2, "after_version": 3}]
}
```

### Export & Provenance Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_provenance` | Trace entity back to extraction run, source document, chunks, curation decisions | `entity_key: str` |
| `export_ontology` | Export ontology as OWL Turtle or JSON-LD string | `ontology_id: str`, `format: str = "turtle"` |

### Entity Resolution Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `run_entity_resolution` | Trigger full ER pipeline (blocking → scoring → clustering) | `ontology_id: str`, `config: dict \| None` |
| `explain_entity_match` | Field-by-field similarity breakdown for two entities | `key1: str`, `key2: str` |
| `get_entity_clusters` | WCC entity clusters with member details | `ontology_id: str` |

### Belief Revision Tools

Mirror the [Belief Revision REST surface](./api-reference.md#belief-revision)
so MCP-connected agents can curate and consolidate ontologies. Background
consolidation defaults to `dry_run=true` here (the REST endpoint defaults to
`false`) because external agents are more likely to call it speculatively.
See [ADR-008](./adr/008-belief-revision-substrate.md) for the IBR design.

| Tool | Description | Parameters |
|------|-------------|------------|
| `list_revisions_inbox` | Pending `FLAG_FOR_CURATION` rows for one ontology | `ontology_id: str`, `limit: int = 50` |
| `list_recent_revisions` | Filterable list of recent `revision_meta` rows | `ontology_id: str \| None`, `status: str \| None`, `agent_type: str \| None`, `limit: int = 50` |
| `get_revision` | One revision by `_key`, full payload | `key: str` |
| `decide_revision` | Apply curator decision (`accept` / `reject` / `modify`) | `key: str`, `decision: str`, `decided_by: str = "mcp_agent"`, `note: str \| None`, `override_action: str \| None`, `new_vertex_data: dict \| None` |
| `run_consolidation` | Rules + decay + stale-belief scan; defaults to dry-run | `ontology_id: str`, `dry_run: bool = True`, `job_key: str \| None`, `stale_age_days: int \| None`, `stale_min_confidence: float \| None` |
| `get_circuit_breaker_state` | Current LLM-revision rate-limiter snapshot | (none) |

**Safety notes for agents:**

- `decide_revision` is **idempotent** — calling it twice on the same key
  returns `already_decided: true` and does not mutate the graph again.
- `run_consolidation` with `dry_run=True` produces a `PlannedAction` list
  without writing to `revision_meta` or the graph; always preview first.
- `get_circuit_breaker_state` should be polled before submitting a batch of
  decisions if you suspect the upstream LLM agent is being rate-limited.

## Resource Catalog

MCP resources provide read-only data summaries.

| URI | Description |
|-----|-------------|
| `aoe://ontology/domain/summary` | Summary of all domain ontologies: count, names, class counts |
| `aoe://extraction/runs/recent` | Last 10 extraction runs with status |
| `aoe://system/health` | System health: ArangoDB connection status, collection counts |
| `aoe://ontology/{ontology_id}/stats` | Detailed stats for a specific ontology: classes, properties, edges, versions |

**Example — `aoe://system/health`:**

```json
{
  "status": "healthy",
  "arango_connected": true,
  "collection_count": 15,
  "collections": [
    {"name": "ontology_classes", "count": 1247, "type": "document"},
    {"name": "subclass_of", "count": 892, "type": "edge"}
  ]
}
```

## Authentication

### Development Mode (stdio)

No authentication required. All tools operate in the default organization context with full permissions.

### Runtime Mode (SSE)

API key authentication via the `api_keys` collection in ArangoDB.

**API Key Setup:**

1. Create an API key record in the `api_keys` collection:

```json
{
  "_key": "key_001",
  "key_hash": "<sha256 hash of the API key>",
  "org_id": "org_acme",
  "status": "active",
  "permissions": ["ontology:read", "extraction:trigger", "er:read"],
  "expires_at": null
}
```

2. Pass the API key in MCP request metadata.

**Organization Isolation:**

- Each API key is scoped to an `org_id`
- Tool results are filtered to only show data belonging to the authenticated org
- The default org (`default`) can see all data
- Shared/global data (no `org_id` field) is visible to all orgs

**Permissions:**

| Permission | Grants |
|-----------|--------|
| `ontology:read` | Query ontologies, class hierarchy, properties, search |
| `ontology:write` | Modify ontologies (future) |
| `extraction:trigger` | Trigger extraction runs |
| `extraction:read` | Check extraction status, get results |
| `er:read` | View merge candidates, clusters |
| `er:trigger` | Run entity resolution pipeline |
| `export:read` | Export ontologies, trace provenance |
| `temporal:read` | Snapshots, history, diffs |
| `system:health` | System health resource |

## Configuration

### Environment Variables

The MCP server uses the same configuration as the FastAPI backend (`app/config.py`). Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARANGO_HOST` | `http://localhost:8530` | ArangoDB connection URL |
| `ARANGO_DB` | `OntoExtract` | Database name |
| `ARANGO_USER` | `root` | Database user |
| `ARANGO_PASSWORD` | `changeme` | Database password |

### Transport Options

| Transport | Use Case | Auth | Port |
|-----------|----------|------|------|
| `stdio` | Cursor, Claude Desktop | None (dev mode) | N/A |
| `sse` | Custom clients, remote agents | API key | 8001 (default) |

## Docker

The MCP server can be run as a standalone container:

```bash
docker run -e ARANGO_HOST=http://arango:8530 \
  -p 8001:8001 \
  aoe-mcp-server \
  python -m app.mcp.server --transport sse --port 8001
```

## Troubleshooting

**Tools return empty results:**
- Verify ArangoDB is running and accessible at the configured host
- Check that the target ontology exists in `ontology_registry`
- For BM25 search, ensure the `ontology_classes_search` ArangoSearch view is created

**SSE connection refused:**
- Confirm the server is running with `--transport sse`
- Check the port is not in use
- Verify firewall rules allow the configured port

**Authentication errors:**
- In stdio mode, auth is skipped — no API key needed
- For SSE, ensure the `api_keys` collection exists and the key is valid
- Check that the key hash matches (SHA-256 of the raw key)
