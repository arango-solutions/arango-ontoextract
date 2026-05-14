# AOE Multi-Subagent Implementation Prompts

**Purpose:** Orchestration prompts for parallelizing AOE implementation across multiple Cursor agent sessions. Each subagent owns a vertical slice of the codebase and can run concurrently with others within the same phase.

**How to use:** Copy the relevant subagent prompt into a new Cursor agent session. Run subagents within the same phase in parallel. Wait for all subagents in a phase to complete before starting the next phase.

---

## Phase 1 Subagents (run in parallel)

### Subagent 1A: Database Schema & Migration Framework

```
You are implementing the database schema and migration framework for the
Arango-OntoExtract (AOE) platform.

CONTEXT:
- Read PRD.md Section 5.1 (ArangoDB Collections) for the complete schema
- Read PRD.md Section 5.3 (Temporal Ontology Versioning) for interval semantics
- Read backend/app/db/AGENTS.md for package boundaries
- Read backend/app/config.py for deployment mode awareness (local_docker vs cluster)
- The existing backend/app/db/schema.py has a basic schema — you are replacing it
  with a proper migration framework

YOUR TASKS (from IMPLEMENTATION_PLAN.md Week 1, tasks 1.1–1.10):

1. Create migration runner framework:
   - backend/migrations/__init__.py
   - backend/migrations/runner.py
   Runner must: track applied migrations in `_system_meta` collection, apply pending
   migrations in numeric order, be idempotent (safe to re-run), log each migration
   applied.

2. Create 8 migration scripts (each must be idempotent — check before create):
   - 001_initial_collections.py: Non-temporal document collections (documents, chunks,
     extraction_runs, curation_decisions, notifications, organizations, users,
     _system_meta, ontology_registry)
   - 002_versioned_vertices.py: ontology_classes, ontology_properties,
     ontology_constraints (temporal vertex collections)
   - 003_edge_collections.py: All 8 edge collections (subclass_of, equivalent_class,
     has_property, extends_domain, extracted_from, related_to, merge_candidate, imports)
   - 004_named_graphs.py: domain_ontology graph with vertex/edge definitions per
     PRD Section 5.1
   - 005_mdi_indexes.py: MDI-prefixed indexes on [created, expired] for ALL versioned
     vertex and edge collections. Use type "mdi-prefixed", fieldValueTypes "double"
   - 006_ttl_indexes.py: Sparse TTL indexes on ttlExpireAt field for all versioned
     collections
   - 007_arangosearch_views.py: ArangoSearch view on ontology_classes covering label
     and description fields
   - 008_vector_indexes.py: HNSW vector index on chunks.embedding

3. Update backend/app/db/schema.py so init_schema(db) calls the migration runner.

4. Add `make migrate` target to Makefile.

FILES YOU OWN:
- backend/migrations/ (entire directory — create it)
- backend/app/db/schema.py (modify)
- Makefile (add migrate target only)

FILES YOU MUST NOT TOUCH:
- backend/app/db/client.py (already working)
- backend/app/config.py (already working)
- backend/app/api/ (other subagent)
- frontend/ (other subagent)

ACCEPTANCE CRITERIA:
- `make migrate` on a fresh ArangoDB creates all collections, edges, graphs, and indexes
- Running `make migrate` twice is safe (idempotent)
- _system_meta collection tracks schema_version and list of applied migrations
- All versioned collections have MDI-prefixed + TTL indexes
- Migration runner logs each migration it applies

TESTING:
- Create backend/tests/integration/test_migrations.py
- Test: apply all migrations on fresh DB → verify collections exist
- Test: run migrations twice → no errors (idempotent)
- Test: verify MDI index exists on ontology_classes
- Test: verify TTL index exists on ontology_classes
- Test: verify named graph domain_ontology has correct edge definitions
- Use the test_db fixture from conftest.py (will be created by Subagent 1C)
```

### Subagent 1B: Document Ingestion Pipeline

