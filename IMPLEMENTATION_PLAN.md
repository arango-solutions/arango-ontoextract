# AOE Implementation Plan

**Derived from:** PRD.md v3 (2026-03-28)
**Approach:** Each PRD phase is decomposed into weekly sprints with specific tasks, files to create/modify, dependencies, and acceptance criteria.

---

## Phase 1: Foundation (Weeks 1–3)

**Goal:** Database schema, document ingestion pipeline, test infrastructure, dev-time MCP.

### Week 1: Schema, Migration Framework & Test Infrastructure

**Focus:** Get the database schema deployed, migration tooling in place, and CI pipeline running.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 1.1 | Implement migration runner framework | `backend/migrations/runner.py`, `backend/migrations/__init__.py` | — | `python -m migrations.runner` applies pending migrations in order; tracks state in `aoe_system_meta` (not `_system_meta`, which is invalid on ArangoDB Enterprise clusters) |
| 1.2 | Migration 001: Create all non-temporal collections | `backend/migrations/001_initial_collections.py` | 1.1 | `documents`, `chunks`, `extraction_runs`, `curation_decisions`, `notifications`, `organizations`, `users`, `aoe_system_meta`, `ontology_registry` created idempotently |
| 1.3 | Migration 002: Create versioned vertex collections | `backend/migrations/002_versioned_vertices.py` | 1.2 | `ontology_classes`, `ontology_properties`, `ontology_constraints` created with temporal field defaults |
| 1.4 | Migration 003: Create edge collections | `backend/migrations/003_edge_collections.py` | 1.3 | All 8 edge collections created (`subclass_of`, `equivalent_class`, `has_property`, `extends_domain`, `extracted_from`, `related_to`, `merge_candidate`, `imports`) |
| 1.5 | Migration 004: Create named graphs | `backend/migrations/004_named_graphs.py` | 1.4 | `domain_ontology` graph created with correct vertex/edge definitions per PRD Section 5.1 |
| 1.6 | Migration 005: MDI-prefixed temporal indexes | `backend/migrations/005_mdi_indexes.py` | 1.3, 1.4 | MDI-prefixed indexes on `[created, expired]` deployed on all versioned vertex and edge collections |
| 1.7 | Migration 006: TTL indexes for historical aging | `backend/migrations/006_ttl_indexes.py` | 1.3, 1.4 | Sparse TTL indexes on `ttlExpireAt` field for all versioned collections |
| 1.8 | Migration 007: ArangoSearch views | `backend/migrations/007_arangosearch_views.py` | 1.2, 1.3 | ArangoSearch view on `ontology_classes` (label, description) for BM25 blocking |
| 1.9 | Migration 008: Vector indexes | `backend/migrations/008_vector_indexes.py` | 1.2 | HNSW vector index on `chunks.embedding` field. Must use raw ArangoDB REST API (`db._conn.send_request`) as `python-arango` high-level methods do not expose HNSW vector parameters. |
| 1.10 | Update `schema.py` to call migration runner | `backend/app/db/schema.py` | 1.1 | `init_schema(db)` runs all pending migrations |
| 1.11 | CI pipeline: lint + type check + unit tests | `.github/workflows/ci.yml` | — | GitHub Actions runs `ruff check`, `mypy`, `pytest tests/unit/` on every push |
| 1.12 | Docker Compose test profile | `docker-compose.test.yml` | — | `docker compose -f docker-compose.test.yml up` starts ephemeral ArangoDB + Redis for integration tests |
| 1.13 | Test conftest with auto-create/drop test DB | `backend/tests/conftest.py` | 1.12 | `test_db` fixture creates unique DB, runs migrations, yields, drops DB |
| 1.14 | Copy test fixtures | `backend/tests/fixtures/ontologies/aws.ttl`, `backend/tests/fixtures/sample_documents/` | — | Sample OWL file and 2-3 test documents (PDF, DOCX, Markdown) in fixtures |
| 1.15 | Integration test: migration runner | `backend/tests/integration/test_migrations.py` | 1.1–1.9, 1.13 | All migrations apply cleanly on fresh DB; re-running is idempotent |
| 1.16 | Migration 009: ER collections | `backend/migrations/009_er_collections.py` | 1.4 | `similarTo`, `entity_clusters`, `golden_records` collections created |
| 1.17 | Migration 010: Process graph | `backend/migrations/010_process_graph.py` | 1.4 | Creates `aoe_process` named graph with `has_chunk`, `extracted_from`, `has_property`, `subclass_of`, `produced_by` edges; adds `extracted_from` to `domain_ontology` graph |

**Week 1 exit:** `make migrate` creates the full schema on a fresh ArangoDB. CI pipeline green. Test DB auto-provisioning works.

### Week 2: Document Ingestion Pipeline

**Focus:** Upload → parse → chunk → embed, with full API and tests.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 2.1 | Document repository (DB layer) | `backend/app/db/documents_repo.py` | W1 | CRUD for `documents` and `chunks` collections; typed functions, no raw AQL in other modules |
| 2.2 | Document parsing service (PDF/DOCX/Markdown) | `backend/app/services/ingestion.py` | — | Parses PDF (via `pymupdf` or `pdfplumber`), DOCX (via `python-docx`), and Markdown; extracts text preserving structure |
| 2.3 | Semantic chunking | `backend/app/services/ingestion.py` | 2.2 | Chunks text at section/paragraph boundaries; respects `max_tokens` config; preserves source page/section metadata |
| 2.4 | Vector embedding service | `backend/app/services/embedding.py` | — | Calls OpenAI `text-embedding-3-small` (or configurable model); returns embeddings for text chunks |
| 2.5 | Async pipeline orchestration (Celery/ARQ) | `backend/app/services/ingestion.py`, `backend/app/tasks.py` | 2.2, 2.3, 2.4 | Document upload triggers async task: parse → chunk → embed → store; status updates to `documents.status` |
| 2.6 | Implement document API endpoints | `backend/app/api/documents.py` | 2.1, 2.5 | `POST /upload` triggers pipeline, `GET /{doc_id}` returns status, `GET /{doc_id}/chunks` returns chunks with pagination |
| 2.7 | SHA-256 duplicate detection | `backend/app/services/ingestion.py` | 2.1 | Hash check on upload; rejects identical files with `409 Conflict` |
| 2.8 | Pagination helper (cursor-based) | `backend/app/db/pagination.py` | — | Reusable cursor-based pagination for all list endpoints; returns `{data, cursor, has_more, total_count}` |
| 2.9 | Standard error response handler | `backend/app/api/errors.py` | — | FastAPI exception handlers producing PRD Section 7.8 error format |
| 2.10 | Unit tests: parsing, chunking, embedding | `backend/tests/unit/test_ingestion.py`, `backend/tests/unit/test_embedding.py` | 2.2–2.4 | Mocked LLM/embedding calls; tests for PDF/DOCX/Markdown parsing; edge cases (empty doc, huge doc) |
| 2.11 | Integration tests: document API | `backend/tests/integration/test_documents_api.py` | 2.6, 1.13 | Upload sample PDF → verify chunks created → verify status transitions |
| 2.12 | Add backend dependencies | `backend/pyproject.toml` | — | Add `pymupdf`, `python-docx`, `langchain`, `openai`, `celery`/`arq`, `redis` |

**Week 2 exit:** Can upload a PDF via API and retrieve semantically chunked, embedded content. Duplicate detection works. Pagination and error format established.

### Week 3: Dev-time MCP Server & Ontology Registry

**Focus:** MCP for Cursor development, ontology registry foundation, frontend test setup.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 3.1 | Dev-time MCP server scaffold | `backend/app/mcp/server.py`, `backend/app/mcp/__init__.py` | W1 | MCP server starts via stdio; connects to same ArangoDB instance |
| 3.2 | MCP tool: `query_collections` | `backend/app/mcp/tools/introspection.py` | 3.1 | Claude in Cursor can list collections and sample documents |
| 3.3 | MCP tool: `run_aql` | `backend/app/mcp/tools/introspection.py` | 3.1 | Claude can run read-only AQL queries against the dev database |
| 3.4 | Ontology registry repository | `backend/app/db/registry_repo.py` | W1 | CRUD for `ontology_registry` collection |
| 3.5 | Ontology library API endpoints | `backend/app/api/ontology.py` | 3.4 | `GET /library` lists registered ontologies; `GET /library/{id}` returns detail with stats |
| 3.6 | Frontend: install Jest + React Testing Library + Playwright | `frontend/package.json`, `frontend/jest.config.ts`, `frontend/playwright.config.ts` | — | `npm test` runs Jest; `npx playwright test` runs E2E |
| 3.7 | Frontend: API client scaffold | `frontend/src/lib/api-client.ts` | — | Typed fetch wrapper for all backend API endpoints; handles pagination envelope |
| 3.8 | Frontend: health check page | `frontend/src/app/page.tsx` | 3.7 | Landing page calls backend `/ready` endpoint (not `/api/v1/health`); shows backend status, registered ontology count, quick links |
| 3.8a | Frontend: document upload page | `frontend/src/app/upload/page.tsx` | 3.7, 2.6 | Drag-and-drop file upload (PDF/DOCX/Markdown); shows recent documents with status and chunk counts; calls `POST /api/v1/documents/upload` |
| 3.9 | CI pipeline: add integration tests + frontend lint | `.github/workflows/ci.yml` | 1.11, 1.12 | CI runs integration tests against Docker ArangoDB; runs `eslint` + `tsc --noEmit` on frontend |
| 3.10 | Makefile: `make migrate`, `make test-unit`, `make test-integration` | `Makefile` | 1.1, 1.11 | Convenience commands for common dev workflows |

**Phase 1 exit:** Full schema deployed. Document ingestion pipeline working end-to-end. Dev MCP server operational in Cursor. CI pipeline green with unit + integration tests. Coverage ≥ 80% on foundation code.

---

## Phase 2: Extraction Pipeline & Agentic Orchestration (Weeks 4–7)

**Goal:** LLM-driven ontology extraction via LangGraph, with pipeline monitoring UI.

