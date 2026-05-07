# AOE — Remaining Work Plan

**Document Version:** 3.0
**Date:** April 10, 2026
**Baseline:** v0.1.0 tag + Sprints A–K, B, G, F, J + audit fixes + temporal integrity fixes
**PRD Reference:** `PRD.md` — Arango-OntoExtract Product Requirements Document

---

## Executive Summary

The AOE (Arango-OntoExtract) system has a working end-to-end extraction pipeline, ontology editor, pipeline monitor, quality metrics, and multi-document support. This document details the remaining work required to achieve full PRD compliance and production readiness.

**Completed:** ~78% of PRD requirements (§6.1–6.6, §6.10–6.13 incl. quality dashboard, most of §6.8, §7.2.1)
**Remaining:** ~22% across 7 work streams + 2 future streams, estimated 8–10 weeks (core) + TBD (Streams 8–9)

**Recent completions (since v1.0 of this document):**
- Multi-signal confidence scoring with 7 signals incl. LLM-as-Judge faithfulness + semantic validator
- Ontology health score (0–100) with traffic-light display
- Temporal soft-delete with full referential integrity for ontology deprecation
- Curation reject cascade fix (edges now properly expired)
- 10 audit fixes (3 critical: NEVER_EXPIRES, extracted_from expired, entity counts)
- Pipeline DAG scrollable canvas, Quality Judge step visible, skipped step marking
- VCR timeline fix (array response, Unix timestamps, event type inference)
- Extraction reliability (5 retries, backoff, async ainvoke, concurrent support)
- Edge routing fix (rdfs:subClassOf arrows, OWL label conventions)
- Detailed deletion/referential integrity documentation (`docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`)
- PRD corrections (FAISS IVF vector index, Sigma.js target architecture, deletion contexts)

---

## Current State Summary

### What's Working

| Area | Status | Key Capabilities |
|------|--------|-----------------|
| Document Ingestion (§6.1) | **Complete** | Upload (PDF, DOCX, MD), chunking, auto-extraction trigger, multi-doc, CRUD |
| Extraction Pipeline (§6.2, §6.11) | **Complete** | 6-agent LangGraph pipeline (strategy, extractor, consistency, quality judge, ER stub, filter), async/concurrent, 7-signal confidence scoring |
| Tier 2 Extensions (§6.3) | **Complete** | Domain context injection, tier2 prompts, strategy auto-detection |
| Visual Curation (§6.4) | **Complete** | Graph canvas (React Flow), node/edge actions, VCR timeline, diff view, provenance, standalone editor with CRUD |
| Temporal Time Travel (§6.5) | **Mostly Complete** | Edge-interval versioning, snapshot API, timeline events, VCR slider. Missing: playback animation |
| ArangoDB Visualizer (§6.6) | **Complete** | Themes, canvas actions, saved queries (temporal-aware), viewpoints, auto-install |
| MCP Server (§6.10) | **Complete** | Runtime MCP tools for ontology operations |
| Pipeline Monitor (§6.12) | **Complete** | Real-time step DAG with polling, metrics (tokens, cost, entities, confidence, completeness, agreement), error log |
| Quality Metrics (§6.13) | **Mostly Complete** | Multi-signal confidence (7 signals incl. faithfulness judge + semantic validator), ontology health score, quality panel in library, unified `/dashboard`, **Per-Ontology Quality** tab (live `GET /quality/{id}` radar + cards), recharts radar on scorecard drill-down, audited OntoQA panel, connectivity metric. Missing: `/quality/history`, gold-standard recall API, optional future RAG benchmark UI. |
| Import/Export (§6.8 partial) | **Partial** | Export (Turtle, JSON-LD, CSV), OWL import via ArangoRDF, library search (ArangoSearch), tagging, full CRUD with cascade. Missing: imports graph, standard ontology catalog. |
| Admin (§7.2.1) | **Complete** | Soft/full reset (with named graph cleanup), extraction run deletion |
| Deletion & Integrity | **Complete** | Temporal soft-delete for ontology deprecation, cross-ontology edge cascade, curation reject cascade, document delete with provenance expiry. See `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`. |

### What's Not Done

| Area | Status | Gap |
|------|--------|-----|
| Entity Resolution (§6.7) | **Stub** | ER agent exists but uses placeholder logic. No real `arango-entity-resolution` library integration. |
| Imports, Composition & Dependencies (§6.15, §6.8.8–8.16) | **Phase 0 done; later phases pending** | `owl:imports` edge tracking, `sync_owl_imports_edges`, and `GET/POST/DELETE /api/v1/ontology/{id}/imports` are shipped (see Stream 1 below). Standard catalog, dependency graph UI, effective graph API still pending. |
| Constraints (§6.14) | **Not Started** | No OWL restriction or SHACL shape extraction, import, display, or export |
| Schema Extraction (§6.9) | **Stub** | Service shell exists but minimal implementation. No named graph-aware extraction, no direct graph-to-ontology mapping fallback, no UI for graph selection |
| Quality Dashboard (§6.13.7) | **Partially Done** | Unified `/dashboard`, `/quality` → per-ontology tab, recharts radar, audited OntoQA metrics, connectivity metric, qualitative evaluation, live per-ontology six-dimension view. Missing: history tracking, gold-standard recall, curation throughput timer, RAG benchmark comparison |
| Testing & CI (§8) | **Partial** | ~500 unit tests exist but no CI pipeline, no coverage enforcement |
| Production Ops (§8.5) | **Not Started** | No OpenTelemetry, no alerting, no performance benchmarks |
| Visualizer Migration | **Not Started** | React Flow → Sigma.js/graphology (PRD target architecture) |

