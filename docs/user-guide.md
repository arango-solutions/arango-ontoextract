# AOE User Guide

A comprehensive walkthrough for using the Arango-OntoExtract (AOE) platform — from setup to production ontology management.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Upload a Document](#2-upload-a-document)
3. [Run Extraction](#3-run-extraction)
4. [Curate the Ontology](#4-curate-the-ontology)
5. [Promote to Production](#5-promote-to-production)
6. [Use the VCR Timeline](#6-use-the-vcr-timeline)
7. [Entity Resolution](#7-entity-resolution)
8. [Import and Export](#8-import-and-export)
9. [MCP Integration](#9-mcp-integration)
10. [Ontology Library](#10-ontology-library)
11. [API Reference](#11-api-reference)

---

## 1. Getting Started

### Prerequisites

| Requirement | Minimum Version |
|-------------|-----------------|
| Python | 3.11+ |
| Node.js | 18+ |
| Docker & Docker Compose | Latest stable |
| Anthropic API key | — |
| OpenAI API key | For embeddings |

### Installation

```bash
# Clone the repository
git clone <repo-url> && cd ontology_generator

# Copy environment config and add your API keys
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and OPENAI_API_KEY

# One-command setup (Python venv, pip install, npm install)
make setup

# Start ArangoDB and Redis
make infra

# Start the backend (port 8000)
make backend

# In a second terminal, start the frontend (port 3000)
make frontend
```

### First Run Verification

After startup, verify each service is accessible:

| Service | URL | Expected |
|---------|-----|----------|
| Backend API | http://localhost:8000/health | `{"status": "ok"}` |
| API Docs (Swagger) | http://localhost:8000/docs | Interactive OpenAPI UI |
| Frontend | http://localhost:3000 | Landing page with system status |
| ArangoDB UI | http://localhost:8529 | ArangoDB web interface |

Run the database migration to create the schema:

```bash
make migrate
```

The migration runner creates all required collections, indexes, named graphs, and ArangoSearch views.

---

## 2. Upload a Document

AOE ingests PDF, DOCX, and Markdown files. Each upload triggers an async processing pipeline that parses, chunks, and embeds the content.

### Step-by-Step

1. **Via API** — upload a file with `POST /api/v1/documents/upload`:

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@my_document.pdf" \
  -F "org_id=my_org"
```

2. **Via Frontend** — navigate to the document upload page and drag-and-drop your file.

### Expected Response

```json
{
  "doc_id": "abc123",
  "filename": "my_document.pdf",
  "status": "uploading"
}
```

### Processing Pipeline

The document progresses through these statuses:

```
uploading → parsing → chunking → embedding → ready
```

If any step fails, the status becomes `error` with a descriptive `error_message`.

### Check Document Status

```bash
curl http://localhost:8000/api/v1/documents/abc123
```

Response includes `status`, `chunk_count`, and `error_message` (if applicable).

### View Chunks

```bash
curl "http://localhost:8000/api/v1/documents/abc123/chunks?limit=10"
```

Returns paginated chunks with text content, token counts, and chunk indexes.

### Duplicate Detection

AOE computes a SHA-256 hash of each uploaded file. Re-uploading an identical file returns `409 Conflict` with a reference to the existing document.

---

## 3. Run Extraction

Once a document is in `ready` status, trigger LLM-driven ontology extraction.

### Trigger Extraction

```bash
curl -X POST http://localhost:8000/api/v1/extraction/run \
  -H "Content-Type: application/json" \
  -d '{"document_id": "abc123"}'
```

Response:

```json
{
  "run_id": "run_456",
  "doc_id": "abc123",
  "status": "running"
}
```

### Monitor the Pipeline

**Via API** — poll the run status:

```bash
curl http://localhost:8000/api/v1/extraction/runs/run_456
```

**Via WebSocket** — connect for real-time updates:

```
ws://localhost:8000/ws/extraction/run_456
```

Events emitted: `step_started`, `step_completed`, `step_failed`, `pipeline_paused`, `completed`.

**Via Frontend** — the Pipeline Monitor Dashboard at `/pipeline` shows:
- Real-time Agent DAG with status icons per pipeline step
- Token usage and estimated cost
- Error log with retry buttons

### Pipeline Steps

The LangGraph extraction pipeline runs these agents in sequence:

1. **Strategy Selector** — analyzes document type and selects model/prompt configuration
2. **Extraction Agent** — N-pass LLM extraction with self-correction and RAG context
3. **Consistency Checker** — cross-pass agreement filtering with confidence scoring
4. **Entity Resolution Agent** — detects duplicates against existing ontologies
5. **Pre-Curation Filter** — removes noise, annotates confidence tiers, adds provenance

### View Results

```bash
# Extracted entities
curl http://localhost:8000/api/v1/extraction/runs/run_456/results

# Per-agent step details (tokens, duration, errors)
curl http://localhost:8000/api/v1/extraction/runs/run_456/steps

# LLM cost breakdown
curl http://localhost:8000/api/v1/extraction/runs/run_456/cost
```

### Retry a Failed Run

```bash
curl -X POST http://localhost:8000/api/v1/extraction/runs/run_456/retry
```

---

## 4. Curate the Ontology

After extraction, a staging graph contains draft ontology entities. Domain experts review and refine them through the Visual Curation Dashboard.

### Open the Curation Dashboard

Navigate to `/curation/{runId}` in the frontend. The dashboard shows:

- **Graph Canvas** — interactive visualization of extracted classes and relationships (React Flow)
- **Node Detail Panel** — click any class to see URI, label, description, confidence, provenance
- **Action Buttons** — approve, reject, edit, or merge each entity

### Individual Decisions

Record a decision via API:

```bash
curl -X POST http://localhost:8000/api/v1/curation/decide \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run_456",
    "entity_key": "cls_001",
    "entity_type": "class",
    "action": "approve",
    "curator_id": "user_jane",
    "notes": "Confirmed by SME"
  }'
```

Available actions: `approve`, `reject`, `edit`, `merge`.

### Batch Operations

Select multiple entities in the graph canvas and apply bulk actions:

```bash
curl -X POST http://localhost:8000/api/v1/curation/batch \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run_456",
    "decisions": [
      {"entity_key": "cls_001", "entity_type": "class", "action": "approve", "curator_id": "user_jane"},
      {"entity_key": "cls_002", "entity_type": "class", "action": "approve", "curator_id": "user_jane"},
      {"entity_key": "cls_003", "entity_type": "class", "action": "reject", "curator_id": "user_jane"}
    ]
  }'
```

### Edit an Entity

When editing, pass `edited_data` with the fields to update:

```bash
curl -X POST http://localhost:8000/api/v1/curation/decide \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run_456",
    "entity_key": "cls_002",
    "entity_type": "class",
    "action": "edit",
    "curator_id": "user_jane",
    "edited_data": {"label": "Corrected Label", "description": "Updated description"}
  }'
```

### Merge Entities

When two entities represent the same concept:

```bash
curl -X POST http://localhost:8000/api/v1/curation/merge \
  -H "Content-Type: application/json" \
  -d '{
    "source_keys": ["cls_duplicate_1"],
    "target_key": "cls_canonical",
    "merged_data": {"label": "Canonical Entity"},
    "curator_id": "user_jane"
  }'
```

### Review Decision History

```bash
curl "http://localhost:8000/api/v1/curation/decisions?run_id=run_456&limit=50"
```

Every decision is recorded as an audit trail entry with timestamps and curator IDs.

---

## 5. Promote to Production

After curation, approved entities move from the staging graph to the production ontology.

### Promotion Workflow

1. **Review Summary** — the Promote Panel in the curation UI shows what will be promoted (counts of approved classes, properties, edges)
2. **Confirm** — click "Promote" or use the API
3. **Verify** — check the production graph

### Promote via API

```bash
curl -X POST http://localhost:8000/api/v1/curation/promote/run_456 \
  -H "Content-Type: application/json" \
  -d '{"ontology_id": "my_ontology"}'
```

Response includes a promotion report:

```json
{
  "run_id": "run_456",
  "status": "completed",
  "promoted_classes": 12,
  "promoted_properties": 8,
  "promoted_edges": 15,
  "skipped": 3,
  "errors": []
}
```

### Check Promotion Status

```bash
curl http://localhost:8000/api/v1/curation/promote/run_456/status
```

### What Happens During Promotion

- Approved entities in the staging graph receive new temporal versions in the production graph
- Each promoted entity gets `created` = now, `expired` = NEVER_EXPIRES
- If a production entity with the same URI exists, it is expired and a new version is inserted
- All edges are re-created pointing to the new production versions
- The staging graph remains intact for audit purposes

---

## 6. Use the VCR Timeline

The VCR Timeline enables time-travel through your ontology's history. Every edit, promotion, and merge creates a temporal version.

### Timeline Controls

In the frontend at `/curation/{runId}`, the VCR Timeline slider appears below the graph canvas:

- **Play/Pause** — animate through ontology history
- **Rewind/Fast-forward** — step between discrete change events
- **Drag** — jump to any timestamp
- **Event markers** — tick marks at each version creation event

### Point-in-Time Snapshot

```bash
curl "http://localhost:8000/api/v1/ontology/my_ontology/snapshot?at=1711500000.0"
```

Returns the full graph state (classes, properties, edges) as they were at that timestamp.

### Version History for a Class

```bash
curl http://localhost:8000/api/v1/ontology/class/cls_001/history
```

Returns all versions sorted by `created` DESC, showing what changed in each version.

### Compare Two Points in Time

```bash
curl "http://localhost:8000/api/v1/ontology/my_ontology/diff?t1=1711500000.0&t2=1711600000.0"
```

Returns added, removed, and changed entities between the two timestamps.

### Timeline Events

```bash
curl http://localhost:8000/api/v1/ontology/my_ontology/timeline
```

Returns discrete change events for the VCR slider tick marks.

### Revert to a Previous Version

```bash
curl -X POST "http://localhost:8000/api/v1/ontology/class/cls_001/revert?to_version=1711400000.0"
```

Creates a new current version that restores the historical state. The revert itself becomes a new entry in the version history.

---

## 7. Entity Resolution

Entity Resolution (ER) detects and merges duplicate or overlapping concepts across ontologies.

### Run the ER Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/er/run \
  -H "Content-Type: application/json" \
  -d '{"ontology_id": "my_ontology"}'
```

The pipeline runs blocking (ArangoSearch BM25), scoring (field-by-field similarity + topological similarity), and clustering (WCC) stages.

### Review Merge Candidates

```bash
curl "http://localhost:8000/api/v1/er/runs/{run_id}/candidates?min_score=0.7&limit=20"
```

Each candidate pair includes a similarity score and field-level breakdown.

### Explain a Match

```bash
curl -X POST http://localhost:8000/api/v1/er/explain \
  -H "Content-Type: application/json" \
  -d '{"key1": "cls_001", "key2": "cls_002"}'
```

Returns detailed field-by-field similarity breakdown (label, description, URI, topological neighbors).

### Execute a Merge

```bash
curl -X POST http://localhost:8000/api/v1/er/merge \
  -H "Content-Type: application/json" \
  -d '{"source_key": "cls_duplicate", "target_key": "cls_canonical", "strategy": "most_complete"}'
```

### Cross-Tier Resolution

Find duplicates between a local ontology and a domain ontology:

```bash
curl -X POST http://localhost:8000/api/v1/er/cross-tier \
  -H "Content-Type: application/json" \
  -d '{"local_ontology_id": "org_acme_local", "domain_ontology_id": "financial_services", "min_score": 0.6}'
```

### View Entity Clusters

```bash
curl http://localhost:8000/api/v1/er/runs/{run_id}/clusters
```

### Configure the Pipeline

```bash
# View current config
curl http://localhost:8000/api/v1/er/config

# Update config
curl -X PUT http://localhost:8000/api/v1/er/config \
  -H "Content-Type: application/json" \
  -d '{"similarity_threshold": 0.8, "topological_weight": 0.3}'
```

---

## 8. Import and Export

### Import an Existing Ontology

Upload an OWL/TTL file to add it to the ontology library:

```bash
curl -X POST http://localhost:8000/api/v1/ontology/import \
  -F "file=@my_ontology.ttl"
```

The import process:
1. Parses the OWL/TTL file via rdflib
2. Transforms to ArangoDB via ArangoRDF PGT
3. Creates a registry entry in `ontology_registry`
4. Tags all imported entities with `ontology_id`
5. Creates a per-ontology named graph

### Export an Ontology

```bash
# Export as Turtle (default)
curl "http://localhost:8000/api/v1/ontology/export?format=ttl"

# Export as JSON-LD
curl "http://localhost:8000/api/v1/ontology/export?format=json-ld"
```

Supported formats: `ttl` (Turtle), `json-ld`, `csv`.

### Schema Extraction

Extract an ontology from an existing ArangoDB database schema:

```bash
curl -X POST http://localhost:8000/api/v1/ontology/schema/extract \
  -H "Content-Type: application/json" \
  -d '{"connection": {"host": "http://remote-arango:8529", "db": "target_db"}}'
```

Uses `arango-schema-mapper` to reverse-engineer the database schema into OWL, then imports it into AOE.

---

## 9. MCP Integration

AOE exposes all ontology operations to AI agents via the Model Context Protocol (MCP). Two transport modes are supported:

### Connect from Cursor

Add to your `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "aoe": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/ontology_generator/backend"
    }
  }
}
```

### Connect from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aoe": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/ontology_generator/backend"
    }
  }
}
```

### Runtime SSE (Custom Clients)

```bash
cd backend
python -m app.mcp.server --transport sse --port 8001
```

### Available MCP Tools

| Category | Tool | Description |
|----------|------|-------------|
| Introspection | `query_collections` | List all ArangoDB collections |
| Introspection | `run_aql` | Execute read-only AQL queries |
| Introspection | `sample_collection` | Sample documents from a collection |
| Ontology | `query_domain_ontology` | Ontology summary with stats |
| Ontology | `get_class_hierarchy` | SubClassOf tree as nested dict |
| Ontology | `get_class_properties` | Properties for a class |
| Ontology | `search_similar_classes` | BM25 search on labels/descriptions |
| Pipeline | `trigger_extraction` | Start an extraction run |
| Pipeline | `get_extraction_status` | Run status and stats |
| Pipeline | `get_merge_candidates` | ER merge candidates |
| Temporal | `get_ontology_snapshot` | Point-in-time graph state |
| Temporal | `get_class_history` | All versions of a class |
| Temporal | `get_ontology_diff` | Changes between timestamps |
| Export | `get_provenance` | Trace entity to source |
| Export | `export_ontology` | Export as OWL Turtle or JSON-LD |
| ER | `run_entity_resolution` | Trigger ER pipeline |
| ER | `explain_entity_match` | Field-by-field similarity |
| ER | `get_entity_clusters` | WCC entity clusters |

For the full MCP tool catalog with parameters and examples, see [docs/mcp-server.md](mcp-server.md).

---

## 10. Ontology Library

The Ontology Library is a managed registry of all ontologies in the system — both imported and extracted.

### Browse the Library

**Via Frontend** — navigate to `/library` to see all registered ontologies with status badges and stats.

**Via API:**

```bash
curl "http://localhost:8000/api/v1/ontology/library?limit=25"
```

### View Ontology Details

```bash
curl http://localhost:8000/api/v1/ontology/library/financial_services
```

Returns the registry entry plus stats (class count, property count).

### Ontology Lifecycle

```
Import/Extract → Draft → Review → Active → (Deprecated)
```

### Organization Ontology Selection

Organizations select which domain ontologies serve as base context for Tier 2 extraction:

```bash
# Set base ontologies for an organization
curl -X PUT http://localhost:8000/api/v1/ontology/orgs/org_acme/ontologies \
  -H "Content-Type: application/json" \
  -d '{"ontology_ids": ["financial_services", "compliance"]}'

# View selected ontologies
curl http://localhost:8000/api/v1/ontology/orgs/org_acme/ontologies
```

### Two-Tier Model

- **Tier 1 — Domain Ontologies**: standardized industry schemas shared across organizations
- **Tier 2 — Localized Extensions**: organization-specific sub-graphs linked to Tier 1 via `rdfs:subClassOf`

When Tier 2 extraction runs, the selected domain ontologies are injected as context so the LLM can classify entities as EXISTING, EXTENSION, or NEW.

---

## 11. API Reference

Full interactive API documentation is available at http://localhost:8000/docs when the backend is running (Swagger UI auto-generated from FastAPI).

For a static endpoint catalog, see [docs/api-reference.md](api-reference.md).

For MCP tool documentation, see [docs/mcp-server.md](mcp-server.md).