### Week 4: LangGraph Scaffold & Strategy Selector

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 4.1 | Install LangGraph; define state schema | `backend/app/extraction/state.py` | — | `ExtractionPipelineState` TypedDict matching PRD Section 6.11 |
| 4.2 | Pipeline graph definition | `backend/app/extraction/pipeline.py` | 4.1 | `StateGraph` with nodes for each agent; conditional edges; compiles to runnable |
| 4.3 | Strategy Selector agent | `backend/app/extraction/agents/strategy.py` | 4.1 | Analyzes document type + length; selects model, prompt template, chunk params |
| 4.4 | Prompt template system | `backend/app/extraction/prompts/` | — | Per-domain prompt templates; Jinja2 or string templates; domain ontology context injection slot |
| 4.5 | Extraction run service | `backend/app/services/extraction.py` | 4.2, W2 | Creates `extraction_runs` record; dispatches LangGraph pipeline; updates status |
| 4.6 | Extraction API endpoints (full) | `backend/app/api/extraction.py` | 4.5 | `POST /run`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/steps`, `POST /runs/{id}/retry`, `GET /runs/{id}/cost` |
| 4.7 | Unit tests: strategy selector | `backend/tests/unit/test_strategy_selector.py` | 4.3 | Different document types produce different configs |

### Week 5: Extraction Agent & Consistency Checker

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 5.1 | Extraction Agent (N-pass with self-correction) | `backend/app/extraction/agents/extractor.py` | 4.1, 4.4 | Runs N LLM passes; validates output against `ExtractedClass`/`ExtractionResult` Pydantic models; retries up to 3x on validation failure with error message fed back |
| 5.2 | Consistency Checker agent | `backend/app/extraction/agents/consistency.py` | 4.1 | Compares N-pass results; keeps concepts appearing in ≥ M passes; assigns confidence scores |
| 5.3 | RAG context injection | `backend/app/extraction/agents/extractor.py` | W2 (embedding) | Retrieves relevant chunks via vector similarity; injects into extraction prompt |
| 5.4 | Pipeline checkpointing | `backend/app/extraction/pipeline.py` | 4.2 | LangGraph state persisted to Redis or DB; pipeline resumable after failure |
| 5.5 | Structured agent logging | `backend/app/extraction/agents/` (all) | 4.1 | Every agent step emits structured log with `run_id`, step name, duration, tokens, errors |
| 5.6 | Record LLM response fixtures | `backend/tests/fixtures/llm_responses/` | 5.1 | 3-5 recorded extraction responses for deterministic testing |
| 5.7 | Unit tests: extractor, consistency checker | `backend/tests/unit/test_extraction_parser.py`, `backend/tests/unit/test_consistency.py` | 5.1, 5.2, 5.6 | Mocked LLM responses; tests for validation failure + retry; tests for cross-pass agreement filtering |

### Week 6: ArangoRDF Integration & Staging Graphs

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 6.1 | ArangoRDF bridge service | `backend/app/services/arangordf_bridge.py` | — | Wraps `arango_rdf.rdf_to_arangodb_by_pgt()`; adds post-import `ontology_id` tagging; creates per-ontology named graph |
| 6.2 | Extraction → OWL serialization | `backend/app/services/extraction.py` | 5.1 | Converts `ExtractionResult` (Pydantic) → rdflib Graph (OWL/TTL) |
| 6.3 | Staging graph creation | `backend/app/services/ontology.py` | 6.1, 6.2, W1 | Extraction output imported via PGT into `staging_{run_id}` named graph; all entities tagged with `ontology_id` |
| 6.4 | Temporal versioning service | `backend/app/services/temporal.py` | W1 | `create_version()`, `expire_entity()`, `re_create_edges()` — core edge-interval time travel operations |
| 6.5 | Ontology repository (DB layer) | `backend/app/db/ontology_repo.py` | W1 | CRUD for `ontology_classes`, `ontology_properties`, edges; all operations use temporal versioning |
| 6.6 | Staging ontology API endpoint | `backend/app/api/ontology.py` | 6.3, 6.5 | `GET /staging/{run_id}` resolves `ontology_id` from the extraction run, then returns all current classes, properties, and edges for that ontology as JSON |
| 6.6a | Graph materialization after extraction | `backend/app/services/extraction.py` | 6.5 | After successful extraction, auto-populate `ontology_classes`, `ontology_properties`, and edges (`has_property`, `subclass_of`, `extracted_from`) from `ExtractionResult`. Also auto-register in `ontology_registry`. |
| 6.6b | Per-ontology named graph auto-creation | `backend/app/services/ontology_graphs.py` | 6.6a | After extraction and registration, auto-create a per-ontology named graph (`ontology_{name_slug}`) with human-readable name derived from the ontology's registry `name` field (e.g., `ontology_financial_services_domain`). |
| 6.6c | Per-ontology API endpoints | `backend/app/api/ontology.py` | 6.5 | `GET /{ontology_id}/classes`, `GET /{ontology_id}/properties?keys=`, `GET /{ontology_id}/edges`, `GET /graphs` — per-ontology class/property/edge retrieval and graph listing |
| 6.7 | Integration tests: ArangoRDF import | `backend/tests/integration/test_arangordf_import.py` | 6.1, 1.13, 1.14 | Import `aws.ttl` → verify collections populated → verify named graph → verify `ontology_id` tagging |
| 6.8 | Integration tests: temporal versioning | `backend/tests/integration/test_temporal_queries.py` | 6.4, 1.13 | Create entity → edit → verify old expired + new created → point-in-time snapshot returns correct version. Temporal convention: `expired == NEVER_EXPIRES` (sys.maxsize = 9223372036854775807) for current entities. |

### Week 7: Pipeline Monitor Dashboard & WebSocket

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 7.1 | WebSocket endpoint: extraction progress | `backend/app/api/ws_extraction.py` | 4.5 | `ws://host/ws/extraction/{run_id}` emits `step_started`, `step_completed`, `step_failed`, `completed` |
| 7.2 | Agent step event emission | `backend/app/extraction/pipeline.py` | 7.1 | LangGraph node callbacks publish events to WebSocket via Redis Pub/Sub |
| 7.3 | Frontend: Pipeline Monitor page scaffold | `frontend/src/app/pipeline/page.tsx` | 3.7 | Route `/pipeline` with run list and detail layout; includes "Curate" button linking to `/curation/{runId}` for completed runs |
| 7.4 | Frontend: Run List component | `frontend/src/components/pipeline/RunList.tsx` | 7.3 | Filterable/sortable list of extraction runs; status badges; auto-refresh |
| 7.5 | Frontend: Agent DAG component (React Flow) | `frontend/src/components/pipeline/AgentDAG.tsx` | 7.3 | React Flow graph rendering the LangGraph pipeline; custom node components with status icons |
| 7.6 | Frontend: WebSocket hook | `frontend/src/lib/use-websocket.ts` | — | React hook for WebSocket connection with reconnect logic; updates Agent DAG nodes in real-time |
| 7.7 | Frontend: Run Metrics panel | `frontend/src/components/pipeline/RunMetrics.tsx` | 7.3 | Duration, token usage, estimated cost, entity counts |
| 7.8 | Frontend: Error Log panel | `frontend/src/components/pipeline/ErrorLog.tsx` | 7.3 | Timestamped error list; expandable details; retry button |
| 7.9 | E2E test: extraction pipeline | `backend/tests/e2e/test_extraction_flow.py` | 6.3, 4.6 | Upload PDF → trigger extraction → verify staging graph created → verify run status transitions |
| 7.10 | Frontend unit tests: pipeline components | `frontend/src/components/pipeline/__tests__/` | 7.4–7.8 | Component rendering, mock WebSocket events, status transitions |

**Phase 2 exit:** Full extraction pipeline working end-to-end. Pipeline Monitor Dashboard shows real-time agent status. Can extract an ontology from a PDF, store it in staging, and monitor progress via UI.

---

## Phase 3: Curation Dashboard, VCR Timeline & Visualizer (Weeks 8–12)

**Goal:** Visual curation, temporal time travel, and ArangoDB Visualizer customization.

### Week 8: Curation Dashboard — Graph Rendering & Actions

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 8.1 | Frontend: Curation page scaffold | `frontend/src/app/curation/[runId]/page.tsx` | 3.7 | Route `/curation/{runId}` with graph viewport and side panels |
| 8.2 | Frontend: Graph Canvas (React Flow or Cytoscape) | `frontend/src/components/graph/GraphCanvas.tsx` | — | Renders ontology graph: nodes = classes (colored by type/tier), edges = relationships; zoom, pan, filter |
| 8.3 | Frontend: Node detail panel | `frontend/src/components/curation/NodeDetail.tsx` | 8.2 | Click node → side panel shows URI, label, description, status, confidence, provenance links |
| 8.4 | Frontend: Node actions (approve/reject/edit/merge) | `frontend/src/components/curation/NodeActions.tsx` | 8.3 | Action buttons; each action calls backend API; UI updates optimistically |
| 8.5 | Frontend: Edge actions (approve/reject/retype) | `frontend/src/components/curation/EdgeActions.tsx` | 8.2 | Right-click or select edge → action panel |
| 8.6 | Frontend: Batch operations | `frontend/src/components/curation/BatchActions.tsx` | 8.2 | Multi-select nodes/edges → bulk approve/reject |
| 8.7 | Curation service (backend) | `backend/app/services/curation.py` | 6.4, 6.5 | `record_decision()` creates `curation_decisions` entry + temporal version; `promote_staging()` moves approved entities |
| 8.8 | Curation API endpoints (full) | `backend/app/api/curation.py` | 8.7 | `POST /decide`, `GET /decisions`, `POST /merge` — all with temporal versioning |
| 8.9 | Promotion service | `backend/app/services/ontology.py` | 8.7, 6.4 | Move approved staging entities to production graph; create temporal versions |

### Week 9: Provenance, Diff View & Confidence

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 9.1 | Provenance display | `frontend/src/components/curation/ProvenancePanel.tsx` | 8.3 | Click node → see source chunks with highlighted text; links to document viewer |
| 9.2 | Confidence score visualization | `frontend/src/components/graph/GraphCanvas.tsx` | 8.2 | Nodes colored/sized by confidence; low-confidence nodes visually highlighted |
| 9.3 | Diff view: staging vs production | `frontend/src/components/curation/DiffView.tsx` | 8.2 | Side-by-side or overlay: new nodes green, removed red, changed yellow |
| 9.4 | Staging promotion workflow UI | `frontend/src/components/curation/PromotePanel.tsx` | 8.9 | Review summary → confirm → one-click promotion; shows what will be promoted |
| 9.5 | Integration tests: curation workflow | `backend/tests/integration/test_curation_workflow.py` | 8.7, 8.8 | Record decision → verify `curation_decisions` entry → verify temporal version created → promote → verify in production graph |
| 9.6 | Frontend component tests: curation | `frontend/src/components/curation/__tests__/` | 8.3–8.6 | Component rendering with mocked API; action click handlers |

### Week 10: Temporal APIs & VCR Timeline

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 10.1 | Point-in-time snapshot API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `GET /ontology/{id}/snapshot?at={ts}` returns full graph state at timestamp |
| 10.2 | Version history API | `backend/app/api/ontology.py`, `backend/app/db/ontology_repo.py` | 6.5 | `GET /ontology/class/{key}/history` returns all versions by URI sorted by `created` DESC |
| 10.3 | Temporal diff API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `GET /ontology/{id}/diff?t1=&t2=` returns added/removed/changed entities |
| 10.4 | Timeline events API | `backend/app/api/ontology.py` | 6.5 | `GET /ontology/{id}/timeline` returns discrete change events for slider tick marks |
| 10.5 | Revert-to-version API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `POST /ontology/class/{key}/revert?to_version={n}` creates new current version restoring historical state |
| 10.6 | Frontend: VCR Timeline slider | `frontend/src/components/timeline/VCRTimeline.tsx` | 10.1, 10.4 | Timeline control with play/pause/rewind/ff; drag to any timestamp; graph re-renders |
| 10.7 | Frontend: Timeline event markers | `frontend/src/components/timeline/VCRTimeline.tsx` | 10.4 | Tick marks on timeline at each version creation; click jumps to that moment |
| 10.8 | Frontend: Diff overlay on graph | `frontend/src/components/graph/DiffOverlay.tsx` | 10.3, 8.2 | Overlay colors: added (green), removed (red), changed (yellow) |
| 10.9 | Frontend: Entity Focus mode | `frontend/src/components/timeline/EntityHistory.tsx` | 10.2 | Select class → vertical timeline showing all versions with diffs between each |
| 10.10 | Integration tests: temporal APIs | `backend/tests/integration/test_temporal_queries.py` | 10.1–10.5 | Create 3 versions → snapshot at each timestamp → diff between t1 and t3 → revert to v1 → verify |
| 10.11 | Frontend tests: VCR timeline | `frontend/src/components/timeline/__tests__/VCRTimeline.test.tsx` | 10.6 | Slider interaction, timestamp display, mock API responses |