### Recently Fixed (since v1.0 of this plan)

| Fix | PRD Ref | Impact |
|-----|---------|--------|
| Ontology deletion now uses temporal soft-delete (was hard delete) | FR-8.13 | History preserved, VCR works post-deprecation |
| Curation reject now cascades to edges | FR-4.2, §5.3 | No dangling edge references |
| `extracted_from` edges now include `expired` field | §5.3 | Temporal queries work correctly |
| `get_ontology_detail` counts filter by `expired == NEVER_EXPIRES` | §7.3 | Accurate class/property counts after edits |
| `NEVER_EXPIRES` uses `sys.maxsize` consistently (was hardcoded in documents.py) | §5.3 | Platform-safe sentinel value |
| Document deletion uses `time.time()` consistently (was `DATE_NOW()/1000`) | §5.3 | No clock skew between app and DB |
| `retry_run` preserves `target_ontology_id`, `domain_ontology_ids`, `doc_ids` | §6.11 | Retries use original config |
| Staging endpoint standardized to `edge_type` (was `type`) | §7.8 | Consistent API contract |
| System reset cleans up per-ontology named graphs and additional collections | §7.2.1 | Clean fresh start |
| PRD corrected: ArangoDB uses FAISS IVF (not standalone HNSW) for vector indexes | §6.7 | Accurate technical spec |
| Unified quality dashboard (`/dashboard`) with `/quality` redirect to per-ontology tab, recharts radar chart, live per-ontology quality tab | FR-13.7 | All quality dimensions visible on spider chart |
| OntoQA schema metrics (relationship richness, attribute richness, max depth, annotation completeness) | FR-13.16 | Industry-standard ontology evaluation after dashboard metric audit |
| Connectivity metric in health score (20% weight) | FR-13.14 | Flat taxonomies without relationships now penalized |
| `related_to` edge materialization from object properties | FR-2.7 | Inter-class relationships visible in graph |
| Parallel pipeline (Quality Judge ∥ ER Agent fork/join) | §6.11 | Faster extraction, proper DAG visualization |
| Object property detection (`_is_object_property`) with smart range matching | FR-2.7 | Non-http class URIs correctly identified |
| Deferred relationship resolution (second pass after all classes) | FR-2.7 | Forward-referenced classes now resolved |
| LangGraph `Annotated` reducers for parallel state merging | §6.11 | No more "Can receive only one value per step" errors |
| Document-ontology mapping pills on upload page | FR-1.10 | Each document shows linked ontologies |
| OWL/RDFS foundation layer added to PRD (§6.8b) | §6.8b | Planned: metamodel entities, rdf:type edges, UI toggle |
| Ontology release management added to PRD (§6.8a) | §6.8a | Planned: semver, breaking change detection, revert |
| 13 use cases + RBAC matrix added to PRD (§2a) | §2a | Workflow testing matrix for E2E tests |

---

## Work Streams

### Stream 0: PGT Property Collection Alignment (PRIORITY — object-centric-ux branch)
**PRD:** §5.1 (data model), ADR-006
**Duration:** 1.5 weeks
**Priority:** P0 — schema foundation for all other work
**Dependencies:** None (but all other streams depend on this)
**Branch:** `object-centric-ux`

#### Objectives
- Split `ontology_properties` into `ontology_object_properties` (relationships) + `ontology_datatype_properties` (attributes)
- Replace `has_property` and `related_to` edges with `rdfs_domain` and `rdfs_range_class` edges
- Update extraction prompt to separately request `attributes` and `relationships`
- Align extracted ontology schema with ArangoRDF PGT import schema
- Migrate existing data

See `docs/adr/006-pgt-aligned-property-collections.md` for full design rationale and `IMPLEMENTATION_PLAN.md` Sprint PGT for detailed task breakdown (12 tasks).

---

### Stream 1: Ontology Imports, Composition & Dependency Management
**PRD:** §6.15 FR-15.1–15.12, §6.8 FR-8.8–8.11, FR-8.16
**Duration:** 2 weeks remaining (Phase 0 complete, Phase 1 partially complete)
**Priority:** P1 — blocks standard ontology usage and ontology composition
**Dependencies:** None
**Team Size:** 1 backend + 1 frontend developer

#### Objectives
- Track `owl:imports` relationships as edges between ontology registry entries
- Enable loading standard ontologies (FIBO, Schema.org, Dublin Core) from a built-in catalog
- Visualize the ontology dependency graph in the Library UI
- Cascade analysis before ontology deletion (warn about dependents)
- **Create composed ontologies** that import and extend existing ontologies
- **Compute effective ontology graphs** (own + transitive import closure)
- **Import-aware extraction** that reuses imported concepts

#### Tasks — Phase 0: Core Create & Import APIs (COMPLETED)

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| H.0a | Create empty ontology API | Backend | **DONE** | `POST /ontology/create` creates a registry entry with no graph content. Accepts optional `imports` list to create `imports` edges at creation time. Validates uniqueness and target existence. |
| H.0b | Imports CRUD API | Backend | **DONE** | `GET /{id}/imports`, `GET /{id}/imported-by`, `POST /{id}/imports`, `DELETE /{id}/imports/{target_id}`. Circular dependency detection. Temporal soft-delete on removal. |
| H.0c | Create Ontology dialog | Frontend | **DONE** | "New Ontology" dialog accessible from canvas context menu (right-click → "New Ontology…"). Fields: name, description, tier, multi-select import picker with all library ontologies. |
| H.0d | Manage Imports overlay | Frontend | **DONE** | Accessible from ontology context menu → "Manage Imports". Lists current imports with remove action. "Add Import" picker shows available ontologies excluding self and already-imported. |
| H.0e | Unit tests | Both | **DONE** | 13 backend tests (create, conflict, imports CRUD, self-import rejection, duplicate detection). 7 frontend tests (dialog render, validation, API calls, import selection). |

