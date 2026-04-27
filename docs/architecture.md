# AOE Architecture Overview

This document describes the system architecture of the Arango-OntoExtract (AOE) platform.

---

## System Architecture

```
                     ┌──────────────────────────┐
                     │   External AI Agents      │
                     │   (any MCP client)        │
                     └────────────┬─────────────┘
                                  │ MCP Protocol (stdio / SSE)
                                  │
┌─────────────────────────────────┼──────────────────────────────────┐
│                          Frontend (Next.js)                        │
│                                                                    │
│  ┌──────────────┐  ┌───────────────────┐  ┌────────────────────┐  │
│  │  Document     │  │  Visual Curation  │  │  Pipeline Monitor  │  │
│  │  Upload       │  │  Dashboard        │  │  Dashboard         │  │
│  └──────────────┘  └───────────────────┘  └────────────────────┘  │
│  ┌──────────────┐  ┌───────────────────┐  ┌────────────────────┐  │
│  │  VCR Timeline │  │  Ontology Library │  │  ER Merge Panel    │  │
│  └──────────────┘  └───────────────────┘  └────────────────────┘  │
└────────────────────────────┬───────────────────────────────────────┘
                             │ REST API / WebSocket
                             │
┌────────────────────────────┴───────────────────────────────────────┐
│                      Backend (Python / FastAPI)                     │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │            LangGraph Agentic Orchestration Layer             │  │
│  │                                                              │  │
│  │  Strategy ──▶ Extraction ──▶ Consistency ──▶ ER ──▶ Filter  │  │
│  │  Selector     Agent         Checker         Agent   Agent   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌────────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Ingestion  │ │ Extraction   │ │ Entity   │ │ Curation      │  │
│  │ Service    │ │ Service      │ │ Resol.   │ │ Service       │  │
│  └────────────┘ └──────────────┘ └──────────┘ └───────────────┘  │
│  ┌────────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Temporal   │ │ ArangoRDF    │ │ Promotion│ │ OWL Serializer│  │
│  │ Service    │ │ Bridge       │ │ Service  │ │               │  │
│  └────────────┘ └──────────────┘ └──────────┘ └───────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                    MCP Server (FastMCP)                    │   │
│  │                    (dev stdio + runtime SSE)               │   │
│  └────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬───────────────────────────────────────┘
                             │ python-arango driver
                             │
┌────────────────────────────┴───────────────────────────────────────┐
│                      ArangoDB (Multi-Model)                        │
│                                                                    │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────┐ ┌────────────┐  │
│  │  Document    │ │  Graph (OWL   │ │  Vector  │ │  Arango-   │  │
│  │  Store       │ │  via PGT)     │ │  Index   │ │  Search    │  │
│  └──────────────┘ └───────────────┘ └──────────┘ └────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Named Graphs: domain_ontology, ontology_{id},               │  │
│  │               local_ontology_{org_id}, staging_{run_id}     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
          ┌──────────┐
          │  Redis   │  Rate limiting, notification pub/sub
          └──────────┘
```

---

## Component Descriptions

### FastAPI Backend

The Python backend is the central service. It handles REST API requests, runs the LLM extraction pipeline, manages temporal versioning, and serves the MCP server.

| Layer | Responsibility | Key Files |
|-------|---------------|-----------|
| API routes | HTTP endpoint handlers, input validation, response formatting | `backend/app/api/` |
| Services | Business logic, orchestration, pipeline execution | `backend/app/services/` |
| DB repositories | ArangoDB access, AQL queries, CRUD operations | `backend/app/db/` |
| Extraction pipeline | LangGraph agents, LLM calls, prompt templates | `backend/app/extraction/` |
| Models | Pydantic schemas for validation and serialization | `backend/app/models/` |
| MCP server | Model Context Protocol tool exposure | `backend/app/mcp/` |

### Next.js Frontend

React 18 + Next.js 14 application providing the user interface.