### Week 11: ArangoDB Graph Visualizer Customization

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 11.1 | Ontology theme JSON definitions | `docs/visualizer/themes/ontology_theme.json` | — | OWL/RDFS/SKOS node type colors, icons, and edge styles per PRD Section 6.6 |
| 11.2 | Canvas action definitions | `docs/visualizer/actions/ontology_actions.json` | — | All 7 right-click actions from PRD Section 6.6; AQL queries with temporal edge filtering |
| 11.3 | Saved query definitions | `docs/visualizer/queries/ontology_queries.json` | — | All 10 saved queries from PRD Section 6.6 (class hierarchy, orphans, cross-tier, temporal queries) |
| 11.4 | Visualizer install script | `scripts/setup/install_visualizer.py` | 11.1–11.3 | Idempotent installer: creates themes, canvas actions, saved queries, viewpoints per graph; `_demote_builtin_defaults()` sets `isDefault: false` on built-in Default themes so AOE themes take precedence |
| 11.3a | Temporal snapshot saved query | `docs/visualizer/queries/ontology_queries.json` | 11.3 | "Ontology at Point in Time" query with `@snapshot_time` bind var (0 = current); uses `FILTER created <= t AND (expired == NEVER_EXPIRES OR expired > t)`; displays timestamps in ISO 8601 alongside Unix. Also add "Changes Since" query with `@since_time`. |
| 11.4a | Process graph visualizer assets | `docs/visualizer/themes/process_theme.json`, `docs/visualizer/actions/process_actions.json`, `docs/visualizer/queries/process_queries.json` | — | Separate theme/actions/queries for `aoe_process` graph with pipeline-specific node colors and traversal queries |
| 11.5 | Viewpoint auto-creation | `scripts/setup/install_visualizer.py` | 11.4 | `ensure_default_viewpoint()` creates viewpoint per ontology graph; links actions + queries |
| 11.5a | Auto-install visualizer for new ontology graphs | `scripts/setup/install_visualizer.py`, `backend/app/services/extraction.py` | 11.4, 6.6b | After per-ontology graph creation (post-extraction), automatically deploy visualizer theme, canvas actions, saved queries, and viewpoint links so the new graph is immediately explorable in ArangoDB UI |
| 11.6 | Integration tests: visualizer install | `backend/tests/integration/test_visualizer_install.py` | 11.4, 1.13 | Run installer twice → idempotent → verify `_graphThemeStore`, `_canvasActions`, `_editor_saved_queries` populated; verify built-in Default themes demoted |

### Week 12: Integration, Polish & Phase 3 Testing

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 12.1 | Connect curation UI to staging graph | Integration across 8.x and 10.x | W8–W10 | Full flow: see staging graph → make decisions → see temporal versions → scrub timeline |
| 12.2 | Frontend: Ontology Library browser | `frontend/src/app/library/page.tsx`, `frontend/src/components/library/OntologyCard.tsx`, `frontend/src/components/library/ClassHierarchy.tsx` | 3.5, 6.6c | List all registered ontologies; drill into class hierarchy; clicking a class shows inline detail panel with description, URI, confidence, RDF type, properties (with ranges), and links to ArangoDB Graph Visualizer — Platform UI (`/ui/{db}/graphs/{graph}`) with Database UI fallback (`/_db/{db}/_admin/aardvark/index.html#graph/{graph}`) |
| 12.3 | Frontend E2E: curation workflow | `frontend/e2e/curation.spec.ts` | 12.1 | Playwright: open staging → approve class → verify promoted |
| 12.4 | Frontend E2E: VCR timeline | `frontend/e2e/timeline.spec.ts` | 10.6 | Playwright: load ontology → drag slider → verify graph changes |
| 12.5 | Performance check: graph rendering | — | 8.2 | Verify < 2s render for 500-node graph; add lazy loading if needed |
| 12.6 | Phase 3 documentation | `docs/design/curation-dashboard.md` | — | Architecture decisions for graph library choice, temporal UX patterns |

**Phase 3 exit:** Domain expert can visually review, edit, and promote extracted ontologies. VCR timeline works. ArangoDB Visualizer customized. ≥ 80% backend coverage; CI green.

---

## Phase 4: Tier 2, Entity Resolution & Pre-Curation (Weeks 13–16)

### Week 13: Tier 2 Context-Aware Extraction

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 13.1 | Domain ontology context serializer | `backend/app/services/ontology.py` | 6.5 | Serialize domain ontology class hierarchy as compact text for LLM prompt injection |
| 13.2 | Tier 2 prompt templates | `backend/app/extraction/prompts/tier2/` | 4.4 | Prompt includes domain ontology context; instructs LLM to classify as EXISTING/EXTENSION/NEW |
| 13.3 | Extension classification in extraction output | `backend/app/models/ontology.py` | — | `ExtractionClassification` enum already exists; verify extraction agent uses it |
| 13.4 | Cross-tier edge creation | `backend/app/services/ontology.py` | 6.4, 6.5 | `extends_domain` edges created for EXTENSION entities linking local → domain classes |
| 13.5 | Organization ontology selection API | `backend/app/api/ontology.py` | 3.4 | `PUT /orgs/{org_id}` to select base ontologies; extraction uses only selected ontologies as context |
| 13.6 | Conflict detection service | `backend/app/services/ontology.py` | 6.5 | Detects same-URI, contradicting range, hierarchy redefinition per PRD Section 6.3 |

### Week 14: Entity Resolution Integration

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 14.1 | Install `arango-entity-resolution` dependency | `backend/pyproject.toml` | — | Library available for import |
| 14.2 | ER configuration service | `backend/app/services/er.py` | 14.1 | `ERPipelineConfig` configured for ontology fields (label, description, uri); blocking strategy orchestration |
| 14.3 | Topological similarity scoring (AOE-specific) | `backend/app/services/er.py` | 14.2, 6.5 | Graph neighborhood comparison: shared properties, shared parents as scoring dimension |
| 14.4 | ER API endpoints | `backend/app/api/er.py` | 14.2 | All 8 endpoints from PRD Section 7.5: run, status, candidates, clusters, explain, cross-tier, config |
| 14.5 | ER collections creation (migration) | `backend/migrations/009_er_collections.py` | 14.1 | `similarTo`, `entity_clusters`, `golden_records` collections created |
| 14.6 | Integration tests: ER pipeline | `backend/tests/integration/test_er_pipeline.py` | 14.2, 14.5 | Seed 20 ontology classes with near-duplicates → run pipeline → verify candidate pairs → verify clusters |

### Week 15: Pre-Curation Filter & ER LangGraph Agents

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 15.1 | Entity Resolution LangGraph agent | `backend/app/extraction/agents/er_agent.py` | 14.2, 4.2 | Wraps ER pipeline; invoked after consistency checker; produces merge candidates + `extends_domain` edges |
| 15.2 | Pre-Curation Filter agent | `backend/app/extraction/agents/filter.py` | 4.2 | Removes noise (generic terms, duplicates within run); annotates confidence tiers; adds provenance |
| 15.3 | Add ER + filter nodes to LangGraph pipeline | `backend/app/extraction/pipeline.py` | 15.1, 15.2 | Full pipeline: Strategy → Extraction → Consistency → ER → Pre-Curation → Staging |
| 15.4 | Human-in-the-loop breakpoint | `backend/app/extraction/pipeline.py` | 15.3 | Pipeline pauses after pre-curation; emits WebSocket event; resumes after curation decisions |
| 15.5 | Unit tests: ER agent, filter agent | `backend/tests/unit/test_er_agent.py`, `backend/tests/unit/test_filter_agent.py` | 15.1, 15.2 | Mocked ER pipeline; verify filtering removes ≥ 20% noise |

### Week 16: Merge UI & Cross-Tier Dashboard

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 16.1 | Frontend: Merge candidate panel | `frontend/src/components/curation/MergeCandidates.tsx` | 14.4 | Shows candidate pairs with scores, `explain_match` evidence; accept/reject buttons |
| 16.2 | Frontend: Merge execution | `frontend/src/components/curation/MergeExecutor.tsx` | 8.7 | One-click merge; shows before/after; preserves provenance |
| 16.3 | Frontend: Cross-tier visualization | `frontend/src/components/graph/GraphCanvas.tsx` | 8.2 | Domain classes in one color, local extensions in another; `extends_domain` edges visible |
| 16.4 | E2E test: Tier 2 extraction + ER + merge | `backend/tests/e2e/test_tier2_flow.py` | 15.3, 8.7 | Upload org doc → extract with domain context → ER finds duplicates → merge in UI → verify |

**Phase 4 exit:** Tier 2 extraction extends domain ontology. ER detects and suggests merges. Pre-curation reduces review burden by ≥ 20%. Cross-tier visualization works.

---

## Phase 5: MCP Server & Runtime Integration (Weeks 17–19)

### Week 17: Runtime MCP Server Core

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 17.1 | MCP server as standalone process | `backend/app/mcp/server.py` | 3.1 | Runs independently from FastAPI; supports stdio + SSE transports |
| 17.2 | Ontology query tools | `backend/app/mcp/tools/ontology.py` | 3.4, 6.5 | `query_domain_ontology`, `get_class_hierarchy`, `get_class_properties`, `search_similar_classes` |
| 17.3 | Pipeline tools | `backend/app/mcp/tools/pipeline.py` | 4.5 | `trigger_extraction`, `get_extraction_status`, `get_merge_candidates` |
| 17.4 | Temporal tools | `backend/app/mcp/tools/temporal.py` | 6.4 | `get_ontology_snapshot`, `get_class_history`, `get_ontology_diff` |
| 17.5 | Provenance + export tools | `backend/app/mcp/tools/export.py` | 6.5 | `get_provenance`, `export_ontology` |

### Week 18: MCP Resources, ER Integration & Auth

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 18.1 | MCP resources | `backend/app/mcp/resources/` | 17.1 | `aoe://ontology/domain/summary`, `aoe://extraction/runs/recent`, `aoe://system/health` |
| 18.2 | ER MCP tool proxying | `backend/app/mcp/tools/er.py` | 14.2, 17.1 | AOE MCP server proxies calls to `arango-entity-resolution` MCP tools |
| 18.3 | Organization-scoped auth for MCP | `backend/app/mcp/auth.py` | 17.1 | MCP tools filter by `org_id`; API key validation |
| 18.4 | Auto-generate tool schemas from Pydantic | `backend/app/mcp/server.py` | 17.2–17.5 | Tool parameter schemas derived from Pydantic models |

### Week 19: MCP Testing & Documentation

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 19.1 | Integration tests: MCP tools | `backend/tests/integration/test_mcp_tools.py` | 17.2–17.5 | Each MCP tool returns correct data; org isolation enforced |
| 19.2 | MCP server documentation | `docs/mcp-server.md` | 17.1 | Tool catalog, connection instructions for Cursor + Claude Desktop + custom clients |
| 19.3 | E2E test: external agent workflow | `backend/tests/e2e/test_mcp_e2e.py` | 17.1 | Simulated external agent: connect → query ontology → trigger extraction → check status |

**Phase 5 exit:** External AI agents can connect via MCP and query/trigger all ontology operations. Tool schemas auto-generated. Org isolation enforced.

---

## Phase 6: Production Hardening (Weeks 20–24)

### Week 20: Import/Export

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 20.1 | OWL/TTL import service | `backend/app/services/arangordf_bridge.py` | 6.1 | Import via UI or API; creates registry entry; per-ontology named graph; `ontology_id` tagging |
| 20.2 | OWL/TTL/JSON-LD export service | `backend/app/services/export.py` | 6.5 | Export any ontology graph as valid OWL 2 Turtle, JSON-LD, or CSV |
| 20.3 | Import/export API endpoints | `backend/app/api/ontology.py` | 20.1, 20.2 | `POST /import` (file upload), `GET /export?format=ttl` |
| 20.4 | Schema extraction service | `backend/app/services/schema_extraction.py` | — | Wraps `arango-schema-mapper`; connects to external ArangoDB; extracts → OWL → AOE import pipeline |
| 20.5 | Schema extraction API endpoints | `backend/app/api/ontology.py` | 20.4 | `POST /schema/extract`, `GET /schema/extract/{run_id}` |
| 20.6 | Integration tests: import/export roundtrip | `backend/tests/integration/test_import_export.py` | 20.1, 20.2 | Import `aws.ttl` → export as TTL → re-import → verify equivalence |