#### Tasks — Phase 1: Import Tracking & Catalog

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| H.1 | `imports` edge creation on OWL import | Backend | **DONE** | `sync_owl_imports_edges` already creates `imports` edges after PGT import. |
| H.2 | `ontology_imports` named graph | Backend | 2h | Create named graph with `ontology_registry` as vertices and `imports` as edges. Migration script. |
| H.3 | Imports API endpoints | Backend | **DONE** | `GET /{id}/imports`, `GET /{id}/imported-by` implemented in Phase 0. Remaining: `GET /imports-graph` (full dependency DAG). Estimate for remaining: 2h. |
| H.4 | Cascade analysis on delete | Backend | 3h | Before deprecating an ontology, traverse `imports` graph to find dependents. Return list. Frontend shows confirmation dialog with affected ontologies. |
| H.5 | Standard ontology catalog | Backend | 6h | JSON catalog of standard ontologies (FIBO modules, Schema.org, Dublin Core, FOAF, PROV-O, SKOS, OWL-Time) with URLs, descriptions, class counts. API: `GET /ontology/catalog`, `POST /ontology/catalog/{id}/import`. |
| H.6 | Catalog import UI | Frontend | 4h | "Import Standard Ontology" button in library. Opens catalog browser with descriptions, one-click import with progress indicator. |
| H.7 | Imports dependency graph in Library UI | Frontend | 6h | New "Dependencies" tab in library showing a DAG of ontology imports. Click a node to navigate to that ontology. |
| H.8 | Base ontology selector in extraction UI | Frontend | 3h | Searchable "Base Ontologies" multi-select on upload page. Selected ontologies sent as `base_ontology_ids`. Backend injects their classes as context and records `imports` edges. |
| H.9 | Visualizer queries for imports | Backend | 2h | Saved AQL queries: "Ontology Dependencies" (traversal), "Upstream Ontologies" (ancestors), "Downstream Dependents" (children). |
| H.10 | Export includes `owl:imports` triples | Backend | 3h | OWL/Turtle export traverses `imports` edges from the ontology's registry entry and emits `owl:imports` triples. Re-importable into AOE or external tools. (FR-15.12) |

#### Tasks — Phase 2: Ontology Composition (Advanced)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| H.11 | ~~"Create Composed Ontology" API~~ | Backend | **DONE** | Merged into `POST /ontology/create` with `imports` parameter. |
| H.12 | Effective ontology API | Backend | 8h | `GET /ontology/{id}/effective` computes transitive closure of `imports` edges, then merges classes/properties/edges from self + all imported ontologies. Result is cached with an ETag based on registry `updated_at` timestamps. Imported entities are annotated with `source_ontology_id`. (FR-15.8) |
| H.13 | Import conflict detection | Backend | 4h | When computing effective graph, detect naming conflicts (same class label or URI across imported ontologies). Return conflicts as warnings in the API response. (FR-15.11) |
| H.14 | ~~Composed ontology creation UI~~ | Frontend | **DONE** | Merged into CreateOntologyDialog with multi-select imports. |
| H.15 | Effective graph rendering in canvas | Frontend | 6h | When viewing a composed ontology, the graph canvas renders imported entities with distinct visual treatment (dimmed color, dashed border, "imported" badge, or grouped by source ontology). Legend explains the distinction. Context menu on imported entities shows "Go to source ontology". (FR-15.8) |
| H.16 | Drag-and-drop import composition | Frontend | 4h | Drag an ontology from Asset Explorer onto the canvas of an open ontology to add it as an import. Creates `imports` edge and refreshes effective graph. Context menu "Remove Import" on imported ontology groups. (FR-15.10) |
| H.17 | Import-aware extraction prompts | Backend | 4h | When extracting into a composed ontology, the LLM prompt includes the effective ontology (own + imported classes) as context. Instructions tell the LLM to reuse imported concepts via `rdfs:subClassOf` or `owl:equivalentClass` rather than duplicating. (FR-15.9) |

#### Implementation Plan — Recommended Order

| Phase | Tasks | Est. Duration | Prerequisites |
|-------|-------|---------------|---------------|
| **Phase 0 (COMPLETE)** | H.0a–H.0e | — | None |
| **Phase 1a: Catalog & Graph** | H.2, H.3 (remaining), H.5, H.6, H.9 | 3 days | Phase 0 |
| **Phase 1b: Integration** | H.4, H.7, H.8, H.10 | 3 days | Phase 1a |
| **Phase 2a: Effective Graph** | H.12, H.13 | 3 days | Phase 1 |
| **Phase 2b: Canvas & Extraction** | H.15, H.16, H.17 | 3 days | Phase 2a |

**Parallelization:** Phase 1a backend tasks (H.2, H.3, H.5, H.9) can run in parallel with each other. H.6 (catalog UI) can start as soon as H.5 (catalog API) delivers. Phase 2a (effective graph API) can begin before Phase 1b completes.

**Exit Criteria:** `owl:imports` tracked as edges. Standard ontologies importable from catalog. Imports dependency graph visible in UI and ArangoDB Visualizer. Users can create composed ontologies that inherit imported axioms. Effective graph rendered in canvas with visual distinction for imported entities. Export preserves `owl:imports`.

---