```
You are implementing the document ingestion pipeline for the Arango-OntoExtract
(AOE) platform.

CONTEXT:
- Read PRD.md Section 6.1 (Document Ingestion & Chunking) for requirements
- Read PRD.md Section 7.1 (Document Endpoints) for API spec
- Read PRD.md Section 7.8 (API Conventions) for pagination, error format, rate limiting
- Read backend/app/api/AGENTS.md and backend/app/models/AGENTS.md for boundaries
- Read backend/app/models/documents.py for existing Pydantic models
- Read backend/app/api/documents.py for existing route stubs (replace with real impl)

YOUR TASKS (from IMPLEMENTATION_PLAN.md Week 2, tasks 2.1–2.12):

1. Document repository (DB layer):
   - backend/app/db/documents_repo.py
   CRUD for `documents` and `chunks` collections. Typed functions returning Pydantic
   models. Never expose raw python-arango objects.

2. Cursor-based pagination helper:
   - backend/app/db/pagination.py
   Reusable for all list endpoints. Returns {data, cursor, has_more, total_count}.
   Cursor is an opaque base64-encoded token.

3. Standard error response handler:
   - backend/app/api/errors.py
   FastAPI exception handlers producing the error format from PRD Section 7.8:
   {error: {code, message, details, request_id}}
   HTTP status codes: 400, 401, 403, 404, 409, 422, 429, 500.

4. Document parsing service:
   - backend/app/services/ingestion.py
   Parse PDF (pymupdf/pdfplumber), DOCX (python-docx), Markdown. Extract text
   preserving structure (headings, sections, tables). Return structured text with
   page/section metadata.

5. Semantic chunking (in ingestion.py):
   Chunk at section/paragraph boundaries. Configurable max_tokens. Each chunk carries
   doc_id, chunk_index, source page, section heading.

6. Vector embedding service:
   - backend/app/services/embedding.py
   Calls configurable embedding model (default: text-embedding-3-small via OpenAI).
   Batch embedding support.

7. Async pipeline orchestration:
   - backend/app/tasks.py (Celery or ARQ task)
   Upload triggers async: parse → chunk → embed → store. Updates documents.status
   through each stage (uploading → parsing → chunking → embedding → ready/failed).

8. SHA-256 duplicate detection (in ingestion.py):
   Hash file on upload. Check against existing documents. Return 409 if duplicate.

9. Implement document API endpoints (replace stubs):
   - backend/app/api/documents.py
   POST /upload, GET /{doc_id}, GET /{doc_id}/chunks (paginated), GET / (paginated),
   DELETE /{doc_id} (soft delete).

10. Add dependencies to backend/pyproject.toml:
    pymupdf (or pdfplumber), python-docx, openai, celery (or arq), redis

FILES YOU OWN:
- backend/app/db/documents_repo.py (create)
- backend/app/db/pagination.py (create)
- backend/app/api/errors.py (create)
- backend/app/services/ingestion.py (create)
- backend/app/services/embedding.py (create)
- backend/app/tasks.py (create)
- backend/app/api/documents.py (rewrite stubs)
- backend/app/models/documents.py (extend if needed)
- backend/pyproject.toml (add deps only)

FILES YOU MUST NOT TOUCH:
- backend/app/db/client.py, backend/app/config.py
- backend/app/db/schema.py, backend/migrations/ (Subagent 1A)
- backend/app/api/ontology.py, extraction.py, curation.py, health.py
- frontend/ (other subagent)

ACCEPTANCE CRITERIA:
- POST /api/v1/documents/upload with a PDF → returns doc_id, status "uploading"
- Async pipeline processes: status transitions uploading → parsing → chunking →
  embedding → ready
- GET /api/v1/documents/{doc_id} → returns document with current status
- GET /api/v1/documents/{doc_id}/chunks → returns paginated chunks with text,
  chunk_index, token_count
- Uploading same file twice → 409 Conflict
- All list endpoints use cursor-based pagination
- All errors use standard error format

TESTING:
- backend/tests/unit/test_ingestion.py: Parse sample PDF, DOCX, Markdown (mock file
  I/O); test chunking boundaries; test SHA-256 dedup
- backend/tests/unit/test_embedding.py: Mock OpenAI call; verify batch embedding
- backend/tests/integration/test_documents_api.py: Upload sample PDF → verify chunks
  created; test pagination; test duplicate rejection
- Use fixtures from backend/tests/fixtures/sample_documents/
```

### Subagent 1C: Test Infrastructure & CI Pipeline