### Week 21: Authentication & Multi-Tenancy

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 21.1 | Auth middleware (OAuth 2.0 / OIDC) | `backend/app/api/auth.py`, `backend/app/api/dependencies.py` | — | JWT validation; extracts user + org from token; FastAPI dependency |
| 21.2 | RBAC enforcement | `backend/app/api/dependencies.py` | 21.1 | Role-based guards: `admin`, `ontology_engineer`, `domain_expert`, `viewer` |
| 21.3 | Organization/user API endpoints | `backend/app/api/orgs.py` | 21.1 | All 8 endpoints from PRD Section 7.6 |
| 21.4 | `org_id` filter enforcement in repository layer | `backend/app/db/` (all repos) | 21.1 | All tenant-scoped queries filter by `org_id` from auth context |
| 21.5 | Frontend: auth integration | `frontend/src/lib/auth.ts`, `frontend/src/middleware.ts` | 21.1 | Login redirect, token management, role-based UI visibility |

### Week 22: Notifications & Observability

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 22.1 | Notification service | `backend/app/services/notification.py` | — | Writes to `notifications` collection; publishes to Redis Pub/Sub |
| 22.2 | Notification API endpoints | `backend/app/api/notifications.py` | 22.1 | `GET /notifications` (paginated), `POST /notifications/{id}/read`, `GET /notifications/unread-count` |
| 22.3 | WebSocket: curation collaboration | `backend/app/api/ws_curation.py` | 22.1 | `ws://host/ws/curation/{session_id}` broadcasts decision events to all curators |
| 22.4 | Prometheus metrics | `backend/app/api/metrics.py` | — | Request latency, extraction throughput, queue depth, error rates |
| 22.5 | OpenTelemetry tracing | `backend/app/main.py` | — | Spans across ingestion → extraction → storage; trace context propagation |
| 22.6 | Alerting rules | `docs/ops/alerts.yml` | 22.4 | Alert definitions: extraction failure rate > 10%, API error rate > 1%, queue backlog > 100 |

### Week 23: Performance, Rate Limiting & Deployment

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 23.1 | Rate limiting middleware | `backend/app/api/rate_limit.py` | — | Per-org limits per PRD Section 7.8 |
| 23.2 | Response caching (snapshot cache) | `backend/app/services/temporal.py` | — | Materialized snapshot cache for frequently-accessed timestamps |
| 23.3 | Dockerfiles | `backend/Dockerfile`, `frontend/Dockerfile`, `backend/app/mcp/Dockerfile` | — | Multi-stage builds; size targets per PRD Section 8.6 |
| 23.4 | Docker Compose production profile | `docker-compose.prod.yml` | 23.3 | All services + TLS + health checks |
| 23.5 | Kubernetes manifests (optional) | `k8s/` | 23.3 | Deployments, services, ingress, HPA for backend |
| 23.6 | Index tuning based on query profiling | `backend/migrations/010_index_tuning.py` | — | Add any missing indexes identified by AQL profiling |

### Week 24: Documentation, Final Testing & Release

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 24.1 | OpenAPI spec review and finalization | — | All API work | OpenAPI spec matches all implemented endpoints |
| 24.2 | User guide | `docs/user-guide.md` | — | Walkthrough: upload → extract → curate → promote → export |
| 24.3 | Architecture decision records | `docs/adr/` | — | ADRs for: graph library choice, temporal pattern, ER integration, auth approach |
| 24.4 | Full E2E test suite | `backend/tests/e2e/`, `frontend/e2e/` | All | Complete flow: auth → upload → extract → curate → merge → promote → export → MCP query |
| 24.5 | Performance benchmarks | `docs/benchmarks.md` | 23.6 | Document: graph rendering < 2s @ 500 nodes, API p95 < 200ms, extraction < 5min/doc |
| 24.6 | Proxy pattern decision | `docs/adr/temporal-proxy-pattern.md` | — | Measure edge re-creation cost; document decision on whether Phase 6 proxy migration is needed |
| 24.7 | Release v1.0.0 | — | All | Tag, changelog, deployment to production |

**Phase 6 exit:** Production-ready with auth, multi-tenancy, observability, notifications, import/export, and documentation. v1.0.0 tagged and deployed.

---

## Summary: Task Count by Phase

| Phase | Weeks | Tasks | Key Dependencies |
|-------|-------|-------|------------------|
| 1: Foundation | 1–3 | 40 | None (greenfield) |
| 2: Extraction Pipeline | 4–7 | 41 | Phase 1 (schema, ingestion, test infra) |
| 3: Curation & Timeline | 8–12 | 40 | Phase 2 (extraction, staging graphs, temporal service) |
| 4: Tier 2 & ER | 13–16 | 22 | Phase 2 (extraction pipeline) + Phase 3 (curation UI) |
| 5: MCP Server | 17–19 | 14 | Phase 2 (extraction) + Phase 3 (temporal) + Phase 4 (ER) |
| 6: Production | 20–24 | 27 | All prior phases |
| **Total** | **24 weeks** | **184 tasks** | |

## Critical Path

```
Schema (W1) → Ingestion (W2) → LangGraph + Extraction (W4-5) → ArangoRDF + Staging (W6)
    ↓                                                                    ↓
Test Infra (W1) ──────────────────────────────────────────────→ All integration tests
    ↓                                                                    ↓
MCP Dev (W3) ──────────────────────────────────────────────────→ MCP Runtime (W17)
    ↓                                                                    ↓
Upload Page (W3) ─→ Library Page (W12) ←── Per-Ontology APIs (W6)
                                                                         ↓
Extraction → Materialization (W6) → Per-ontology Graph (W6) → Visualizer Auto-Install (W11)
                                                                         ↓
Temporal Service (W6) → Temporal APIs (W10) → VCR Timeline (W10) → Snapshot Cache (W23)
    ↓                       ↓
Curation Service (W8) → Curation UI (W8-9) → ER UI (W16)
    ↓
ArangoRDF Bridge (W6) → Import/Export (W20) → Schema Extraction (W20)
    ↓
ER Integration (W14) → ER Agent (W15) → ER MCP (W18)
```

---

## Addendum: Gap Analysis & Remediation Plan

**Derived from:** System audit conducted 2026-03-27, comparing implemented code against PRD v3.

### Gap Classification

Each gap is classified by severity:
- **BUG**: Code exists but is broken (will error at runtime)
- **UNWIRED**: Code is implemented but not connected to the rest of the system
- **STUB**: Route/function exists but returns placeholder data
- **INCOMPLETE**: Feature partially works but key behavior is missing
- **MISSING**: No implementation exists

---

### Sprint A: Critical Bugs & Wiring Fixes (1 week)

**Status: COMPLETE** (verified in repo, April 2026). The table below is the original audit list, kept for traceability; each item is **done** as described in the verification column.

**Goal (historical):** Fix runtime errors and connect implemented but unwired components.

| # | Gap | Was | Files | Status | Verification |
|---|-----|-----|-------|--------|--------------|
| A.1 | Schema extraction status endpoint broken | BUG | `backend/app/api/ontology.py` | **DONE** | `get_extraction_status` is imported from `schema_extraction`; `GET /schema/extract/{run_id}` delegates to it. |
| A.2 | `expired` field inconsistency in existing DB data | BUG | Migrations + temporal collections | **DONE** | `019_backfill_expired_sentinel.py` backfills `expired == null` (and related) to `NEVER_EXPIRES` across versioned vertices and edges; see also Addendum L (L.23). Sprint C.1 intent absorbed here. |
| A.3 | WebSocket extraction events never published | UNWIRED | `backend/app/services/extraction.py`, `backend/app/api/ws_extraction.py` | **DONE** | `execute_run` defaults `event_callback` to `publish_event` from `ws_extraction` (see `tests/unit/test_pipeline_events.py`). |
| A.4 | Rate limit middleware not registered | UNWIRED | `backend/app/main.py`, `backend/app/api/rate_limit.py` | **DONE** | `RateLimitMiddleware` is added when `settings.rate_limit_enabled` is True. |
| A.5 | VCR Timeline scrubber doesn't update the graph | UNWIRED | `frontend/src/app/curation/[runId]/page.tsx`, `VCRTimeline.tsx` | **DONE** | Curation page passes `onTimestampChange` / snapshot handling so the scrubber drives graph data. |
| A.6 | EntityHistory component not mounted | UNWIRED | `frontend/src/app/curation/[runId]/page.tsx`, `EntityHistory.tsx` | **DONE** | `EntityHistory` is imported and rendered with real handlers (no empty `onShowHistory`). |
| A.7 | DiffOverlay component not imported anywhere | UNWIRED | `frontend/src/components/graph/DiffOverlay.tsx` | **DONE** | Curation page loads `DiffOverlay` (dynamic import) and uses it in diff view mode. |
| A.8 | Frontend auth cookie vs localStorage mismatch | BUG | `frontend/src/middleware.ts`, `frontend/src/lib/auth.ts` | **DONE** | `setToken` writes **both** `localStorage` and cookie `aoe_auth_token` (same name as middleware); `getToken` reads either. |
| A.9 | Login page missing | MISSING | `frontend/src/app/login/page.tsx` | **DONE** | `/login` route exists; middleware allows it in `PUBLIC_PATHS`. |

**Sprint A exit (met):** No remaining A-list runtime gaps. WebSocket pipeline events are published. VCR timeline, history, and diff overlay are wired on curation. Auth cookie + login align with production-mode middleware.

---

### Sprint B: Backend Stubs & Incomplete Endpoints (1 week)

**Goal:** Replace all remaining TODO/placeholder endpoints with real implementations.

| # | Gap | Severity | Files | Fix |
|---|-----|----------|-------|-----|
| B.1 | `GET /ontology/domain` returns empty | STUB | `backend/app/api/ontology.py` | Implement to query all current classes/edges across all ontologies in `domain_ontology` graph, paginated. |
| B.2 | `GET /ontology/domain/classes` returns empty | STUB | `backend/app/api/ontology.py` | Implement with filters (label search, tier, confidence threshold, ontology_id). |
| B.3 | `GET /ontology/local/{org_id}` returns empty | STUB | `backend/app/api/ontology.py` | Query classes/edges where `org_id` matches, including `extends_domain` edges. |
| B.4 | `POST /ontology/staging/{run_id}/promote` is stub | STUB | `backend/app/api/ontology.py` | Wire to `promotion.py` service (real promotion exists at `POST /curation/promote/{run_id}`). Consolidate or redirect. |
| B.5 | Tier 2 pipeline path not wired | INCOMPLETE | `backend/app/services/extraction.py` | `start_run` always uses `tier1_standard`. Add logic: if org has selected domain ontologies, inject `serialize_domain_context()` and use `tier2_standard` prompt. |
| B.6 | `BatchActions` doesn't send `run_id` in body | INCOMPLETE | `frontend/src/components/curation/BatchActions.tsx` | Verify API contract for `POST /curation/batch` and include `run_id` in the request body. |
| B.7 | Curation edge decision doesn't update local graph state | INCOMPLETE | `frontend/src/app/curation/[runId]/page.tsx` | `handleNodeDecision` only updates `graph.classes`; edge approve/reject doesn't update `graph.edges`. Add edge state update handler. |
| B.8 | ER page `allCandidates` never populated | INCOMPLETE | `frontend/src/app/entity-resolution/page.tsx` | `setAllCandidates` is declared but never called. Wire it when loading candidates so merge candidate overlays appear on the graph. |

**Sprint B exit:** All API endpoints return real data. Tier 2 extraction works for organizations with selected domain ontologies.

---

### Sprint C: Temporal Data Integrity & Visualizer Reinstall (3 days)

**Goal:** Ensure temporal data consistency and redeploy visualizer assets.