### Stream 2: Entity Resolution Integration
**PRD:** §6.7 FR-7.1–7.11
**Duration:** 1.5 weeks
**Priority:** P1 — key differentiator for ontology quality
**Dependencies:** None (can run in parallel with Stream 1)
**Team Size:** 1 backend + 1 frontend developer

#### Objectives
- Replace the ER agent stub with real `arango-entity-resolution` library integration
- Configure blocking, scoring, clustering, and merge workflows for ontology concepts
- Surface merge candidates in the curation UI with explanations

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| ER.1 | Install and configure `arango-entity-resolution` | Backend | 3h | Add library dependency. Create `ERPipelineConfig` for ontology matching: vector blocking on class label/description embeddings, BM25 on labels, weighted field similarity (Jaro-Winkler on label, Levenshtein on description). |
| ER.2 | Replace ER agent stub | Backend | 6h | `er_agent_node` calls `ConfigurableERPipeline` with the ontology config. Writes similarity edges to `similarTo` collection. Stores merge candidates in pipeline state. |
| ER.3 | Topological similarity scoring | Backend | 4h | AOE-specific scoring layer: compare graph neighborhoods (shared properties via `has_property`, shared parents via `subclass_of`). Add as additional dimension to `final_score`. |
| ER.4 | WCC clustering | Backend | 3h | Configure `WCCClusteringService` with auto backend selection. Group similar entities into clusters. |
| ER.5 | Merge execution service | Backend | 4h | Wire `GoldenRecordService` for merge execution. Field-level strategy: `most_complete_with_quality`. Merged entity gets combined properties; losing entity expires with temporal versioning. |
| ER.6 | ER run API endpoints | Backend | 3h | `POST /er/run` (trigger ER on an ontology), `GET /er/runs/{id}` (status), `GET /er/runs/{id}/candidates` (pairs with scores), `GET /er/runs/{id}/clusters` (WCC clusters). |
| ER.7 | Merge candidate UI | Frontend | 6h | Merge candidates panel in curation UI: show candidate pairs with similarity scores, field-by-field comparison, `explain_match` evidence, accept/reject/skip actions. |
| ER.8 | Cross-tier resolution | Backend | 4h | `resolve_entity_cross_collection` matches local concepts against domain ontology. Suggests `owl:equivalentClass` or `rdfs:subClassOf` links. |
| ER.9 | ER MCP tools integration | Backend | 3h | Proxy ER-specific MCP tool calls to the `arango-entity-resolution` MCP server. |

**Exit Criteria:** ER agent produces real merge candidates. Candidates visible in curation UI with scores and explanations. Merge execution preserves temporal history.

---

### Stream 3: OWL Constraints & SHACL Shapes
**PRD:** §6.14 FR-14.1–14.7
**Duration:** 1 week
**Priority:** P2 — formal ontology completeness
**Dependencies:** Stream 1 (imports needed for constraint context)
**Team Size:** 1 developer

#### Objectives
- Extract OWL restrictions and SHACL shapes from LLM extraction and OWL imports
- Store, display, and export constraints

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| I.1 | Constraint extraction prompts | Backend | 4h | Extend extraction prompts: "For each class, identify cardinality constraints, value restrictions, and data validation rules." Add `constraints` field to `ExtractedClass`. |
| I.2 | Constraint materialization | Backend | 3h | `_materialize_to_graph` writes constraints to `ontology_constraints` collection with temporal fields. |
| I.3 | OWL restriction import via ArangoRDF | Backend | 4h | After PGT import, parse `owl:Restriction` blank nodes. Create `ontology_constraints` documents linked to target class and property. |
| I.4 | SHACL shapes import | Backend | 4h | Parse SHACL shapes graphs (Turtle). Create `ontology_constraints` with `constraint_type: "sh:NodeShape"` or `"sh:PropertyShape"`. |
| I.5 | Constraints API endpoint | Backend | 2h | `GET /library/{ontology_id}/constraints` returns all OWL restrictions and SHACL shapes. |
| I.6 | Constraints display in Library UI | Frontend | 3h | Class detail panel shows constraints: cardinality badges, value restrictions, SHACL rules with severity icons. |
| I.7 | Constraints display in Curation UI | Frontend | 3h | NodeDetail shows constraints alongside properties. Curators can approve/reject/edit. |
| I.8 | Constraints in OWL export | Backend | 3h | Turtle export includes `owl:Restriction` constructs. New `export_shacl()` for SHACL shapes graph. |
| I.9 | Constraints in temporal queries | Backend | 2h | `get_snapshot` and `get_diff` include constraints from `ontology_constraints`. |

**Exit Criteria:** Constraints extractable, importable, displayable, and exportable. SHACL shapes stored alongside OWL restrictions.

---

### Stream 4: Quality Dashboard & History
**PRD:** §6.13 FR-13.7, FR-13.8, FR-13.5, FR-13.2
**Duration:** 3 days
**Priority:** P1 — completes the quality metrics story
**Dependencies:** None
**Team Size:** 1 frontend developer

#### Objectives
- Dedicated quality dashboard page with traffic-light indicators
- Quality history tracking over time
- Gold-standard recall comparison
- Curation throughput timer

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| Q.1 | Quality dashboard page | Frontend | 6h | **DONE** — unified `/dashboard`, `/quality` → `?tab=per-ontology-quality`, summary cards, per-ontology score table, detail radar, metric cards, qualitative evaluation, **Per-Ontology Quality** live tab, flags/alerts. |
| Q.2 | Quality history API | Backend | 4h | `GET /quality/{ontology_id}/history` returns quality scores over time. Store quality snapshots in a `quality_history` collection on each extraction completion. |
| Q.3 | Trend sparklines | Frontend | 3h | Small sparkline charts on the quality dashboard showing metric trends from history data. |
| Q.4 | Gold-standard recall comparison | Backend | 4h | `POST /quality/recall` accepts a reference OWL/TTL file. Computes `recall = |extracted ∩ reference| / |reference|` using fuzzy label matching. Returns per-class match details. |
| Q.5 | Curation throughput timer | Frontend | 3h | Session start timestamp on curation page load. On each decision, compute elapsed time. Display "concepts reviewed / hour" counter in curation header. Send timing data to backend. |