```
You are setting up the test infrastructure and CI pipeline for the
Arango-OntoExtract (AOE) platform.

CONTEXT:
- Read PRD.md Section 8.9 (Testing & Code Quality) for the full testing strategy
- Read backend/tests/AGENTS.md for test structure boundaries
- Read backend/pyproject.toml for existing dev dependencies
- The project uses pytest, pytest-asyncio, pytest-cov, ruff, mypy (backend)
- The frontend uses Next.js 15, React 18

YOUR TASKS (from IMPLEMENTATION_PLAN.md Week 1 tasks 1.11–1.14, Week 3 tasks
3.6, 3.9):

1. Test conftest with auto-create/drop test DB:
   - backend/tests/conftest.py
   Session-scoped fixture: creates unique DB (aoe_test_{uuid}), runs migrations,
   yields StandardDatabase handle, drops DB after session. Also: mock_settings
   fixture overriding config for test environment.

2. Docker Compose test profile:
   - docker-compose.test.yml
   Ephemeral ArangoDB + Redis for integration tests. No persistent volumes.
   ArangoDB on port 8540 (avoid conflict with dev on 8530).

3. CI pipeline (GitHub Actions):
   - .github/workflows/ci.yml
   Stages:
   a. Lint & Type Check: ruff check + mypy --strict (backend), eslint + tsc (frontend)
   b. Backend Unit Tests: pytest tests/unit/ --cov --cov-fail-under=80
   c. Backend Integration Tests: spin up docker-compose.test.yml, run pytest
      tests/integration/
   d. Frontend Lint: eslint + tsc --noEmit
   All stages must pass for PR merge.

4. Test fixtures:
   - backend/tests/fixtures/sample_documents/: 1 sample PDF, 1 DOCX, 1 Markdown
   - backend/tests/fixtures/ontologies/aws.ttl: Copy from aws_ontology if available,
     otherwise create a minimal OWL ontology in Turtle format (5-10 classes with
     subClassOf hierarchy)
   - backend/tests/fixtures/llm_responses/: Create 2-3 mock LLM extraction response
     JSON files matching the ExtractionResult Pydantic model
   - backend/tests/fixtures/embeddings/: Create 1 pre-computed embedding fixture
     (small numpy array or list)

5. Frontend test setup:
   - frontend/jest.config.ts (Jest configuration for Next.js)
   - frontend/playwright.config.ts (Playwright E2E config)
   - Update frontend/package.json with test dependencies: jest,
     @testing-library/react, @testing-library/jest-dom, msw, playwright

6. Makefile test targets:
   Add: make test-unit, make test-integration, make test-all, make lint, make
   type-check

FILES YOU OWN:
- backend/tests/conftest.py (create)
- backend/tests/fixtures/ (entire directory — create)
- docker-compose.test.yml (create)
- .github/workflows/ci.yml (create)
- frontend/jest.config.ts (create)
- frontend/playwright.config.ts (create)
- frontend/package.json (add test deps only)
- Makefile (add test targets only)

FILES YOU MUST NOT TOUCH:
- backend/app/ (other subagents)
- frontend/src/ (other subagents)
- backend/migrations/ (Subagent 1A)

ACCEPTANCE CRITERIA:
- `make test-unit` runs all backend unit tests (currently just test_health.py)
- `make test-integration` starts Docker test services, runs integration tests,
  stops services
- `make lint` runs ruff + mypy (backend) and eslint + tsc (frontend)
- CI pipeline runs on every push and PR
- Test DB fixture creates/drops DB automatically
- All test fixtures are present and well-structured
```

### Subagent 1D: Dev MCP Server & Frontend Foundation