| # | Gap | Severity | Files | Fix |
|---|-----|----------|-------|-----|
| C.1 | Backfill `expired: null` → `NEVER_EXPIRES` in DB | BUG | New: `backend/migrations/012_backfill_expired_sentinel.py` | AQL update on `ontology_classes`, `ontology_properties`, and all edge collections to set `expired = 9223372036854775807` where `expired == null OR expired == 0`. |
| C.2 | Re-run MDI index migration with corrected `prefixFields` | BUG | `backend/migrations/005_mdi_indexes.py` | Drop existing `idx_*_mdi_temporal` indexes (which had wrong `prefixFields: ["created"]`) and re-create with `prefixFields: ["ontology_id"]`. Add migration `013_reindex_mdi.py`. |
| C.3 | Redeploy visualizer saved queries | — | `scripts/setup/install_visualizer.py` | Re-run installer to deploy updated queries (sentinel values, `ontology_at_time`, `ontology_changes_since`) and actions. |
| C.4 | Verify `has_chunk` and `produced_by` edges populated | INCOMPLETE | `backend/app/services/extraction.py` | `_materialize_to_graph` creates `extracted_from` edges but does not create `has_chunk` (documents→chunks) or `produced_by` (ontology_registry→extraction_runs) edges. Add these to complete the `aoe_process` graph lineage. |

**Sprint C exit:** All temporal data uses sentinel consistently. MDI indexes correct. Process graph fully populated.

---

### Sprint D: Test Coverage & CI Hardening (1 week)

**Goal:** Reach ≥80% coverage across all layers. Add missing tests and CI stages.

| # | Gap | Severity | Files | Fix |
|---|-----|----------|-------|-----|
| D.1 | E2E tests not in CI | INCOMPLETE | `.github/workflows/ci.yml` | Add `test-e2e` job running `pytest tests/e2e/` with full infra (ArangoDB + Redis). |
| D.2 | Frontend tests not in CI | MISSING | `.github/workflows/ci.yml` | Add `test-frontend` job: `npm test` (Jest) and optionally `npx playwright test` for E2E. |
| D.3 | Missing component tests | MISSING | `frontend/src/components/` | No tests for: `GraphCanvas`, `ClassHierarchy`, `ErrorLog`, `EntityHistory`, `DiffOverlay`. Create basic render + interaction tests. |
| D.4 | `.env.example` incomplete | INCOMPLETE | `.env.example` | Add missing settings: `OPENAI_BASE_URL`, `RATE_LIMIT_ENABLED`, `NEXT_PUBLIC_ARANGO_URL`, `NEXT_PUBLIC_ARANGO_DB`. |
| D.5 | Root `AGENTS.md` missing | MISSING | `AGENTS.md` | Create top-level `AGENTS.md` describing repo structure, module boundaries, and development conventions. |

**Sprint D exit:** CI runs all test types. Coverage ≥80%. Environment template complete.

---

### Sprint E: Production Polish (1 week)

**Goal:** Final production-readiness items from Phase 6.

| # | Gap | Severity | Files | Fix |
|---|-----|----------|-------|-----|
| E.1 | OpenTelemetry tracing not implemented | MISSING | `backend/app/main.py` | PRD §8.5 requires spans across ingestion → extraction → storage. Add `opentelemetry-api` + `opentelemetry-sdk` and instrument key services. |
| E.2 | Alerting rules not defined | MISSING | `docs/ops/alerts.yml` | PRD §8.5 requires alert definitions for extraction failure rate, API error rate, queue backlog. |
| E.3 | Temporal `ttlExpireAt` not set on historical versions | INCOMPLETE | `backend/app/services/temporal.py` | `expire_entity` sets `expired` but verify `ttlExpireAt` is set for garbage collection. |
| E.4 | Visualizer auto-install post-extraction | INCOMPLETE | `backend/app/services/extraction.py` | After `ensure_ontology_graph()`, call `install_for_ontology_graph()` to deploy theme/actions/queries for the new per-ontology graph automatically. |
| E.5 | Performance benchmarks not measured | MISSING | `docs/benchmarks.md` | File exists but likely placeholder. Run actual benchmarks: graph rendering, API p95, extraction time per doc. |

**Sprint E exit:** Observability, alerting, auto-deploy of visualizer assets, and performance validation complete.

---

### Sprint F: Ontology Quality Metrics (1.5 weeks)

**Goal:** Implement the ontology quality metrics system referenced in PRD §3.2 (Success Metrics), FR-4.8 (Confidence scores), and FR-12.4 (Per-run metrics). Currently **zero** quality metrics are computed, tracked, or displayed — only pipeline run metrics (token count, cost, duration) exist.

**PRD Gap Analysis:**

| PRD Metric | Target | Current Status |
|------------|--------|----------------|
| Extraction precision (acceptance rate) | ≥ 80% classes accepted without edits | **MISSING** — curation decisions are recorded but never aggregated |
| Extraction recall | ≥ 70% of gold-standard concepts found | **MISSING** — no gold-standard comparison mechanism |
| Curation throughput | 50+ concepts/hour | **MISSING** — no time tracking in curation UI |
| Deduplication accuracy | ≥ 85% merge suggestions correct | **MISSING** — merge accept/reject decisions not aggregated |
| Time to first ontology | < 30 minutes | **MISSING** — no end-to-end pipeline timing |
| Ontology structural quality | Not explicitly numeric in PRD, but implied | **MISSING** — no orphan detection, cycle detection, or completeness analysis |

#### Sub-sprint F1: Backend Quality Metrics Service (4 days)

| # | Task | Files | Fix |
|---|------|-------|-----|
| F1.1 | Extraction precision computation | `backend/app/services/quality_metrics.py` (new) | Query `curation_decisions` collection. Compute `acceptance_rate = accepted / (accepted + rejected + edited)` per ontology and per run. Count "accepted without edits" vs "accepted with edits" vs "rejected". |
| F1.2 | Curation throughput tracking | `backend/app/services/curation.py`, `backend/app/db/curation_repo.py` | Add `decided_at` timestamp to each `curation_decision`. Compute `concepts_per_hour = count(decisions) / (max(decided_at) - min(decided_at)) * 3600` per curator session. |
| F1.3 | Deduplication accuracy | `backend/app/services/quality_metrics.py` | Query ER merge decisions (accepted/rejected merge suggestions). Compute `dedup_accuracy = accepted_merges / total_merge_suggestions`. |
| F1.4 | Time-to-first-ontology | `backend/app/services/quality_metrics.py` | Compute `time_to_ontology = extraction_run.completed_at - document.uploaded_at` using `documents` and `extraction_runs` collections. |
| F1.5 | Ontology structural quality analysis | `backend/app/services/quality_metrics.py` | Compute per-ontology: (a) **Completeness** — % of classes with ≥1 property, % of properties with defined domain+range; (b) **Coherence** — detect subclass cycles via AQL traversal, count orphan classes (no parent, not a root); (c) **Avg confidence** — mean confidence score across all current classes; (d) **Coverage** — classes-per-chunk ratio vs source document chunk count. |
| F1.6 | Gold-standard recall comparison | `backend/app/services/quality_metrics.py` | Import a reference OWL ontology, extract class labels, compute `recall = |extracted ∩ reference| / |reference|` using fuzzy string matching. Expose as `POST /api/v1/quality/recall` with uploaded reference file. |
| F1.7 | Quality metrics API endpoints | `backend/app/api/quality.py` | `GET /api/v1/quality/{ontology_id}` returns merged ontology + extraction quality. `GET /api/v1/quality/dashboard` returns scorecards, aggregate `summary`, and alerts (supersedes removed `/quality/summary`). `GET .../evaluation`, `GET .../class-scores` implemented. `GET .../history` and `POST .../recall` specified in PRD but not implemented yet. |

#### Sub-sprint F2: Frontend Quality Dashboard (4 days)

| # | Task | Files | Fix |
|---|------|-------|-----|
| F2.1 | Quality metrics types | `frontend/src/types/quality.ts` (new) | TypeScript interfaces for `OntologyQualityMetrics` (acceptance_rate, avg_confidence, completeness, coherence_issues, coverage, dedup_accuracy, time_to_ontology), `QualityHistory`, `QualitySummary`. |
| F2.2 | Quality dashboard page | `frontend/src/app/dashboard/page.tsx` | Unified `/dashboard` route; `/quality` redirects to `?tab=per-ontology-quality`. Tabs: library-wide dashboard (summary, score table, detail radar) and **Per-Ontology Quality** (`PerOntologyQualityReport.tsx`) using live `GET /quality/{id}`. Flags/alerts; qualitative evaluation in detail view. |
| F2.3 | Per-ontology quality panel in Library | `frontend/src/app/library/page.tsx` | Add a "Quality" tab or section to the inline detail panel when an ontology is selected. Show acceptance rate, avg confidence, completeness %, coherence issues, structural warnings (orphans, cycles). |
| F2.4 | Curation session timer | `frontend/src/app/curation/[runId]/page.tsx` | Add session start timestamp on page load. On each curation decision, compute elapsed time and send to backend. Display "concepts reviewed / hour" counter in the curation UI header. |
| F2.5 | Low-confidence highlighting in curation graph | `frontend/src/components/graph/GraphCanvas.tsx` | FR-4.8 requires low-confidence entities to be visually highlighted. Add conditional node styling: red border for confidence < 0.5, yellow for 0.5–0.7, green for > 0.7. |
| F2.6 | Quality metrics in landing page | `frontend/src/app/page.tsx` | Add a "System Health" section showing aggregate extraction precision, active ontology count, and average quality score. |
| F2.7 | Quality section in pipeline run detail | `frontend/src/components/pipeline/RunMetrics.tsx` | Extend the existing RunMetrics component to include per-run quality stats: acceptance rate (if curation has started), avg confidence of extracted entities, completeness %. |

#### Sub-sprint F3: Visualizer Quality Queries (2 days)

| # | Task | Files | Fix |
|---|------|-------|-----|
| F3.1 | Low-confidence classes query | `docs/visualizer/queries/ontology_queries.json` | Add saved AQL query: "Low Confidence Classes" — returns classes where `confidence < @threshold` (default 0.6). Color-coded by confidence band in the visualizer. |
| F3.2 | Orphan classes query | `docs/visualizer/queries/ontology_queries.json` | Add saved AQL query: "Orphan Classes" — classes with no inbound `subclass_of` edge and no outbound `subclass_of` edge (isolated nodes). |
| F3.3 | Incomplete classes query | `docs/visualizer/queries/ontology_queries.json` | Add saved AQL query: "Classes Without Properties" — classes with zero `has_property` outbound edges. |
| F3.4 | Redeploy visualizer queries | `scripts/setup/install_visualizer.py` | Re-run installer to deploy new quality-oriented queries. |

**Sprint F exit:** All five PRD §3.2 success metrics are computed and displayed. Ontology structural quality is analyzed and visible in both the custom UI and ArangoDB Visualizer. Low-confidence entities are highlighted in the curation graph. Quality trends are tracked over time.

---

### Sprint G: Multi-Document Ontologies & Incremental Extraction (1.5 weeks)

**Goal:** Support building ontologies from multiple documents and adding documents to existing ontologies.

| # | Task | Files | Description |
|---|------|-------|-------------|
| G.1 | Extend extraction API for multi-doc and target ontology | `backend/app/api/extraction.py`, `backend/app/models/extraction.py` | `StartRunRequest` accepts `doc_ids: list[str]` (optional) and `target_ontology_id: str` (optional). When `target_ontology_id` is set, extraction uses existing ontology as context (like Tier 2) and merges results into it instead of creating a new ontology. |
| G.2 | Multi-document chunk batching in extraction service | `backend/app/services/extraction.py` | `start_run` loads chunks from all `doc_ids`, concatenates them, and passes to the pipeline. All materialized classes get the same `ontology_id`. Multiple `extracted_from` edges created (one per source doc). |
| G.3 | Incremental extraction service | `backend/app/services/extraction.py` | When `target_ontology_id` is set: (a) serialize existing ontology classes as context, (b) run extraction, (c) Consistency Checker compares against existing classes, (d) new classes tagged as EXISTING/EXTENSION/NEW, (e) results go to staging for curation. |
| G.4 | "Add Document" API endpoint | `backend/app/api/ontology.py` | `POST /library/{ontology_id}/add-document` accepts a file upload, creates a document, and triggers incremental extraction targeting the specified ontology. |
| G.5 | "Add Document" button in Library UI | `frontend/src/app/library/page.tsx` | When an ontology is selected, show an "Add Document" button that opens a file picker and calls the add-document endpoint. Shows extraction progress. |
| G.6 | Target ontology selector in Upload page | `frontend/src/app/upload/page.tsx` | Add a searchable dropdown: "Create New Ontology" (default) or select an existing ontology from the library. When existing is selected, extraction targets that ontology. |
| G.7 | Document-ontology relationship API | `backend/app/api/ontology.py`, `backend/app/api/documents.py` | `GET /ontology/library/{id}/documents` lists source documents. `GET /documents/{id}/ontologies` lists ontologies extracted from a document. |
| G.8 | Document list on ontology detail | `frontend/src/app/library/page.tsx` | When viewing an ontology, show list of source documents with links to each. |