**Exit Criteria:** All five PRD §3.2 success metrics visible on a single dashboard page with trend visualization.

---

### Stream 4b: Pipeline History Timeline Slider
**PRD:** §6.12 FR-12.11
**Duration:** 1 day
**Priority:** P1 — extends existing pipeline monitor with temporal navigation
**Dependencies:** None (pipeline monitor already complete)
**Team Size:** 1 developer

#### Objectives
- Add a VCR-style timeline slider to the pipeline monitor that lets users scrub through extraction runs chronologically
- Selecting a position on the slider auto-selects the corresponding run, updating the DAG, metrics, and error panels
- Play/pause auto-advances through runs so users can watch pipeline evolution over time
- Reuses visual language from the ontology VCR timeline (§6.5) for consistency

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| PH.1 | `PipelineHistorySlider` component | Frontend | 4h | VCR-style slider with play/pause/rewind/ff, speed control. Each tick = one extraction run ordered by `started_at`. Selecting a tick fires `onSelectRun(runId)`. Shows run status color, document name, and relative timestamp for the current position. |
| PH.2 | Wire into pipeline page | Frontend | 1h | Mount `PipelineHistorySlider` above the DAG area in `/pipeline`. Slider `onSelectRun` syncs with the existing `selectedRunId` state. Sidebar `RunList` selection and slider selection stay in sync bidirectionally. |
| PH.3 | Run summary strip | Frontend | 2h | Below the slider, show a compact summary of the selected run: status badge, duration, entity count, cost — so users get context without switching to the Metrics tab. |
| PH.4 | Unit tests | Frontend | 2h | Tests for `PipelineHistorySlider`: renders runs as ticks, play/pause advances index, slider change fires callback, empty state, loading state. |

**Exit Criteria:** Users can scrub through all extraction runs via a slider on the pipeline page. Play mode auto-advances through runs. Selecting a run on the slider updates the DAG/metrics/errors panels. Tests pass.

---

### Stream 5: Schema Extraction from ArangoDB
**PRD:** §6.9 FR-9.1–9.13
**Duration:** 2 weeks
**Priority:** P2 — value-add for existing ArangoDB users
**Dependencies:** Stream 1 (imports/composition), Stream 3 (constraints)
**Team Size:** 1 developer

#### Objectives
- Connect to any ArangoDB instance and reverse-engineer its schema into an ontology
- Leverage `arango-schema-mapper` library for enhanced schema extraction
- **Named graph-aware extraction** that reads edge definitions for precise relationship mapping
- **Built-in fallback** that works without the external `schema_analyzer` library
- **Integration with composition** — schema-derived ontologies can import standard ontologies

#### Tasks — Phase 1: Core Schema Extraction

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| S.1 | Wire `arango-schema-mapper` integration | Backend | 6h | Call `snapshot_physical_schema()` and `AgenticSchemaAnalyzer` to produce conceptual model. Handle connection credentials securely. |
| S.2 | OWL export from schema | Backend | 3h | Call `export_conceptual_model_as_owl_turtle()` and feed into ArangoRDF import pipeline. |
| S.3 | Schema extraction API | Backend | 3h | `POST /schema/extract` accepts connection URL + credentials, triggers extraction. `GET /schema/extract/{run_id}` returns status and results. |
| S.4 | Provenance tracking for schema sources | Backend | 2h | Extracted classes link to source database URL + collection name (not document chunks). |
| S.5 | Schema diff for evolution tracking | Backend | 4h | Re-extract periodically. Diff against previous extraction to detect schema drift. Reuse temporal diff infrastructure. |

#### Tasks — Phase 2: Named Graph & Direct Mapping

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| S.6 | Named graph discovery API | Backend | 4h | `GET /schema/graphs?db_url=...` connects to the target database, calls `db.graphs()`, and returns a list of named graphs with their edge definitions (edge collection, from vertex collections, to vertex collections). Used by the UI to let users select which graph(s) to extract. (FR-9.9) |
| S.7 | Named graph-aware extraction | Backend | 6h | Enhance the extraction pipeline to read edge definitions from selected named graphs. Each edge definition maps to an `owl:ObjectProperty` with `rdfs:domain` set to the `from` vertex collection's class and `rdfs:range` set to the `to` vertex collection's class. Produces richer relationship semantics than collection-only scanning. (FR-9.9) |
| S.8 | Direct graph-to-ontology mapping (no `schema_analyzer`) | Backend | 8h | Built-in fallback that works without `arangodb-schema-analyzer`: (a) document collections → `owl:Class`, (b) edge collections → `owl:ObjectProperty` with domain/range from edge definitions, (c) sampled document fields → `owl:DatatypeProperty` with range inferred from value types (string→`xsd:string`, number→`xsd:integer`/`xsd:decimal`, boolean→`xsd:boolean`, array→`rdf:List`, nested object→new class). Outputs complete OWL/Turtle. (FR-9.10) |
| S.9 | Index and constraint mapping | Backend | 4h | Map ArangoDB indexes to ontology constraints: unique indexes → `owl:maxCardinality 1`, required fields (from collection schema validation) → `owl:minCardinality 1`, geo indexes → GeoSPARQL property annotation. Results feed into `ontology_constraints` collection. (FR-9.12) |
| S.10 | Schema-derived ontology auto-imports | Backend | 4h | When extracting, user can select existing ontologies to import. Creates `imports` edges. Optionally triggers ER between schema-derived classes and imported classes to suggest `owl:equivalentClass` / `rdfs:subClassOf` alignments. (FR-9.11) |