```
You are implementing the development-time MCP server and frontend foundation for
the Arango-OntoExtract (AOE) platform.

CONTEXT:
- Read PRD.md Section 6.10 (MCP Server) for MCP tool specifications
- Read PRD.md Section 4.2 (Tech Stack) for frontend tech choices
- Read backend/app/AGENTS.md for application root boundaries
- The MCP server enables Claude in Cursor to introspect the live ArangoDB instance

YOUR TASKS (from IMPLEMENTATION_PLAN.md Week 3, tasks 3.1–3.5, 3.7–3.8, 3.10):

1. Dev-time MCP server scaffold:
   - backend/app/mcp/__init__.py
   - backend/app/mcp/server.py
   - backend/app/mcp/tools/__init__.py
   - backend/app/mcp/tools/introspection.py
   Uses `mcp` Python SDK. Starts via stdio transport. Connects to same ArangoDB
   configured in settings.

2. MCP introspection tools:
   - query_collections: List all collections with document counts
   - run_aql: Execute a read-only AQL query and return results (limit 100 rows)
   - sample_collection: Return N sample documents from a collection

3. Ontology registry repository:
   - backend/app/db/registry_repo.py
   CRUD for ontology_registry collection. Functions: create_registry_entry,
   get_registry_entry, list_registry_entries, update_registry_entry,
   deprecate_registry_entry. All return typed dicts or Pydantic models.

4. Ontology library API endpoints (replace stubs in ontology.py):
   - GET /api/v1/ontology/library → list all registered ontologies (paginated)
   - GET /api/v1/ontology/library/{ontology_id} → get ontology detail with stats
   Keep all other ontology.py endpoints as stubs for now.

5. Frontend API client:
   - frontend/src/lib/api-client.ts
   Typed fetch wrapper. Handles: base URL from env, pagination envelope parsing,
   error response parsing, auth token header (stub for now).

6. Frontend landing page (replace placeholder):
   - frontend/src/app/page.tsx
   Shows: backend connection status (calls /health and /ready), system stats
   (document count, ontology count via /api/v1/stats), quick-action links.

7. Add MCP dependency to backend/pyproject.toml: `mcp`

FILES YOU OWN:
- backend/app/mcp/ (entire directory — create)
- backend/app/db/registry_repo.py (create)
- backend/app/api/ontology.py (modify library endpoints only; keep other stubs)
- frontend/src/lib/api-client.ts (create)
- frontend/src/app/page.tsx (rewrite)
- backend/pyproject.toml (add mcp dep only)

FILES YOU MUST NOT TOUCH:
- backend/app/db/client.py, backend/app/config.py
- backend/app/api/documents.py (Subagent 1B)
- backend/app/api/errors.py (Subagent 1B)
- backend/migrations/ (Subagent 1A)
- backend/tests/ (Subagent 1C)

ACCEPTANCE CRITERIA:
- MCP server starts: python -m app.mcp.server
- Claude in Cursor can list collections and run AQL queries
- GET /api/v1/ontology/library returns paginated list (empty initially)
- Frontend landing page shows backend health status
- API client handles pagination envelope and error format
```

---

## Phase 2 Subagents (run in parallel after Phase 1 completes)

### Subagent 2A: LangGraph Extraction Pipeline (Backend)

```
You are implementing the LangGraph agentic extraction pipeline for the
Arango-OntoExtract (AOE) platform.

CONTEXT:
- Read PRD.md Section 6.11 (Agentic Extraction Pipeline) for full architecture
- Read PRD.md Section 6.2 (Domain Ontology Extraction) for extraction requirements
- Read backend/app/extraction/AGENTS.md for package boundaries
- Read backend/app/models/ontology.py for ExtractionResult, ExtractedClass models
- Phase 1 is complete: schema deployed, ingestion pipeline working, test infra ready

YOUR TASKS (IMPLEMENTATION_PLAN.md Weeks 4-6, tasks 4.1–4.7, 5.1–5.7, 6.1–6.8):

1. LangGraph state schema:
   - backend/app/extraction/state.py
   ExtractionPipelineState TypedDict per PRD Section 6.11

2. Pipeline graph definition:
   - backend/app/extraction/pipeline.py
   StateGraph: Strategy Selector → Extraction → Consistency → Staging
   Conditional edges. Compiles to runnable. Node callbacks emit structured logs.

3. Strategy Selector agent:
   - backend/app/extraction/agents/strategy.py
   Analyzes doc type + length. Returns extraction config (model, prompt, chunks).

4. Extraction Agent (N-pass with self-correction):
   - backend/app/extraction/agents/extractor.py
   Runs N LLM passes (configurable, default 3). Each pass validates against
   ExtractedClass/ExtractionResult Pydantic models. On validation failure: feeds
   error back to LLM, retries up to 3x. RAG: retrieves relevant chunks via vector
   similarity, injects into prompt.

5. Consistency Checker:
   - backend/app/extraction/agents/consistency.py
   Compares N-pass results. Keeps concepts in ≥ M passes (configurable, default 2).
   Assigns confidence scores based on cross-pass agreement.

6. Prompt template system:
   - backend/app/extraction/prompts/__init__.py
   - backend/app/extraction/prompts/tier1_standard.py
   - backend/app/extraction/prompts/tier1_technical.py
   Per-domain templates. Include domain ontology context injection slot for Tier 2.

7. Pipeline checkpointing:
   LangGraph state persisted to Redis. Pipeline resumable after failure.

8. Extraction run service:
   - backend/app/services/extraction.py
   Creates extraction_runs record. Dispatches LangGraph pipeline. Updates status
   per agent step. Tracks token usage and cost.

9. ArangoRDF bridge service:
   - backend/app/services/arangordf_bridge.py
   Wraps arango_rdf.rdf_to_arangodb_by_pgt(). Post-import ontology_id tagging.
   Per-ontology named graph creation.

10. Extraction → OWL serialization:
    In extraction service: convert ExtractionResult (Pydantic) → rdflib Graph (OWL).

11. Staging graph creation:
    - backend/app/services/ontology.py
    Extraction output → PGT import → staging_{run_id} named graph.

12. Temporal versioning service:
    - backend/app/services/temporal.py
    Core functions: create_version(), expire_entity(), re_create_edges()
    Edge-interval time travel: expire old vertex + edges, insert new vertex + edges.
    NEVER_EXPIRES = sys.maxsize sentinel.

13. Ontology repository:
    - backend/app/db/ontology_repo.py
    CRUD for ontology_classes, ontology_properties, edges. All writes go through
    temporal versioning.

14. Extraction API endpoints (replace stubs):
    - backend/app/api/extraction.py
    POST /run, GET /runs (list), GET /runs/{id}, GET /runs/{id}/steps,
    GET /runs/{id}/results, POST /runs/{id}/retry, GET /runs/{id}/cost

15. WebSocket for pipeline progress:
    - backend/app/api/ws_extraction.py
    ws://host/ws/extraction/{run_id} emits step_started, step_completed,
    step_failed, completed events via Redis Pub/Sub.

16. Add dependencies: langgraph, langchain, langchain-anthropic, langchain-openai,
    arango-rdf, rdflib

FILES YOU OWN:
- backend/app/extraction/ (entire directory)
- backend/app/services/extraction.py
- backend/app/services/arangordf_bridge.py
- backend/app/services/temporal.py
- backend/app/services/ontology.py
- backend/app/db/ontology_repo.py
- backend/app/api/extraction.py (rewrite stubs)
- backend/app/api/ws_extraction.py (create)

FILES YOU MUST NOT TOUCH:
- backend/app/db/client.py, backend/app/config.py
- backend/app/api/documents.py, curation.py, health.py
- backend/app/services/ingestion.py, embedding.py
- frontend/ (other subagent)

TESTING:
Write all of these:
- backend/tests/unit/test_strategy_selector.py
- backend/tests/unit/test_extraction_parser.py
- backend/tests/unit/test_consistency.py
- backend/tests/unit/test_temporal_versioning.py
- backend/tests/integration/test_arangordf_import.py
- backend/tests/integration/test_temporal_queries.py
- backend/tests/e2e/test_extraction_flow.py
Use recorded LLM fixtures from tests/fixtures/llm_responses/ (mock all LLM calls).
```