**Sprint G exit:** Users can build ontologies from multiple documents and incrementally add new documents to existing ontologies.

---

### Sprint H: Ontology Imports & Dependency Management (1.5 weeks)

**Goal:** Represent, track, and visualize `owl:imports` relationships. Enable loading standard ontologies.

| # | Task | Files | Description |
|---|------|-------|-------------|
| H.1 | Imports edge creation on OWL import | `backend/app/services/arangordf_bridge.py` | After PGT import, parse the source graph for `owl:imports` triples. For each imported IRI, look up the matching `ontology_registry` entry and create an `imports` edge. Warn if imported ontology not in library. |
| H.2 | Imports graph named graph | `backend/migrations/014_imports_graph.py` (new) | Create `ontology_imports` named graph with `ontology_registry` as vertex collection and `imports` as edge collection. |
| H.3 | Imports API endpoints | `backend/app/api/ontology.py` | `GET /library/{id}/imports`, `GET /library/{id}/imported-by`, `GET /imports-graph`. |
| H.4 | Cascade analysis on delete | `backend/app/services/ontology_graphs.py` | Before deprecating an ontology, traverse `imports` graph to find dependents. Return list of affected ontologies. Frontend shows confirmation dialog. |
| H.5 | Standard ontology catalog | `backend/app/services/ontology_catalog.py` (new), `docs/catalog/` | JSON catalog of standard ontologies (FIBO modules, Schema.org, Dublin Core, FOAF, PROV-O, SKOS, OWL-Time, GeoSPARQL) with URLs, descriptions, class counts. API: `GET /ontology/catalog`, `POST /ontology/catalog/{id}/import`. |
| H.6 | Catalog import UI | `frontend/src/app/upload/page.tsx` or `frontend/src/app/library/page.tsx` | "Import Standard Ontology" button opening a catalog browser. One-click import with progress indicator. |
| H.7 | Imports dependency graph in Library UI | `frontend/src/app/library/page.tsx` | New "Dependencies" tab showing a React Flow DAG of ontology imports. Click a node to navigate to that ontology. |
| H.8 | Base ontology selector in extraction UI | `frontend/src/app/upload/page.tsx` | Searchable "Base Ontologies" multi-select. Selected ontologies are sent as `base_ontology_ids` in the extraction request. Backend injects their classes as context and records `imports` edges on the result. |
| H.9 | Visualizer queries for imports | `docs/visualizer/queries/ontology_queries.json` | Saved AQL queries: "Ontology Dependencies" (traversal of imports graph), "Upstream Ontologies" (ancestors), "Downstream Dependents" (children). |

**Sprint H exit:** `owl:imports` tracked as edges. Standard ontologies importable from catalog. Imports dependency graph visible in UI and ArangoDB Visualizer.

---

### Sprint I: Ontology Constraints (OWL Restrictions & SHACL) (1 week)

**Goal:** Extract, import, store, display, and export OWL restrictions and SHACL shapes.

| # | Task | Files | Description |
|---|------|-------|-------------|
| I.1 | Constraint extraction prompts | `backend/app/extraction/prompts/` | Extend extraction prompts to ask LLM for constraints: "For each class, identify cardinality constraints, value restrictions, and data validation rules." Add `constraints` field to `ExtractedClass` Pydantic model. |
| I.2 | Constraint materialization | `backend/app/services/extraction.py` | `_materialize_to_graph` writes extracted constraints to `ontology_constraints` collection with temporal fields. |
| I.3 | OWL restriction import via ArangoRDF | `backend/app/services/arangordf_bridge.py` | After PGT import, parse `owl:Restriction` blank nodes from the source rdflib graph. Create `ontology_constraints` documents linked to their target class and property. |
| I.4 | SHACL shapes import | `backend/app/services/shacl_import.py` (new) | Parse SHACL shapes graphs (Turtle files). Create `ontology_constraints` documents with `constraint_type: "sh:NodeShape"` or `"sh:PropertyShape"`. Link to target classes via `target_class`. |
| I.5 | Constraints API endpoint | `backend/app/api/ontology.py` | `GET /library/{ontology_id}/constraints` returns all OWL restrictions and SHACL shapes for an ontology. |
| I.6 | Constraints display in Library UI | `frontend/src/app/library/page.tsx` | Class detail panel shows associated constraints: cardinality badges (e.g., "1..* holders"), value restrictions (e.g., "allValuesFrom: Currency"), SHACL rules with severity icons. |
| I.7 | Constraints display in Curation UI | `frontend/src/app/curation/[runId]/page.tsx` | NodeDetail shows constraints alongside properties. Curators can approve/reject/edit constraints. |
| I.8 | Constraints in OWL export | `backend/app/services/export.py` | OWL Turtle export includes `owl:Restriction` constructs. New `export_shacl()` function exports SHACL shapes as a separate shapes graph. |
| I.9 | Constraints in temporal queries | `backend/app/services/temporal.py` | `get_snapshot` and `get_diff` include constraints from `ontology_constraints` collection. |

**Sprint I exit:** Constraints extractable, importable, displayable, and exportable. SHACL shapes stored alongside OWL restrictions.

---

### Sprint J: Full CRUD, Search & Library Organization (1 week)

**Goal:** Complete document and ontology lifecycle operations. Full-text search. Hierarchical library organization.

| # | Task | Files | Description |
|---|------|-------|-------------|
| J.1 | Document re-upload (update) | `backend/app/api/documents.py`, `backend/app/db/documents_repo.py` | `PUT /documents/{doc_id}` soft-deletes old version, creates new document linked to the same `ontology_id`s. Triggers re-extraction warning if auto-extract enabled. |
| J.2 | Document hard-delete with cascade analysis | `backend/app/api/documents.py` | `DELETE /documents/{doc_id}` shows affected ontologies (via `extracted_from` edges). Soft-deletes document and chunks. Expires `extracted_from` edges. Does NOT delete ontology classes. |
| J.3 | Ontology metadata update | `backend/app/api/ontology.py` | `PUT /ontology/library/{id}` updates name, description, tags, tier, status. |
| J.4 | Ontology deprecation with cascade | `backend/app/api/ontology.py`, `backend/app/services/ontology_graphs.py` | `DELETE /ontology/library/{id}` performs cascade analysis (imports graph traversal), returns affected list, requires confirmation. On confirm: expires all classes/properties/edges, removes per-ontology graph, marks registry as `deprecated`. |
| J.5 | ArangoSearch view for library search | `backend/migrations/015_library_search.py` (new) | Create ArangoSearch view across `ontology_registry` (name, description), `ontology_classes` (label, description), `ontology_properties` (label). |
| J.6 | Library search API | `backend/app/api/ontology.py` | `GET /ontology/search?q=...` performs full-text search via ArangoSearch. Returns ranked results with snippets and source ontology info. |
| J.7 | Library search UI | `frontend/src/app/library/page.tsx` | Search bar at top of library page. Debounced input calls search API. Results grouped by ontology. |
| J.8 | Hierarchical library view | `frontend/src/app/library/page.tsx` | Toggle between flat list and hierarchy view. Hierarchy uses `imports` graph: domain ontologies as top-level, local extensions nested under their parents. |
| J.9 | Ontology tagging | `backend/app/db/registry_repo.py`, `frontend/src/app/library/page.tsx` | Add `tags: list[str]` to registry. UI shows tag chips; filterable by tag. |

**Sprint J exit:** Full document and ontology lifecycle management. Full-text search across the library. Hierarchical organization via imports graph.

---

### Sprint K: Standalone Ontology Graph Editor (1.5 weeks)

**Goal:** Provide a full ontology graph editor accessible from the library — not just the per-extraction-run staging curation page. This is the core PRD §6.4 feature that allows ongoing ontology management, manual class creation, and visual editing outside of extraction workflows.

**Current State:**
- `/curation/[runId]` exists with `GraphCanvas`, `NodeDetail`, `NodeActions`, `EdgeActions`, `BatchActions`, `ProvenancePanel`, `DiffView`, `PromotePanel`, `VCRTimeline`, `EntityHistory`, `DiffOverlay` — Sprint A wiring complete; see Sprint A verification table.
- **There is no way to open an ontology graph editor from the library page.** The library shows a class hierarchy tree with inline detail, but no interactive graph view or editing capability outside of extraction run staging.
- The PRD explicitly says the curation dashboard should work in both "Staging mode" (per run) and "Ontology mode" (per ontology) — the latter does not exist.

| # | Task | Files | Description |
|---|------|-------|-------------|
| K.1 | Ontology editor page scaffold | `frontend/src/app/ontology/[ontologyId]/edit/page.tsx` (new) | New route `/ontology/[ontologyId]/edit`. Loads all current classes, properties, and edges for the ontology via existing API endpoints. Renders the same `GraphCanvas` and side panel as the curation page, but fed from ontology data instead of staging data. |
| K.2 | Shared curation/editor layout component | `frontend/src/components/graph/OntologyEditor.tsx` (new) | Extract the shared layout (graph viewport + side panel + toolbar) from the curation page into a reusable component. Both `/curation/[runId]` and `/ontology/[ontologyId]/edit` use this component with different data sources. |
| K.3 | Backend: create class endpoint | `backend/app/api/ontology.py` | `POST /ontology/{ontology_id}/classes` creates a new class with `source_type: "manual"`, temporal versioning (`created: now, expired: NEVER_EXPIRES`). Returns the created class. |
| K.4 | Backend: create property endpoint | `backend/app/api/ontology.py` | `POST /ontology/{ontology_id}/properties` creates a new property, plus a `has_property` edge from the domain class. |
| K.5 | Backend: create/update edge endpoint | `backend/app/api/ontology.py` | `POST /ontology/{ontology_id}/edges` creates a new edge (subclass_of, related_to, etc.) with temporal versioning. `PUT` to update (expires old, creates new). |
| K.6 | Backend: update class/property endpoint | `backend/app/api/ontology.py` | `PUT /ontology/{ontology_id}/classes/{key}` updates class fields. Uses `temporal.update_entity` to expire old version and create new. `PUT .../properties/{key}` analogous. |
| K.7 | Frontend: Add class dialog | `frontend/src/components/graph/AddClassDialog.tsx` (new) | Modal dialog for adding a new class: label, URI, description, parent class (optional select), properties (dynamic list). Calls create endpoints. |
| K.8 | Frontend: Add property dialog | `frontend/src/components/graph/AddPropertyDialog.tsx` (new) | Modal for adding a property to a selected class: label, range type, description. |
| K.9 | Frontend: Drag-and-drop reparenting | `frontend/src/components/graph/GraphCanvas.tsx` | On drag of a class node onto another, show drop indicator. On drop, call edge create/update endpoint to create `subclass_of` edge. Visual feedback for valid drop targets. |
| K.10 | Frontend: Inline class rename | `frontend/src/components/graph/GraphCanvas.tsx`, `frontend/src/components/curation/NodeDetail.tsx` | Double-click a node label to edit it inline. Calls update endpoint on blur/enter. |
| K.11 | Library-to-editor navigation | `frontend/src/app/library/page.tsx` | Add "Edit Graph" button on ontology cards and in the class detail panel. Links to `/ontology/{ontologyId}/edit`. When clicking a class in the hierarchy, optionally open editor focused on that class. |
| K.12 | Editor toolbar | `frontend/src/app/ontology/[ontologyId]/edit/page.tsx` | Top toolbar with: "Add Class", "Add Property", "Add Edge", color mode toggle (confidence/status/type), VCR Timeline toggle, export button, link to ArangoDB Visualizer. |