| Page | Purpose |
|------|---------|
| `/` | Landing page with system health status |
| `/workspace` | Unified workspace — asset explorer, **Sigma.js** ontology graph, VCR timeline |
| `/dashboard` | Metrics and quality (including per-ontology quality tab) |
| `/pipeline` | Pipeline Monitor — real-time extraction DAG, run list, metrics |
| `/curation/{runId}` | Visual Curation Dashboard — **React Flow** graph, node actions, VCR timeline |
| `/library` | Ontology Library browser |
| `/quality` | Redirects to `/dashboard?tab=per-ontology-quality` |
| `/ontology/{ontologyId}/edit` | Ontology structure editor (**React Flow**) |
| `/entity-resolution` | ER workflows (**React Flow** where a graph is shown) |

Key UI components:
- **SigmaCanvas** — Sigma.js graph on `/workspace` (large-scale ontology visualization)
- **GraphCanvas** — React Flow graph for curation, ontology editor, and related flows
- **VCRTimeline** — temporal slider with play/pause/rewind controls
- **AgentDAG** — React Flow rendering of the LangGraph pipeline with live status
- **MergeCandidates** — ER candidate review with accept/reject

### ArangoDB

Multi-model database serving as the single persistence layer for documents, graphs, vectors, and full-text search.

| Capability | Usage |
|------------|-------|
| Document store | Uploaded documents, chunks, extraction runs, curation decisions, notifications |
| Graph | Ontology class hierarchies, property associations, cross-tier links |
| Vector index | HNSW index on chunk embeddings for RAG retrieval and ER blocking |
| ArangoSearch | BM25 full-text search on class labels/descriptions for ER blocking and search |
| Named graphs | Per-ontology isolation, staging graphs, domain/local separation |
| MDI indexes | Multi-dimensional indexes on `[created, expired]` for temporal range queries |
| TTL indexes | Automatic garbage collection of historical ontology versions |

### Redis

Implemented uses:

1. **Rate limiting** — sliding-window API limits stored in Redis sorted sets
2. **Notification Pub/Sub** — best-effort notification events after persistence in ArangoDB

Planned uses include async task queueing, broader WebSocket fanout, and materialized
snapshot caching. The backend degrades gracefully for the implemented Redis paths:
rate limiting passes through if Redis is unavailable, and notifications are still
persisted in ArangoDB even if Pub/Sub publish fails.

### MCP Server

Standalone process (FastMCP) that exposes ontology operations to AI agents. Runs alongside the FastAPI backend, sharing the same ArangoDB instance.

| Transport | Use Case | Auth |
|-----------|----------|------|
| stdio | Cursor IDE, Claude Desktop (dev-time) | None |
| SSE | Custom MCP clients, remote agents (runtime) | API key, org-scoped |

---

## Data Flow

### Document → Extraction → Staging → Curation → Production

```
  ┌──────────┐      ┌──────────┐      ┌──────────────┐
  │ Document │─────▶│  Parse   │─────▶│  Semantic    │
  │ Upload   │      │  (PDF/   │      │  Chunking    │
  │          │      │  DOCX/MD)│      │              │
  └──────────┘      └──────────┘      └──────┬───────┘
                                              │
                                    ┌─────────▼────────┐
                                    │  Vector Embedding │
                                    │  (OpenAI)        │
                                    └─────────┬────────┘
                                              │
                                    ┌─────────▼────────┐
                                    │  Store in DB     │
                                    │  (documents +    │
                                    │   chunks)        │
                                    └─────────┬────────┘
                                              │
  ┌──────────────────────────────────────────┐│
  │      LangGraph Extraction Pipeline       ││
  │                                          ▼│
  │  Strategy ──▶ Extractor ──▶ Consistency  ││
  │  Selector     (N-pass       Checker      ││
  │               LLM)                       ││
  │                    ──▶ ER Agent ──▶ Filter││
  └─────────────────────────────┬────────────┘│
                                │              │
                      ┌─────────▼────────┐     │
                      │  Staging Graph   │     │
                      │  (staging_{run}) │     │
                      └─────────┬────────┘     │
                                │              │
                      ┌─────────▼────────┐     │
                      │  Curation        │     │
                      │  (approve/reject │     │
                      │   /edit/merge)   │     │
                      └─────────┬────────┘     │
                                │              │
                      ┌─────────▼────────┐     │
                      │  Promotion       │     │
                      │  (staging →      │     │
                      │   production)    │     │
                      └─────────┬────────┘     │
                                │              │
                      ┌─────────▼────────┐     │
                      │  Production      │     │
                      │  Ontology Graph  │     │
                      │  (temporal       │     │
                      │   versioned)     │     │
                      └──────────────────┘
```