### Subagent 2B: Pipeline Monitor Dashboard (Frontend)

```
You are implementing the Pipeline Monitor Dashboard for the Arango-OntoExtract
(AOE) platform.

CONTEXT:
- Read PRD.md Section 6.12 (Pipeline Monitor Dashboard) for full specification
- Read PRD.md Section 7.8 (WebSocket Events) for event format
- Read IMPLEMENTATION_PLAN.md Week 7 tasks 7.3–7.10
- Phase 1 frontend foundation is complete: API client, Jest, Playwright configured
- The backend WebSocket endpoint (ws://host/ws/extraction/{run_id}) is being built
  by Subagent 2A concurrently

YOUR TASKS:

1. Install React Flow:
   Add reactflow to frontend/package.json dependencies

2. Pipeline Monitor page:
   - frontend/src/app/pipeline/page.tsx
   Route /pipeline. Layout: left sidebar (run list), main area (agent DAG + metrics).

3. Run List component:
   - frontend/src/components/pipeline/RunList.tsx
   Fetches GET /api/v1/extraction/runs (paginated). Shows: run ID, document name,
   status badge (queued/running/completed/failed), timestamp, duration.
   Filterable by status. Sortable by date. Auto-refreshes every 5s for active runs.

4. Agent DAG component:
   - frontend/src/components/pipeline/AgentDAG.tsx
   React Flow graph with 5 nodes: Strategy Selector → Extraction Agent →
   Consistency Checker → Entity Resolution Agent → Pre-Curation Filter → Staging.
   Fixed layout (not dynamic). Custom node component with: agent name, status icon
   (○ pending, ▶ running, ✓ completed, ✗ failed, ⏸ paused), elapsed time.
   Edges: solid for sequential, dashed for conditional.

5. WebSocket hook:
   - frontend/src/lib/use-websocket.ts
   React hook: connects to ws://host/ws/extraction/{run_id}. Handles reconnection.
   Events: step_started, step_completed, step_failed, pipeline_paused, completed.
   Returns current step states as a Map<string, AgentStatus>.

6. Run Metrics panel:
   - frontend/src/components/pipeline/RunMetrics.tsx
   Shows: total duration, token usage (prompt + completion), estimated cost by
   model, entity counts (classes extracted, properties extracted), pass agreement rate.

7. Error Log panel:
   - frontend/src/components/pipeline/ErrorLog.tsx
   Timestamped error/warning list. Expandable details. Retry button calls
   POST /api/v1/extraction/runs/{run_id}/retry.

8. Run Timeline (Gantt):
   - frontend/src/components/pipeline/RunTimeline.tsx
   Horizontal bars showing when each agent step started/ended. Reveals bottlenecks.

FILES YOU OWN:
- frontend/src/app/pipeline/ (create)
- frontend/src/components/pipeline/ (create entire directory)
- frontend/src/lib/use-websocket.ts (create)
- frontend/package.json (add reactflow dep only)

FILES YOU MUST NOT TOUCH:
- frontend/src/app/page.tsx (Subagent 1D)
- frontend/src/lib/api-client.ts (already created by Phase 1)
- backend/ (other subagent)

TESTING:
- frontend/src/components/pipeline/__tests__/RunList.test.tsx
- frontend/src/components/pipeline/__tests__/AgentDAG.test.tsx
- frontend/src/components/pipeline/__tests__/RunMetrics.test.tsx
Use msw (Mock Service Worker) for API mocking. Mock WebSocket with jest.
```