**Sprint K exit:** Users can open any ontology from the library in a full interactive graph editor. They can visually explore the graph, add/edit/delete classes and properties, reparent classes via drag-and-drop, view the VCR timeline, and navigate back to the library. This is the core visual curation experience described in PRD §6.4.

---

### Remediation Summary

Original phased backlog (historical sizing). **Current completion** matches the **Remaining Work Priority (Updated March 31, 2026)** table later in this document — A, C, K, B, G, J are **done**; F is **mostly done**; primary open tracks are **PGT**, H, ER, quality history, I, S, D, E, V.

| Sprint | Duration | Tasks | Priority |
|--------|----------|-------|----------|
| ~~A: Critical Bugs & Wiring~~ | ~~1 week~~ | ~~9~~ | **DONE** — see Sprint A verification table |
| ~~B: Backend Stubs~~ | ~~1 week~~ | ~~8~~ | **DONE** |
| ~~C: Data Integrity & Reindex~~ | ~~3 days~~ | ~~4~~ | **DONE** (backfill: `019`; MDI: `005` / L.25; residual: C.4 lineage if needed) |
| D: Test Coverage & CI | 1 week | 5 | **P2** — quality gate before release |
| E: Production Polish | 1 week | 5 | **P2** — required for v1.0.0 |
| F: Ontology Quality Metrics | 1.5 weeks | 18 | **MOSTLY DONE** — dashboard + live per-ontology radar; history / recall pending |
| ~~G: Multi-Document & Incremental Extraction~~ | ~~1.5 weeks~~ | ~~8~~ | **DONE** |
| H: Ontology Imports & Dependencies | 1.5 weeks | 9 | **P1** — `owl:imports`, standard ontology catalog |
| I: Constraints (OWL + SHACL) | 1 week | 9 | **P2** — formal constraints support |
| ~~J: Full CRUD, Search & Library Organization~~ | ~~1 week~~ | ~~9~~ | **DONE** |
| ~~K: Standalone Ontology Graph Editor~~ | ~~1.5 weeks~~ | ~~12~~ | **DONE** |
| **Total (original plan)** | **~12 weeks** | **96 tasks** | |

### Recommended Execution Order

```
Sprint C (data integrity)  ─┐
                             ├─→ ~~Sprint A~~ (complete) ─┬─→ ~~Sprint K~~ (ontology editor — done)
                             │                            │
                             └─ C.1–C.3 parallel with A  └─→ ~~Sprint B~~ (stubs — largely done) ─┬─→ ~~Sprint G~~ (multi-doc — done) ─→ Sprint H (imports) ─→ Sprint I (constraints)
                                                                                  │
                                                                                  ├─→ Sprint F (quality metrics)
                                                                                  │
                                                                                  └─→ Sprint J (CRUD, search) ─→ Sprint D (tests) ─→ Sprint E (polish)
```

- Sprint A and K are **complete** in the current codebase; new work should branch from **`object-centric-ux` / Sprint PGT** (schema alignment) unless you are picking up imports (H), ER, or quality history.
- Sprint C backfill/reindex items are **largely done** (migration `019`, MDI fixes in `005` per Addendum L); treat C.4 (`has_chunk` / `produced_by` lineage) and visualizer redeploy as the remaining C-class follow-ups if still open.
- Sprint H (imports) builds on multi-doc and library behavior already shipped (**G** / **J** done); catalog + `owl:imports` graph remain the gap.
- Sprint I (constraints) can follow H, leveraging the import pipeline for OWL restriction parsing.
- Sprint D (tests) and E (polish) remain final gates before a tagged release.

---

### Addendum L: Pipeline Enrichment, System Reset, Auto-Extraction & UI Fixes

**Status: IMPLEMENTED**

#### L-I: Pipeline Enrichment & System Administration (PRD §7.2, §7.2.1)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.1 | Enrich extraction run list API | `backend/app/api/extraction.py` | DONE | `GET /extraction/runs` now joins against `documents` for `document_name` and `chunk_count`, queries `ontology_classes`/`ontology_properties` for live entity counts, and computes `duration_ms`, `error_count`, and includes `model`. |
| L.2 | Delete extraction run API | `backend/app/api/extraction.py` | DONE | `DELETE /extraction/runs/{run_id}` removes the run document and its `results_*` document. Does not cascade to ontology data. |
| L.3 | Admin reset endpoints | `backend/app/api/admin.py`, `backend/app/main.py` | DONE | `POST /admin/reset` truncates all ontology/extraction collections while preserving documents and chunks. `POST /admin/reset/full` purges everything. Both gated by `ALLOW_SYSTEM_RESET=true` env var. |
| L.4 | Enriched RunList UI | `frontend/src/components/pipeline/RunList.tsx`, `frontend/src/types/pipeline.ts` | DONE | Run cards show document name (primary), chunk count, classes extracted, properties extracted, error count, duration, and model. Delete button appears on hover with confirmation. |
| L.5 | Reset UI | `frontend/src/app/pipeline/page.tsx` | DONE | Click-based "Reset" dropdown in Pipeline Monitor header with two options: soft reset (keeps docs) and full reset. Confirms before executing. Re-fetches run list after reset. |
| L.6 | PRD updates | `PRD.md` | DONE | Added `DELETE /extraction/runs/{run_id}`, enriched `GET /extraction/runs` description, and new Section 7.2.1 (Admin endpoints). |

#### L-II: Auto-Extraction on Upload (PRD §6.1 FR-1.6, §6.11)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.7 | Auto-trigger extraction after upload | `frontend/src/app/upload/page.tsx` | DONE | After successful document upload (parse + chunk), the UI automatically triggers `POST /api/v1/extraction/run` with the new `doc_id`. Three-phase UX: "Uploading…" → "Starting extraction…" → "Success — extraction started" with links to Pipeline Monitor and Library. |
| L.8 | "Extract" button on documents | `frontend/src/app/upload/page.tsx` | DONE | Each document with `ready` status in the Recent Documents list displays an "Extract" button. Clicking it triggers extraction and redirects to Pipeline Monitor. Enables re-extraction after a soft reset without re-uploading. |

#### L-III: Curation Graph & Pipeline Visualization Fixes (PRD §6.4, §6.12)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.9 | Graph layout fix (hierarchy edges only) | `frontend/src/components/graph/GraphCanvas.tsx` | DONE | `computeLayout` now filters edges to `HIERARCHY_EDGE_TYPES` (`subclass_of`, `extends_domain`, `related_to`) for positioning. Non-class edges (`has_property`, `extracted_from`) excluded from class graph rendering. Parent nodes centered over children. |
| L.10 | NodeDetail crash fix | `frontend/src/components/curation/NodeDetail.tsx` | DONE | Added `(node.status ?? "pending")` fallback. Fixed Unix timestamp rendering (multiply by 1000). Hidden `Expired` row when value is `NEVER_EXPIRES` sentinel. |
| L.11 | REST fallback for pipeline steps | `frontend/src/lib/use-websocket.ts` | DONE | Added `fetchStepsFromRest()` to fetch `step_logs` from `GET /extraction/runs/{runId}` as fallback when WebSocket is unavailable. `BACKEND_TO_FRONTEND_STEP` mapping aligns backend step names (`extractor`, `er_agent`) to frontend `PIPELINE_STEPS`. |
| L.12 | Empty curation state | `frontend/src/app/curation/[runId]/page.tsx` | DONE | When no ontology data exists for a run, shows clear "No ontology data for this run" message with links to Pipeline and Library. All action buttons disabled when `!hasData`. |
| L.13 | RunList timestamp fix | `frontend/src/components/pipeline/RunList.tsx` | DONE | `formatRelativeTime` handles both Unix timestamps (number) and ISO strings. Uses `run.started_at` with fallback to `run.created_at`. |

#### L-IV: Library & Ontology Card UX (PRD §6.8 FR-8.3, §6.4 FR-4.13)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.14 | OntologyCard click affordance | `frontend/src/components/library/OntologyCard.tsx` | DONE | Added `cursor-pointer`, `hover:border-blue-300`, `title="Click to explore class hierarchy"`. "Click to explore →" hint on hover. |
| L.15 | Curate Ontology button in library | `frontend/src/app/library/page.tsx` | DONE | Replaced "Open in Platform UI" and "Open in DB UI" links (which required separate login) with a "Curate Ontology" button linking to `/curation/{extraction_run_id}`. |
| L.16 | Export dropdown in library | `frontend/src/app/library/page.tsx` | DONE | Added "Export ▾" dropdown with OWL/Turtle, JSON-LD, and CSV options. Links to backend `/api/v1/ontology/{ontology_id}/export?format=`. |
| L.17 | Class detail "View in Curation" | `frontend/src/app/library/page.tsx` | DONE | Replaced external visualizer links in class detail panel with "View in Curation Dashboard" link focused on the selected class. |

#### L-V: Per-Ontology Graphs & Visualizer Customization (PRD §6.2 FR-2.10, FR-2.11, §6.6)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.18 | Per-ontology graph creation | `backend/app/services/ontology_graphs.py` | DONE | Auto-creates `ontology_{name_slug}` named graph after extraction with human-readable name. |
| L.19 | Process graph (`aoe_process`) | `backend/migrations/010_process_graph.py` | DONE | Named graph connecting `documents` → `chunks` → `ontology_classes` → `ontology_properties` → `extraction_runs` with provenance edges. |
| L.20 | Visualizer auto-install | `scripts/setup/install_visualizer.py` | DONE | Idempotent installer deploys themes, canvas actions, saved queries, and viewpoints for both per-ontology graphs and `aoe_process`. Preserves ArangoDB default theme. Prunes theme to actual graph collections. |
| L.21 | Removed `all_ontologies` graph | `backend/app/services/ontology_graphs.py`, `backend/migrations/011_all_ontologies_graph.py` | DONE | `domain_ontology` serves as the composite graph. `all_ontologies` was redundant and removed. |
| L.22 | Human-readable graph names | `backend/app/services/ontology_graphs.py` | DONE | Ontology graph names derived from registry `name` field (e.g., "Financial Services Domain" → `ontology_financial_services_domain`). |

#### L-VI: Temporal Data & Index Fixes (PRD §5.3)

| ID | Task | Files | Status | Description |
|----|------|-------|--------|-------------|
| L.23 | `expired` field sentinel backfill | Manual AQL | DONE | Backfilled 169 documents across `ontology_classes`, `ontology_properties`, `subclass_of`, `has_property`, `extracted_from` from `null` to `NEVER_EXPIRES` (9223372036854775807). |
| L.24 | AQL double-brace syntax fix | `backend/app/api/ontology.py` | DONE | Corrected `{{edge_type: @et}}` to `{edge_type: @et}` in `list_ontology_edges` and `get_staging` endpoints. |
| L.25 | MDI-prefixed index corrections | `backend/migrations/005_mdi_indexes.py` | DONE | Updated to use `prefixFields: ["ontology_id"]` and `fields: ["created", "expired"]` per PRD §5.3. |

### Coverage Verification: PRD vs Implementation Plan

All PRD §6 features are tracked in the implementation plan:

| PRD Section | Feature | Plan Location | Status |
|-------------|---------|---------------|--------|
| §6.1 FR-1.1–1.5 | Document ingestion basics | Phase 1, Week 2 | **IMPLEMENTED** |
| §6.1 FR-1.6 | Upload status + auto-extract | Phase 1 + L.7 | **IMPLEMENTED** |
| §6.1 FR-1.7–1.8 | Multi-doc ontologies, add doc | Sprint G | **IMPLEMENTED** |
| §6.1 FR-1.9–1.10 | Full CRUD, many-to-many | Sprint J | **IMPLEMENTED** |
| §6.2 FR-2.1–2.6 | Core extraction pipeline | Phase 2 | **IMPLEMENTED** (parallel fork/join, object property detection, deferred relationship resolution, `related_to` edge materialization) |
| §6.2 FR-2.7–2.11 | Materialization, graphs, visualizer | Phase 2 + L.18–L.22 | **IMPLEMENTED** |
| §6.2 FR-2.12–2.13 | Incremental + multi-doc extraction | Sprint G | **IMPLEMENTED** |
| §6.3 FR-3.1–3.5 | Tier 2 local extensions | Sprint B | **IMPLEMENTED** |
| §6.4 FR-4.1–4.9 | Visual curation dashboard | Phase 3 + Sprint A (complete) | **IMPLEMENTED** (VCR, EntityHistory, DiffOverlay, WS pipeline events, schema extract status — see Sprint A verification) |
| §6.4 FR-4.10–4.13 | Standalone ontology editor | Sprint K | **IMPLEMENTED** |
| §6.5 FR-5.1–5.11 | Temporal time travel + VCR | Phase 3 + fixes | **IMPLEMENTED** (snapshot, timeline, VCR slider working) |
| §6.6 FR-6.1–6.12 | ArangoDB Visualizer customization | Phase 3 + L.20 + Sprint C | **IMPLEMENTED** |
| §6.7 FR-7.1–7.11 | Entity resolution | Phase 4 | STUB — needs `arango-entity-resolution` integration |
| §6.8 FR-8.1–8.7 | Import/export + CRUD | Phase 6 + Sprint J + fixes | **IMPLEMENTED** (export, import, CRUD with temporal cascade) |
| §6.8 FR-8.8–8.16 | Imports graph, catalog, search | Sprint J (partial) | PARTIALLY IMPLEMENTED — search done, imports/catalog pending (Sprint H) |
| §6.9 FR-9.1–9.7 | Schema extraction from ArangoDB | Phase 6 | STUB |
| §6.10 FR-10.1–10.5 | MCP server (runtime) | Phase 5 | **IMPLEMENTED** |
| §6.11 FR-11.1–11.10 | Agentic extraction pipeline | Phase 2 + quality judge | **IMPLEMENTED** (6-agent parallel pipeline, async `ainvoke`, concurrent extraction, `Annotated` reducers for state merging) |
| §6.12 FR-12.1–12.10 | Pipeline monitor dashboard | Phase 2 + L + fixes | **IMPLEMENTED** (polling, step DAG, metrics, errors) |
| §6.13 FR-13.1–13.13 | Ontology quality metrics | Sprint F + confidence fixes + Q.1 | **MOSTLY IMPLEMENTED** (7-signal confidence, health score, quality panel, unified `/dashboard`, per-ontology live radar tab, recharts radar on scorecard detail, audited OntoQA panel, connectivity metric; missing: `/quality/history`, gold-standard recall API, RAG benchmark comparison) |
| §6.14 FR-14.1–14.7 | OWL restrictions + SHACL | Sprint I | NOT STARTED |
| §6.15 FR-15.1–15.6 | Ontology imports & dependencies | Sprint H | NOT STARTED |
| §7.2.1 | Admin reset endpoints | L.3 + fixes | **IMPLEMENTED** (with named graph cleanup) |
| §5.3 | Temporal integrity & deletion | Audit fixes | **IMPLEMENTED** (soft-delete cascade, cross-ontology edges, reject cascade) |

### Remaining Work Priority (Updated March 31, 2026)

| Sprint | Duration | Tasks | Priority | Blocks | Status |
|--------|----------|-------|----------|--------|--------|
| ~~C: Data Integrity & Reindex~~ | ~~3 days~~ | ~~4~~ | ~~P0~~ | | **DONE** |
| ~~A: Critical Bugs & Wiring~~ | ~~1 week~~ | ~~9~~ | ~~P0~~ | | **DONE** |
| ~~K: Standalone Ontology Editor~~ | ~~1.5 weeks~~ | ~~12~~ | ~~P0~~ | | **DONE** |
| ~~B: Backend Stubs~~ | ~~1 week~~ | ~~8~~ | ~~P1~~ | | **DONE** |
| ~~G: Multi-Doc & Incremental~~ | ~~1.5 weeks~~ | ~~8~~ | ~~P1~~ | | **DONE** |
| ~~F: Quality Metrics~~ | ~~1.5 weeks~~ | ~~18~~ | ~~P1~~ | | **MOSTLY DONE** (dashboard page done; history tracking, gold-standard recall pending) |
| ~~J: CRUD, Search & Organization~~ | ~~1 week~~ | ~~9~~ | ~~P1~~ | | **DONE** |
| H: Imports & Dependencies | 1.5 weeks | 9 | **P1** | Standard ontology support | PENDING |
| ER: Entity Resolution Integration | 1.5 weeks | 9 | **P1** | Deduplication | PENDING |
| Q: Quality Dashboard + History | 3 days | 5 | **P1** | PRD §6.13 completeness | PARTIALLY DONE (Q.1 radar dashboard done; Q.2–Q.5 pending) |
| I: Constraints (OWL + SHACL) | 1 week | 9 | **P2** | Formal constraints | PENDING |
| S: Schema Extraction | 1 week | 6 | **P2** | Reverse engineering | PENDING |
| D: Test Coverage & CI | 1 week | 7 | **P2** | Quality gate | PENDING |
| E: Production Polish | 1 week | 7 | **P2** | v1.0.0 readiness | PENDING |
| PGT: Property Collection Alignment | 1.5 weeks | 12 | **P0** | Schema alignment (ADR-006) | PENDING — on `object-centric-ux` branch |
| OWL: Foundation Layer (Metamodel) | 1 week | 7 | **P1** | Formal OWL completeness (depends on PGT) | PENDING |
| V: Sigma.js Migration | 2–3 weeks | 11 | **P1** (post-v1.0) | Scalability | PENDING |
| **Total remaining** | **~8–9 weeks** | **~70 tasks** | | |

See `docs/REMAINING_WORK_PLAN.md` for detailed task breakdowns per stream.

---

### Sprint PGT: Property Collection Alignment (1.5 weeks)

**Goal:** Align the extraction pipeline's storage model with ArangoRDF PGT's collection-per-type pattern. Split `ontology_properties` into `ontology_object_properties` + `ontology_datatype_properties`, replace `has_property`/`related_to` with `rdfs_domain`/`rdfs_range_class` edges, and update the extraction prompt to separately request attributes and relationships.

**PRD Reference:** §5.1 (data model), ADR-006
**Branch:** `object-centric-ux`

| # | Task | Files | Description |
|---|------|-------|-------------|
| PGT.1 | Create new collections migration | `backend/migrations/017_pgt_collections.py` | Create `ontology_object_properties`, `ontology_datatype_properties` (vertex), `rdfs_domain`, `rdfs_range_class` (edge). |
| PGT.2 | Update Pydantic models | `backend/app/models/ontology.py` | Replace `ExtractedProperty` with `ExtractedAttribute` (`label`, `range_datatype`, `description`, `confidence`) and `ExtractedRelationship` (`label`, `target_class_uri`, `description`, `confidence`). Update `ExtractedClass` to have `attributes` + `relationships` instead of `properties`. |
| PGT.3 | Update extraction prompt | `backend/app/extraction/prompts/tier1_standard.py`, `tier2/tier2_standard.py` | Split `properties` array into `attributes` (datatype) and `relationships` (object). Clear guidance to LLM on the distinction. |
| PGT.4 | Update consistency checker | `backend/app/extraction/agents/consistency.py` | Merge attributes and relationships separately across passes. Property agreement computed per type. |
| PGT.5 | Update materialization | `backend/app/services/extraction.py` | Write to `ontology_object_properties` + `ontology_datatype_properties`. Create `rdfs_domain` + `rdfs_range_class` edges. Remove `has_property` + `related_to` creation. |
| PGT.6 | Update quality metrics | `backend/app/services/quality_metrics.py`, `confidence.py` | Connectivity queries use `rdfs_range_class`. Completeness uses `rdfs_domain`. OntoQA metrics updated. |
| PGT.7 | Update import bridge | `backend/app/services/arangordf_bridge.py` | Map PGT collections (`owl_ObjectProperty` → `ontology_object_properties`). Post-import creates `rdfs_domain`/`rdfs_range_class` edges. |
| PGT.8 | Data migration script | `backend/migrations/018_migrate_properties.py` | Migrate existing `ontology_properties` → split collections. Convert `has_property` → `rdfs_domain`. Convert `related_to` → `rdfs_range_class`. |
| PGT.9 | Update graph visualization | `frontend/src/components/graph/GraphCanvas.tsx` | Render object properties as labeled edges via `rdfs_domain`→`rdfs_range_class` traversal. Update edge type handling. |
| PGT.10 | Update API endpoints | `backend/app/api/ontology.py` | Class detail returns attributes + relationships separately. Edge listing uses new collections. Export uses new collections. |
| PGT.11 | Update named graphs | `backend/app/services/ontology_graphs.py` | Edge definitions use `rdfs_domain`, `rdfs_range_class` instead of `has_property`, `related_to`. |
| PGT.12 | Update tests | All test files referencing `ontology_properties`, `has_property`, `related_to` | Adapt to new collection names and query patterns. |

**Sprint PGT exit:** Extracted and imported ontologies share the same schema. ObjectProperty and DatatypeProperty stored in separate collections. Domain/range expressed as graph edges. Extraction prompt clearly distinguishes attributes from relationships.

---

### Sprint OWL: OWL/RDFS Foundation Layer (1 week)

**Goal:** Seed the OWL/RDFS metamodel vocabulary as first-class entities, create formal `rdf:type`/`rdfs:domain`/`rdfs:range` edges during materialization, and add UI toggle for foundation visibility.

**PRD Reference:** §6.8b

| # | Task | Files | Description |
|---|------|-------|-------------|
| OWL.1 | Foundation seed migration | `backend/migrations/016_owl_foundation.py` (new) | Idempotent migration creates ~50 foundation entities (`owl:Class`, `rdfs:subClassOf`, XSD datatypes, etc.) in `ontology_classes` and `ontology_properties` with `source_type: "foundation"`, `ontology_id: "owl_rdfs_foundation"`, `created: 1355184000` (OWL 2 W3C Rec date), `confidence: 1.0`. |
| OWL.2 | `rdf:type` edges in materialization | `backend/app/services/extraction.py` | After inserting each class, create `rdf:type` edge to `ontology_classes/owl_Class`. After each property, `rdf:type` edge to `owl_ObjectProperty` or `owl_DatatypeProperty`. |
| OWL.3 | `rdfs:domain`/`rdfs:range` edges | `backend/app/services/extraction.py` | For each property, create `rdfs:domain` edge from property to domain class, `rdfs:range` edge from property to range class or XSD datatype entity. |
| OWL.4 | Metric exclusion filter | `backend/app/services/quality_metrics.py` | All metric queries add `FILTER doc.source_type != "foundation"` or filter by specific `ontology_id`. Verify health score, confidence, completeness, connectivity, OntoQA metrics all exclude foundation. |
| OWL.5 | UI toggle: "Show OWL Foundation" | `frontend/src/components/graph/GraphCanvas.tsx`, editor page, curation page | Toggle button in toolbar. When off (default), filter out nodes/edges where `source_type == "foundation"`. When on, render foundation nodes with gray style, smaller size. |
| OWL.6 | VCR timeline exclusion | `backend/app/services/temporal.py` | `get_timeline_events` excludes entities with `source_type == "foundation"`. |
| OWL.7 | Export includes foundation prefixes | `backend/app/services/export.py`, `owl_serializer.py` | OWL/Turtle export adds `@prefix owl:`, `rdfs:`, `rdf:`, `xsd:` declarations and includes `rdf:type`, `rdfs:domain`, `rdfs:range` triples for each extracted class/property. |