#### Tasks — Phase 3: UI

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| S.11 | Schema extraction UI with graph selection | Frontend | 6h | Form for ArangoDB connection details. After connecting, displays discovered named graphs with edge definition previews. User selects graph(s), optionally selects base ontologies to import, and previews the proposed class/property/edge mapping before confirming extraction. Progress indicator and results link to curation. (FR-9.13) |
| S.12 | Schema preview panel | Frontend | 4h | Before committing to extraction, shows a read-only preview: proposed classes (from collections), proposed relationships (from edge definitions), proposed properties (from sampled fields). User can deselect collections/fields to exclude from extraction. |

**Exit Criteria:** Users can point AOE at any ArangoDB instance, select named graphs, and generate an ontology from its schema — with or without `schema_analyzer`. Named graph edge definitions produce precise relationship mappings. Schema-derived ontologies can import standard ontologies. Results land in staging for curation.

---

### Stream 6: Testing, CI & Quality Gates
**PRD:** §8 (Non-Functional Requirements)
**Duration:** 1 week
**Priority:** P2 — required before v1.0.0 release
**Dependencies:** All feature streams should be complete
**Team Size:** 1 developer

#### Current Test Coverage

| Layer | Tests | Coverage | Gap |
|-------|-------|----------|-----|
| Backend unit tests | ~500 | ~65% | Missing: GraphCanvas, some API routes |
| Backend integration tests | ~80 | ~40% | Missing: full pipeline integration with DB |
| Backend E2E tests | ~27 | ~20% | Not in CI |
| Frontend unit tests | ~60 | ~30% | Missing: most components |
| Frontend E2E (Playwright) | 0 | 0% | Not started |

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| D.1 | GitHub Actions CI pipeline | DevOps | 4h | Workflow: lint → type-check → unit test → integration test (with ArangoDB service container) → frontend test. Run on PR and push to main. |
| D.2 | Coverage gates | DevOps | 2h | Fail CI if backend coverage < 80% or frontend coverage < 60%. Upload coverage reports to Codecov or similar. |
| D.3 | Missing backend integration tests | Backend | 6h | Full extraction pipeline with real DB, temporal versioning round-trip, quality metrics computation, import/export round-trip. |
| D.4 | Missing frontend component tests | Frontend | 6h | Tests for: GraphCanvas, ClassHierarchy, QualityPanel, AddClassDialog, AddPropertyDialog, OntologyCard, VCRTimeline. |
| D.5 | Playwright E2E tests | Frontend | 8h | Core flows: upload document → extraction completes → view in library → edit in editor → export. Login flow. Reset flow. |
| D.6 | `.env.example` completion | DevOps | 1h | Add all required settings with comments. |
| D.7 | Root `AGENTS.md` | Docs | 2h | Repository structure, module boundaries, development conventions for AI agents. |

**Exit Criteria:** CI runs all test types on every PR. Coverage ≥ 80% backend, ≥ 60% frontend. Playwright tests cover core user flows.

---

### Stream 7: Production Polish & Observability
**PRD:** §8.5 (Observability), §8.3 (Performance)
**Duration:** 1 week
**Priority:** P2 — required for production deployment
**Dependencies:** Stream 6 (tests must pass first)
**Team Size:** 1 developer

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| E.1 | OpenTelemetry tracing | Backend | 6h | Instrument key services with `opentelemetry-api` + `opentelemetry-sdk`. Spans across ingestion → extraction → materialization → graph creation. Export to Jaeger or OTLP endpoint. |
| E.2 | Alerting rules | DevOps | 3h | Define alerts for: extraction failure rate > 20%, API p95 > 2s, extraction queue depth > 10, database connection failures. |
| E.3 | TTL garbage collection | Backend | 2h | Verify `ttlExpireAt` is set on expired entities. Configure ArangoDB TTL index for automatic cleanup of historical versions older than configurable retention period (default: 90 days). |
| E.4 | Auto-install visualizer post-extraction | Backend | 2h | After `ensure_ontology_graph()`, call `install_for_ontology_graph()` to deploy theme/actions/queries for each new per-ontology graph. |
| E.5 | Performance benchmarks | Backend | 4h | Measure and document: extraction time per chunk, graph rendering time by node count, API p95 latency, concurrent extraction throughput. |
| E.6 | Docker Compose production config | DevOps | 4h | Production-grade docker-compose with health checks, resource limits, log aggregation, and environment-specific config. |
| E.7 | README update | Docs | 2h | Update README with current architecture, setup instructions, demo walkthrough, and API reference. |

**Exit Criteria:** Traces visible in observability platform. Alerts configured. Performance baselines documented. Production deployment guide complete.

---

### Stream 8: Visualizer Migration (Future Phase)
**PRD:** §6.4 FR-4.1 (target architecture), §6.4 FR-4.10 (TopBraid-class editor)
**Duration:** 2–3 weeks
**Priority:** P1 (future phase — after v1.0.0)
**Dependencies:** All other streams complete
**Team Size:** 1–2 frontend developers