---

## Phase 3 Subagents (run in parallel after Phase 2 completes)

### Subagent 3A: Curation Backend (Services + APIs)

```
You are implementing the curation backend services and temporal APIs for AOE.

CONTEXT:
- Read PRD.md Sections 6.4, 6.5 for curation and temporal requirements
- Read PRD.md Section 7.4 (Curation Endpoints) for API spec
- Read PRD.md Section 5.3 for temporal versioning details
- Phase 2 complete: temporal service, ontology repo, extraction pipeline working

YOUR TASKS (IMPLEMENTATION_PLAN.md Weeks 8-10 backend tasks):

1. Curation service:
   - backend/app/services/curation.py
   record_decision(): creates curation_decisions entry + new temporal version.
   promote_staging(): moves approved entities to production graph with temporal
   versioning. batch_decide(): bulk approve/reject.

2. Curation API endpoints (replace stubs):
   - backend/app/api/curation.py
   POST /decide, GET /decisions (paginated), POST /merge

3. Promotion service (in ontology.py):
   Staging → production. Creates temporal versions. Updates named graphs.

4. Temporal APIs:
   - GET /ontology/{id}/snapshot?at={timestamp}: point-in-time graph state
   - GET /ontology/class/{key}/history: all versions by URI
   - GET /ontology/{id}/diff?t1=&t2=: temporal diff (added/removed/changed)
   - GET /ontology/{id}/timeline: discrete change events for VCR tick marks
   - POST /ontology/class/{key}/revert?to_version={n}: revert to historical version

5. Integration tests for all of the above

FILES YOU OWN:
- backend/app/services/curation.py (create)
- backend/app/api/curation.py (rewrite stubs)
- backend/app/api/ontology.py (add temporal endpoints)
- backend/app/services/temporal.py (extend with snapshot/diff/revert)

TESTING:
- backend/tests/integration/test_curation_workflow.py
- backend/tests/integration/test_temporal_queries.py (extend)
```

### Subagent 3B: Curation Dashboard (Frontend)

```
You are implementing the Visual Curation Dashboard frontend for AOE.

CONTEXT:
- Read PRD.md Sections 6.4, 6.5 for curation dashboard and VCR timeline specs
- Read IMPLEMENTATION_PLAN.md Weeks 8-10, 12 frontend tasks
- React Flow is already installed (from Pipeline Monitor). Reuse for graph rendering.
- API client already exists at frontend/src/lib/api-client.ts

YOUR TASKS (IMPLEMENTATION_PLAN.md Weeks 8-10 frontend tasks):

1. Graph Canvas, Node/Edge actions, Batch operations (Week 8)
2. Provenance panel, Confidence visualization, Diff view, Promotion UI (Week 9)
3. VCR Timeline slider, Timeline markers, Diff overlay, Entity Focus mode (Week 10)
4. Ontology Library browser (Week 12)
5. E2E tests: curation + timeline (Week 12)

FILES YOU OWN:
- frontend/src/app/curation/ (create)
- frontend/src/app/library/ (create)
- frontend/src/components/graph/ (create)
- frontend/src/components/curation/ (create)
- frontend/src/components/timeline/ (create)
- frontend/src/components/library/ (create)
- frontend/e2e/curation.spec.ts, timeline.spec.ts, library.spec.ts

FILES YOU MUST NOT TOUCH:
- frontend/src/components/pipeline/ (Subagent 2B)
- frontend/src/app/pipeline/ (Subagent 2B)
- backend/ (Subagent 3A)
```