### Temporal Versioning Flow

Every ontology mutation follows the edge-interval pattern:

1. Current vertex gets `expired = now`
2. New vertex inserted with `created = now`, `expired = NEVER_EXPIRES`
3. All edges to/from old vertex are expired
4. New edges created pointing to/from new vertex

This enables point-in-time snapshots via AQL range filters on `[created, expired]`.

---

## Technology Choices and Rationale

| Component | Technology | Why |
|-----------|-----------|-----|
| Database | ArangoDB 3.12+ | Single engine for documents, graphs, vectors, and full-text search — no need for separate Elasticsearch, Neo4j, or Pinecone |
| Ontology bridge | ArangoRDF (PGT) | Stores OWL/RDFS ontologies in ArangoDB while preserving metamodel semantics; enables graph traversals on ontology structures |
| Backend | FastAPI (Python 3.11+) | Async-native, Pydantic-first validation, auto-generated OpenAPI docs; strong LLM library ecosystem |
| LLM orchestration | LangGraph | Stateful multi-step agent graphs with checkpointing, conditional edges, and human-in-the-loop breakpoints |
| LLM providers | Claude (primary), GPT-4o (fallback) | Best-in-class structured extraction with JSON schema enforcement |
| Frontend | Next.js 14 + React 18 | Server-side rendering, file-based routing, React Server Components |
| Graph visualization | Sigma.js + React Flow | Sigma for the main `/workspace` canvas (WebGL performance at scale); React Flow for curation, pipeline DAG, ontology editor, and ER UIs that need rich node interactions |
| Entity resolution | arango-entity-resolution | ArangoDB-native ER with blocking, scoring, and WCC clustering; supports GAE backend |
| Temporal indexing | MDI-prefixed indexes | ArangoDB's multi-dimensional indexes optimized for interval range queries on `[created, expired]` |
| MCP server | FastMCP (mcp Python SDK) | Standard MCP protocol for AI agent interoperability |
| Async work | Celery + Redis (planned) | Battle-tested async task processing for document ingestion pipeline |
| Embeddings | OpenAI text-embedding-3-small | High-quality vector embeddings for RAG and ER similarity scoring |

---

## Deployment Modes

AOE supports three ArangoDB deployment targets, configured via the `TEST_DEPLOYMENT_MODE` environment variable:

### Local Docker

```
TEST_DEPLOYMENT_MODE=local_docker
```

- Single ArangoDB server in Docker
- No GAE, no SmartGraphs
- WCC clustering uses in-memory Python Union-Find
- Auto-creates database via `_system` access
- Best for: local development, CI

### Self-Managed Platform

```
TEST_DEPLOYMENT_MODE=self_managed_platform
```

- Remote ArangoDB Enterprise cluster
- GAE enabled, SmartGraphs and SatelliteCollections available
- WCC clustering uses GAE backend
- SSL/TLS required
- Best for: staging, production

### ArangoDB Managed Platform (AMP)

```
TEST_DEPLOYMENT_MODE=managed_platform
```

- ArangoDB Managed Platform (cloud)
- GAE enabled, API key authentication for Graph API
- Database must be pre-provisioned (no `_system` access)
- SSL required
- Best for: cloud production deployments
- **Note:** Requires ArangoDB 4.0+

### Container Images

| Image | Base | Size Target |
|-------|------|-------------|
| `aoe-backend` | `python:3.11-slim` | < 500 MB |
| `aoe-frontend` | `node:20-alpine` (Next.js standalone) | < 100 MB |
| `aoe-mcp-server` | `python:3.11-slim` | < 400 MB |

### Production Docker Compose

```bash
docker compose -f docker-compose.prod.yml up -d
```

Includes all services with TLS termination and health checks.