#### Objectives
- Replace React Flow (DOM-based, limited to ~100 nodes) with Sigma.js + graphology (WebGL, handles 100K+ nodes)
- Implement TopBraid Composer-class editing panels

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| V.1 | Sigma.js + graphology integration | Frontend | 8h | Install `@react-sigma/core`, `graphology`, `graphology-layout-forceatlas2`. Create `SigmaGraphCanvas` component with same props interface as current `GraphCanvas`. |
| V.2 | ForceAtlas2 layout | Frontend | 4h | Replace dagre with ForceAtlas2 for organic, force-directed layout. Add layout toggle (hierarchy vs. force-directed). |
| V.3 | Semantic zoom | Frontend | 4h | At low zoom: show only class labels and group clusters. At medium zoom: show properties count. At high zoom: show full detail. |
| V.4 | Edge bundling | Frontend | 3h | Use graphology-edge-bundling for clean edge rendering in dense graphs. |
| V.5 | Class tree browser panel | Frontend | 6h | Left sidebar with hierarchical class tree (from `subclass_of` traversal), search, drag-to-reparent. |
| V.6 | Property matrix panel | Frontend | 6h | Spreadsheet-style view of all properties across classes (domain × range). Sortable, filterable, editable. |
| V.7 | Restriction editor panel | Frontend | 6h | Visual builder for OWL restrictions (cardinality, value, has-value, qualified). Generates `owl:Restriction` constructs. |
| V.8 | Namespace manager | Frontend | 3h | Settings dialog for managing ontology prefixes and namespaces. |
| V.9 | Validation console | Frontend | 4h | Bottom panel showing real-time OWL consistency issues and SHACL validation results. |
| V.10 | Migrate curation page to Sigma.js | Frontend | 4h | Replace `GraphCanvas` usage in `/curation?runId=…` with `SigmaGraphCanvas`. |
| V.11 | Migrate editor page to Sigma.js | Frontend | 4h | Replace `GraphCanvas` usage in `/ontology/edit?ontologyId=…` with `SigmaGraphCanvas`. |

**Exit Criteria:** All graph visualization uses Sigma.js/graphology. TopBraid-class editor panels available. Graphs with 1000+ nodes render smoothly.

---

### Stream 9: Unified Ontology Storage (Architecture Rethink)
**PRD:** §5.1 (data model), §6.8 (import/export), §6.15 (imports & dependencies)
**Duration:** TBD (needs analysis spike first)
**Priority:** P1 (architectural — blocks multi-ontology querying, cross-ontology ER, and namespace management)
**Dependencies:** Stream 0 (PGT alignment) should be complete first
**Team Size:** 1 backend developer

#### Problem Statement
Currently each ontology is stored in its own named graph backed by **dedicated collections** (e.g. `ontology_import_abc123_classes`, `ontology_import_abc123_edges`). This leads to:
- **Collection proliferation:** Every import/extraction creates new ArangoDB collections, hitting cluster limits in production.
- **Cross-ontology queries require UNION over N collections** instead of a single filtered scan.
- **No shared namespace/URI index:** Duplicate URIs across ontologies are invisible until ER runs.
- **Import graph (§6.15) is hard to implement:** dependency edges between ontologies span collection boundaries.
- **Backup/restore complexity:** Hundreds of small collections instead of a few large ones.

#### Proposed Direction
Move to a **fixed set of shared collections** (e.g. `ontology_classes`, `ontology_edges`, `ontology_properties`) where each document carries:
- `ontology_id` — which ontology it belongs to
- `namespace` — the URI namespace for grouping/filtering
- Existing temporal fields (`created`, `expired`) for time-travel

Ontology isolation switches from "separate collection" to "filter by `ontology_id`" (with a persistent index on that field). Named graphs can still be defined as filtered views over the shared collections if needed for ArangoDB Graph API compatibility.

#### Analysis Tasks (Spike)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| U.0 | Inventory current collection-per-ontology usage | Backend | 4h | Catalog every place that creates/references per-ontology collections (repos, migrations, graph definitions, AQL queries). |
| U.1 | Design shared collection schema | Backend | 4h | Define the unified document schema with `ontology_id`, `namespace`, indexes. Write ADR. |
| U.2 | Migration strategy | Backend | 4h | Plan data migration from N collection pairs → shared collections. Must be reversible. |
| U.3 | Performance benchmarking | Backend | 4h | Compare query performance: current (small dedicated collections) vs. proposed (large shared collection + `ontology_id` index) at 10, 50, 100 ontologies. |
| U.4 | Impact on temporal queries | Backend | 2h | Verify that time-travel queries still perform well with the extra `ontology_id` filter dimension. |

#### Implementation Tasks (Post-Spike, if approved)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| U.5 | Create shared collections + migration | Backend | 8h | New migration creating `ontology_classes`, `ontology_edges`, `ontology_properties` with composite indexes. Data migration script. |
| U.6 | Update repositories | Backend | 8h | Rewrite class/edge/property repos to use shared collections with `ontology_id` filter instead of dynamic collection names. |
| U.7 | Update extraction pipeline | Backend | 4h | Pipeline writes to shared collections with correct `ontology_id`. |
| U.8 | Update import/export | Backend | 4h | OWL/Turtle import targets shared collections. Export filters by `ontology_id`. |
| U.9 | Namespace index + cross-ontology queries | Backend | 4h | ArangoSearch view or persistent index on `namespace` + `uri` for cross-ontology dedup and browsing. |
| U.10 | Update tests | Backend | 4h | All affected tests updated for shared-collection access pattern. |

**Exit Criteria:** All ontology data lives in shared collections. Cross-ontology queries use simple filters. Collection count is O(1) not O(N). All existing tests pass.

---