### Subagent 3C: ArangoDB Graph Visualizer Customization

```
You are implementing ArangoDB Graph Visualizer customization for AOE.

CONTEXT:
- Read PRD.md Section 6.6 for themes, canvas actions, saved queries, viewpoints
- Read the ArangoDB Visualizer Customizer skill at
  /Users/arthurkeen/.cursor/skills/arangodb-visualizer-customizer/SKILL.md
- Read PRD.md Section 9.7 for reference implementations to follow

YOUR TASKS (IMPLEMENTATION_PLAN.md Week 11):

1. Theme JSON with OWL/RDFS/SKOS node type colors and icons
2. 7 canvas actions with AQL (all filtering current edges: expired == NEVER_EXPIRES)
3. 10+ saved queries (class hierarchy, orphans, cross-tier, temporal snapshots)
4. Idempotent install script with viewpoint auto-creation
5. Integration test: install twice, verify idempotent

FILES YOU OWN:
- docs/visualizer/ (create entire directory)
- scripts/setup/install_visualizer.py (create)
- backend/tests/integration/test_visualizer_install.py
```

---

## Phase 4 Subagents (run in parallel after Phase 3 completes)

### Subagent 4A: Tier 2 Extraction & Entity Resolution (Backend)

```
You are implementing Tier 2 context-aware extraction and entity resolution for AOE.

CONTEXT:
- Read PRD.md Sections 6.3 (Tier 2), 6.7 (Entity Resolution), 6.11 (ER/Filter agents)
- Read PRD.md Section 9.4 for arango-entity-resolution library integration details
- Phase 3 complete: curation, temporal versioning, all APIs working

YOUR TASKS (IMPLEMENTATION_PLAN.md Weeks 13-15):

1. Domain ontology context serializer (Week 13)
2. Tier 2 prompt templates with EXISTING/EXTENSION/NEW classification (Week 13)
3. Cross-tier edge creation (extends_domain) (Week 13)
4. Conflict detection service (Week 13)
5. arango-entity-resolution integration: ERPipelineConfig, blocking, scoring (Week 14)
6. Topological similarity scoring (AOE-specific) (Week 14)
7. ER API endpoints (8 endpoints from PRD Section 7.5) (Week 14)
8. ER collections migration (Week 14)
9. Entity Resolution LangGraph agent (Week 15)
10. Pre-Curation Filter agent (Week 15)
11. Full pipeline: Strategy → Extraction → Consistency → ER → Filter → Staging (Week 15)
12. Human-in-the-loop breakpoint (Week 15)

FILES YOU OWN:
- backend/app/services/er.py (create)
- backend/app/api/er.py (create)
- backend/app/extraction/agents/er_agent.py (create)
- backend/app/extraction/agents/filter.py (create)
- backend/app/extraction/prompts/tier2/ (create)
- backend/app/extraction/pipeline.py (extend with ER + filter nodes)
- backend/migrations/009_er_collections.py (create)
```

### Subagent 4B: Merge UI & Cross-Tier Frontend

```
You are implementing the merge candidate UI and cross-tier visualization for AOE.

CONTEXT:
- Read PRD.md Section 6.7 (Entity Resolution requirements FR-7.7 through FR-7.9)
- Phase 3 curation dashboard complete with graph canvas

YOUR TASKS (IMPLEMENTATION_PLAN.md Week 16):

1. Merge candidate panel (shows pairs with scores, explain_match evidence)
2. Merge execution UI (one-click merge, before/after, provenance preservation)
3. Cross-tier visualization (domain vs local coloring, extends_domain edges)
4. E2E test: Tier 2 extraction + ER + merge

FILES YOU OWN:
- frontend/src/components/curation/MergeCandidates.tsx
- frontend/src/components/curation/MergeExecutor.tsx
- frontend/src/components/graph/GraphCanvas.tsx (extend with cross-tier coloring)
- frontend/e2e/entity-resolution.spec.ts
```

---

## Phase 5: MCP Server (single subagent — smaller scope)