### Stream 10: Workspace UX — Selection Sync & Interaction Polish
**PRD:** §6.4 FR-4.16a (bidirectional selection sync), §6.4 FR-4.14 (context menus)
**Duration:** 0.5 weeks remaining
**Priority:** P1 — high-impact UX with minimal scope
**Dependencies:** None
**Team Size:** 1 frontend developer

#### Tasks

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| W.1 | `focusNode(key)` on SigmaViewportApi | Frontend | **DONE** | `SigmaViewportApi` extended with `focusNode(nodeKey)` that animates the camera to center on the given node. The camera zooms to `ratio ≤ 0.4` for visibility. |
| W.2 | `selectedNodeKey` prop on SigmaCanvas | Frontend | **DONE** | New prop drives a combined `nodeReducer` that applies a persistent `highlighted` ring on the selected node (Sigma's built-in highlight style), composable with the existing `visibleNodeKeys` filter. |
| W.3 | `selectedClassKey` + `onSelectClass` props on AssetExplorer | Frontend | **DONE** | New props propagate through `OntologyItem` → `ClassItem`. `ClassItem` button gets an indigo selection ring; `scrollIntoView({ block: "nearest", behavior: "smooth" })` auto-scrolls when selected from the graph. |
| W.4 | Auto-expand ontology tree on graph selection | Frontend | **DONE** | When `selectedClassKey` is set (from a graph click), the parent `OntologyItem` auto-expands its Classes section so the highlighted row is visible. |
| W.5 | Workspace page wiring | Frontend | **DONE** | `handleSelectClassFromSidebar` calls `focusNode` + sets `selectedNodeKey`. Both `SigmaCanvas.selectedNodeKey` and `AssetExplorer.selectedClassKey` are driven by the same `selectedNodeKey` state. |
| W.6 | Edge selection in sidebar | Frontend | 2h | Click an edge (relation) row in the sidebar to select and center on that edge in the graph. Requires `focusEdge` on viewport API. |
| W.7 | Keyboard navigation | Frontend | 3h | Arrow keys navigate between class rows in the sidebar (up/down); Enter opens detail panel; Tab cycles between sidebar and canvas focus. |
| W.8 | Minimap selected indicator | Frontend | 1h | Selected node shown as a bright dot on the Sigma minimap (if minimap is enabled). |

**Exit Criteria:** Clicking a class in either the sidebar or the graph highlights and centers the same entity in both views. The interaction feels instant and fluid.

---

## Recommended Execution Order

```
Week 1-2:    Stream 1 Phase 1 (Import Tracking & Catalog) + Stream 2 (ER) — in parallel
Week 3:      Stream 1 Phase 2 (Ontology Composition) + Stream 3 (Constraints) — in parallel
Week 4:      Stream 4 (Quality Dashboard) + Stream 5 Phase 1 (Core Schema Extraction) — in parallel
Week 5:      Stream 5 Phase 2-3 (Named Graph Mapping & UI)
Week 6:      Stream 6 (Testing & CI)
Week 7:      Stream 7 (Production Polish)
             → v1.0.0 Release
Week 8-10:   Stream 8 (Sigma.js Migration) — post-release
```

### Parallelization Opportunities

| Parallel Track A | Parallel Track B | Notes |
|-----------------|-----------------|-------|
| Stream 1 Phase 1 (Imports) — backend heavy | Stream 2 (ER) — backend heavy | No dependencies between them |
| Stream 1 Phase 2 (Composition) — backend | Stream 3 (Constraints) — backend | Composition depends on Phase 1 but not on Constraints |
| Stream 4 (Quality Dashboard) — frontend | Stream 5 Phase 1 (Schema Core) — backend | No overlap |
| Stream 5 Phase 2 (Named Graph) — backend | Stream 4 (Quality Dashboard) — frontend | Schema depends on Stream 1 for imports integration |

### Risk Factors

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `arango-entity-resolution` library API changes | Stream 2 delay | Pin library version, review API before starting |
| Large ontology import performance (FIBO = 20K+ classes) | Stream 1 delay | Test with FIBO early, optimize batch imports |
| LLM extraction unreliability (empty responses) | Ongoing | Already mitigated with 5 retries + backoff; consider adding Anthropic fallback |
| React Flow → Sigma.js migration complexity | Stream 8 delay | Build Sigma component alongside React Flow first, switch over when ready |
| Effective ontology graph size explosion (deep import chains) | Stream 1 Phase 2 performance | Limit transitive depth (configurable, default 5), cache effective graph with ETag invalidation |
| Cross-database schema extraction security | Stream 5 risk | Never persist target DB credentials; use connection pooling with timeout; document security model |
| `arangodb-schema-analyzer` library unavailable | Stream 5 Phase 2 delay | Built-in direct mapping fallback (S.8) ensures core functionality without the optional library |

---

## Metrics & Definition of Done

### v1.0.0 Release Criteria

- [ ] All PRD §6 features implemented (Streams 1–5)
- [ ] CI pipeline passes on every commit (Stream 6)
- [ ] Backend test coverage ≥ 80%
- [ ] Frontend test coverage ≥ 60%
- [ ] No critical or high-severity bugs open
- [ ] Performance benchmarks documented (Stream 7)
- [ ] Production deployment guide complete
- [ ] README updated with current state

### Quality Targets (PRD §3.2)

| Metric | Target | How Measured |
|--------|--------|-------------|
| Extraction precision | ≥ 80% classes accepted without edits | Curation acceptance rate |
| Extraction recall | ≥ 70% of gold-standard concepts found | Gold-standard comparison |
| Curation throughput | 50+ concepts/hour | Curation timer |
| Deduplication accuracy | ≥ 85% merge suggestions correct | ER acceptance rate |
| Time to first ontology | < 30 minutes | Upload-to-completion timing |