### Subagent 5A: Runtime MCP Server

```
You are implementing the runtime MCP server for AOE, extending the dev-time MCP
created in Phase 1.

CONTEXT:
- Read PRD.md Section 6.10 for full MCP tool/resource specifications
- Read backend/app/mcp/ for existing dev-time MCP scaffold
- All backend services are complete: ontology, temporal, extraction, ER, curation

YOUR TASKS (IMPLEMENTATION_PLAN.md Weeks 17-19):

1. Extend MCP server with SSE transport (alongside existing stdio) (Week 17)
2. Ontology query tools: 4 tools (Week 17)
3. Pipeline tools: 3 tools (Week 17)
4. Temporal tools: 3 tools (Week 17)
5. Provenance + export tools: 2 tools (Week 17)
6. MCP resources: 4 resource URIs (Week 18)
7. ER MCP tool proxying to arango-entity-resolution MCP (Week 18)
8. Organization-scoped auth for MCP (Week 18)
9. Auto-generate tool schemas from Pydantic models (Week 18)
10. Integration tests + documentation (Week 19)

FILES YOU OWN:
- backend/app/mcp/ (extend everything)
- docs/mcp-server.md (create)
- backend/tests/integration/test_mcp_tools.py
- backend/tests/e2e/test_mcp_e2e.py
```

---

## Phase 6 Subagents (run in parallel after Phase 5 completes)

### Subagent 6A: Import/Export & Schema Extraction

```
Tasks 20.1–20.6 from IMPLEMENTATION_PLAN.md. OWL/TTL import via ArangoRDF,
export via rdflib, schema extraction via arango-schema-mapper.
Own: backend/app/services/export.py, schema_extraction.py, ontology API extensions.
```

### Subagent 6B: Auth, Multi-Tenancy & Notifications

```
Tasks 21.1–21.5, 22.1–22.6 from IMPLEMENTATION_PLAN.md. OAuth 2.0, RBAC, org
isolation, notifications, observability.
Own: backend/app/api/auth.py, dependencies.py, orgs.py, notifications.py,
ws_curation.py, metrics.py. Frontend auth integration.
```

### Subagent 6C: DevOps & Deployment

```
Tasks 23.1–23.6 from IMPLEMENTATION_PLAN.md. Rate limiting, caching, Dockerfiles,
docker-compose.prod.yml, optional K8s manifests, index tuning.
Own: backend/Dockerfile, frontend/Dockerfile, docker-compose.prod.yml, k8s/,
rate_limit.py.
```

### Subagent 6D: Documentation & Final Testing

```
Tasks 24.1–24.7 from IMPLEMENTATION_PLAN.md. OpenAPI review, user guide, ADRs,
full E2E suite, performance benchmarks, proxy pattern decision, release.
Own: docs/ (all), final E2E tests.
```

---

## Orchestration Rules

1. **Phase gates are strict:** ALL subagents in a phase must complete before ANY
   subagent in the next phase starts. Each phase builds on the prior phase's
   completed work.

2. **File ownership is exclusive:** Each subagent owns specific files. No two
   subagents touch the same file within a phase. This prevents merge conflicts.

3. **Shared infrastructure is Phase 1:** Pagination, error format, test fixtures,
   CI pipeline, and API client are established in Phase 1 and used by all
   subsequent subagents.

4. **Backend before frontend within a phase:** When a subagent depends on an API
   that another subagent is building concurrently, the frontend subagent should
   mock the API initially and integrate once the backend subagent completes.

5. **Every subagent writes tests:** No subagent is "done" until its acceptance
   criteria are met and tests pass.

6. **Commit convention:** Each subagent commits to a feature branch named
   `phase-{N}/{subagent-name}` (e.g., `phase-1/schema-migrations`). Branches
   are merged to `main` at the phase gate.

## Parallelization Summary

| Phase | Parallel Subagents | Estimated Duration |
|-------|-------------------|-------------------|
| 1 | 4 subagents (1A, 1B, 1C, 1D) | 1-2 weeks |
| 2 | 2 subagents (2A, 2B) | 2-3 weeks |
| 3 | 3 subagents (3A, 3B, 3C) | 3-4 weeks |
| 4 | 2 subagents (4A, 4B) | 2-3 weeks |
| 5 | 1 subagent (5A) | 1-2 weeks |
| 6 | 4 subagents (6A, 6B, 6C, 6D) | 2-3 weeks |
| **Total with parallelization** | | **~11-17 weeks** (vs 24 sequential) |
