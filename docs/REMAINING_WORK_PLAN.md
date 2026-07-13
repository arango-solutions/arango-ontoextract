# AOE — Remaining Work Plan

**Document Version:** 3.5
**Date:** July 5, 2026
**Baseline:** v1.1.0 (released) — supersedes v1.0.0, v0.4.0-dev (perf/IBR streams), v0.3.0, v0.2.0 and v0.1.0
**PRD Reference:** `PRD.md` — Arango-OntoExtract Product Requirements Document

---

## Executive Summary

The AOE (Arango-OntoExtract) system has a working end-to-end extraction pipeline, ontology editor, pipeline monitor, quality metrics, multi-document support, **iterative belief-revision substrate**, and **substantial workspace-load performance work**. This document details the remaining work required to achieve full PRD compliance and production readiness.

**Completed (v0.4.0-dev):** ~95% of PRD requirements. Shipped: Streams 1 (Imports + Composition), 2 (Entity Resolution, hand-rolled), 3 (Constraints v1), 4 (Quality Dashboard Q.2–Q.5), 5 (Schema Extraction), 6 (Testing & CI — 5-tier pipeline + coverage gates), 7 (Production Ops), 11 (Belief Revision Phases 1–3), 12 (perf T1–T5, T7–T10), 13 (Image-Aware Extraction), and the **Sigma.js core of Stream 8** (the workspace canvas is WebGL now).
**Released — v1.0.0:** the full PRD §6 functional scope. All of the previously-tracked v1.0.0 tail items are closed (Stream 12 T6 — `/effective` per-stage `ms_*` telemetry + a real-DB profile that pinned the O(n²) subclass-cycle DFS at 1.9s on 3000 classes, rewritten as a linear three-colour DFS → 42ms (~45×), making `/edges` + `/effective` pagination unnecessary; Stream 3 I.7 curator approve/reject/edit in `fbb72db`; Stream 4 exit criteria met).
**Released — v1.1.0:** CH.1 structure-aware chunking foundation (`doc_format` + slide/page index on chunks, `eed591a`), CQ.3 `app/api/ontology.py` split into a cohesive sub-router package (`2ff0c26`), and **Stream 18 — Relational Schema → Ontology** (RS.1–RS.4: `relational-schema-analyzer` adopted, relational→OWL/SHACL mapping, MCP preview/extract tools, `RelationalExtractionOverlay`). The `relational-schema-analyzer` library was extracted from `r2g` and is no longer blocking.
**Post-v1.1 (remaining):** Stream 16 (Domain Detection & Multi-Ontology Routing, DD.1–DD.5); Stream 17 (Structure-Aware Chunking CH.2–CH.5, deck/slide-aware); Stream 5 PR 4 (Schema-Analyzer LLM enrichment, applies to both ArangoDB and relational output); Stream 19 (LLM-Assisted Release Governance, RR.1–RR.6); Stream 14 code-quality tail (CQ.4(b), CQ.5 rename/reparent wiring); Stream 8 editor panels (semantic zoom, edge bundling, property matrix, restriction editor, namespace manager, validation console) + legacy-route removal; Stream 9 unified-storage spike; Stream 4 RAG-benchmark comparison UI (optional, needs a spec). See the refreshed execution order below.

### v0.3.0 highlights (since v0.2.0)

- **Performance:** `?include=summary` projections on `/classes` + `/edges` (~3x payload reduction); single-item `/edges/{key}` and `/properties/{key}` endpoints (kills the workspace detail-panel N+1); module-level `ontologyDataCache` with in-flight dedup and mutation-driven invalidation (instant ontology re-visit); `GET /edges` collapsed from 8-14 sequential WAN round-trips to 2 (one `db.collections()` plus one AQL with FLATTEN-over-subqueries).
- **Importer robustness:** RDF format sniffer overrides misleading file extensions (`.owl` content that's actually Turtle now imports cleanly); parse failures surface a "rename to .ttl/.rdf" suggestion plus a preview of offending bytes.
- **Workspace UX fixes:** Loading spinner shows the right ontology name (no more flashing the previous ontology while switching); VCR timeline defaults to LATEST event on ontology load (no more partial canvas requiring manual scrub to the right edge).
- **Stage-level perf telemetry:** `list_ontology_classes`, `fetch_live_edges_and_properties`, and `list_ontology_edges` all log per-stage `ms_*` so future optimization is data-driven, not guess-driven.

### v0.2.0 highlights (Stream 11 Phase 1 + Phase 2)

The full belief-revision substrate (`revision_meta` collection, evidence-age + evidence-count signals, confidence decay, ontology rule engine R1–R4, touchpoint discovery, mechanical verdict classifier, LLM revision agent, Levi-identity supersede helper, LangGraph belief-revision node wired into the pipeline behind a feature flag, integration tests over the Q.1–Q.3 fixtures) shipped in v0.2.0. **Phase 3 (Revisions Inbox UX, accept/reject/modify endpoints, background consolidation, MCP tools, dashboard tiles, safety guards) is the only remaining IBR work.**

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
| Document Ingestion (§6.1) | **Complete** | Upload (PDF, DOCX, PPTX, MD), chunking, auto-extraction trigger, multi-doc, CRUD. Image-aware extraction shipped (Stream 13): embedded images / scanned pages are inventoried, captioned via OpenAI Vision or on-prem Tesseract when configured, and surfaced to extraction prompts with slide/page provenance + orphan-risk warnings. |
| Extraction Pipeline (§6.2, §6.11) | **Complete** | 6-agent LangGraph pipeline (strategy, extractor, consistency, quality judge, entity-resolution, filter), async/concurrent, 7-signal confidence scoring. ER agent is a real (hand-rolled) node — see Stream 2 |
| Tier 2 Extensions (§6.3) | **Complete** | Domain context injection, tier2 prompts, strategy auto-detection |
| Visual Curation (§6.4) | **Complete** | Workspace graph canvas with two graph-style renderers: **Network (circles) → Sigma.js + graphology, WebGL** (`SigmaCanvas`, Stream 8 core) and **Box & Arrow (UML) → React Flow** (`BoxArrowCanvas`). Node/edge actions, VCR timeline, diff view, provenance, standalone editor with CRUD. Legacy `/curation` + `/ontology/edit` routes also use React Flow pending deprecation. |
| Temporal Time Travel (§6.5) | **Mostly Complete** | Edge-interval versioning, snapshot API, timeline events, VCR slider. Missing: playback animation |
| ArangoDB Visualizer (§6.6) | **Complete** | Themes, canvas actions, saved queries (temporal-aware), viewpoints, auto-install |
| MCP Server (§6.10) | **Complete** | Runtime MCP tools for ontology operations |
| Pipeline Monitor (§6.12) | **Complete** | Real-time step DAG with polling, metrics (tokens, cost, entities, confidence, completeness, agreement), error log |
| Quality Metrics (§6.13) | **Mostly Complete** | Multi-signal confidence (7 signals incl. faithfulness judge + semantic validator), ontology health score, quality panel in library, unified `/dashboard`, **Per-Ontology Quality** tab (live `GET /quality/{id}` radar + cards), recharts radar on scorecard drill-down, audited OntoQA panel, connectivity metric, `/quality/history` (Q.2), gold-standard recall API + overlay (Q.4). Stream 4 exit criteria met (Q.1–Q.5 shipped). The optional RAG benchmark UI is unscoped and moved to post-v1.0. |
| Import/Export (§6.8) | **Complete** | Export (Turtle, JSON-LD, CSV, SHACL), OWL import via ArangoRDF, library search (ArangoSearch), tagging, full CRUD with cascade, imports graph (migration `025`, `ontology_imports_graph.py`), standard ontology catalog (`GET /catalog`, Stream 1 H.5). |
| Admin (§7.2.1) | **Complete** | Soft/full reset (with named graph cleanup), extraction run deletion |
| Deletion & Integrity | **Complete** | Temporal soft-delete for ontology deprecation, cross-ontology edge cascade, curation reject cascade, document delete with provenance expiry. See `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`. |

### What's Not Done

| Area | Status | Gap |
|------|--------|-----|
| Entity Resolution (§6.7) | **COMPLETE hand-rolled (Stream 2 closed, v0.4.0-dev)** | `er_agent_node` is a real LangGraph node (blocking, weighted scoring incl. topological similarity, union-find clustering, golden-record merge via temporal `update_class` + `expire_entity`, cross-tier edges). Run-scoped REST under `/api/v1/er/` + per-pair accept/reject/explain, workspace `MergeCandidatesOverlay` ("Find Duplicates…"), and three MCP tools all ship. The `arango-entity-resolution` library is installed but intentionally unused — its services are person-record-focused and a poor fit for ontology classes; hand-rolled is the correct domain fit (see Stream 2 plan-vs-reality audit). |
| Imports, Composition & Dependencies (§6.15, §6.8.8–8.16) | **COMPLETE (Phase 0 + Phase 1 + Phase 2a + Phase 2b shipped in v0.4.0-dev)** | `owl:imports` edge tracking, imports CRUD, `ontology_imports` named graph, standard ontology catalog (`/ontology/catalog` + bundled DCMI sample), `GET /imports-graph` DAG endpoint, cascade-on-delete impact, base-ontology selector on extraction, OWL exports preserving `owl:imports`, workspace catalog-browser overlay, workspace imports-dependency overlay (DAG canvas + library deep-link), three Visualizer saved queries, effective-graph API (`GET /{id}/effective` with inline conflicts + ETag), merge-conflict detection (duplicate URI / duplicate label / subclass cycle via import), canvas rendering of imported entities (dashed slate border + dimmed fill on Sigma + box-arrow + "Open Source Ontology" context-menu deep-link, with the legend swatch surfacing only when imports are present), drag-and-drop import composition (drag any ontology row onto the canvas to add an `imports` edge, with self/duplicate pre-check, cycle detection on the backend, undo-toast on success, and per-entity "Remove Import (<source name>)" context-menu entries — all routed through a new module-level toast surface), and import-aware extraction prompts (the effective ontology — own + transitive imports — is serialized as a tree-shaped header + reuse guidelines and prepended to `domain_context` for every extraction targeting a composed ontology, so the LLM is told which classes already exist and instructed to reuse via `rdfs:subClassOf` / `owl:equivalentClass` rather than minting duplicates the conflict detector will later flag) are all shipped. |
| Belief Revision UX (§6.16, Stream 11 Phase 3) | **Complete (v0.4.0-dev)** | Revisions Inbox overlay (IBR.14), inline detail panel (IBR.15), accept/reject/modify REST + service (IBR.16), background consolidation + admin endpoints (IBR.17), four safety guards (IBR.18), Quality Dashboard "Revisions Activity" tile (IBR.19), six MCP tools (IBR.20), and docs cross-link (IBR.21) all shipped. See ADR-008 implementation status appendix. |
| Constraints (§6.14) | **PR 1–PR 5 shipped (v0.4.0-dev)** | Extraction (PR 1) → OWL restriction import (PR 2) → SHACL shapes import (PR 3) → materialization → API → temporal → rule engine alignment + workspace UI display (PR 4) + OWL Turtle restriction export & new SHACL shapes export (PR 5) all shipped (I.1–I.6, I.8, I.9, plus rule-engine schema reconciliation and SHACL/OWL cross-vocab combination). Stream 3 v1 complete. I.7 (curator approve / reject / edit mutation actions) also shipped in commit `fbb72db` — three mutation endpoints (`POST /{id}/constraints/{key}/approve`, `POST .../reject`, `PUT .../{key}`) backed by temporal repo helpers, the `ConstraintManageRow` UI in `ClassConstraintsSection`, and 12+ tests. Stream 3 fully closed. |
| Schema Extraction (§6.9) | **Complete (v0.4.0-dev)** | Stream 5 PR 1 (backend extraction) + PR 2 (schema-extraction overlay) + PR 3 sub-A (S.9 constraint mapping) + PR 3 sub-B backend (S.5 schema diff endpoint) + **S.5 frontend overlay** (`SchemaDiffOverlay` on `/workspace`, context menus) all shipped. |
| Quality Dashboard (§6.13.7) | **Mostly Done (v0.4.0-dev)** | Unified `/dashboard`, `/quality` → per-ontology tab, recharts radar, audited OntoQA metrics, connectivity metric, qualitative evaluation, live per-ontology six-dimension view, **event-tagged history tracking (Q.2)**, **trend sparklines (Q.3)**, **gold-standard recall (Q.4)**, **curation throughput timer (Q.5)**. Complete — exit criteria met. The optional RAG benchmark comparison UI was never a formal Stream 4 task and is deferred to post-v1.0. |
| Workspace Performance (Stream 12) | **Mostly Done (v0.4.0-dev)** | T1+T2+T3+T4+T5 (projections, single-item endpoints, client cache, FLATTEN consolidation, telemetry, format sniffer, UI race fixes), T7 (`/runs/{id}/cost` quality cache), T8 (`/runs` bulk-enrichment in 2 AQL), T9 (no `include=full` on canvas paths), and **T10 `/classes` keyset pagination** all shipped. Remaining: T6 WTW switch profile (needs a real per-stage capture); `/edges` + `/effective` pagination intentionally deferred (see T10 row — canvas uses `/effective`, and both need whole-set handling that a profile should justify first). |
| Testing & CI (§8) | **Complete (Stream 6 PR 1 + PR 2, v0.4.0-dev)** | 5-tier GitHub Actions pipeline (`.github/workflows/ci.yml`): lint (ruff + mypy on py3.11/3.12, eslint + tsc) + pre-commit drift backstop → unit (backend `--cov-fail-under=80`, frontend Jest `coverageThreshold` 55/70/70/55) → integration (ArangoDB + Redis service containers) → E2E (backend pytest + Playwright `workspace.spec.ts`) → unified Docker image build + health/WS smoke. ~1700 backend + ~590 frontend tests; Codecov upload on both layers. See Stream 6 audit. |
| Production Ops (§8.5) | **Stream 7 complete (v0.4.0-dev)** | Stream 7 PR 1 (TTL GC + visualizer auto-install), PR 2 (OpenTelemetry tracing), PR 3 (alerting + prod docker-compose hardening + monitoring profile), PR 4 (ops benchmarks harness + README/docs refresh). All four PRs shipped. |
| Image-Aware Extraction (§6.1, §6.2, §6.11) | **Complete (Stream 13 IMG.1–IMG.8 + OpenAI Vision + Tesseract adapters)** | Visual asset inventory (PPTX picture/chart shapes, PDF image blocks, scanned-only pages); labeled placeholders + alt-text + caption markers in chunk text; `chunk_kind` + per-chunk `visual_assets` propagated through chunking; `visual_heavy_presentation` strategy + `tier1_visual_aware` prompt; both cloud (`OpenAIVisionCaptionProvider`) and on-prem (`TesseractCaptionProvider`) caption adapters auto-loaded lazily on `visual_caption_provider="openai_vision"` / `="tesseract"` + no-op default + per-doc cap; orphan-risk warning persisted to `extraction_runs.stats.warnings` when visual-heavy input correlates with parent-less classes; regression coverage in `tests/unit/test_visual_extraction_regression.py`, `tests/unit/test_visual_captions_openai.py`, and `tests/unit/test_visual_captions_tesseract.py`. |
| Visualizer Migration (Stream 8) | **Sigma.js canvas DONE; editor panels outstanding** | The default `/workspace` Network graph style runs on **Sigma.js + graphology** (`SigmaCanvas.tsx`: WebGL renderer, ForceAtlas2 / circular / grid / random layouts, PageRank sizing, noverlap) with a class-tree browser (`ClassHierarchy` / `AssetExplorer`, search + drag-to-reparent) — i.e. V.1 / V.2 / V.5 shipped as part of the object-centric workspace. React Flow is **not fully retired**: it still backs the workspace **Box & Arrow (UML) graph style** (`BoxArrowCanvas`), the **legacy routes** (`/curation`, `/ontology/edit`, `/entity-resolution`), and the **pipeline DAG** (`AgentDAG.tsx`). Outstanding: TopBraid-class editor panels (V.3 semantic zoom, V.4 edge bundling, V.6 property matrix, V.7 restriction editor, V.8 namespace manager, V.9 validation console) and legacy-route migration/removal (V.10 / V.11). See Stream 8 audit. |

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

### Known Extraction Quality Gaps (Test Fixtures for Stream 11)

These are concrete, reproducible cases observed in the live demo where the
extraction pipeline produced an incomplete or inconsistent ontology. Each one
is a regression test fixture for the Belief Revision work in Stream 11
(IBR.4 rule engine, IBR.7 mechanical verdict, IBR.13 end-to-end tests). Do
not patch these by hand on the live database — fixing the symptom hides the
underlying gap that the Belief Revision Agent must learn to catch.

| # | Ontology | Observed Gap | Expected Behavior | Verdict the Pipeline Should Emit | Owning Task |
|---|----------|--------------|-------------------|----------------------------------|-------------|
| Q.1 | Financial Services Domain (`225351740`) | `Account` and `Escrow Account` exist as sibling classes with no `subClassOf` edge between them. `Checking Account subClassOf Account` is correctly extracted, so the schema is internally inconsistent. | `Escrow Account subClassOf Account` should be inferred from naming convention + sibling pattern (Checking/Savings/Escrow are all account subtypes). | `GAP-FILLING` — Touchpoint Discovery (IBR.5) flags the label-overlap signal, Mechanical Verdict (IBR.7) classifies as gap-filling, LLM Revision Agent (IBR.8) proposes the `subClassOf` edge with evidence quote from the source document. | IBR.13 |
| Q.2a | Financial Services Domain (`225351740`) | `ExtendedTransaction` has no `subClassOf` edge to `Transaction`, yet other classes use it polymorphically: `Alert.linked_transactions → ExtendedTransaction` and `SuspiciousActivityReport.describes → ExtendedTransaction`. It also redeclares `originator` and `beneficiary` properties already present on `Transaction`. | `ExtendedTransaction subClassOf Transaction` (strongest signal: polymorphic range usage + overlapping property set + name-prefix overlap). | `GAP-FILLING` — Touchpoint Discovery flags label-overlap **and** property-set overlap **and** range-substitution; Mechanical Verdict (IBR.7) classifies as gap-filling with high confidence; LLM agent confirms with evidence from source. | IBR.13 |
| Q.2b | Financial Services Domain (`225351740`) | `TransactionDetail` has no edge connecting it to `Transaction`, but it duplicates Transaction's `originator` / `beneficiary` properties — suggesting either subclass-of OR part-of (e.g. `Transaction --hasDetail--> TransactionDetail`). | The pipeline should not silently guess; it should escalate. Either (a) `TransactionDetail subClassOf Transaction`, or (b) `Transaction hasDetail TransactionDetail` (composition), with the choice driven by source-text evidence. | `UNCERTAIN` — Mechanical Verdict cannot disambiguate subclass-vs-composition from structural signals alone; LLM Revision Agent (IBR.8) reads the source provenance to choose; if confidence is below threshold, action is `FLAG_FOR_CURATION`. | IBR.13 |
| Q.2c | Financial Services Domain (`225351740`) | `TransactionChannel` is disconnected from `Transaction` despite the obvious semantic link (a transaction occurs through a channel: ATM, online, mobile, etc.). `ExtendedTransaction` already has a `transaction_channel` property pointing here, so the relationship exists at the extended level but is missing at the base. | `Transaction --channel--> TransactionChannel` (object property, **not** subClassOf — channel is a co-classifier, not a subtype). | `GAP-FILLING` of a relationship (not a class hierarchy) — Touchpoint Discovery flags the property-name match (`*_channel`) on a sibling class; Mechanical Verdict classifies as missing object-property; LLM agent proposes the edge with cardinality. | IBR.13 |
| Q.3a | Financial Services Domain (`225351740`) | Of nine account-related classes, only `CheckingAccount` has `subClassOf Account`. Five clear banking subtypes are orphaned: `EscrowAccount` (also Q.1), `MerchantSettlementAccount`, `NostroAccount`, `VostroAccount`, plus the implicit `MuleAccount` parent (see Q.3b). | All five should have `subClassOf Account` (Nostro and Vostro are formal banking terms; Merchant Settlement and Escrow are functional account types). | `GAP-FILLING` (batch) — exercises the rule engine's ability to propose **multiple** edges in a single revision pass (FR-16.6) without N independent LLM calls. Touchpoint signals: name suffix `*Account` + structural similarity to `CheckingAccount`. | IBR.13 |
| Q.3b | Financial Services Domain (`225351740`) | `ThirdPartyMuleAccount` exists as a leaf class but its implied parent `MuleAccount` was never extracted, so the taxonomy has a hole. The name itself encodes a two-level hierarchy: `ThirdPartyMuleAccount → MuleAccount → Account`. | The pipeline should **propose a new intermediate class** `MuleAccount subClassOf Account`, then attach `ThirdPartyMuleAccount subClassOf MuleAccount`. | `REFINED` with class **creation** (not just edge creation) — this is the hardest verdict because it requires the LLM Revision Agent (IBR.8) to propose new vertices, not just new edges. Source-text evidence required; in absence of it, action is `FLAG_FOR_CURATION`. | IBR.13 (extension) |
| Q.3c | Financial Services Domain (`225351740`) | `AccountStatus` and `MuleAccountActivity` share the `Account` name prefix but are **not** account subtypes. `AccountStatus` is an enum/vocabulary (it has a `value` property); `MuleAccountActivity` is an activity observed on a mule account. A naive prefix-match rule would wrongly classify both as `subClassOf Account`. | `Account --status--> AccountStatus` (relationship, like Q.2c). `MuleAccountActivity` should reference an account (`MuleAccountActivity --observedOn--> MuleAccount`), not be a subtype of one. | **Negative test:** Mechanical Verdict (IBR.7) must **NOT** emit `GAP-FILLING(subClassOf)` here despite the name overlap. The `*Status`/`*Activity` suffix and the presence of independent attributes are disambiguating signals the rule engine must learn. Critical regression test for false-positive prevention. | IBR.13 (negative) |
| Q.4 | PPTX deck with visual hierarchy | PowerPoint decks that encode class hierarchy in screenshots, diagrams, SmartArt-as-image, or title-only slides can yield orphan classes because the current parser extracts text boxes/tables/notes only. Embedded images and scanned pages are omitted from chunks; slide headings are stored as metadata but not always visible to the LLM. | PPTX/PDF ingestion should inventory visual assets, OCR/caption them when configured, feed labeled visual context to extraction prompts, and preserve slide/page provenance. The extraction run should warn when high orphan count correlates with visual-heavy input. | `GAP-FILLING` + ingestion remediation — first fix evidence capture (Stream 13), then let belief revision repair residual hierarchy gaps with visual evidence citations. | Stream 13 + IBR.13 |

When a new gap is observed in the demo, append a new row here rather than
patching the live data. The growing list becomes the acceptance suite for
Stream 11 Phase 2.

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
**Duration:** Phase 0 + Phase 1 (1a + 1b) + Phase 2a complete in v0.4.0-dev. Phase 2b (canvas rendering / drag-and-drop / extraction prompts) remaining.
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
| H.2 | `ontology_imports` named graph | Backend | **DONE (v0.4.0-dev)** | Migration `025_ontology_imports_graph.py` creates the `ontology_imports` named graph (`ontology_registry` vertices ↔ `imports` edges). Defensive guards skip if either collection is missing; idempotent against re-runs. Tests: 5 unit tests on the migration's guard logic + idempotency, plus 1 integration test that verifies the graph exists with the correct single edge definition after `apply_all`. |
| H.3 | Imports API endpoints | Backend | **DONE (v0.4.0-dev)** | `GET /{id}/imports` + `GET /{id}/imported-by` shipped in Phase 0. New: `GET /api/v1/ontology/imports-graph?root=<key>&direction=both&max_depth=<n>` returning `{nodes, edges, root, direction, truncated}`. Backed by `app/services/ontology_imports_graph.py` (`build_imports_dag`) which handles whole-registry or rooted-subgraph traversal via one AQL pass per direction; output sorted + de-duplicated for flicker-free UIs. Tests: 11 service unit tests (full DAG / rooted / direction / depth clamp / missing collections) + 3 API tests (routing, parameter validation, error shape). |
| H.4 | Cascade analysis on delete | Backend | **DONE (v0.4.0-dev)** | New service `app/services/ontology_dependency.py` traverses the `imports` graph (transitive, INBOUND, BFS, depth-bounded), counts cross-ontology `extends_domain` edges, per-collection expirations, extraction runs (target + domain), quality history snapshots, released versions, and pending revisions. New endpoint `GET /api/v1/ontology/library/{id}/deletion-impact` returns the report; the existing `DELETE` dry-run path now embeds the same payload under `deletion_impact`. Frontend `OntologyDeleteDialog.tsx` overlay fetches the impact, lists transitive dependents with depth, renders an expire-counts table + warnings, and gates the destructive action behind the typed-name confirmation. Replaces the inline `requestConfirm` flow in `contextMenus/ontology.ts`. Tests: 14 backend service unit tests + 3 API tests + 7 frontend dialog tests + updated context-menu test. |
| H.5 | Standard ontology catalog | Backend | **DONE (v0.4.0-dev)** | Curated catalog at `backend/app/data/standard_ontology_catalog.json` (DCMI, FOAF, PROV-O, SKOS, OWL-Time, FIBO modules, Schema.org). One ontology (DCMI Terms minimal) is bundled inline at `backend/app/data/ontologies/dcterms_minimal.ttl` as an offline-importable proof of concept; the rest are URL-only and fetched on demand. Service `app/services/standard_ontology_catalog.py` loads via `importlib.resources` (portable across PyInstaller/wheel installs), resolves bundled vs. remote sources, and delegates to `arangordf_bridge.import_from_file` / `import_from_url`. New endpoints: `GET /api/v1/ontology/catalog` (list) + `POST /api/v1/ontology/catalog/{catalog_id}/import` (one-click import; returns the new `registry_key`). Tests: 14 service unit tests (catalog shape, bundled-vs-URL resolution, import dispatch, error paths) including a smoke test that imports the bundled DCMI file end-to-end. |
| H.6 | Catalog import UI | Frontend | **DONE (v0.4.0-dev)** | `CatalogBrowserOverlay.tsx` (workspace overlay per UI rule 9, not a new route). Fetches the catalog, renders one row per entry (name + description + class/property counts + tags + bundled/remote badge + tier badge), and one-clicks `POST /ontology/catalog/{id}/import` with a per-row spinner. Already-imported entries are detected against `GET /library` and replaced with an "✓ Imported" pill so the user never trips the 409 conflict. Invoked from two surfaces per UI rules 2 + 20: (1) the canvas right-click menu adds "Browse Standard Catalog…" (primary), (2) the Asset Explorer "Ontologies" section gains a 📚 header action + an empty-state CTA (discoverability). Esc + × close. Tests: 10 component tests (catalog fetch, per-source badges, already-imported disable, import dispatch, URL-encoded IDs, inline error display, registry-fetch fallback, Esc/× close, parent-supplied registry skip) + canvas-menu test for the new entry. |
| H.7 | Imports dependency graph in workspace | Frontend | **DONE (v0.4.0-dev)** | `ImportsDependencyOverlay.tsx` workspace overlay (per UI rule 9 — overlay, not a new tab on `/library`). Consumes `GET /imports-graph?root=<key>&direction=both` and renders a hand-rolled SVG Sugiyama-style layered DAG: root in the centre, ancestors (what this ontology imports) to the left, dependents (who imports this ontology) to the right, BFS depth = column index. Pure `computeLayout()` is exported and unit-tested so re-renders are flicker-free. Left-click selects + shows "Open in workspace" CTA; double-click re-roots the DAG on the clicked node; depth dropdown re-fetches with new `max_depth`; legend + truncation warning + empty-state copy. Wiring: (1) ontology right-click menu adds "View Dependency Graph…", (2) the legacy `/library` aside gets a "Dependencies" button that deep-links to `/workspace?ontologyId=X&overlay=dependencies` which the workspace page reads on mount to auto-open the overlay. Tests: 6 pure-layout tests (BFS layers, stable y-ordering, orphan column, diamond dedupe) + 10 component tests (fetch params, render, empty/error/truncated, depth change, Open-in-workspace, Esc/× close) + 3 ontology-menu tests for the new entry. |
| H.8 | Base ontology selector in extraction UI | Frontend | **DONE (v0.4.0-dev)** | Multi-select "Base Ontologies" picker on `/upload` (excludes the currently-selected target ontology so users can't request a self-import). Selected IDs are forwarded as `base_ontology_ids` to `POST /api/v1/extraction/run`. Backend (`app/services/extraction.py`) persists them on the run record and post-success calls `_record_base_ontology_imports`, which creates one `imports` edge per base id with robust skip-guards (missing target, missing base, self-import, duplicate, cycle) — the helper logs warnings and continues so a single bad id never fails the whole extraction. API layer (`app/api/extraction.py`) threads the new list through `create_run_record` + `execute_run`. Tests: 8 backend unit tests (`test_extraction_base_imports.py`: persistence, every skip-guard, AQL bind-var filtering, route-level pass-through) + 3 frontend tests (multi-select renders, target ontology is excluded from base options, selected ids appear in the POST body and are omitted when nothing is chosen). |
| H.9 | Visualizer queries for imports | Backend | **DONE (v0.4.0-dev)** | New `ontology_imports` graph entry in `scripts/setup/install_visualizer.py::GRAPH_CONFIGS` plus three asset bundles under `docs/visualizer/`: a theme (`themes/ontology_imports_theme.json`) styling registry nodes by `tier`/`status` and imports edges, three canvas actions (`actions/ontology_imports_actions.json`) for direct dependencies / direct dependents / full dependency tree, and three saved AQL queries (`queries/ontology_imports_queries.json`) named "Ontology Dependencies (Full DAG)", "Upstream Ontologies", "Downstream Dependents" — all of which exercise the `ontology_imports` named graph from H.2. Tests: 9 unit tests validating the JSON shape of every asset (`test_visualizer_imports_assets.py`) so a typo in a saved query is caught without needing a live ArangoDB visualizer to load it. |
| H.10 | Export includes `owl:imports` triples | Backend | **DONE (v0.4.0-dev)** | `app/services/export.py::_build_rdf_graph` now calls `_add_imports_to_graph`, which AQL-queries the live `imports` edges for the exported ontology and emits one `owl:imports` triple per dependency (preferring the target ontology's `name`/URI; falling back to `import_iri` when the target row is missing). Re-importable into AOE and external tools (FR-15.12). Tests: 6 unit tests (`TestExportOwlImports`) covering happy path, fallback-to-`import_iri`, skipped rows (missing both), absent collections, AQL filter correctness, and emitted-triple ordering. |

#### Tasks — Phase 2: Ontology Composition (Advanced)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| H.11 | ~~"Create Composed Ontology" API~~ | Backend | **DONE** | Merged into `POST /ontology/create` with `imports` parameter. |
| H.12 | Effective ontology API | Backend | **DONE (v0.4.0-dev)** | New service `app/services/ontology_effective.py` (`compute_effective_ontology`) walks `imports` OUTBOUND from the target (ancestors), unions classes/edges/properties for the full closure in 3 AQL round-trips (one per entity kind, parameterised by `oid IN @oids`), and stamps each entity with `source_ontology_id` / `source_ontology_name` / `is_imported`. New endpoint `GET /api/v1/ontology/{id}/effective?include=summary|full&max_depth=10` returns `{ontology_id, ontology_name, include, sources, classes, edges, properties, conflicts, etag, truncated}` with a weak `W/"..."` ETag derived from `(ontology_id, include profile, every source's updated_at)` so `If-None-Match` short-circuits to `304 Not Modified`. The `LIVE_EDGE_COLLECTIONS` / `LIVE_PROP_COLLECTIONS` allow-lists were lifted from `api/ontology.py` into `services/ontology_projections.py` so per-ontology and effective-graph paths share one source of truth. Tests: 23 service unit tests (registry lookup / self-only / transitive closure / depth clamp / summary vs full projection / edge annotation / missing collections / ETag stability + invalidation) + 8 API tests (200 with ETag header / 304 on weak match / W/ prefix-stripping comparison / 200 on stale validator / 404 missing / summary-vs-full ETag distinction / max_depth bounds). (FR-15.8) |
| H.13 | Import conflict detection | Backend | **DONE (v0.4.0-dev)** | Inline in `compute_effective_ontology`'s response under `conflicts[]`. Three kinds: (1) `duplicate_uri` — same `uri` in two or more *different* sources; same-ontology duplicates are filtered upstream because they are writer bugs, not merge conflicts; (2) `duplicate_label` — same `label` (case-insensitive, whitespace-stripped) in two or more sources with *different* URIs (same-URI cases are reported only as `duplicate_uri` to avoid double-reporting); (3) `subclass_cycle_via_import` — cycle in the merged `subclass_of` graph that requires at least one imported edge (a cycle entirely within self is owned by per-ontology validation). Cycles canonicalised by rotating the smallest node first so the same cycle is never reported via different starting points. Each conflict carries `{kind, key, sources: [{ontology_id, ontology_name, entity_key}], message}` so the UI can deep-link. Tests covered alongside H.12 (URI conflict / same-source URI not flagged / label conflict / same-URI not double-reported / cycle-via-import / self-only cycle not flagged). (FR-15.11) |
| H.14 | ~~Composed ontology creation UI~~ | Frontend | **DONE** | Merged into CreateOntologyDialog with multi-select imports. |
| H.15 | Effective graph rendering in canvas | Frontend | **DONE (v0.4.0-dev)** | Workspace canvas now sources the open ontology from `GET /api/v1/ontology/{id}/effective?include=summary` (one round-trip replacing the prior `/classes` + `/edges` pair); the response is cached under a new `effective` cache key, invalidated by every approve/reject/delete (including property mutations because the wire payload carries `properties[]`). New shared module `frontend/src/components/workspace/importedEntityStyle.ts` exposes `IMPORTED_NODE_BORDER` (a muted slate) + `dimColorForImported()` (linear mix toward slate-900 for `#rrggbb` / `#rgb` hex; saturation/lightness drop with an 18% L floor for `hsl(H, S%, L%)`; unrecognised forms returned unchanged); both Sigma and the React Flow box-arrow canvas now route every per-paint colour through this helper when the class/edge carries `is_imported: true`, so the encoding is identical across renderers. The class right-click menu (and edge menu) replaces the destructive section with a single `Open Source Ontology (<name>)` deep-link that calls `actions.handleSelectOntology(source_ontology_id)`; the entry is disabled-not-fired when `source_ontology_id` is absent so a malformed payload cannot trigger `handleSelectOntology(undefined)`. The legend (`CanvasLensLegend`) only renders the "imported" swatch row when at least one entity on the canvas is imported (controlled by a memoised `canvasHasImported` flag in `app/workspace/page.tsx`); the swatch text explicitly names the dashed border + dimmed fill encoding and tells the user the right-click is how they open the source. Tests added: `importedEntityStyle.test.ts` (10 cases pinning the dim math: factor=0 identity, factor=1 collapses to slate-900, default-factor linear mix, `#rgb` short-form expansion, HSL S/L drop, HSL L floor at 18%, identity branch for `rgb()` / named / empty / invalid hex), `ClassBoxNode` extended (3 cases: solid border + no pill on owned, dashed border + opacity-75 + "Imported from <name>" tooltip + aria-labelled pill on imported, generic source-label fallback), `CanvasLensLegend` extended (4 cases: swatch absent on default, absent when `hasImported=false`, present when `hasImported=true`, present across all 5 lenses), `class.test.ts` extended (6 cases: imported menu drops Approve/Reject/Delete, Open Source Ontology deep-links via `handleSelectOntology`, bare label when source name missing, disabled fallback when source id missing, History/Provenance still rendered, `is_imported: false` falls back to full menu), `edge.test.ts` extended (4 cases: same as class for the edge menu). Full frontend Jest suite green at 537 passing (was 519); `npm run type-check` and `npm run lint` clean. (FR-15.8) |
| H.16 | Drag-and-drop import composition | Frontend | **DONE (v0.4.0-dev)** | Every ontology row in `AssetExplorer` is now `draggable`; a dedicated `frontend/src/lib/importDragCheck.ts` module owns the canonical MIME (`application/x-aoe-ontology`), JSON payload shape (`{ontologyId, ontologyName}`), and the pure pre-check (`checkImportDragCandidate`) that catches self-imports + duplicates from the open ontology's effective-graph `sources[]` before any network round-trip. Cycles too deep for the closure fall through to the backend's 10-hop OUTBOUND BFS guard (`add_ontology_import`), and the 400 surfaces as an error toast. The workspace `<main>` canvas wrapper now accepts drops anywhere (Sigma + box-arrow alike) — `onDragOver` keys off the MIME so unrelated drags (file drags, native text drags) fall through. Successful imports invalidate the `effective` cache + bump the explorer's library nonce + emit an 8-second undo-toast whose action button issues `DELETE /imports/{target}`; the same `removeImportEdge` callback also backs a new per-entity "Remove Import (<source name>)" context-menu entry on imported classes and edges (rendered alongside "Open Source Ontology", danger-styled, disabled when `source_ontology_id` is missing). New module-level toast surface (`frontend/src/lib/toast.ts` + `components/workspace/ToastHost.tsx`) — pushed at the page root above `ManageImportsOverlay`'s `z-9999`, host owns auto-dismiss timers so unmount cancels every pending callback, subscribers receive the queue synchronously on subscribe (no flash-of-empty), throwing listeners are isolated on both `emit` and initial-delivery paths. Tests added: `lib/__tests__/toast.test.ts` (8 cases: defaults, kind/duration/action overrides, sync initial delivery, unsubscribe cuts further deliveries, dismiss is idempotent, clear is idempotent, throwing listener isolation), `lib/__tests__/importDragCheck.test.ts` (12 cases: clean pass, no-canvas / self-import / duplicate / deep-transitive duplicate / null-sources optimistic accept / blank-name fallback rejection branches, payload write/read round-trip, MIME pin, foreign-MIME `null`, malformed-JSON `null`, missing-field `null`), `components/workspace/__tests__/ToastHost.test.tsx` (7 cases: empty-queue renders nothing, push renders with right kind, fake-timer auto-dismiss, sticky `durationMs=0` never dismisses, action awaits async then dismisses, × dismisses without firing action, unmount cancels pending timers), `components/workspace/__tests__/AssetExplorerOntologyDrag.test.tsx` (2 cases: `draggable=true` on row, dragStart writes canonical payload + sets `effectAllowed=copy`), `contextMenus/__tests__/class.test.ts` extended (3 cases: imported menu adds Remove Import after Open Source Ontology, danger-styled, fires `removeImportEdge` with source id+name; falls back to source id when name absent; disabled when source id absent), `contextMenus/__tests__/edge.test.ts` extended (1 case: same for edges). Full frontend Jest suite green at 570 passing (was 537); type-check + lint clean. (FR-15.10) |
| H.17 | Import-aware extraction prompts | Backend | **DONE (v0.4.0-dev)** | New `serialize_effective_ontology_context(db, ontology_id, max_depth=10)` in `backend/app/services/ontology_context.py` consumes `compute_effective_ontology` (H.12) and emits a tree-shaped prompt header: `Existing ontology context (reuse these classes; do not duplicate):` followed by a `Your ontology (<name>):` section for owned classes and one `Imported from <SourceName> (depth N):` section per BFS-depth-ordered ancestor in the imports closure. Each class line is `- <label> [<uri>]`; `subclass_of` edges (when both ends share a source) drive two-space-indent nesting. Closes with explicit reuse guidelines (`REUSE its URI`, `parent_uri` + `classification: "extension"`, equivalence via `classification: "existing"`). Returns `""` for fresh-and-importless targets so greenfield runs are unchanged; `ValueError` from a missing registry entry is swallowed to `""` so a stale `target_ontology_id` never poisons a run. Wired into `services/extraction.py` immediately after the existing Tier 2 `serialize_multi_domain_context` block: when `target_ontology_id` is set, the effective context is **prepended** to `domain_context` (effective first so the LLM weights it more heavily; the existing org-level domain text is appended). Failures inside the closure walk are non-fatal — logged via `log.warning(... exc_info=True)` and the extraction continues with the pre-H.17 `domain_context`. The injected text flows through the existing `{domain_context}` slot in `tier1_standard` / `tier1_technical` / `tier2_standard` templates, so no prompt-template rewrite was needed. Tests: 6 unit cases for the serializer (empty target → empty string; owned-only renders self section + footer; imports render per-source sections with BFS-depth label; `subclass_of` edges produce nested tree; missing source name falls back to `_key`; unknown target → empty string), 3 integration cases on `services/extraction.py::execute_run` (target set → effective context prepended before existing domain context; target absent → serializer never invoked; serializer failure → run completes with pre-H.17 context, no crash). Full backend suite green at 1677 passing; mypy + ruff clean on `services/ontology_context.py` and `services/extraction.py`. (FR-15.9) |

#### Implementation Plan — Recommended Order

| Phase | Tasks | Est. Duration | Prerequisites |
|-------|-------|---------------|---------------|
| **Phase 0 (COMPLETE)** | H.0a–H.0e | — | None |
| **Phase 1a (COMPLETE v0.4.0-dev)** | H.2, H.3 (remaining), H.5, H.6, H.9 | shipped | Phase 0 |
| **Phase 1b (COMPLETE v0.4.0-dev)** | H.4, H.7, H.8, H.10 | shipped | Phase 1a |
| **Phase 2a (COMPLETE v0.4.0-dev)** | H.12, H.13 | shipped | Phase 1 |
| **Phase 2b: Canvas & Extraction (COMPLETE v0.4.0-dev)** | H.15, H.16, H.17 | shipped | Phase 2a |

**Stream 1 status:** ALL streams complete. Phase 0 (data model), Phase 1a/1b (catalog + dependency overlays), Phase 2a (effective-graph API + conflict detection), and Phase 2b (canvas rendering of imported entities + drag-and-drop import composition + import-aware extraction prompts) are all shipped in v0.4.0-dev.

**Exit Criteria — all met:** `owl:imports` tracked as edges ✓. Standard ontologies importable from catalog ✓. Imports dependency graph visible in UI and ArangoDB Visualizer ✓. Users can create composed ontologies that inherit imported axioms ✓ (via drag-and-drop or `ManageImportsOverlay`). Effective graph rendered in canvas with visual distinction for imported entities ✓ (H.15). Export preserves `owl:imports` ✓. Extraction into composed ontologies is import-aware ✓ (H.17 prepends the effective ontology tree + reuse guidelines to the LLM prompt's `domain_context`).

---

### Stream 2: Entity Resolution Integration
**PRD:** §6.7 FR-7.1–7.11
**Duration:** 1.5 weeks (rescoped — see plan-vs-reality audit below)
**Priority:** P1 — key differentiator for ontology quality
**Dependencies:** None (can run in parallel with Stream 1)
**Team Size:** 1 backend + 1 frontend developer

#### Objectives
- Replace the ER agent stub with real `arango-entity-resolution` library integration
- Configure blocking, scoring, clustering, and merge workflows for ontology concepts
- Surface merge candidates in the curation UI with explanations

#### Plan-vs-reality audit (v0.4.0-dev)

When Stream 2 was re-opened in v0.4.0-dev we discovered the plan tasks
ER.1–ER.9 had drifted significantly from the codebase. Most of the
backend was already shipped — hand-rolled inside `app/services/er.py`
rather than via the `arango-entity-resolution` library that is listed
in `pyproject.toml` but never actually imported. The frontend
`MergeCandidates` / `MergeExecutor` components on the deprecated
`/entity-resolution` route were built against an aspirational API
(`/api/v1/er/candidates`, `/api/v1/er/candidates/{pair_id}/accept`)
that the backend never implemented. The actual shipped REST surface
is run-id-scoped: `/api/v1/er/runs/{run_id}/candidates`.

Stream 2 was scoped as two PRs; only PR 1 was actually needed:

- **PR 1 — Workspace ER overlay (DONE, commit `a29c0a7`)** — fresh
  `MergeCandidatesOverlay` in the workspace, bound to the real
  backend, with new per-pair accept / reject / explain endpoints.
- **PR 2 — Library refactor (INTENTIONALLY DEFERRED)** — the
  `arango-entity-resolution` package (importable as
  `entity_resolution`) is installed at 3.5.1 but its
  `GoldenRecordService`, `BlockingService`, and `SimilarityService`
  are **person-record-focused**: default field strategies are keyed on
  `first_name`, `last_name`, `email`, `phone`, `address`, `city`,
  `state`, `zip_code`, `company`, etc. Forcing the swap on ontology
  classes (label / description / uri / tier) would require either
  ugly field-name remapping or verbose per-field strategy overrides,
  and the resulting golden-record output shape would no longer match
  the temporal `update_class` + `expire_entity` contract. Hand-rolled
  is the correct domain fit. Only `WCCClusteringService` would have
  been a clean swap (it takes a `db` directly and returns a
  `List[List[str]]` matching what `_execute_clustering` already
  produces) — but the in-memory union-find is fine at our current
  ontology sizes and trading it for a server-side AQL traversal is
  not worth the dependency churn until we have millions of similarTo
  edges to cluster.

  **Action:** keep the hand-rolled implementations; do not pursue the
  library swap. Re-open this section only if (a) we need golden
  records for non-ontology records (e.g. resolving documents or
  organisations) where the library's defaults fit, or (b) WCC
  performance on a real workload exceeds in-memory union-find
  capacity.

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| ER.1 | Install and configure `arango-entity-resolution` | Backend | **INSTALLED, INTENTIONALLY UNUSED (v0.4.0-dev)** | Library is in `backend/pyproject.toml` as `arango-entity-resolution>=0.1` and installs at 3.5.1 under the import name `entity_resolution`. `services/er.py` never imports it — every primitive (blocking, scoring, clustering, golden-record) is hand-rolled inline because the library's services are person-record-focused (see "Plan-vs-reality audit" above for the full rationale). Hand-rolled is the correct domain fit; the library entry can remain as a future option for non-ontology entities. |
| ER.2 | Replace ER agent stub | Backend | **DONE hand-rolled (v0.4.0-dev)** | `app/extraction/agents/er_agent.py::er_agent_node` is a real LangGraph node: pulls existing classes for the open ontology, scores each extracted class against them via `score_existing_class_vs_extracted`, populates `merge_candidates` on the pipeline state, and delegates cross-tier edge creation to `app/services/cross_tier.py::create_cross_tier_edges`. Uses hand-rolled scoring instead of the library — bundled into PR 2. |
| ER.3 | Topological similarity scoring | Backend | **DONE (v0.4.0-dev)** | `app/services/er_topology.py` implements a weighted-Jaccard score across shared properties, parents, children, and overall neighborhood. Wired into both `explain_match` and `_execute_scoring` (combined-score component). Batch variant `compute_batch_topological_similarity` caches per-class neighborhoods so the n×n pipeline does O(n) DB reads instead of O(n²). |
| ER.4 | WCC clustering | Backend | **DONE hand-rolled (v0.4.0-dev)** | Union-Find clustering inside `_execute_clustering` -- not the library's `WCCClusteringService`. PR 2 will swap to the library for auto backend selection + the optional graph-DB-side execution path on large ontologies. |
| ER.5 | Merge execution service | Backend | **DONE hand-rolled (v0.4.0-dev)** | `execute_merge` calls `_create_golden_record` (strategies: `most_complete`, `newest`), then `update_class` + `expire_entity` for temporal-correct retire-on-merge. Also stamps `golden_records` collection when present. PR 2 will route through the library's `GoldenRecordService` so the `most_complete_with_quality` strategy and field-level provenance come for free. |
| ER.6 | ER run API endpoints | Backend | **DONE (v0.4.0-dev)** | Shipped under `/api/v1/er/`: `POST /run`, `GET /runs/{id}`, `GET /runs/{id}/candidates`, `GET /runs/{id}/clusters`, `POST /explain`, `POST /merge`, `POST /cross-tier`, `GET/PUT /config`. PR 1 added three more per-pair routes: `POST /candidates/{pair_id}/accept`, `POST /candidates/{pair_id}/reject`, `GET /candidates/{pair_id}/explain` — the workspace overlay binds to these. `GET /runs/{id}/candidates` now accepts `?include_resolved=true` so prior decisions can be audited. |
| ER.7 | Merge candidate UI | Frontend | **DONE in workspace (v0.4.0-dev, PR 1)** | `frontend/src/components/workspace/MergeCandidatesOverlay.tsx` ships an overlay-not-route per `ui-architecture.mdc` rule 9. Triggers `POST /api/v1/er/run` on mount, fetches candidates from `GET /runs/{id}/candidates`, lets the curator inline-accept / inline-reject / expand-explain each pair. Optimistic local removal on decision; toast feedback for success and failures (no `window.confirm`). Opened from the canvas right-click context menu (`Find Duplicates…`) when an ontology is loaded -- same per-ontology gating as `Show Pending Revisions`. The legacy `/entity-resolution` page and its `MergeCandidates` / `MergeExecutor` components remain on the deprecated path -- do not extend; they target an API shape that was never implemented. |
| ER.8 | Cross-tier resolution | Backend | **DONE hand-rolled (v0.4.0-dev)** | `get_cross_tier_candidates` walks every (local, domain) class pair and combines `jaro_winkler(label)` + `token_overlap(description)`. The agent-side companion `create_cross_tier_edges` (in `app/services/cross_tier.py`) materialises `extends_domain` edges for EXTENSION-classified entities. Library swap is part of PR 2. |
| ER.9 | ER MCP tools integration | Backend | **DONE (v0.4.0-dev)** | Three tools registered in `app/mcp/tools/er.py`: `run_entity_resolution` (triggers pipeline), `explain_entity_match` (field-by-field breakdown), `get_entity_clusters` (WCC member lists). All delegate to `services/er.py`. Once PR 2 lands, the same tools transparently use the library implementations. |

**Exit Criteria — MET:**
Workspace canvas right-click → "Find Duplicates…" runs ER for the
open ontology and lists candidates in an overlay; per-pair
accept/reject persists via the new
`/candidates/{pair_id}/{accept,reject}` endpoints; explain expansion
shows field-level scores; tests pass at 1707 backend + 591 frontend.

The library-refactor PR was intentionally not pursued — see the
plan-vs-reality audit above. Stream 2 is closed.

---

### Stream 3: OWL Constraints & SHACL Shapes
**PRD:** §6.14 FR-14.1–14.7
**Duration:** 1 week (5 PRs, PR 1 shipped in v0.4.0-dev)
**Priority:** P2 — formal ontology completeness
**Dependencies:** Stream 1 (imports needed for constraint context) ✓
**Team Size:** 1 developer

#### Plan-vs-reality audit (v0.4.0-dev)

Pre-PR-1 state of the codebase:

| Layer | Shipped? |
|-------|----------|
| `ontology_constraints` collection (migration `002_versioned_vertices`) | yes (scaffolding only) |
| MDI / TTL / temporal indexes on `ontology_constraints` (migrations 005 / 006 / 019 / 020) | yes |
| Named-graph membership (`004_named_graphs`), deprecation cascade, admin reset truncation | yes |
| **Writers (extract / import / materialize)** | **no** |
| **Read API** | **no** |
| **Workspace / Library UI** | **no** |
| **OWL restriction export, SHACL export** | **no** |
| **Temporal snapshot / diff includes constraints** | **no** |
| Rule engine: `_cardinality_violation` opportunistically reads `ontology_constraints` | yes, but with a non-PRD internal schema (`constraint_type: "cardinality"`, single doc with `min_cardinality` + `max_cardinality`) -- no-ops on empty collection in practice |
| `has_constraint` edge collection (referenced in dependency / delete code) | **never migrated** -- deferred |

**Implication:** Stream 3 is essentially greenfield. The collection and indexes exist; nothing populates or reads them in production. The rule engine's existing reader needs a one-line filter alignment when writers land.

#### PR split

The original 9-task list (I.1–I.9) is regrouped into 5 vertical-slice PRs, each independently shippable:

| PR | Scope | Tasks | Status |
|----|-------|-------|--------|
| **PR 1** | **Data plane vertical slice** -- extraction → materialization → read API → temporal → rule-engine alignment | I.1, I.2, I.5, I.9, rule-engine schema reconciliation | **DONE (v0.4.0-dev)** |
| **PR 2** | **OWL restriction import via ArangoRDF** -- post-PGT hook parses `owl:Restriction` blank nodes from imported Turtle / RDF-XML / JSON-LD and materializes them as PR 1-shaped rows | I.3 | **DONE (v0.4.0-dev)** |
| **PR 3** | **SHACL shapes parser + import** -- new `app/services/shacl_import.py` walks `sh:NodeShape` / `sh:PropertyShape`, materialises each property constraint into `ontology_constraints` with `constraint_type="sh:PropertyShape"`, rule engine extended to fire on `sh:minCount` / `sh:maxCount` so OWL + SHACL cardinality constraints combine into one bound check per (class, property) | I.4 | **DONE (v0.4.0-dev)** |
| **PR 4** | **Workspace UI for constraints** -- new `ClassConstraintsSection` lazy-rendered under the class detail in `FloatingDetailPanel`. Fetches `/library/{id}/constraints?class_id=...` (added `?class_id` filter and `on_class` repo kwarg so per-click fetch is one round-trip, not an ontology scan). Groups by property, collapses min/max/exact cardinality rows into a unified bound badge (strictest-wins across OWL + SHACL, mirroring the rule engine), source pills distinguish extracted / OWL / SHACL provenance, SHACL severity glyphs (Violation / Warning / Info) with `role="img"` for a11y, XSD prefix stripped from `sh:datatype` values, `sh:in` enumerations rendered as joined list. Empty-state renders nothing (zero DOM) to keep the panel compact. | I.6 | **DONE (v0.4.0-dev)** |
| **PR 6** | **Constraint curator mutation actions** -- approve / reject / edit endpoints + `ConstraintManageRow` UI (the I.7 unblock). See the I.7 row above for the full surface. | I.7 | **DONE (commit `fbb72db`)** |
| **PR 5** | **OWL Turtle restriction export + new SHACL shapes export** -- `_add_owl_restrictions_to_graph` walks `ontology_constraints` rows where `constraint_type == "owl:Restriction"` and emits `owl:Restriction` blank nodes attached via `rdfs:subClassOf` (cardinality / quantified / hasValue, with IRI-vs-literal disambiguation). New `export_shacl()` + `_build_shacl_graph` group SHACL-typed rows by class into one `sh:NodeShape` (with `sh:targetClass`) per class, one `sh:PropertyShape` per property carrying all of that property's SHACL constraints. Cross-vocabulary firewall: OWL rows never leak into the SHACL graph and vice versa (test-pinned both directions). API gains `?format=shacl` returning `.shapes.ttl`. | I.8 | **DONE (v0.4.0-dev)** |

#### Tasks

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| I.1 | Constraint extraction prompts | Backend | **DONE (PR 1)** | `ExtractedConstraint` + `RestrictionType` enum (`minCardinality` / `maxCardinality` / `cardinality` / `allValuesFrom` / `someValuesFrom` / `hasValue`) added to `app/models/ontology.py`; `ExtractedClass.constraints: list[ExtractedConstraint] = []` so existing extractions continue to validate. Both `tier1_standard` and `tier1_technical` prompts gained a `"constraints"` JSON-schema slot plus explicit guidelines (with worked examples) instructing the LLM to emit one restriction per row, with property_uri matching the SAME class's attributes/relationships, and to NOT infer "exactly one" from a singular noun. |
| I.2 | Constraint materialization | Backend | **DONE (PR 1)** | `_materialize_to_graph` builds a per-class URI → (prop_key, collection) map as it walks attributes + queues relationships, then materializes each LLM constraint into `ontology_constraints` with the PRD §6.14 OWL-native shape: `constraint_type="owl:Restriction"`, `on_class`, `property_id` (resolved to `ontology_datatype_properties/...` or `ontology_object_properties/...`, may be `null` when the LLM-supplied URI doesn't match -- which is logged as a warning but persisted so post-hoc repair can recover), `property_uri` (always retained verbatim), `restriction_type`, `restriction_value`, plus standard temporal fields. Fragment fallback handles LLM namespace drift. |
| I.3 | OWL restriction import via ArangoRDF | Backend | **DONE (PR 2)** | `_import_owl_restrictions` runs in `import_owl_to_graph` AFTER PGT (or rdflib-fallback) AND after `_tag_documents_with_ontology_id` so the class/property AQL resolver sees correctly-tagged rows. `_extract_owl_restrictions` walks the rdflib graph for blank-node `owl:Restriction`s attached via `rdfs:subClassOf` **and** `owl:equivalentClass`, identifying min/max/cardinality + allValuesFrom/someValuesFrom/hasValue. Each restriction becomes one `ontology_constraints` row in the PR 1 wire shape (`constraint_type="owl:Restriction"`, `on_class`, `property_id` resolved across object + datatype property collections or `null` when unmatched, `property_uri` always retained, `restriction_value` coerced to int for cardinality kinds), plus a new `import_source: "owl_restriction"` provenance marker that distinguishes import rows from PR 1's `extraction_run_id`-stamped rows. Qualified cardinality (`owl:minQualifiedCardinality` + `owl:onClass`) is recognized and warn-skipped (deferred). Cardinality literals tolerate typed (`"1"^^xsd:nonNegativeInteger`), untyped (`"1"`), and bare Python int forms. Class-orphan rows are dropped (the rule engine joins on `on_class`, so they'd never fire); property-orphan rows are persisted with `property_id=null` mirroring PR 1's resolver-miss path. Stats dict surfaces `restrictions_imported` count. |
| I.4 | SHACL shapes import | Backend | **DONE (PR 3)** | New `app/services/shacl_import.py` with a pure rdflib walker (`_extract_shacl_property_constraints`) and a DB-aware orchestrator (`import_shacl_shapes`), wired into `import_owl_to_graph` right after PR 2's OWL restriction hook. Walks `sh:NodeShape` (both explicitly-typed shapes and shapes discovered via `sh:targetClass`) for every `sh:property` blank node, emitting one `ontology_constraints` row per (target_class, property_path, SHACL constraint kind) in the PR 1 wire shape. **Supported in v1**: `sh:targetClass` + implicit class target (shape that IS itself `owl:Class`/`rdfs:Class`); simple URI `sh:path`; `sh:minCount`, `sh:maxCount`, `sh:datatype`, `sh:class`, `sh:hasValue`, `sh:pattern`, `sh:nodeKind`; `sh:in` enumeration (value stored as `list[str]`); severity inheritance NodeShape→PropertyShape with `sh:Violation` default; `sh:message` captured as the row description (synthetic shape-iri fallback when absent). **Deferred -- explicit WARNING, never silent**: complex `sh:path` expressions (sequence/inverse/alternative), `sh:targetSubjectsOf`/`targetObjectsOf`/`targetNode`, combinators (`sh:and`/`or`/`xone`/`not`), qualified value shapes, `sh:sparql`, `sh:closed`. Provenance marker `import_source: "shacl_shape"` distinguishes SHACL rows from PR 2's `"owl_restriction"` and PR 1's `extraction_run_id`. Rule engine's cardinality query widened: `constraint_type IN ['owl:Restriction','sh:PropertyShape']` AND `restriction_type IN ['minCardinality','maxCardinality','cardinality','sh:minCount','sh:maxCount']` -- OWL and SHACL constraints on the same (class, property) collapse into one bound check, so redundant declarations don't double-fire and cross-vocabulary pairs (OWL min + SHACL max) work naturally. Stats dict carries new `shacl_constraints_imported` field. |
| I.5 | Constraints API endpoint | Backend | **DONE (PR 1)** | `GET /api/v1/ontology/library/{ontology_id}/constraints` with optional `?constraint_type=owl:Restriction` and `?include_unresolved=true|false` filters. Joins `on_class` → `ontology_classes` for `class_label` and `property_id` → property collection for `property_label` in two AQL passes (one per id-batch), so the UI can render constraints without follow-up round-trips. Stable sort by (class_label, property_uri, restriction_type). Backed by new `app/db/constraints_repo.py` with `list_constraints_for_ontology`, `list_constraints_for_class`, `count_constraints_for_ontology` helpers. |
| I.6 | Constraints display in workspace `FloatingDetailPanel` | Frontend | **DONE (PR 4)** | New `ClassConstraintsSection` component lazy-rendered under the class detail; pure `groupConstraintsByProperty` helper collapses cardinality rows and combines OWL + SHACL bounds via strictest-wins, source pills (extracted / OWL / SHACL) and SHACL severity glyphs make provenance visible without leaving the panel. |
| I.7 | Constraint actions in workspace context menu | Backend + Frontend | **DONE (commit `fbb72db`)** | Curator approve / reject / edit of constraints. Mutation API shipped: `POST /{ontology_id}/constraints/{constraint_key}/approve` (sets `status="approved"` via temporal versioning), `POST .../reject` (soft-deletes by expiring the row), `PUT .../{constraint_key}` (edits `restriction_value` / `description`, resets `status="pending"` for re-review) — all with a cross-ontology guard (`_resolve_live_constraint`) and backed by `constraints_repo.get_constraint` / `update_constraint` / `expire_constraint`. Frontend: `ConstraintManageRow` inside `ClassConstraintsSection` adds a per-row "Manage" expander with approve (✓) / reject (✗) / edit (✎) controls, a status pill, inline edit inputs with numeric coercion, and error-resilient refetch. Tests: 7 backend API cases + repo coverage + 5 frontend cases. |
| I.8 | Constraints in OWL + SHACL export | Backend | **DONE (PR 5)** | OWL Turtle export now emits `owl:Restriction` blank nodes attached via `rdfs:subClassOf` for every OWL-typed constraint row (covers cardinality / allValuesFrom / someValuesFrom / hasValue, with IRI-vs-literal autodetection on `hasValue`). New `export_shacl()` builds a parallel SHACL shapes graph (`sh:NodeShape` per class, one `sh:PropertyShape` per property with all SHACL constraints, severity + message inherited from the imported shape). Routed through the existing `/{ontology_id}/export` endpoint as `?format=shacl` returning `text/turtle` with a `.shapes.ttl` filename. |
| I.9 | Constraints in temporal queries | Backend | **DONE (PR 1)** | `ontology_constraints` added to `_ONTOLOGY_VERTEX_COLLECTIONS` AND a new `_CONSTRAINT_VERTEX_COLLECTIONS` so `get_snapshot` returns constraints in a dedicated `constraints` bucket (kept distinct from classes/properties so existing callers' field shapes stay stable). `TemporalSnapshot` Pydantic + frontend `TemporalSnapshot` TS interface both extended with `constraints?: OntologyConstraint[]` (added `OntologyConstraint` TS type with the full PRD wire fields). Rule-engine `_cardinality_violation` rewritten to read the PRD shape (`constraint_type == 'owl:Restriction'` + `restriction_type IN ['minCardinality', 'maxCardinality', 'cardinality']`), with `cardinality` (exactly N) expanded to `min == max == N` for evaluation. Multiple rows per (class, property) are grouped client-side before the bounds check, so a class with both min and max cardinality on the same property evaluates as a single bound pair. Non-int `restriction_value` is skipped with a warning instead of crashing the consolidation run. |

#### PR 1 implementation notes

* **Data shape** (locked by PR 1; subsequent PRs MUST honour it): one OWL restriction = one `ontology_constraints` row with `{constraint_type: "owl:Restriction", on_class, property_id, property_uri, restriction_type, restriction_value, ontology_id, extraction_run_id, confidence, evidence, description, created, expired}`. SHACL (PR 3) will use `constraint_type: "sh:NodeShape"` / `"sh:PropertyShape"` in the same collection.
* **Rule engine alignment**: the previous internal schema (`constraint_type: "cardinality"`, `class_id`, `min_cardinality`/`max_cardinality` on the same doc) had **zero live data** in production (the no-data-returns-empty test proved it) so the cutover is safe; the 4 rule-engine tests were rewritten to use the PRD shape and a new `test_exact_cardinality_emits_violation_when_above` covers the `cardinality` expansion path.
* **`has_constraint` edges deferred**: not part of any current migration; `ontology_dependency.py` references the collection name but doesn't fail when it's missing. Adding it would be PR 6 if traversal queries need it -- not blocking the UI work.
* **Test coverage added**:
  * `tests/unit/test_extracted_constraint_model.py` (8 tests) -- model + enum + class-with-constraints validation.
  * `tests/unit/test_constraints_repo.py` (9 tests) -- repo with optional kwargs + empty-collection paths.
  * `tests/unit/test_constraints_api.py` (5 tests) -- 404, empty, label enrichment + stable sort, unresolved-property null fallback, kwarg pass-through.
  * `tests/unit/test_extraction_service.py::TestMaterializeConstraints` (5 new tests) -- min+max two-row split, attribute resolution to datatype-properties, unresolved-URI warning + null `property_id`, fragment-fallback resolution, no-constraints no-write.
  * `tests/unit/test_ontology_rule_engine.py::TestCardinalityViolation` rewritten (2 new tests added: exact-cardinality and non-int-restriction-value skip).
  * `tests/unit/test_temporal_snapshot.py` new `test_returns_constraints_in_snapshot_bucket`; existing `test_returns_empty_when_no_collections` updated to assert empty constraints bucket.
* **Verification**: full backend unit suite green (1770/1770); frontend type-check + jest (617/617) + eslint clean.

**Exit Criteria (PR 1):** ✓ Constraints extractable from LLM output, materialized into `ontology_constraints`, queryable via REST (`GET /library/{id}/constraints` with class + property label enrichment), included in temporal snapshots, and read by the rule engine in the PRD-aligned shape.

#### PR 2 implementation notes

* **Hook point**: `import_owl_to_graph` runs `_import_owl_restrictions` between `_tag_documents_with_ontology_id` and `_ensure_named_graph`. Tagging must happen first so the constraint resolver's AQL (`FILTER c.ontology_id == @oid`) can find the just-imported classes and properties; the named-graph step still picks up `ontology_constraints` because that collection was already in `_ensure_import_collections` and `_ensure_named_graph`'s orphan list.
* **Provenance distinction**: PR 1 rows carry `extraction_run_id` (LLM source); PR 2 rows carry `import_source: "owl_restriction"` and `confidence: 1.0` (imported axioms are explicit, not inferred). Both consume identically from the rule engine and the `/library/{id}/constraints` API -- no consumer code branches on source.
* **Pure walker + DB writer split**: `_extract_owl_restrictions` and `_interpret_owl_restriction` are pure rdflib (zero DB calls) so the OWL-pattern coverage tests stand alone; `_import_owl_restrictions` is the DB-aware orchestrator with batched class + property resolution.
* **Attachment patterns covered**: `rdfs:subClassOf [a owl:Restriction; ...]` (the textbook anonymous-superclass pattern) AND `owl:equivalentClass [a owl:Restriction; ...]` (the equivalent-class definition pattern). Named superclasses (`rdfs:subClassOf :Foo`) are correctly ignored -- the walker filters on `isinstance(candidate, BNode)`.
* **Deferred -- captured in code with explicit warnings, NOT silently dropped**:
  * Qualified cardinality (`owl:minQualifiedCardinality` + `owl:onClass` / `owl:onDataRange`) -- needs a wider wire shape, deferred until the rule engine + UI agree on scope columns.
  * Nested class expressions on `owl:allValuesFrom` / `owl:someValuesFrom` (intersection / union / complement blank nodes) -- requires recursive descent; current behaviour skips with a warning.
* **Test coverage added** (`tests/unit/test_owl_restriction_import.py`, 22 tests):
  * `TestExtractOwlRestrictions` (11 tests) -- subClassOf + equivalentClass attachment, min/max producing two rows, exact cardinality, all/someValuesFrom + hasValue (URI + literal), named-superclass non-match, qualified-cardinality warn-skip, missing onProperty warn-skip, unrecognized-predicate warn-skip.
  * `TestCoerceCardinalityInt` (6 tests) -- python int, bool rejection, typed XSD literal, untyped digit literal, non-numeric literal rejection, random-object rejection.
  * `TestImportOwlRestrictions` (4 tests) -- no-restrictions short-circuit, full PR 1 wire-shape contract (every field asserted, `extraction_run_id` proven absent), unresolved-class skip-with-warn, unresolved-property null-property-id persistence.
  * `TestImportOwlToGraphReturnsRestrictionsCount` (1 test) -- end-to-end smoke that the hook is invoked with the correct rdf_graph + ontology_id, and the stats dict carries `restrictions_imported`.
* **Verification**: backend `ruff` clean on touched files; backend unit suite green 1792/1792 (1770 from PR 1 baseline + 22 new); mypy on `app/` shows only the pre-existing `arango_rdf` / `fitz` missing-stub warnings (no new errors); frontend `npx tsc --noEmit` clean (PR 2 is backend-only -- no frontend churn).

**Exit Criteria (PR 2):** ✓ An OWL file containing `owl:Restriction` blank nodes (min/max/exact cardinality + allValuesFrom + someValuesFrom + hasValue), uploaded via `import_from_file` or `import_from_url`, produces `ontology_constraints` rows in the PR 1 wire shape that are read identically by the rule engine, the `/library/{id}/constraints` API, and temporal snapshots.

#### PR 3 implementation notes

* **Module placement**: SHACL parsing lives in a NEW `app/services/shacl_import.py` rather than `arangordf_bridge.py`. Adding it to the bridge would push that file past the 1500-line cap from `modularity-and-structure.mdc`; SHACL's separate vocabulary makes it a natural module boundary anyway. The bridge does one lazy import + one function call to invoke it.
* **Hook ordering**: `_import_owl_restrictions` (PR 2) runs first, then `import_shacl_shapes`. Both rely on the same tagged class/property collections; the order between them doesn't matter for correctness, only for trace-log readability.
* **Row shape -- one constraint per row, matching PR 1**: a `sh:PropertyShape` with `sh:minCount 1` AND `sh:datatype xsd:string` AND `sh:pattern "..."` produces THREE rows. Each carries `constraint_type: "sh:PropertyShape"`, the same `on_class`, the same `property_uri`, a distinct `restriction_type` (`"sh:minCount"`, `"sh:datatype"`, `"sh:pattern"`), and the kind-appropriate `restriction_value` (int / URI string / regex string). This mirrors PR 1 + PR 2 exactly so the rule engine, the API, and temporal snapshots have no SHACL-special-case code paths.
* **NodeShape has no row of its own in v1**: NodeShape-level metadata (severity, target class) is inherited by every child PropertyShape. The shape's IRI is preserved in a `shape_iri` field for UI traceability. `sh:closed` would need a NodeShape-only row and is deferred.
* **Provenance markers** (now three sources, all read identically):
  * PR 1: `extraction_run_id` (LLM extraction)
  * PR 2: `import_source: "owl_restriction"`, `confidence: 1.0`
  * PR 3: `import_source: "shacl_shape"`, `confidence: 1.0`, plus `severity` + `shape_iri` SHACL-specific fields
* **Rule engine widening -- OWL and SHACL collapse into ONE bound check**: the cardinality query expanded to `constraint_type IN ['owl:Restriction','sh:PropertyShape']` AND `restriction_type IN ['minCardinality','maxCardinality','cardinality','sh:minCount','sh:maxCount']`. The grouping by `(on_class, property_uri)` is unchanged, so an OWL `minCardinality 1` and a SHACL `sh:minCount 1` on the same property both write to `slot["min"]`, producing one violation when the actual count is below the bound (never two duplicates). Cross-vocabulary pairs work naturally too -- e.g. OWL provides the lower bound, SHACL the upper.
* **Severity precedence**: PropertyShape `sh:severity` > NodeShape `sh:severity` > spec default (`sh:Violation`). Applied in the walker so the row shape is self-describing and the materializer doesn't need to know SHACL semantics.
* **`sh:in` enumeration storage**: value stored as `list[str]` (the only non-scalar value in any constraint row across the three sources). The API endpoint and rule engine treat unknown `restriction_type`s opaquely, so future readers (PR 4 UI, PR 5 export) can introspect this without any backend change.
* **Failure-mode discipline**: identical to PR 2. Orphan class → skip+warn (rule engine joins on `on_class`, an orphan can't fire). Unresolved property URI → persist with `property_id=null` for post-hoc repair. All deferred constructs (complex paths, combinators, alternative targets, qualified shapes, sparql) emit an explicit WARNING log naming the offending shape -- the curator should know what was skipped, not just that something was.
* **Refused half-imports**: a PropertyShape that combines a simple `sh:minCount 1` with a deferred construct (e.g. `sh:or (...)`) is skipped in its ENTIRETY, not partially. Half-importing a shape would misrepresent the schema; warn-skip the whole shape so the curator notices.
* **Test coverage added** (35 new tests):
  * `tests/unit/test_shacl_import.py::TestExtractShaclPropertyConstraints` (15 tests) -- targetClass + implicit target, min+max two-row, datatype/class/pattern/nodeKind/hasValue/in, severity inheritance both directions, sh:message capture, anonymous shape, multi-target shape, complex-path warn-skip, missing-path warn-skip, combinator warn-skip, targetSubjectsOf warn-skip, non-int count warn-skip, plain owl:Class non-match.
  * `tests/unit/test_shacl_import.py::TestCoerceCountInt` (6 tests) -- python int, negative reject, bool reject, typed XSD, untyped digit, non-numeric reject.
  * `tests/unit/test_shacl_import.py::TestReadRdfList` (3 tests) -- well-formed list, empty list, non-list input.
  * `tests/unit/test_shacl_import.py::TestImportShaclShapes` (5 tests) -- no-shapes short-circuit, full row-shape contract (every field asserted, `extraction_run_id` proven absent), unresolved-class skip-with-warn, unresolved-property null-property-id, synthetic description when no `sh:message`.
  * `tests/unit/test_shacl_import.py::TestImportOwlToGraphSurfacesShaclCount` (1 test) -- end-to-end smoke that the bridge hook is invoked and stats dict carries `shacl_constraints_imported`.
  * `tests/unit/test_ontology_rule_engine.py::TestCardinalityViolation` (4 NEW tests) -- SHACL `sh:minCount` fires below-min violation, SHACL `sh:maxCount` fires above-max violation, OWL + SHACL same-bound rows collapse into ONE violation (no duplicate), OWL min + SHACL max cross-vocabulary combination works.
* **Verification**: backend ruff clean on all touched files; backend unit suite green 1827/1827 (1792 PR 2 baseline + 35 new); mypy `app/` shows only the pre-existing 7 errors (no new errors introduced -- `shacl_import.py` is fully type-checked); frontend `npx tsc --noEmit` clean (PR 3 is backend-only).

**Exit Criteria (PR 3):** ✓ A SHACL Turtle file containing `sh:NodeShape` with `sh:property` blocks (covering `sh:minCount`, `sh:maxCount`, `sh:datatype`, `sh:class`, `sh:hasValue`, `sh:pattern`, `sh:nodeKind`, `sh:in`), uploaded via `import_from_file` or `import_from_url`, produces `ontology_constraints` rows that are read identically by the rule engine (firing the cardinality rule via either OWL or SHACL predicates), the `/library/{id}/constraints` API, and temporal snapshots; OWL and SHACL constraints on the same property combine into one bound check.

#### PR 4 implementation notes

* **Component placement**: `frontend/src/components/workspace/ClassConstraintsSection.tsx` -- new self-contained module (component + pure grouping helper + a small set of formatting helpers). Lives next to `FloatingDetailPanel.tsx` so the parent's import is a single relative-ish path; not promoted to a shared `hooks/` location until a second consumer needs constraints (matches the rule "Read first. Match the patterns. Then write." -- the existing FDP inlines its fetch, so the new section follows the same convention rather than introducing a fresh abstraction).
* **Wiring**: `FloatingDetailPanel` only renders the section when `entityType === "class"` AND the entity has loaded -- the constraints fetch fires after the entity fetch resolves (separate `useEffect` in the child component, keyed on `[ontologyId, classKey]`), so the panel paints the class header / properties first and the constraints arrive shortly after without blocking the initial render.
* **Backend assist (only required change outside the UI)**: `constraints_repo.list_constraints_for_ontology` gained an optional `on_class` kwarg and `/library/{id}/constraints` gained an optional `?class_id=` query param. Same single endpoint -- the workspace adds the filter so a per-click panel fetch scales with constraints-per-class (typically 0-10) rather than constraints-per-ontology (potentially hundreds). Two new repo tests (`test_list_constraints_filters_by_on_class_when_provided`, `test_list_constraints_combines_all_filters`) and one new API test (`test_forwards_class_id_query_param_to_repo`) pin the contract.
* **Cardinality collapse logic** (in pure `groupConstraintsByProperty`): rows whose `restriction_type` is in `{minCardinality, maxCardinality, cardinality, sh:minCount, sh:maxCount}` AND whose value is a `number` are folded into a per-property combined bound. Strictest-wins for both directions: `max(min1, min2, ...)` for lower bound, `min(max1, max2, ...)` for upper bound -- matches what `_cardinality_violation` evaluates so the badge the user sees is exactly the bound the engine enforces. Rendered as `=N` (exact), `N..M` (range), `=N` (when min equals max), `≥N` (lower-only), `≤N` (upper-only). Non-numeric restriction values on a cardinality kind are defensively treated as chips rather than coerced to NaN.
* **Source provenance pills**: each property group surfaces the union of sources that contributed rows to it -- "extracted" (PR 1, purple) / "OWL" (PR 2, blue) / "SHACL" (PR 3, orange). Classification reads `import_source` first, then falls back on `extraction_run_id`, then on `constraint_type` (for legacy rows that pre-date the provenance markers). Pills sit on the property header so a curator sees provenance independent of which chip they hover.
* **SHACL severity**: rendered as a `<span role="img" aria-label="Violation|Warning|Info">` glyph on the chip (Violation = ⚠ red, Warning = ⚠ amber, Info = ℹ blue). `role="img"` is what makes the icon a first-class screen-reader element AND what lets `getByRole("img", { name: ... })` find it in the test. Unknown / custom severity URIs render as a neutral grey dot rather than dropping the indicator -- explicit over silent.
* **Value humanisation**: `formatValue` strips the XSD namespace from `sh:datatype` values (`http://www.w3.org/2001/XMLSchema#string` → `string`) and joins `sh:in` arrays with commas. Tooltips on the chip carry the full `description` (or `restriction_type` fallback) so the abbreviated chip text never hides information the curator might need.
* **Empty state contract**: when a class has zero constraints, the section returns `null` -- not "Constraints (0)". Pinned in `renders nothing when the class has zero constraints (keeps panel compact)` because every class detail panel would otherwise carry that line of noise.
* **FDP test fallout**: the existing FDP tests used `apiGet.mockResolvedValue(...)` which served the same value for every `api.get`. Adding the constraints fetch broke the two call-count assertions ("does not refetch", "refetches on key change"). Introduced a `mockApiByUrl` helper + `entityCalls()` selector so tests assert against just the entity-endpoint calls; the constraints endpoint is stubbed to `{constraints: []}` by default so unrelated tests don't accidentally rely on its shape.
* **I.7 (resolved in commit `fbb72db`)**: PR 4 shipped read-only display only because the approve / reject mutation endpoints did not yet exist — adding actions without the backing API would have been wiring a button to nothing. PR 6 (commit `fbb72db`) landed that mutation API (`POST /{ontology_id}/constraints/{key}/approve`, `POST .../reject`, `PUT .../{key}`) plus the `ConstraintManageRow` controls, so the deferral is now closed.
* **Test coverage added**:
  * `frontend/src/components/workspace/__tests__/ClassConstraintsSection.test.tsx` (18 tests) -- 10 pure-logic tests on `groupConstraintsByProperty` (every cardinality branch + cross-vocab strictest-wins for both bounds + grouping isolation + defensive non-numeric handling) and 8 rendering tests (URL contract, empty-state-is-null, SHACL severity icon + source pill, XSD prefix stripping, `sh:in` joined display, multi-source pill stack, inline error surfacing, refetch-on-classKey-change).
  * `frontend/src/components/workspace/__tests__/FloatingDetailPanel.test.tsx` (existing 7 tests, all green) -- updated to use the URL-routing mock helper so the new constraints fetch doesn't pollute call counts.
  * `backend/tests/unit/test_constraints_repo.py` (2 new) + `backend/tests/unit/test_constraints_api.py` (1 new) for the `on_class` / `?class_id` kwarg.
* **Verification**: backend unit suite green 1830/1830 (1827 PR 3 baseline + 3 new); backend ruff + format clean on touched files; backend mypy on changed files shows only pre-existing errors in unrelated modules. Frontend: `npx tsc --noEmit` clean; eslint clean on all touched files; jest workspace suite 300/300 green (282 baseline + 18 new).

**Exit Criteria (PR 4):** ✓ Clicking a class node in the workspace canvas opens the floating detail panel; if the class has OWL restrictions or SHACL property shapes, they appear in a "Constraints" section grouped by property with cardinality bounds collapsed across OWL + SHACL, source pills visible, and SHACL severity glyphs rendered accessibly. Classes with no constraints add no DOM (panel stays compact).

#### PR 5 implementation notes

* **Single-graph emission for OWL** -- `_add_owl_restrictions_to_graph` runs inside `_build_rdf_graph` AFTER classes / properties / edges / imports so the class + property URI resolver maps (`class_id_to_uri`, `property_id_to_uri`) are already built. One Arango round-trip per export pulls all OWL-typed constraint rows (`list_constraints_for_ontology(constraint_type="owl:Restriction")`), then each row becomes exactly four triples: `BNode rdf:type owl:Restriction`, `BNode owl:onProperty <prop>`, `BNode <kind-predicate> <value>`, `<class> rdfs:subClassOf BNode`. The shape is intentionally the inverse of PR 2's import walker, so a Turtle file produced here can round-trip back through `import_owl_to_graph` and reproduce the same `ontology_constraints` rows.
* **IRI-vs-literal disambiguation on `owl:hasValue`** -- the OWL spec allows the value of `owl:hasValue` to be either an IRI individual or a literal; downstream OWL parsers need the right node type. We treat any string that starts with `http://` / `https://` as a `URIRef`, anything else as a `Literal`. Numbers / booleans become typed literals naturally so a round-trip preserves the datatype.
* **Cardinality datatype** -- all cardinality values are stamped as `xsd:nonNegativeInteger`. The validator rejects negatives and booleans (which would silently pass `isinstance(int)`) with a structured warning rather than emitting an invalid axiom.
* **Cross-vocabulary firewall** -- the OWL exporter filters on `constraint_type="owl:Restriction"` and ONLY that; SHACL-typed rows never leak in. The SHACL exporter filters on `constraint_type IN ("sh:NodeShape", "sh:PropertyShape")` after fetching once (the helper handles both filter modes for testability). Two dedicated tests (`test_shacl_typed_rows_excluded_from_owl_export` + `test_owl_typed_rows_excluded_from_shacl_export`) pin both directions so a future filter loosening doesn't quietly produce a cross-vocabulary leak.
* **SHACL grouping** -- one `sh:NodeShape` per target class (synthetic deterministic IRI: `<classURI>Shape` so re-exports produce stable IRIs for diffing / citation), one `sh:PropertyShape` BNode per (class, property) pair. Multiple SHACL constraints on the same property (e.g. `sh:minCount` + `sh:datatype` + `sh:pattern`) all land on the SAME `sh:PropertyShape` rather than fragmenting into separate ones -- matches how every SHACL parser expects to read shapes and how a curator thinks about a property's constraint set.
* **`sh:in` list emission** -- arrays are written as proper RDF lists using `rdflib.collection.Collection` so a downstream SHACL parser sees `sh:in ( "S" "M" "L" )` (the canonical Turtle form), not a malformed bare-literal triple.
* **Severity + message** -- the first non-empty `severity` / `description` from a property's rows is attached to the `sh:PropertyShape` (the SHACL spec doesn't allow per-constraint severity on a property shape, only per-shape; multi-severity input collapses to the first observation rather than dropping silently).
* **API routing** -- `/{ontology_id}/export?format=shacl` returns `text/turtle` with `Content-Disposition: attachment; filename="<id>.shapes.ttl"`. The `.shapes.ttl` suffix is the convention SHACL-aware tooling (TopBraid, pyshacl) looks for when discovering shapes next to a main ontology Turtle.
* **Fallback when `property_id` is null** -- a constraint persisted with an unresolved property id (PR 1/PR 2 path when the LLM-supplied URI doesn't match) STILL exports correctly: the exporter falls back on the raw `property_uri` string. Losing the constraint on export would be worse than the resolver miss it represents.
* **Test coverage added** (`tests/unit/test_export.py` + new `tests/unit/test_export_api.py`, 23 new tests):
  * `TestOwlRestrictionEmission` (12 tests) -- min / max / two-row split / exact cardinality / allValuesFrom / someValuesFrom / hasValue (IRI) / hasValue (literal) / unresolved-class skip / property fallback on null property_id / negative cardinality refusal / SHACL-row exclusion / empty constraint set no-op.
  * `TestExportShacl` (7 tests) -- empty SHACL set produces header-only graph / minCount produces NodeShape + PropertyShape with the right targetClass / multiple constraints on one property share ONE PropertyShape / `sh:in` emits an RDF list / severity + message carry to the property shape / two classes produce two NodeShapes / OWL-row exclusion.
  * `test_export_api.py` (4 tests) -- 404 when ontology missing / turtle routing / shacl routing (with a side-effect guard that fails the test if the SHACL request accidentally falls through to the OWL handler) / unknown-format-falls-through-to-turtle.
* **Verification**: backend ruff clean on all touched files; backend unit suite green 1853/1853 (1830 PR 4 baseline + 23 new); mypy on `app/services/export.py` clean (no new errors -- the 3 pre-existing errors in unrelated modules remain unchanged); the existing `test_export.py::TestExportOntology` and `TestExportJsonld` suites all still pass with the new graph builder in place.

**Exit Criteria (PR 5):** ✓ An ontology with OWL restrictions and SHACL shapes can be exported in three shapes -- `?format=turtle` returns an OWL Turtle document with `owl:Restriction` blank nodes for every OWL-typed constraint, `?format=shacl` returns a SHACL shapes Turtle with one `sh:NodeShape` per class and one `sh:PropertyShape` per property, `?format=jsonld` / `csv` continue to work unchanged. Round-trip via PR 2's `import_owl_to_graph` reproduces the same `ontology_constraints` rows.

**Exit Criteria (overall Stream 3):** ✓ Constraints extractable (PR 1), importable from OWL (PR 2), importable from SHACL (PR 3), displayable in the workspace (PR 4), exportable to OWL Turtle + SHACL shapes graph (PR 5), curator approve / reject / edit (PR 6, commit `fbb72db`). **Stream 3 fully complete — no deferred items.**

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
| Q.2 | Quality history API | Backend | 4h | **DONE (v0.4.0-dev)** — `GET /quality/{ontology_id}/history` returns timestamped snapshots; `quality_history` collection (migration `022_quality_history`); `save_quality_snapshot(ontology_id, report, source=, run_id=)` accepts event-tagged sources; `record_event_snapshot()` helper called from `extraction.execute_run` (`source="extraction_completion"`) and `promotion.promote_staging` (`source="promotion"`); failures swallowed so a snapshot bug never breaks the write path. |
| Q.3 | Trend sparklines | Frontend | 3h | **DONE (v0.4.0-dev)** — `QualitySparkline` SVG component on `OntologyScoreTable` with lazy-fetch + module cache, ↑/↓/→ session-trend arrow, accent dots for `extraction_completion` (sky) and `promotion` (emerald) datapoints, loading / single-point / no-data / error fallbacks. |
| Q.4 | Gold-standard recall comparison | Backend | 4h | **DONE (v0.4.0-dev)** — `POST /api/v1/quality/recall` accepts an OWL/TTL/RDF body string, normalises labels (camelCase split, depluralisation, punctuation strip), greedy 1-to-1 best-match via `difflib.SequenceMatcher`, returns precision / recall / F1 plus per-class `matched` / `missed` / `false_positives` and an optional object-properties section. Frontend overlay (`RecallComparisonOverlay`) with file picker, threshold slider, and inline report; opened from `QualityReportOverlay`. |
| Q.5 | Curation throughput timer | Frontend | 3h | **DONE (v0.4.0-dev)** — Client measures gap between consecutive submit clicks (capped at 30 min so idle outliers don't skew session active-time); `recordCurationDecision` / `recordCurationBatchDecision` helpers send `decision_latency_ms` on every decide / batch call; backend persists it on `curation_decisions` and exposes `GET /api/v1/curation/throughput` with active-time + wall-clock fallback strategies. `CurationThroughputCounter` badge in the curation header shows session rate + trailing-10 trend hint. |

**Exit Criteria — MET (v0.4.0-dev):** All five PRD §3.2 success metrics (Q.1–Q.5) visible on a single dashboard page with trend visualization. The "RAG benchmark comparison UI" mentioned in the executive summary was never one of these five tasks and is **not** part of Stream 4's exit criteria; it is an unscoped, optional follow-up deferred to post-v1.0.

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

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| PH.1 | `PipelineHistorySlider` component | Frontend | **DONE (v0.4.0-dev)** | VCR-style slider with play/pause/rewind/ff and speed cycle (0.5x → 4x) lives at `frontend/src/components/pipeline/PipelineHistorySlider.tsx`. Each tick = one extraction run sorted oldest → newest by `started_at`; up to 80 runs draw per-tick status dots (`completed`/`running`/`failed`/`paused`/etc.) so the timeline is scannable at a glance. Selecting a tick fires `onSelectRun(runKey)`. |
| PH.2 | Wire into pipeline page | Frontend | **DONE (v0.4.0-dev)** | Mounted above the DAG in `frontend/src/app/pipeline/page.tsx`. The slider receives `selectedRunId` from the parent and emits `onSelectRun` back via a memoised `handleSelectRun` so RunList and the slider stay in lock-step without ping-ponging into a render loop. (See the explicit guard comment in `PipelineHistorySlider` -- bidirectional sync used to spin the page and reopen the WebSocket on every render before the one-way external→slider edge was added.) |
| PH.3 | Run summary strip | Frontend | **DONE (v0.4.0-dev)** | Below the slider: status dot, document name (truncated), capitalised status, `N classes`, `Ns`/`Nm Xs` duration, and a right-aligned "N min ago" relative timestamp. All driven from the run's `document_name` / `status` / `classes_extracted` / `duration_ms` / `started_at` fields already enriched on `/runs` (now via the T8 bulk path). |
| PH.4 | Unit tests | Frontend | **DONE (v0.4.0-dev)** | 12 tests in `frontend/src/components/pipeline/__tests__/PipelineHistorySlider.test.tsx` cover: fetch + render of runs as ticks, VCR play/pause advances index, slider change fires `onSelectRun`, empty state, loading state, one-way external→slider sync (the regression test for the prior render loop). |

**Exit Criteria — MET:** Users can scrub through all extraction runs via a slider on the pipeline page. Play mode auto-advances. Selecting a run on the slider updates the DAG / metrics / errors panels. All 12 tests pass.

---

### Stream 5: Schema Extraction from ArangoDB
**PRD:** §6.9 FR-9.1–9.13
**Duration:** 2 weeks (rescoped — see plan-vs-reality audit below)
**Priority:** P2 — value-add for existing ArangoDB users
**Dependencies:** Stream 1 (imports/composition) ✓; Stream 3 (constraints) — S.9 only
**Team Size:** 1 developer

#### Plan-vs-reality audit (v0.4.0-dev)

When Stream 5 was opened in v0.4.0-dev we found S.1 + S.2 + S.3 had
already shipped (with a 200-line `_stub_extract_schema` that only
emitted bare `owl:Class` / `owl:ObjectProperty` per collection — no
named-graph awareness, no domain/range, no datatype properties, no
provenance). The optional `arangodb-schema-analyzer` library is **not**
in `pyproject.toml` dependencies; the integration only fires if
someone installs it manually, so the direct/built-in path is the one
that runs in production.

Stream 5 is split into three PRs:

- **PR 1 — Backend, no UI (DONE, this commit)**:
  - **S.6 (NEW)** — `POST /api/v1/ontology/schema/graphs` returns
    named graphs + edge definitions + loose collections, scoped to a
    `SchemaExtractionConfig` body (credentials in body, not query
    string, to avoid URL logging leaks).
  - **S.7 + S.8 (REWRITE)** — `_direct_extract_schema` replaces the
    minimal stub: walks `db.graphs()`, emits `owl:ObjectProperty`
    with `rdfs:domain` / `rdfs:range` resolved from edge definitions,
    samples `field_sample_limit` documents per collection to infer
    `owl:DatatypeProperty` with XSD types (`xsd:string` /
    `xsd:integer` / `xsd:decimal` / `xsd:boolean` /
    `xsd:date` / `xsd:dateTime`), and respects `graph_names` /
    `include_loose` config knobs for partial extractions.
  - **S.4 (NEW)** — `_stamp_per_class_provenance` post-import pass
    stamps `source_db` / `source_collection` / `source_host` on every
    class via a single bulk AQL update (no N+1). Annotations are also
    embedded in the generated TTL via the `aoe:` vocabulary so an
    export-then-re-import round-trip keeps provenance.
  - **S.10 (NEW)** — `imports: list[str]` config field; each entry
    expands to an `owl:imports` triple on the generated ontology
    resource, then the standard `sync_owl_imports_edges` pass wires
    the `imports` edges to the registry.
  - **`_stub_extract_schema` kept as a back-compat alias** so
    existing tests / external callers continue to work; new logic
    lives in `_direct_extract_schema` which returns
    `(ttl, uri_to_collection)` so per-class provenance has the data
    it needs without re-parsing TTL.
  - 42 unit tests added (`test_schema_extraction.py` rewrite +
    `test_schema_extraction_api.py` new) covering XSD type
    inference (incl. the critical `bool`-before-`int` order), field
    sampling, named-graph filter, loose-collection toggle,
    provenance stamping (incl. failure swallowing), auto-imports
    embedding, and the new `/schema/graphs` route's 200 / 400 / 502
    / 422 contract.
  - Total backend unit coverage now **84.80%** over 1730 tests
    (up from ~84.4% at PR start).

- **PR 2 — Frontend UI (DONE, v0.4.0-dev)**:
  `frontend/src/components/workspace/SchemaExtractionOverlay.tsx`.
  Workspace overlay-not-route per `ui-architecture.mdc` rule 9,
  opened from the canvas right-click menu's new "Extract from
  ArangoDB…" entry (peer of "Browse Standard Catalog…"; icon 🗄 —
  noted in the file header that no canonical icon exists for "extract
  from external source" yet). Three-step state machine in one
  component: (1) **connect** — host / db / user / password /
  verify_tls + optional ontology label, validates required fields
  client-side before any network hit, surfaces backend 502s inline;
  (2) **preview** — renders the `/schema/graphs` topology with
  per-graph checkboxes (default all selected), `include_loose`
  toggle, `sample_fields` toggle + `field_sample_limit` numeric
  input, plus an `owl:imports` multi-select sourced from
  `GET /ontology/library?limit=200` (lazy-fetched on entering the
  step, fire-and-forget so a registry outage doesn't block extract);
  a live summary line counts classes + object properties + sampled
  document collections via the pure `summarizeExtraction()` helper
  (exported + unit-tested) so the math is provable without
  rendering; (3) **result** — run id + ontology id + import stats
  + provenance-stamped count, then `onImported(newOntologyId)`
  fires once so the parent (workspace page) refreshes the
  AssetExplorer and switches selection to the new ontology. Esc +
  × close at any step. "Back" from preview to connect preserves
  the connection state. `graph_names` normalises to `null` on the
  wire when every graph is selected (so the backend's "walk all"
  default kicks in) and to an explicit array otherwise — never
  the empty array, which would walk zero graphs. The "Extract &
  Import" button is gated disabled when nothing is selected so a
  zero-output run cannot be triggered. Wiring: new
  `setShowSchemaExtraction(show)` field on
  `WorkspaceContextMenuActions`; `app/workspace/page.tsx` mounts
  the overlay next to `CatalogBrowserOverlay` with the same
  `onImported` post-import dance (`setExplorerLibraryNonce` +
  `handleSelectOntology`). Tests added: 33 new (`canvas.test.ts`
  +1 for the new menu entry; `SchemaExtractionOverlay.test.tsx`
  +23 component + 6 `validateConnection` + 5 `summarizeExtraction`
  pure-helper cases — connect-step rendering, required-field
  validation, ApiError-502 surfaced inline, Esc + × close,
  successful discover transitions to preview, summary line math
  pins, graph toggle updates summary, Extract&Import disabled when
  all unchecked, Back preserves db field, extract POST body shape
  with imports + with partial `graph_names`, extract failure stays
  on preview, result step renders ids + stats). Full frontend
  Jest suite green at 617/617 (was 591 after PR 1). PR 2 ships
  the workspace surface for the backend that landed in PR 1; no
  backend changes.

- **PR 3 sub-A — S.9 constraint mapping (DONE, v0.4.0-dev)**:
  Stream 3 (OWL Constraints & SHACL Shapes) shipped all five PRs,
  unblocking S.9. The direct extractor now walks each document
  collection's `properties()['schema']['rule']` (JSON Schema
  validation) and `indexes()` and emits a SHACL `sh:NodeShape` +
  `sh:PropertyShape` block per class into the same TTL document
  the rest of the schema lands in. The standard `import_from_file`
  pipeline routes those shapes through PR 3's SHACL importer
  (`shacl_import.import_shacl_shapes`) so constraint rows land in
  `ontology_constraints` with no schema-extraction-specific
  post-import step. Mappings (v1):

  | ArangoDB construct | SHACL emission | Notes |
  | --- | --- | --- |
  | `required: ["field"]` | `sh:minCount 1` | Per field |
  | `properties: {field: {type}}` | `sh:datatype <xsd>` | `format` overrides `type` for `date`/`date-time`/`time`/`uri` |
  | `properties: {field: {pattern}}` | `sh:pattern "<regex>"` | Coexists with `sh:datatype` on the same PropertyShape |
  | `properties: {field: {enum}}` | `sh:in (v1 v2 ...)` | RDF list, members stringified for PR 3's `list[str]` wire shape |
  | Single-field unique index | `sh:maxCount 1` | Composite/primary/edge/underscore-prefixed indexes deliberately skipped (no clean per-property mapping) |
  | `minimum` / `maximum` / `minLength` / `maxLength` | not emitted v1 | PR 3 importer doesn't yet recognise `sh:minInclusive` etc. |
  | Nested object properties | not emitted v1 | Same v1 limitation as datatype-property sampling |

  Fields mentioned in the schema rule or a unique index but NOT
  in the sampling map get a synthetic `owl:DatatypeProperty`
  emitted on the fly so the SHACL `sh:path` always lands on a
  declared property (otherwise a fresh table with
  `required: ["email"]` and no data would import a NodeShape
  whose `sh:path` referenced a phantom URI). The synthetic
  property's `rdfs:range` is pulled from the same schema rule's
  `sh:datatype` constraint when present.

  Toggle: `extract_constraints: bool = True` on
  `SchemaExtractionConfig` -- defaults on; set `False` for a
  constraint-free reverse-engineering pass.

  Tests added (40 new in `test_schema_extraction.py`):
  pure-helper coverage for `_jsonschema_type_to_xsd` (every
  XSD branch incl. format-override and union-type fallback),
  `_collect_schema_validation_constraints` (required + type +
  pattern + enum grouping), `_collect_unique_index_fields`
  (single vs composite, primary/edge filtering, underscore
  guard), `_read_collection_validation_and_indexes` (happy
  path + partial-failure tolerance), the orchestrator
  `_emit_collection_shacl_shapes` via the full
  `_direct_extract_schema` integration (six scenarios incl.
  required → `sh:minCount`, unique-index → `sh:maxCount`,
  schema-only field → synthetic property, multiple
  constraints sharing one PropertyShape, `extract_constraints=False`
  skip, empty-collection no-NodeShape), plus a round-trip
  test that parses our emitted TTL through PR 3's actual
  `_extract_shacl_property_constraints` walker so any drift in
  either direction breaks the test rather than silently
  producing unimportable shapes.

- **PR 3 sub-B — S.5 schema diff for evolution (DONE, v0.4.0-dev)**:
  Storage decision: **snapshot-history model** (each extraction
  stays its own ontology; diff is computed on demand from the
  existing `ontology_classes` / `ontology_properties` /
  `ontology_constraints` collections). Rationale: zero migration,
  no behaviour change to existing extractions, the existing PR 1
  S.4 per-class provenance stamping already provides the
  `source_db` / `source_host` fingerprint needed to detect
  "diffed two unrelated ontologies"; the alternative
  version-in-place model would silently mutate an ontology on
  re-extraction which is a UX gotcha; the alternative
  dedicated-collection model would duplicate state we already
  have. Service: `app/services/schema_diff.py` (~330 LOC). API:
  `GET /api/v1/ontology/schema/diff?a=<id>&b=<id>` (GET because
  no credentials, no body, safe to bookmark). Diff semantics:

  | Bucket | Join key | "changed" trigger |
  | --- | --- | --- |
  | Classes | `uri` | Any non-metadata field differs (label, comment, source_db, etc.). |
  | Properties | `uri` (walks `ontology_properties` + `ontology_object_properties` + `ontology_datatype_properties`) | Any non-metadata field; `rdfs_range` drift is the flagship case. |
  | Constraints | `(class_uri, property_uri, restriction_type)` composite -- constraints don't carry URIs of their own, so the AQL resolves `class_id` / `property_id` to URIs server-side via lookup against the per-ontology class + property rows | `restriction_value` differs. Severity / message drift is curator metadata, not schema semantics, and intentionally NOT a change trigger in v1. |

  Provenance compatibility (`source_db` + `source_host`) is a
  warning, not a refusal. The diff serves regardless; the
  `provenance.compatible` flag + `provenance.warning` string tell
  the curator whether they're looking at schema evolution or a
  cross-schema compare.

  Self-diff (`a == b`) raises `ValueError -> 400`: silently
  returning all-empty buckets would mislead a caller into thinking
  nothing changed when they passed the same id by mistake.

  Tests added (41 new across two files): `test_schema_diff.py`
  (37 tests covering every helper -- `_by_uri`, `_schema_data_changed`,
  `_diff_by_uri`, `_constraint_join_key`, `_diff_constraints`,
  `_evaluate_provenance` -- plus eight orchestrator scenarios
  including added class, property range drift, constraint
  tightening, provenance match + mismatch, summary-vs-bucket
  consistency, and missing-collection tolerance) and
  `test_schema_diff_api.py` (4 tests on the route: query-param
  forwarding, self-diff -> 400, warning pass-through, kwarg
  contract).

  Edges (`subclass_of`, `has_property`, `rdfs_domain`,
  `rdfs_range_class`, etc.) are intentionally out of scope for
  v1: their changes are nearly always implicit consequences of
  class / property add / remove that the diff already surfaces.
  If a future iteration wants to surface edge-level drift
  directly, add a fourth bucket without changing the existing
  shape.

  **Frontend UI (DONE, v0.4.0-dev follow-up)**: `SchemaDiffOverlay` on
  `/workspace` calls `GET /schema/diff`, renders accordion buckets for
  classes / properties / constraints, and surfaces `provenance.warning`.
  Opened from ontology explorer + canvas context menus ("Compare Schema
  Evolution…").

#### Tasks

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| S.1 | Wire `arango-schema-mapper` integration | Backend | **DONE (pre-existing)** | `_try_import_schema_mapper()` + `_run_schema_mapper_extract()` -- graceful degradation when the optional library isn't installed (it isn't, by default). |
| S.2 | OWL export from schema | Backend | **DONE (pre-existing)** | TTL fed into `import_from_file` -> standard ArangoRDF PGT pipeline. |
| S.3 | Schema extraction API | Backend | **DONE (pre-existing)** | `POST /api/v1/ontology/schema/extract` + `GET /api/v1/ontology/schema/extract/{run_id}`. |
| S.4 | Provenance tracking for schema sources | Backend | **DONE (PR 1, v0.4.0-dev)** | `_stamp_per_class_provenance` -- per-class `source_db` / `source_collection` / `source_host`. Bulk AQL, no N+1. Failure swallowed so provenance bugs never break extraction. TTL also carries the same triples via the `aoe:` vocab so exports round-trip. |
| S.5 | Schema diff for evolution tracking | Backend + Frontend | **DONE (PR 3 sub-B backend + frontend overlay, v0.4.0-dev)** | Backend: `app/services/schema_diff.py` + `GET /api/v1/ontology/schema/diff?a=&b=`. Frontend: `SchemaDiffOverlay` + context-menu wiring on `/workspace`. Computes `{added, removed, changed}` for classes, properties, and constraints; self-diff → 400; provenance mismatch → warning banner. Edges out of scope for v1. |
| S.6 | Named graph discovery API | Backend | **DONE (PR 1, v0.4.0-dev)** | `POST /api/v1/ontology/schema/graphs` -- returns named graphs + edge definitions + loose collections. POST (not GET) so credentials don't leak via URL. Errors mapped to 400 (bad config) / 502 (upstream Arango unreachable) / 422 (validation). |
| S.7 | Named graph-aware extraction | Backend | **DONE (PR 1, v0.4.0-dev)** | `_direct_extract_schema` walks `db.graphs()`, emits `owl:ObjectProperty` with `rdfs:domain` / `rdfs:range` resolved from edge definitions. Multi-from / multi-to edge defs emit one triple per vertex collection. `graph_names` config restricts the walk; `include_loose` controls fallthrough to non-graph collections. |
| S.8 | Direct graph-to-ontology mapping (no `schema_analyzer`) | Backend | **DONE (PR 1, v0.4.0-dev)** | Same `_direct_extract_schema` path: (a) document collection → `owl:Class`, (b) edge collection → `owl:ObjectProperty` with domain/range from edge def, (c) sampled scalar fields → `owl:DatatypeProperty` with XSD type inferred from value. Field URIs are scoped to the source collection (`{Col}.{field}`) so two collections with a `name` field don't collide. Heterogeneous types fall back to `xsd:string`. Nested objects + arrays skipped for v1 (logged limitation; can recurse in PR 3). |
| S.9 | Index and constraint mapping | Backend | **DONE (PR 3 sub-A, v0.4.0-dev)** | `_direct_extract_schema` now reverse-engineers each document collection's JSON Schema validation rule (`required` -> `sh:minCount 1`; `type`/`format` -> `sh:datatype`; `pattern` -> `sh:pattern`; `enum` -> `sh:in`) and single-field unique indexes (-> `sh:maxCount 1`) into a `sh:NodeShape` + `sh:PropertyShape` block embedded in the generated TTL. Composite-unique, primary, edge, and underscore-prefixed-field indexes are deliberately skipped (no clean per-property SHACL mapping). The standard `import_from_file` path then routes the shapes through PR 3's SHACL importer, so constraints land in `ontology_constraints` with `constraint_type="sh:PropertyShape"` and `import_source="shacl_shape"` with no schema-extraction-specific post-import step. Toggle via `extract_constraints: bool = True` on `SchemaExtractionConfig`. End-to-end round-trip pinned: `test_emitted_ttl_round_trips_through_pr3_shacl_walker` parses our emitted TTL through `_extract_shacl_property_constraints` (the same walker `import_shacl_shapes` uses) and asserts all four constraint kinds materialise correctly. |
| S.10 | Schema-derived ontology auto-imports | Backend | **DONE (PR 1, v0.4.0-dev)** | `imports: list[str]` config field; each entry expands to an `owl:imports` triple on the generated ontology resource; standard `sync_owl_imports_edges` wires the `imports` edges to the registry. ER-based alignment suggestions (the second half of S.10) are PR 2 territory once the UI can show + accept them. |
| S.11 | Schema extraction UI with graph selection | Frontend | **DONE (PR 2, v0.4.0-dev)** | `SchemaExtractionOverlay.tsx` -- canvas right-click "Extract from ArangoDB…" opens an overlay-not-route with a three-step flow: connect form (host/db/user/password/TLS) → graph picker (per-graph checkboxes + loose-collections + field-sampling + auto-imports multi-select) → commit + result. Wired into the workspace canvas context menu via a new `setShowSchemaExtraction` action. |
| S.12 | Schema preview panel | Frontend | **DONE (PR 2, v0.4.0-dev)** | Step 2 of `SchemaExtractionOverlay` is the preview: per-graph edge-definition strings (`from -[edge]→ to`), loose-collection counts, and a live `Will create N classes and M object properties` summary (driven by the exported pure `summarizeExtraction()` helper) so the curator sees the impact before committing. Datatype-property names aren't shown pre-extract because they come from per-collection field sampling that only runs at extract time; a future iteration can add a "dry-run extract" backend endpoint that returns the TTL + URI map without writing to the registry. |

**Exit Criteria — PR 1 MET:** Backend can connect to any ArangoDB,
discover named graphs + edge definitions, and reverse-engineer an
ontology with full domain/range relationships, datatype properties
from sampled scalar fields, per-class source provenance, and
configurable auto-imports of existing AOE ontologies — all without
requiring the optional `arangodb-schema-analyzer` library. 42 new
unit tests; backend coverage 84.80%.

**Exit Criteria — PR 2 MET:** Workspace canvas right-click → "Extract
from ArangoDB…" opens the overlay; the curator can connect to any
ArangoDB, pick which named graphs / loose collections to include,
toggle field sampling + auto-imports, see a live count of classes
and object properties the extraction will produce, and commit —
all without leaving the workspace canvas. Per-step error surfaces
discriminate `400`/`502`/`500` so the user knows whether to fix
credentials, network, or scope. 33 new frontend tests (component
+ pure helpers + canvas menu); full Jest suite at 617/617.

**Exit Criteria — PR 3 MET:** Sub-A (S.9 constraint mapping, commit
`a484d54`) and sub-B (S.5 schema diff, this commit) shipped in
v0.4.0-dev; see "Plan-vs-reality audit" above. Stream 5 is now
**complete** at the backend level. Frontend overlays for both
sub-PRs are deferred to Stream 7 (Production Polish) -- the backend
deliverables are independently useful via REST.

- **PR 4 — Schema-Analyzer LLM enrichment (PLANNED, P2)**:
  Wire the optional `arango-schema-analyzer` library as an **additive
  enrichment layer over** the direct extractor (PRD FR-9.2), *not* a
  replacement. The current `extract_schema()` branches
  `if mapper is not None: _run_schema_mapper_extract(...)` — i.e. the
  moment the library is installed it fully *replaces* the direct path
  and silently regresses per-class provenance (S.4), SHACL constraints
  (S.9), `owl:imports` (S.10) and named-graph filtering (S.7). PR 4
  removes that trap. Tasks:
  - **S.13** — gate enrichment on `config.use_llm_inference` (not on
    mere import availability); the direct path remains the default and
    the structural source of truth. The library stays out of
    `pyproject.toml` (optional, import-guarded); install is the
    operator's choice.
  - **S.14** — run `AgenticSchemaAnalyzer` + `generate_schema_docs`
    to produce a Markdown **domain description**; persist it on the
    `ontology_registry` entry (new `domain_description` field, nullable)
    and return it in the extract result.
  - **S.15** — merge the analyzer's natural-language descriptions onto
    the direct-path TTL as `rdfs:comment` by collection↔entity name
    (best-effort: unmatched analyzer entities are logged, never block
    the import); provenance / SHACL / imports remain untouched.
  - **S.16** — surface the domain description in
    `SchemaExtractionOverlay` (result step) + an "LLM enrichment"
    toggle on the connect step; show it in the ontology info panel.
  - Tests: enrichment-off == today's TTL byte-for-byte (no regression);
    enrichment-on adds `rdfs:comment`s + a stored `domain_description`
    while preserving the S.4/S.9/S.10 outputs; merge tolerates
    analyzer/collection name mismatches.
  **Exit Criteria (PR 4):** with the library installed and
  `use_llm_inference=true`, an Arango extraction yields the *same*
  classes/properties/constraints/provenance/imports as the direct path
  **plus** a stored Markdown domain description and class/property
  `rdfs:comment`s; with the library absent or the flag off, output is
  identical to today's direct extraction.

---

### Stream 6: Testing, CI & Quality Gates
**PRD:** §8 (Non-Functional Requirements)
**Duration:** 1 week (rescoped — see plan-vs-reality audit below)
**Priority:** P2 — required before v1.0.0 release
**Dependencies:** All feature streams should be complete
**Team Size:** 1 developer

#### Plan-vs-reality audit (v0.4.0-dev)

Most of Stream 6 already shipped piecemeal during Streams 1–5; the original
plan estimates (e.g. ~500 backend tests, ~60 frontend tests) are stale by
3–10x. Re-opened in v0.4.0-dev to close the remaining concrete gaps:

| Layer | Tests | Coverage | Gate |
|-------|-------|----------|------|
| Backend unit tests | **1707** | ~85% | ✅ `--cov-fail-under=80` |
| Backend integration tests | **11 suites** | n/a | ✅ ArangoDB + Redis service containers |
| Backend E2E tests | **4 suites** | n/a | ✅ in CI (Tier 4) |
| Frontend unit tests | **591** | 57.77%S / 76.35%B / 72.66%F / 57.77%L | ✅ no-regression gate (PR 1) |
| Frontend E2E (Playwright) | **4 specs** (workspace smoke in CI) | n/a | ✅ `e2e/workspace.spec.ts` in CI; legacy `/curation` + `/entity-resolution` specs remain local-only |
| CI structure | 5-tier | — | ✅ lint → unit → integration → E2E → unified-image+WS smoke |

Stream 6 is being closed as two PRs:

- **PR 1 — CI hardening (this commit)**:
  - Frontend Jest `coverageThreshold` gate in `frontend/jest.config.ts`
    (no-regression floor; ratchet up, never relax).
  - `npm test -- --ci --coverage` in the `test-frontend` CI step.
  - Codecov upload for backend (py3.12 leg) + frontend lcov (token-less
    on public PRs via `fail_ci_if_error: false`; CODECOV_TOKEN secret
    consumed when set).
  - Python `["3.11", "3.12"]` matrix on `lint-backend` + `test-unit`
    (matches `pyproject.toml`'s `requires-python = ">=3.11,<3.14"`).
    Integration / E2E stay on 3.12 since they test deployed behaviour.
  - `frontend/coverage/` + `backend/coverage.xml` + `frontend/playwright-report/`
    + `frontend/test-results/` added to `.gitignore`.
  - Bumped Testing Library `asyncUtilTimeout` to 5000 ms in
    `jest.setup.ts` — v8 coverage instrumentation triples per-render
    cost in jsdom and the default 1000 ms timeout was creating flakes
    in tests that chain mount → effect → fetch → render.
  - Fixed the same flake source on `MergeCandidatesOverlay`'s empty-state
    test (`waitFor` block so both `getByTestId` + `getByText` must hold
    simultaneously, not as serial assertions across an unstable DOM).

- **PR 2 — Playwright E2E in CI (D.5, DONE)**: `e2e/workspace.spec.ts`
  (workspace smoke with mocked APIs) runs in the `test-e2e-frontend` CI
  job. Legacy specs (`timeline`, `curation`, `entity-resolution`) remain
  local-only — two target deprecated routes per `ui-architecture.mdc`.

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| D.1 | GitHub Actions CI pipeline | DevOps | **DONE (v0.3.0)** | 5-tier pipeline: `lint-backend` + `lint-frontend` + `pre-commit` (drift backstop) → `test-unit` + `test-frontend` → `test-integration` (ArangoDB + Redis service containers) → `test-e2e-backend` → `unified-image` (Docker build + health + WS handshake regression smoke). |
| D.2 | Coverage gates | DevOps | **DONE (PR 1, v0.4.0-dev)** | Backend has `--cov-fail-under=80` on the unit job. Frontend now has `coverageThreshold` (55/70/70/55 floor; ratchet-up policy). Codecov uploads via `codecov/codecov-action@v4` on both layers; `fail_ci_if_error: false` so a Codecov outage does not block PRs — the in-repo `--cov-fail-under` + `coverageThreshold` are the source of truth. |
| D.3 | Missing backend integration tests | Backend | **DONE (v0.3.0)** | 11 integration suites: ArangoRDF import, belief revision Q fixtures, curation workflow, documents API, ER pipeline, import/export round-trip, MCP tools, migrations, orgs API, temporal queries, visualizer install. |
| D.4 | Missing frontend component tests | Frontend | **DONE 10x (v0.4.0-dev)** | 591 Jest tests across components, hooks, lib, and workspace contextMenus (plan said ~60). Coverage: statements 57.8% / branches 76.4% / functions 72.7% / lines 57.8%. |
| D.5 | Playwright E2E tests | Frontend | **DONE (PR 2, v0.4.0-dev)** | `test-e2e-frontend` CI job runs `e2e/workspace.spec.ts` (asset explorer + ontology deep-link smoke with mocked APIs). Legacy `/curation` + `/entity-resolution` specs kept local-only. |
| D.6 | `.env.example` completion | DevOps | **DONE (v0.3.x)** | Covers all three deployment modes (`local_docker`, `self_managed_platform`, `managed_platform`), CORS, Redis, LLM providers, ER thresholds, rate limiting, path-prefix routing. |
| D.7 | Root `AGENTS.md` | Docs | **DONE (v0.3.x)** | Module map + conventions + system dependencies + deeper-doc index. |

**Exit Criteria (PR 1 — MET):** CI enforces backend coverage ≥ 80% and
frontend coverage ≥ 55%S / 70%B / 70%F / 55%L on every PR via in-repo
gates; Codecov captures trends. Python 3.11 + 3.12 matrix on lint +
unit. Stream 6 PR 1 closed.

**Exit Criteria (PR 2 — MET):** Playwright workspace smoke in CI.
Stream 6 closed.

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
| E.1 | OpenTelemetry tracing | Backend | **DONE** | Stream 7 PR 2. New `app/observability/tracing.py` wires OTel via `setup_tracing(app)` in `main.py`. Default-off (`settings.otel_enabled=False` -> `ALWAYS_OFF` sampler, zero outbound traffic). When enabled, picks OTLP gRPC exporter if `otel_exporter_otlp_endpoint` set, else falls back to Console (handy for local dev). `ParentBased(TraceIdRatioBased)` sampler is clamped to `[0, 1]` to absorb env typos. FastAPI / HTTPX / logging instrumentors enabled automatically; trace_id/span_id injected into stdlib logs so structlog joins up. Manual spans on the critical path: `ingest.document` (+ parse / chunk / embed / store children) in `tasks.process_document`, `extraction.run` around `run_pipeline`, `extraction.materialize` around the `_materialize_to_graph` loop, and `ontology.graph.ensure` around `ensure_ontology_graph`. 10 new unit tests verify default-off, idempotent setup, OTLP-vs-Console exporter selection, sample-rate clamp, attribute / parent-child / exception-event emission. |
| E.2 | Alerting rules | DevOps | **DONE** | Stream 7 PR 3. New `infra/monitoring/{prometheus.yml,alerts.yml,alertmanager.yml}` ships the four PRD-required Prometheus alert rules with embedded runbook URLs: `ExtractionFailureRateHigh` (critical), `APILatencyP95High` (warning), `ExtractionQueueBacklog` (warning), `ArangoDBConnectionFailures` (critical). Closed the gap where `EXTRACTION_RUNS` / `EXTRACTION_DURATION` / `QUEUE_DEPTH` were defined-but-never-set: wired `EXTRACTION_RUNS.labels(status).inc()` + `EXTRACTION_DURATION.observe(...)` into both the success and failure paths of `execute_run`, `QUEUE_DEPTH{queue="extraction"}` on background-task add/discard, `QUEUE_DEPTH{queue="ingest"}` via a new `_track_ingest_task` helper in `api.documents`. Added `aoe_db_connection_errors_total` counter incremented from `api.health.ready` with a bounded 3-bucket `reason` label (`timeout` / `auth` / `unknown`) so cardinality stays sane. Alertmanager routes split critical (10s group_wait, 1h repeat) from warning (60s, 12h) with an inhibit rule so warnings don't double-page during related criticals. |
| E.3 | TTL garbage collection | Backend | **DONE** | Stream 7 PR 1. Stamped configurable `ttlExpireAt` on every superseded version via `expire_entity` (90-day default; configurable via `temporal_retention_seconds`). Replaced hard-coded `7_776_000` magic numbers in `re_create_edges`. Added migration `026_ttl_indexes_extended.py` covering the four collections added after migration 006 (`ontology_object_properties`, `ontology_datatype_properties`, `rdfs_domain`, `rdfs_range_class`). Closed a real bug where `update_entity → expire_entity` never set `ttlExpireAt`, leaving historical vertex versions accumulating forever despite the TTL index sitting ready to GC them. |
| E.4 | Auto-install visualizer post-extraction | Backend | **DONE** | Stream 7 PR 1. After `ensure_ontology_graph` succeeds in the extraction service, `_auto_install_visualizer_assets` calls `install_for_ontology_graph` so theme + canvas actions + saved queries are wired automatically. Failure-shielded: any visualizer install error (missing asset file, registry write timeout) logs a warning but never aborts the extraction write path. Resolver factored through `_load_visualizer_installer` for clean test isolation. |
| E.5 | Performance benchmarks | Backend | **DONE** | Stream 7 PR 4. New `benchmarks/operations/` harness with three benches (API latency via `TestClient` + mocked DB, materialization throughput across 10/100/500 classes, temporal snapshot across 10c/100c/500c) plus a `run_baselines.py` driver that captures host snapshot + per-scenario p50/p95/p99/min/max/mean into `benchmarks/operations/baseline.md`. Markdown-table rendering helpers in `harness.py` use stable nearest-rank percentile math (no `statistics.quantiles` version drift). Stale metric names in `docs/benchmarks.md` corrected against the actual exposition; `How to Run` section rewritten to point at the shipped harness paths instead of nonexistent ones. `make bench` + `make bench-update` targets added. 19 new unit tests pin the harness contract (percentile math, table rendering, per-bench smoke at small `n`, write-vs-print flag behaviour). Real-DB end-to-end load testing remains a manual `k6`/`locust` exercise per `docs/benchmarks.md`. |
| E.6 | Docker Compose production config | DevOps | **DONE** | Stream 7 PR 3. Hardened `docker-compose.prod.yml` with `deploy.resources.limits`+`reservations` on every service (sized per role: backend 2vCPU/2G, arangodb 4vCPU/4G, redis 0.5vCPU/384M, caddy 0.5vCPU/256M, etc), shared `json-file` log driver capped at 10MB×5 files via a YAML anchor so disks can't fill quietly, and a new `monitoring` profile that brings up Prometheus (v2.55) + Alertmanager (v0.27) with bind-mounted configs from `infra/monitoring/`. Optional `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` env passthrough to the backend wires the Stream 7 PR 2 tracing config without code changes. Prometheus + Alertmanager bind to 127.0.0.1 only; expose through Caddy with auth if needed. Full runbook in `docs/operations/production-deployment.md` covering topology, bring-up, resource sizing, observability endpoints, per-alert remediation steps, Alertmanager receiver customisation, and backup/restore procedures. |
| E.7 | README update | Docs | **DONE** | Stream 7 PR 4. README's "Observability" row flipped from Partial → Done with the full picture (structlog + Prometheus + OTel + alerting + monitoring profile) and a pointer to `docs/operations/production-deployment.md`. New "Configuration" rows for `TEMPORAL_RETENTION_SECONDS` (Stream 7 PR 1), `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_TRACE_SAMPLE_RATE` (Stream 7 PR 2). "Deployment → Docker Compose" section expanded with the `--profile mcp` and `--profile monitoring` bring-up commands and a one-line summary of the resource-limit / log-rotation hardening. "Documentation" table gains rows for the production deployment runbook and the ops-benchmarks README. Stream 7 closes with this PR. |

**PR plan (incremental):**
- **PR 1 (DONE)** — E.3 TTL garbage collection + E.4 visualizer auto-install. Smallest contained slice, fixes a real history-accumulation bug + closes the manual visualizer-install loop. 21 new unit tests; full backend unit suite passes (1949 tests).
- **PR 2 (DONE)** — E.1 OpenTelemetry tracing. New `app/observability/` module, OTLP+Console exporters, FastAPI/HTTPX/logging auto-instrumentation, manual spans on ingest → extraction → materialize → graph paths. 10 new unit tests; full backend unit suite passes (1959 tests).
- **PR 3 (DONE)** — E.2 alerting + E.6 prod docker-compose. New `infra/monitoring/` configs with 4 PRD-required alert rules, live metric wiring (closed `EXTRACTION_RUNS`/`QUEUE_DEPTH` no-op gap), `aoe_db_connection_errors_total` counter on `/ready`, production-hardened compose with resource limits + log rotation + monitoring profile, full runbook doc. 32 new unit tests; full backend unit suite passes (1991 tests).
- **PR 4 (DONE)** — E.5 benchmarks + E.7 README. New `benchmarks/operations/` harness (API latency / materialization / temporal snapshot) with committed baseline numbers, `make bench` + `make bench-update` targets, stale metric names in `docs/benchmarks.md` corrected against the actual exposition, README's Observability row flipped to Done with new env-knob rows for `TEMPORAL_RETENTION_SECONDS` + the three `OTEL_*` settings, and pointers added for the production-deployment runbook + ops-benchmarks README. 19 new unit tests; full backend unit suite passes (2010 tests). **Stream 7 complete.**

**Exit Criteria:** ✓ Traces visible (OTLP + console exporter wired, default-off via `OTEL_ENABLED`). ✓ Alerts configured (`infra/monitoring/alerts.yml` with extraction failure rate / API p95 / queue backlog / DB connectivity). ✓ Performance baselines documented (`benchmarks/operations/baseline.md` + `docs/benchmarks.md`). ✓ Production deployment guide complete (`docs/operations/production-deployment.md`).

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

#### Plan-vs-reality audit (v0.4.0-dev)

The "Future Phase" framing is stale: the **core WebGL migration already
shipped** as part of the object-centric workspace, not as a separate post-v1.0
project. The default `/workspace` Network graph style is `SigmaCanvas.tsx` — a
Sigma.js v3 + graphology renderer with ForceAtlas2 / circular / grid / random
layouts (`graphology-layout-*`), PageRank-based node sizing
(`graphology-metrics/centrality/pagerank`), noverlap, and `@sigma/edge-curve`
+ `@sigma/node-border`.

React Flow (`reactflow`) is **not fully retired** — it still backs:

- the workspace **Box & Arrow (UML) graph style** (`BoxArrowCanvas.tsx`),
  selectable from the canvas "Graph Style" submenu alongside the Sigma
  Network style — so React Flow remains on a primary `/workspace` path;
- the **legacy routes** `/curation`, `/ontology/edit`, `/entity-resolution`
  (slated for removal/overlay-migration per `ui-architecture.mdc`, not a
  Sigma port); and
- the **pipeline DAG** (`AgentDAG.tsx`), a small fixed-size step graph where
  React Flow is a fine fit and a Sigma rewrite has no payoff.

So the renderer swap is **partial by design**: Sigma handles the large
force-directed class graph (its strength); React Flow handles the structured
UML box-arrow view and the DAG (its strength). Full React Flow removal is not
a goal. What remains for stream closure is the **TopBraid-class editor
panels**, which were always the harder half and are independent of the
renderer.

#### Tasks

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| V.1 | Sigma.js + graphology integration | Frontend | **DONE (v0.4.0-dev)** | `frontend/src/components/workspace/SigmaCanvas.tsx` is the workspace canvas: `graphology` graph + Sigma v3 WebGL renderer, dynamically imported on `/workspace`. Replaced React Flow as the primary visualization. |
| V.2 | ForceAtlas2 layout | Frontend | **DONE (v0.4.0-dev)** | `graphology-layout-forceatlas2` + `noverlap` + `circular` wired; canvas context menu "Layout" submenu offers Force-Directed / Circular / Grid / Random (`contextMenus/canvas.ts`). Lens changes never relayout (§14); layout changes always do. |
| V.3 | Semantic zoom | Frontend | **Not started** | Zoom-dependent level-of-detail (labels-only when zoomed out → full detail when zoomed in) is not yet implemented in `SigmaCanvas`. |
| V.4 | Edge bundling | Frontend | **Partial** | `@sigma/edge-curve` provides curved edges (Edge Style menu), but true `graphology`-based edge bundling for dense graphs is not implemented. |
| V.5 | Class tree browser panel | Frontend | **DONE (v0.4.0-dev)** | `ClassHierarchy` (library) + `AssetExplorer` (workspace) render the `subclass_of`-derived class tree with search and drag-to-reparent. |
| V.6 | Property matrix panel | Frontend | **Not started** | No spreadsheet-style domain × range property matrix yet. Property data is reachable per-class via `FloatingDetailPanel` but not as a cross-class matrix. |
| V.7 | Restriction editor panel | Frontend | **Not started (display only)** | Stream 3 PR 4 added constraint *display* in the workspace, but there is no visual `owl:Restriction` *builder*. |
| V.8 | Namespace manager | Frontend | **Not started** | No prefix/namespace settings dialog. |
| V.9 | Validation console | Frontend | **Not started** | OWL/SHACL results surface via the quality report overlay, not a real-time bottom validation console. |
| V.10 | Migrate curation page to Sigma.js | Frontend | **Won't do (route deprecated)** | `/curation` is a legacy route targeted for removal/overlay-migration per `ui-architecture.mdc`; porting its `GraphCanvas` to Sigma is not worth it. The workspace canvas already covers curation via overlays. |
| V.11 | Migrate editor page to Sigma.js | Frontend | **Won't do (route deprecated)** | Same as V.10 for `/ontology/edit`. |

**Exit Criteria:** ~~All graph visualization uses Sigma.js/graphology.~~ The
workspace **Network graph style** uses Sigma.js/graphology and renders 1000+
nodes smoothly (V.1 / V.2 / V.5 met). Remaining for full stream closure: the
TopBraid-class editor panels (V.3 / V.4 / V.6–V.9). The workspace Box & Arrow
(UML) view, legacy-route canvases (V.10 / V.11), and the pipeline DAG keep
React Flow by design — full React Flow removal is not a goal.

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
| W.6 | Edge selection in sidebar | Frontend | **DONE** | `SigmaViewportApi.focusEdge(edgeKey)` + `BoxArrowCanvas`'s equivalent already shipped; `AssetExplorer` `EdgeRow` rows are clickable and fire `onSelectEdge(edgeKey, ontologyId)`; the workspace page's `handleSelectEdgeFromSidebar` calls `viewportApiRef.current?.focusEdge(edgeKey)` and sets `selectedEdgeKey`; both canvases honour the prop with an indigo highlight ring. Sidebar auto-expands the relations accordion when an edge becomes selected from the graph. |
| W.7 | Keyboard navigation | Frontend | **DONE (v0.4.0-dev)** | Arrow Up / Arrow Down navigate between visible sidebar rows when focus is on a `[data-sidebar-row]` button (class rows tagged `class:<ontologyId>:<classKey>`, edge rows tagged `edge:<ontologyId>:<edgeKey>`). Pure decision in `frontend/src/lib/sidebarKeyboardNav.ts::computeNextSidebarRow(key, currentRow, allRows)` -- returns the element to focus next, or `null` for "ignore" (wrong key, current row not in list, already at boundary). The workspace page's keydown handler calls it and `preventDefault()`s on success so the page does not also scroll. No wrap-around: clamps at top/bottom because a thousand-row explorer would surprise users. Enter on a focused row fires the existing button onClick (native behaviour). The canvas pane (`<main>` in `app/workspace/page.tsx`) gets `tabIndex={0}` + `outline-none` so Tab can land on it after the last sidebar row, satisfying the "Tab cycles between sidebar and canvas" exit criterion without trapping focus. Tests: 9 cases in `lib/__tests__/sidebarKeyboardNav.test.ts` (down / up / clamp top / clamp bottom / ignored keys / orphan currentRow / empty rows / single-row / DOM-order respect) + 2 contract tests in `components/workspace/__tests__/AssetExplorerSidebarRowAttribute.test.tsx` pinning the `class:<oid>:<key>` and `edge:<oid>:<key>` attribute shape on real rendered rows. Full frontend Jest suite green at 581 passing (was 570); type-check + lint clean. |
| W.8 | Minimap selected indicator | Frontend | **DEFERRED** | The Sigma workspace canvas has no minimap today (the legacy React-Flow `/curation` page does, but that surface is on the deprecated path -- Stream 8 will replace it). Re-open W.8 alongside Stream 8 when a Sigma minimap lands; the selection state (`selectedNodeKey`) is already plumbed through the page, so the minimap will just need to read it and render a bright dot. |

**Exit Criteria — MET:** Clicking a class or edge in either the sidebar or the graph highlights and centers the same entity in both views; Arrow Up / Arrow Down moves focus across the visible sidebar rows; Tab lands on the canvas pane after the last sidebar row. The interaction feels instant and fluid. W.8 is parked behind the Sigma-minimap work in Stream 8.

---

### Stream 11: Iterative Refinement & Belief Revision
**PRD:** §6.16 FR-16.1–16.14, §6.13 FR-13.26–13.27, §6.11 FR-11.14–11.16, §6.5 (substrate), §7.7b (endpoints)
**ADR:** `docs/adr/008-belief-revision-substrate.md`
**Duration:** ~5 weeks (3 phases)
**Priority:** P1 — closes the loop on iterative knowledge construction; without this, ontology quality plateaus after ~10 documents per ontology
**Dependencies:** Stream 0 (PGT alignment, complete) provides the property-collection split that revision verdicts depend on. Can run in parallel with Stream 1 Phase 2 (composition) and Stream 4 (quality dashboard).
**Team Size:** 1 backend (heavy) + 0.5 frontend (Phase 3 Revisions Inbox UX)

#### Problem Statement

Each document is currently extracted as an independent event. When document `D2` arrives after `D1`:

1. `D1` produced classes/properties/edges in the ontology.
2. Domain experts curated `D1`'s output.
3. `D2` is extracted and merged via Entity Resolution.
4. **No backward pass occurs.** Conclusions made from `D1` are never revisited in light of `D2`'s evidence.

This is a known need with established names: **abductive refinement**, **belief revision**, **iterative knowledge construction**, **continual KG refinement**. The literature (TRAIL 2025, Evo-DKD 2025, Evontree 2025, Graph-Native Cognitive Memory 2026) converges on a hybrid pattern: cheap mechanical rules first, expensive LLM judgment only where rules can't decide, and human-in-the-loop fallback for low-confidence cases.

We have most of the substrate already (temporal versioning, provenance, multi-signal confidence, LangGraph orchestration, curation reject cascade). What we lack is the **revision controller** — the agent that, when new evidence arrives, decides what to do with each existing belief that the new evidence touches.

#### Objectives

- Insert a **Belief Revision Agent** into the LangGraph pipeline (between ER and Quality Judge) that revisits existing beliefs when new evidence arrives
- Implement the four-phase pipeline (touchpoint discovery → mechanical verdict → LLM revision → background consolidation) with formal AGM-operator semantics on top of edge-interval temporal versioning
- Add a **Revisions Inbox** to the workspace so curators can review FLAG_FOR_CURATION revisions
- Add a **background consolidation job** for periodic ontology-wide rule re-runs and confidence decay
- Add **safety guards** (published-item protection, circuit breaker, dry-run, cursor resumption)
- Expose the revision lifecycle via REST + MCP for external agents

#### Tasks — Phase 1: Substrate (1.5 weeks) — **COMPLETE in v0.2.0**

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| IBR.1 | `revision_meta` collection + temporal hooks | Backend | **DONE** | Collection + MDI indexes on `[ontology_id, created]` and `[ontology_id, action, status]`; migration file shipped. |
| IBR.2 | Evidence-age + evidence-count signals | Backend | **DONE** | `compute_class_confidence()` includes 9 signals (was 7); weights rescaled to 1.0; backfill migration applied. |
| IBR.3 | Confidence decay function | Backend | **DONE** | `apply_confidence_decay(belief, half_life_days)` returns `confidence_with_decay` separately. Feature-flagged off (will turn on with consolidation job, IBR.17). |
| IBR.4 | Ontology rule engine (R1–R4) | Backend | **DONE** | `app/services/ontology_rules.py` ships R1 (synonym closure), R2 (subclass transitivity), R3 (disjointness), R4 (redundant subClassOf detection). Single AQL pass per ontology. |
| IBR.5 | Touchpoint discovery service | Backend | **DONE** | `app/services/touchpoint_discovery.py` ships embedding-similarity, exact-label, and chunk-overlap signals. Threshold configurable; default 0.30. |
| IBR.6 | Foundation tests + telemetry | Backend | **DONE** | Substrate tests pass; telemetry counters (`touchpoints_per_run`, `rule_violations_per_run`) wired. |

**Phase 1 exit criteria — MET:** Substrate is in production. `make migrate` + `make test` green for all six tasks.

#### Tasks — Phase 2: Per-document Belief Revision (2 weeks) — **COMPLETE in v0.2.0**

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| IBR.7 | Mechanical verdict classifier | Backend | **DONE** | `app/services/revision_verdict.py` returns REINFORCED / REFINED / GAP-FILLING / REDUNDANT / CONTRADICTED / UNCERTAIN with rule-name justification. Deterministic. |
| IBR.8 | LLM revision agent | Backend | **DONE** | `app/services/revision_agent.py` prompt + structured-output schema + Evo-DKD cross-check (downgrade to FLAG_FOR_CURATION on justification mismatch). Real LLM gated behind env flag. |
| IBR.9 | Levi-identity supersede helper | Backend | **DONE** | `app/db/repositories/temporal_revisions.py::supersede(entity_id, new_doc, agent_meta)` ships as atomic AQL transaction (expire + insert + revision_meta write). Idempotent. |
| IBR.10 | Belief Revision LangGraph node | Backend | **DONE** | `app/extraction/agents/belief_revision.py` orchestrates Phase 1 → 2 → 3. Conditional edge skips Phase 3 LLM agent when no CONTRADICTED + UNCERTAIN. Wired behind `BELIEF_REVISION_ENABLED` feature flag. |
| IBR.11 | Wire into pre-curation filter | Backend | **DONE** | Auto-applied revisions hit the graph via IBR.9; FLAG_FOR_CURATION revisions queued in staging alongside new entities. |
| IBR.12 | Revision metrics on extraction run | Backend | **DONE** | `extraction_runs.stats` carries `touchpoints_discovered`, `verdict_distribution`, `llm_calls`, `tokens_used`, `estimated_cost_usd`, `auto_applied`, `flagged_for_curation`, `mean_revision_latency_ms`. |
| IBR.13 | Phase 2 integration tests | Backend | **DONE** | End-to-end fixtures cover Q.1 (gap-filling), Q.2c (relationship gap-filling), Q.3a (batch gap-filling), Q.3c (negative test for false-positive prevention). MerchantSettlementAccount documented as an IBR.11/embeddings gap (label_fuzzy 0.28 < 0.50 floor). |

**Phase 2 exit criteria — MET:** Re-extracting against an existing ontology produces revision_meta documents; mechanical verdicts cleanly classify the Q.1–Q.3 fixtures; LLM agent fires only on contested cases; auto-applied revisions create proper temporal versions; integration suite covers the full path.

#### Tasks — Phase 3: Curation UX + Consolidation (1.5 weeks)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| IBR.14 | Revisions Inbox overlay | Frontend | **DONE** | `frontend/src/components/workspace/RevisionsInboxOverlay.tsx`. Floating overlay over the canvas (no new route per `ui-architecture.mdc` §9). Opened from the ontology context menu, the canvas context menu (when an ontology is loaded), or the new "Revisions Activity" tile in the Quality Report. Inline accept/reject buttons with optimistic row removal + toast feedback. |
| IBR.15 | Revision detail panel | Frontend | **DONE** | Sibling `RevisionDetailPanel` co-located in `RevisionsInboxOverlay.tsx`. Click any row to expand: verdict, action, agent identity + version, triggering doc, confidence delta, full reasoning, evidence quotes. Modify panel allows curator to override the proposed action and attach an audit note. |
| IBR.16 | Accept/Reject/Modify endpoints + service | Backend | **DONE** | `backend/app/api/revisions.py` exposes `POST /api/v1/revisions/{key}/{accept,reject,modify}`; service layer in `backend/app/services/revision_actions.py` handles idempotency and translates `ValueError` from the supersede helper into HTTP-friendly errors. Modify supports both `override_action` and `new_vertex_data`. Unit-tested at both layers. |
| IBR.17 | Background consolidation job | Backend | **DONE** | `backend/app/services/consolidation.py` orchestrates rule engine → confidence decay → stale-belief scan with `ConsolidationCursor` checkpointing (`consolidation_jobs` collection). Admin endpoints in `backend/app/api/admin.py`: `POST /admin/ontology/{id}/consolidate?dry_run=&job_key=`, `GET /admin/consolidation-jobs[/{key}]`. Stage failures are logged and skipped, not aborted. |
| IBR.18 | Safety guards | Backend | **DONE** | `backend/app/services/revision_safety.py` implements (a) `should_flag_for_curation` — structural revisions on `status="approved"` entities are downgraded to `FLAG_FOR_CURATION`, wired into `belief_revision._apply_mechanical/_apply_llm`; (b) `RevisionRateLimiter` — fixed-window in-memory circuit breaker (`belief_revision_circuit_*` settings) consulted by `belief_revision.revise()` before any LLM call; (c) dry-run support via the consolidate endpoint and `PlannedAction` dataclass; (d) `ConsolidationCursor` for resume-on-restart. Each guard has unit tests. |
| IBR.19 | Quality dashboard revision tiles | Frontend | **DONE** | "Revisions Activity" section in `frontend/src/components/dashboard/QualityReportOverlay.tsx` — Total / Pending / Applied / Rejected KPIs aggregated from `/api/v1/revisions/?ontology_id=&limit=200`, verdict-distribution chips, top-agent label, and a "Show inbox" CTA wired to IBR.14. |
| IBR.20 | Belief-revision MCP tools | Backend | **DONE** | `backend/app/mcp/tools/belief_revision.py` registers six tools: `list_revisions_inbox`, `list_recent_revisions`, `get_revision`, `decide_revision` (dispatches to accept/reject/modify), `run_consolidation` (defaults `dry_run=True`), `get_circuit_breaker_state`. Wired into `app/mcp/server.py`. MCP unit tests cover each tool. |
| IBR.21 | Documentation + ADR cross-link | Docs | **DONE** | ADR-008 grew an "Implementation Status (v0.4.0-dev)" appendix with the file map and operator/curator notes. `docs/user-guide.md` got a new "5. Belief Revision" section (entry points, accept/reject/modify, consolidation, circuit breaker). `docs/api-reference.md` gained a "Belief Revision" section (REST + admin endpoints). `docs/mcp-server.md` gained a "Belief Revision Tools" subsection. `docs/architecture.md` Data Flow now describes the Belief Revision LangGraph node and links to ADR-008. |

**Phase 3 exit criteria — MET:** Curators can accept/reject/modify revisions in the workspace overlay; admins can trigger consolidation passes (with dry-run) and inspect cursors; all four safety guards are exercised in unit tests; six MCP tools are registered and unit-tested; the Quality Report tile surfaces revision health and links into the inbox.

#### Implementation Plan — Recommended Order

| Phase | Tasks | Est. Duration | Prerequisites |
|-------|-------|---------------|---------------|
| **Phase 1: Substrate** | IBR.1, IBR.2, IBR.3, IBR.4, IBR.5, IBR.6 | 1.5 weeks | None beyond Stream 0 (PGT alignment, complete) |
| **Phase 2: Per-doc revision** | IBR.7, IBR.8, IBR.9, IBR.10, IBR.11, IBR.12, IBR.13 | 2 weeks | Phase 1 |
| **Phase 3: UX + consolidation** | IBR.14, IBR.15, IBR.16, IBR.17, IBR.18, IBR.19, IBR.20, IBR.21 | 1.5 weeks | Phase 2 |

**Parallelization within phases:**
- Phase 1: IBR.1, IBR.2/IBR.3, IBR.4, IBR.5 are independent and can run in parallel; IBR.6 is the integration step
- Phase 2: IBR.7 and IBR.8 in parallel; then IBR.9 (Levi helper) is the bottleneck before IBR.10 (the node) can land
- Phase 3: Frontend (IBR.14, IBR.15, IBR.19) can run in parallel with backend (IBR.16, IBR.17, IBR.18, IBR.20)

**Exit Criteria (Stream 11 overall):** A second document uploaded to an ontology with prior curated content visibly revises the prior beliefs (REINFORCED boosts, REFINED supersedes, RETRACT expires, FLAG_FOR_CURATION lands in inbox); curators have a clear inbox UX; admin-triggered consolidation produces a useful report; all safety guards prevent runaway behavior; ADR-008 is the source of truth for the architecture.

---

### Stream 12: Workspace Performance — N+1 elimination, payload reduction, caching
**Origin:** v0.3.0 perf sweep (T1 + T2)
**Duration:** mostly delivered in v0.3.0; remaining items are data-driven
**Priority:** P0 (active items unblock perceived responsiveness on 1000+ class ontologies)
**Dependencies:** None
**Team Size:** 1 backend developer

#### Delivered in v0.3.0

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| T1.1 | `?include=summary` projection on `/classes` and `/edges` | Backend | **DONE** | `app/services/ontology_projections.py` defines `CLASS_SUMMARY_FIELDS` / `EDGE_SUMMARY_FIELDS`; AQL `RETURN` clause for classes, Python projection after rdfs-range enrichment for edges. ~3x payload reduction on the workspace's first paint. |
| T1.2 | Single-item GET endpoints | Backend | **DONE** | `GET /ontology/{id}/edges/{edge_key}` and `GET /ontology/{id}/properties/{prop_key}` ship with rdfs-range enrichment and `property_collection` annotation. Kills the FloatingDetailPanel N+1 (was issuing one list call per click). |
| T1.5 | `ontologyDataCache` (frontend) | Frontend | **DONE** | Module-level cache keyed by `(ontologyId, kind, profile)` with in-flight dedup, mutation-driven invalidation, and `clearOntologyCache` for full reset. Wired into `workspace/page.tsx` and `AssetExplorer.tsx`. Re-visiting an ontology is instant. |
| T2 | Collapse 8-14 `/edges` round-trips into 2 | Backend | **DONE** | `_fetch_live_edges_and_properties` does one `db.collections()` call + one AQL with FLATTEN-over-subqueries (one subquery per existing live edge or property collection). Query strings cached per `(edges, props)` tuple. Tests cover parity, missing collections, AQL-unsafe collection names, summary stripping. |
| T3 | Stage-level perf telemetry | Backend | **DONE** | `list_ontology_classes`, `_fetch_live_edges_and_properties`, `list_ontology_edges` all log per-stage `ms_*` (fetch / enrich / conf / project / collections / aql / total). Both as the message and as `extra=` so future investigations are data-driven, not guess-driven. |
| T4 | OWL-format sniffer for misleading extensions | Backend | **DONE** | `_sniff_format_from_content` overrides extension hints when content begins with strong format signals (`<?xml`, `@prefix`, `{"@context"`); parse failures suggest renaming the file. Fixes the bug where `wtw-edward-kim-ontology.owl` (Turtle inside) failed to import. |
| T5 | UI race-condition fixes | Frontend | **DONE** | Loading spinner shows the right ontology name on switch (was flashing the previous one); VCR timeline defaults to LATEST event on ontology load (was leaving the slider mid-history requiring manual scrub). |

#### Resolved (P0, data-driven) — all DONE

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| T6 | WTW switch ~8-9s investigation | Backend | **DONE (v0.4.0-dev)** | **Telemetry + profile + fix all landed.** (1) The canvas loads `GET /{id}/effective?include=summary`, which had no per-stage timing — `compute_effective_ontology` now logs per-stage `ms_*` (meta-snapshot / closure / fetch / project / conflicts / etag / total) in the `list_ontology_edges` message-plus-`extra` style. (2) A new real-DB profiling bench (`benchmarks/operations/bench_effective_ontology.py`, seeds a synthetic ontology + transitive imports chain and captures the per-stage means) found the bottleneck was **not** the AQL round-trips but `_detect_conflicts` → `_cycle_conflicts`: the old all-paths cycle DFS restarted from every node with per-step list copies, which is super-linear on the long subclass chains real ontologies produce (230ms of 266ms at 1500 classes; **1818ms of 1876ms at 3000 classes**). (3) Rewrote it as a linear-time three-colour iterative DFS (one representative cycle per back-edge, O(V+E)), preserving the canonical-cycle + requires-import contract. **Result: 3000-class effective graph 1876ms → 42ms (~45×); the conflicts stage 1818ms → 3.7ms (~490×); 6000 classes now 85ms.** Cost now scales linearly and lives in the AQL fetch where it belongs, well under the 2s switch budget — so `/edges` + `/effective` pagination stays **unnecessary** (deferred indefinitely). Regression tests: long-acyclic-chain (no false cycle) + cycle-embedded-in-a-longer-chain (lead-in node excluded). |
| T7 | `/runs/{id}/cost` ~9s | Backend | **DONE (v0.4.0-dev)** | `get_run_cost` now caches the expensive `compute_ontology_quality` walk on `extraction_runs.stats.cached_quality` (carries `ontology_id` + `avg_confidence` + `completeness` + `computed_at` + `compute_ms`). First call after extraction computes + persists the snapshot; subsequent calls return it without touching the ontology — ~9s → <50ms on the WTW demo. Cache invalidates automatically when the run's `ontology_id` flips, and `?refresh=true` on the route forces a recompute for callers that just landed a curation decision and want fresh numbers. Response carries `quality_computed_at` + `quality_from_cache` so the UI can render staleness hints and ops can grep the fast/slow split. Cache writes are best-effort — a failed persist logs `warning` and returns the freshly computed numbers; the next call simply retries. Tests: 5 new cases in `TestGetRunCostQualityCache` (cache miss populates snapshot, hit skips compute, `refresh=True` always recomputes, ontology-id mismatch invalidates, write failure does not poison response) + 1 API test confirming `?refresh=true` threads through. Full backend suite green at 1698 passing (was 1677); mypy + ruff clean. |
| T8 | `/runs` ~3s | Backend | **DONE (v0.4.0-dev)** | The `/runs` route enrichment used to issue one `doc_get` per `doc_id` per run **and** one AQL per run for the `ontology_registry` lookup -- ~50 sequential round-trips on a typical 25-row page. The route now bulk-enriches in **exactly two AQL calls per page** regardless of page size: (1) `FOR d IN documents FILTER d._key IN @ids RETURN {key, filename, chunk_count}`, (2) `FOR o IN ontology_registry FILTER o.extraction_run_id IN @rids RETURN {rid, oid}`. Both filters use `IN @ids` so they hit the primary index instead of full-scanning. Per-run stamping reads from the resulting dictionaries; same final shape as the pre-T8 loop, so frontend consumers see no diff. Failures on either bulk fetch are debug-logged and skipped — the route still returns the run page with whatever enrichment succeeded. Tests: updated 3 existing route tests for the new query shape + added 1 new invariant test (`test_list_runs_bulk_enrichment_scales_with_page_size`) that asserts AQL count stays at 2 for a 5-run page spanning 10 docs (was 16 round-trips pre-T8) and that `doc_get` is never called from the list route. Full unit suite green at 1684 passing; mypy + ruff clean. |

#### Pending (P1, larger refactor)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| T9 | Remove `?include=full` from canvas paths | Frontend | **DONE (v0.4.0-dev)** | Audited workspace canvas loads: `fetchGraphData` uses `GET /{id}/effective?include=summary` only; AssetExplorer class/edge previews use `?include=summary`. No live `include=full` fetches on canvas paths — detail panels use single-item endpoints per T1.2. |
| T10 | Pagination cursor on `/classes` and `/edges` | Backend + Frontend | 1 day | **`/classes` DONE (v0.4.0-dev); `/edges` + `/effective` DEFERRED with rationale.** `GET /{id}/classes` gained **opt-in keyset pagination** via the shared `app.db.pagination.paginate` helper: pass `?limit=` (1–500) and an opaque `?cursor=` to pull a page at a time ordered by `(label, _key)`; the response adds `next_cursor` / `has_more` / `total_count`. **Back-compatible:** with no `limit` the endpoint returns the original full `{data:[...]}` list via the single AQL, so every existing caller is unchanged. Summary projection still applies per-page; a corrupt cursor returns `400` (not `500`). Frontend: new reusable `fetchAllPages(buildPath, opts)` helper in `lib/api-client.ts` (follows `next_cursor`, with a `maxPages` cap + non-advancing-cursor guard + `AbortSignal` passthrough); `ClassHierarchy` now pages classes (500/page) to exhaustion so a large ontology never lands as one unbounded response while the hierarchy tree still resolves every parent link. Tests: `tests/unit/test_ontology_list_classes.py` (10 cases: back-compat full path, paginate delegation + keyset params, cursor forwarding, last-page null cursor, summary stripping, empty-collection shapes, `ValueError`→400, real `decode_cursor`→400, real keyset round-trip) + 6 `fetchAllPages` cases in `lib/__tests__/api-client.test.ts`. **Plan-vs-reality finding:** the workspace **canvas does not call `/classes` or `/edges`** — it loads `GET /{id}/effective?include=summary` (target + transitive imports, already ETag/304 + module-cache backed). So `/classes` pagination protects the library `ClassHierarchy` + asset-explorer previews from unbounded payloads, but does **not** address canvas load on huge ontologies. `/edges` pagination was deferred because it is a heterogeneous union over ~9 edge collections with whole-set Python enrichment + confidence (no clean keyset without a real refactor) and benefits no current canvas path; `/effective` pagination was deferred because conflict detection + graph layout both need the full set, and a profile (T6) should justify the larger "progressive load + relayout" effort before it's built. |

**Exit Criteria — MET (v0.4.0-dev):** Workspace switch on a 1000+ class ontology stays under 2s end-to-end (effective-graph computation is now 27ms at 1500 classes / 42ms at 3000 / 85ms at 6000 after the T6 cycle-DFS rewrite — see T6 row); no API endpoint exceeds 1s p95 on demo data; per-stage telemetry remains in the logs as a permanent diagnostic surface (now including `/effective`). A standalone real-DB profiling harness (`benchmarks/operations/bench_effective_ontology.py`) reproduces the numbers on demand.

---

### Stream 13: Image-Aware Document Extraction
**PRD:** §6.1 FR-1.11–FR-1.15, §6.2 FR-2.16–FR-2.17, §6.11 FR-11.17
**Duration:** 1 week
**Priority:** P1 — directly addresses observed PPTX orphan-class quality gap
**Dependencies:** Existing ingestion (`parse_pptx`, `parse_pdf`), chunk storage, extraction prompt/batching, quality orphan metrics

#### Objectives
- Make visual evidence loss observable: every PPTX/PDF run should report visual assets found, processed, skipped, and failed.
- Extract useful text/structure from embedded images, diagrams, screenshots, and scanned pages via configurable OCR or vision-caption providers.
- Preserve provenance for visual evidence so extracted classes, `parent_uri`, attributes, relationships, and constraints can cite slide/page + visual asset IDs.
- Feed visual context to the LLM separately from body text, with prompt guidance that visual hierarchy can support subclass/object-property extraction only when cited.
- Reduce avoidable orphan classes from presentation decks by preserving slide titles, title-only slides, and diagram-derived hierarchy.

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| IMG.1 | Visual asset metadata model | Backend | 0.5 day | **DONE** — `VisualAsset` + `VisualExtractionDiagnostics` in `app/services/visual_extraction.py`; persisted on `documents.metadata.visual_extraction` via `merge_document_user_metadata`. |
| IMG.2 | PPTX visual inventory | Backend | 0.5 day | **DONE** — picture/chart shapes walked (incl. groups) with alt-text preservation; placeholders emitted when configured; title-only slides now produce chunks via `format_section_chunk_text`. |
| IMG.3 | PDF image/scanned-page inventory | Backend | 0.5 day | **DONE** — non-text PDF blocks counted; image-only pages marked with `[Scanned or image-only page N: OCR not configured]`. |
| IMG.4 | OCR / vision-caption adapter | Backend | 1 day | **DONE** — `VisualCaptionProvider` abstract base, `NoOpCaptionProvider` default, `register_caption_provider`/`get_caption_provider` registry with lazy-import for optional adapters. Two concrete providers: `OpenAIVisionCaptionProvider` in `app/services/visual_captions_openai.py` (cloud, activates on `visual_caption_provider="openai_vision"`, uses `openai_api_key` + `visual_caption_openai_model` default `gpt-4o-mini`, retries transport errors with exponential backoff) and `TesseractCaptionProvider` in `app/services/visual_captions_tesseract.py` (on-prem, activates on `visual_caption_provider="tesseract"`, requires `pip install -e .[ocr]` + `tesseract` host binary, aggregates per-word confidence into a structured `CaptionResult`). Both fail loudly with structured failure reasons (`missing_api_key`, `missing_package`, `missing_binary`, `no_text_detected`, `bad_image`, `ocr_error`, `api_error:<detail>`, etc.) so ingestion always falls back to placeholders cleanly. |
| IMG.5 | Visual-aware chunking | Backend | 0.5 day | **DONE** — `Chunk` carries `chunk_kind` (`text` / `visual` / `mixed`) and `visual_assets` (projection of source-section assets); persisted on the chunks collection when non-empty. `Section.visual_asset_indexes` threads asset provenance from parsers through chunking. |
| IMG.6 | Visual-aware extraction strategy | Backend | 1 day | **DONE** — new `visual_heavy_presentation` strategy with `tier1_visual_aware` prompt registered in `app/extraction/prompts`. Detector keys on `chunk_kind` ratio + PPTX format hint; prompt explicitly tells the LLM how to read `[Slide N: Title]`, `[Visual omitted: ...]`, `[Visual (alt text): ...]` markers and caps alt-text-only evidence confidence at 0.7. |
| IMG.7 | Orphan-risk warning | Backend | 0.5 day | **DONE** — `aggregate_document_visual_diagnostics` + `build_orphan_risk_warning` wired into `execute_run`; appends a `visual_heavy_orphans` entry to `extraction_runs.stats.warnings` with per-document slide/page breakdown when thresholds are met. Configurable via `visual_orphan_warning_*` settings. |
| IMG.8 | Regression fixtures and tests | Backend | 1 day | **DONE** — `tests/unit/test_visual_extraction_regression.py` builds an in-process "vehicle taxonomy" PPTX (10 slides, title-only hierarchy + 3 pictures with mixed alt-text) and a scanned PDF (image-only page + text page) via PyMuPDF, then exercises all five exit criteria: inventory counts, placeholder mode toggle, OCR/caption injection (with a stub `VisualCaptionProvider` + max-call cap + provider-failure paths), strategy → prompt routing through `strategy_selector_node`, and the end-to-end orphan-risk warning. Caught + fixed a real bug: `parse_pdf` was missing `fitz.TEXT_PRESERVE_IMAGES` in its text-dict flags, so image-only PDFs silently returned zero blocks and `scanned_page_count` stayed at zero. Caption provider is now wired into `collect_pptx_visual_assets` so a non-no-op provider produces `[Visual (caption): ...]` chunk text and a `vision_caption` asset method. |

**Exit Criteria:** A PPTX/PDF with visual hierarchy no longer loses image evidence silently; visual context reaches extraction prompts with provenance; configured OCR/vision output can support `parent_uri` and object-property evidence; visual-heavy orphan risk is surfaced before curation.

---

### Stream 14: Code Quality & Modularity (tech debt)

**Source:** May 2026 code-quality audit (duplicate code, oversized files, orphaned code, hardwiring, security, doc drift).
**Priority:** P2 — no user-facing behavior change; reduces maintenance risk and unblocks the `modularity-and-structure` file-size cap.

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| CQ.1 | Consolidate score/confidence color thresholds | Frontend | **DONE** | `frontend/src/lib/thresholds.ts` is now the single source for confidence (0.7/0.5) and health (70/50) bands + null-safe text/bg helpers. `SummaryCards`/`MetricCards` use the helpers; `GraphCanvas`, `OntologyCard`, `workspace/page.tsx` share the constants (kept their own output formats). `thresholds.test.ts` added. The confidence *lens* palette stays separate by design. |
| CQ.2 | Wire orphaned `belief_revision_metrics` | Backend | **DONE** | Was a documented-but-unimplemented feature (PRD §7.7a). Added `revisions_dashboard()` aggregator + `GET /api/v1/quality/{ontology_id}/revisions`, tests, and the api-reference row. **Follow-up:** frontend dashboard tile to consume it (FR-13.26). |
| CQ.3 | Split `backend/app/api/ontology.py` (3485 lines) | Backend | **DONE** (`2ff0c26`, slice-1 scaffold `022588c`) | `app/api/ontology/` is now a package whose `__init__.py` builds the prefixed `router` and `include_router`s seven cohesive sub-routers — `library`, `domain`, `entities_read`, `mutations`, `imports_io`, `imports`, `schema_temporal` (each < 1500 lines). Patch-relevant shared deps (`get_db`, `run_aql`, `paginate`, `import_from_file`, `ontology_repo`/`registry_repo`/`constraints_repo`) live in `_shared.py` and are reached via attribute access (`_shared.get_db(...)`), so one `patch("app.api.ontology._shared.<name>")` rebinds them for every sub-router; `asyncio`/`export_svc`/`schema_diff_svc` are re-exported from `__init__` so existing attribute-patch test targets resolve to the same singleton modules. Handlers/state still importable from the package root via re-exports. `include_router` order preserves the original route precedence, guarded by `tests/unit/test_ontology_router_assembly.py` (pins route count + asserts no dynamic route shadows a more specific literal one). ruff + mypy clean; full unit suite green (2225). |
| CQ.4 | Remaining duplicate-code consolidations | Both | PARTIAL | (a) **DONE** — `documentKey()` promoted to `frontend/src/lib/arangoId.ts` (re-exported from `graphCanvasEdges.ts` for the canvas imports); inline `_from/_to.split("/")` duplications migrated in `GraphCanvas`, `ClassHierarchy`, `workspace/page.tsx`; `arangoId.test.ts` added. Legacy routes (`/library`, `/ontology/edit`) and `AssetExplorer`'s label-humanization line left as-is. (b) property/edge collection allowlists (ADR-006 triple) → one shared constant; (c) **DONE** — MCP `export_ontology` tool now delegates to `app.services.export.export_ontology` (single source of truth: registry-aware URIs + `owl:imports` + `owl:Restriction`); removed ~120 lines of thinner duplicate graph-building + its 4 helpers; MCP export tests rewritten to assert delegation. (d) **DONE** — `workspace/page.tsx` `QualityReportSection` now uses the shared `buildQualityReportMetrics()` (previously imported-but-unused) instead of an inline copy; this also fixes a latent bug where completeness/connectivity (already 0–100) were multiplied by 100 again. Radar / `SCHEMA_METRIC_LABELS` remain single-use in `QualityReportOverlay` (not duplicated). |
| CQ.5 | Remaining orphaned code | Frontend | DEFERRED to feature PR | Investigation (2026-05): `EditableLabel` and `ReparentSelect` are **ready-to-wire missing features**, not obsolete — neither class rename nor class reparent is wired through any sanctioned context-menu/DnD path today, and both backend endpoints already exist (`PUT /{ontology_id}/classes/{class_key}` for rename, `POST /{ontology_id}/edges` for subclass_of reparent). Per wiring-over-deletion they must be **wired, not deleted**. Recommended path (its own scoped PR, like CQ.3): inline class rename via `EditableLabel` in the class detail-panel title (double-click is the sanctioned "inline edit where safe" gesture, rule 0/preferred-patterns); class reparent via DnD class→class as the **primary** path (rule 5) with `ReparentSelect` offered as a **secondary** duplicate affordance (rule 2) — both routed through the shared optimistic-curation helper (rule 17) and shipping the full rule-22 checklist (selection handler, detail-panel control, context-menu entry, legend if needed, optimistic update, tests). `useApiCall` is a generic fetch hook with **zero adoption and no test** (not a missing feature, so not provably obsolete → not deleted); fold adoption into the same PR (the rename/reparent handlers are natural first consumers) or a later cleanup. No code change in this CQ batch: doing it right is a feature, not a consolidation. |

**Exit Criteria:** No source file over the `modularity-and-structure` caps; no duplicated threshold/allowlist/key-extraction logic; every orphan either wired or removed with rationale.

---

### Stream 15: Self-Optimizing Ontology (in-pipeline gates, deterministic repair, A-box)

**Source:** `docs/research/Ontologies_3_6 .pdf` (UPM "Self-Optimizing Ontology Project" 3-generation pipeline retrospective: Baseline → T-box Quality Loop → Double Loop with A-box) + its empirical companion `docs/research/Ontologies_27_05.pdf` (measured "without loop vs with loop" results on the demo dataset). Analyzed against our pipeline June 2026.
**Priority:** SO.1/SO.2 are P1 (monetize detectors we already shipped); SO.3 P2; SO.4 is a PRD-level scope decision.

**Framing — where we already are vs. the deck.** On *grounding* we are ahead of the deck: our LLM-as-judge faithfulness rater (`extraction/judges/faithfulness.py`) + semantic validator + ER + belief revision have no analog there. The deck's two load-bearing ideas we *don't* yet have are: (1) **gate-then-repair-before-materialize** — our `quality_judge` only *annotates* scores and flows unconditionally to `filter` (`extraction/pipeline.py`), so a disconnected/orphan-heavy schema still materializes; (2) a **T-box/A-box split** — we extract a T-box only (`prompts/tier1_standard.py`); there is no named-individual (A-box) layer. Crucially, our deterministic detectors already exist but run *post-materialization, on demand*: `services/edge_repair.py` (orphan object-property range inference) and `services/ontology_rule_engine.py` (subclass cycles, disjointness, cardinality conflicts, redundant classes, orphan ranges).

**Empirical baseline (from `Ontologies_27_05.pdf`).** UPM measured the same demo dataset with and without the quality loop. These are the targets SO.2's metrics should reproduce, and the benchmark SO.1/SO.3 are judged against:

| Metric | Without loop | With loop | Note |
|---|---|---|---|
| Faithfulness | 1.0 | **0.8** | ⚠️ *dropped* — denser graph came partly from less-grounded links |
| Completeness | 50% | 100% | |
| Semantic Validity | 0.80 | 0.80 | unchanged |
| Connectivity | 28% | 100% | the disconnected-schema failure mode SO.1 attacks |
| Structural Integrity | 0.11 | 0.7 | |
| Classes / Properties | 18 / 39 | 23 / 63 | (the 63 matches `edge_repair.py`'s "23/63 orphans" demo note — same dataset) |

Multi-hop query traversability was the qualitative test ("Which academic center manages the degree program for this subject?" resolving Subject→Degree→Academic Center→concrete individual). **Guardrail takeaway:** the loop's only regression was *faithfulness* (1.0→0.8). SO.1's repairs are deterministic + evidence-anchored (no invention) so they should not move it, but this must be **measured, not assumed**, and it is the hard cap on SO.3 (the LLM surgeon), where ungrounded expansion would realistically creep in.

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| SO.1 | In-pipeline structural gate + deterministic repair | Backend | **DONE** (flag **ON** as of SO.2) | Flag-gated `extraction/agents/structural_gate.py` node between `belief_revision` and `filter`. Computes a pre-materialization health report on the in-memory merged class list (dangling relationship targets, zero-degree "island" classes, classes without parent, classes without properties) and applies two of the deck's 100%-reliable deterministic rules: **URI normalization** (rewrite a relationship target that matches a known class only by fragment/normalized key to its canonical URI) and **link recovery** (re-point a relationship whose target resolves to no class at the class named in the relationship's own evidence text — the proven `edge_repair` substring heuristic, applied in-memory). Gated behind `settings.structural_gate_enabled` (**default ON**; transparent pass-through when disabled — config-only rollback). Before/after counts + repair audit land in `step_logs[].metadata`. Unit-tested in `tests/unit/test_structural_gate.py`. **Faithfulness guardrail (done):** `test_repairs_never_touch_faithfulness_inputs` proves by construction that repairs only rewrite relationship *targets* and never touch class uri/label/description/evidence/attributes (the inputs the faithfulness judge reads), so the gate cannot reproduce UPM's 1.0→0.8 faithfulness slip — which is what justified flipping the default ON. |
| SO.2 | Post-write graph-health metrics ("island" detection + ratios) | Backend + Frontend | **MOSTLY DONE** | `services/quality_metrics.py` now surfaces **`structural_integrity`** (0–1, matching the UPM 0.11→0.7 baseline; extracted from the health-score formula — pure arithmetic, no extra DB round-trip) and **`island_count`/`island_classes`** — true zero-degree "connects to nothing" classes via `_island_classes`, strictly stronger than `orphan_count` (a subclass-orphan that still participates in an object property is *not* an island). **Connectivity** (28%→100%) and **Completeness** (50%→100%) already existed. Frontend surfaces both: `MetricCards` ("Isolated Classes" card + backend-sourced Structural Integrity) and the shared `buildQualityReportMetrics` rows. Unit-tested (`test_quality_metrics.py` islands + integrity; `qualityReportDisplay.test.ts`). **Deferred:** the **materialized-vs-declared ratio** — needs the gate's declared/dropped relationship counts persisted to `extraction_runs.stats` (the data lives in `step_logs[].metadata` today but isn't a clean per-ontology stat); building it half-wired would be misleading, so it's split out. Also deferred: pinning the UPM baselines as a live demo-dataset regression test (needs a seeded fixture ontology). |
| SO.3 | LLM "Surgeon" bounded-patch repair loop | Backend | PLANNED | Where deterministic rules (SO.1) can't resolve a violation, feed the `ontology_rule_engine` violation report to an LLM that emits a **bounded patch over only the damaged subgraph** (deck's `optimizer_surgeon`), iterating ~3× until the gate passes. Natural host: the existing `services/revision_agent.py` / belief-revision machinery. Needs a circuit breaker (cf. `belief_revision_max_revisions`) and a hard attempt cap to avoid spend blow-ups (the deck flags "double generative dependence" cost). |
| SO.4 | A-box (named-individual) extraction — second loop | Backend + PRD | NEEDS DECISION | The deck's headline: after a frozen T-box, a Loop 2 extracts *instances* with the actual T-box in the prompt, generates cross-relations from a **closed catalog of entity names** (anti-hallucination), applies deterministic A-box repairs (URI normalization, semantic re-typing, chunk co-occurrence forced edges, noise filter), then re-extracts on health-gate failure. This changes what AOE *is* (ontology + populated knowledge graph). **Decide in PRD before building** — scope, storage (A-box collections + temporal model), UI (instance lens), and a "rerun Phase C only" affordance. |

**Exit Criteria (SO.1–SO.2):** structural gate runs behind a flag with full unit coverage and a no-op-when-disabled guarantee (**met**); **Faithfulness-no-regression guardrail in place** (**met** — `test_repairs_never_touch_faithfulness_inputs` proves the gate never touches the faithfulness judge's inputs, which is what let us flip the default ON); health metrics Connectivity / Structural Integrity / Completeness / islands computed and surfaced (**met** — backend + frontend + tests). **Remaining for full SO.2:** (a) the materialized-vs-declared ratio (deferred — needs declared/dropped counts persisted to `extraction_runs.stats`), and (b) a live demo-dataset regression test asserting the UPM with-loop baselines (needs a seeded fixture ontology). SO.3/SO.4 gated on their own design notes; SO.3's hard acceptance gate is "no Faithfulness regression beyond a small, explicit tolerance."

---

### Stream 16: Domain Detection & Multi-Ontology Routing
**PRD:** §6.2 FR-2.15; §13 Q13 (resolved → A-now / C-next)
**Priority:** P2 — unlocks clean ontologies from mixed-domain source docs (decks, filings)
**Dependencies:** Stream 1 (imports / `/effective`) ✓ for Phase 2; chunk-level topic units (Stream 17 CH.3) sharpen segmentation but are not required for Phase 1
**Team Size:** 1 developer

**Framing.** Today the pipeline assumes **one output ontology per run**: all chunks from `doc_ids` are concatenated into one `document_chunks` list and materialized to one `target_ontology_id` (or one auto-registered ontology). "Domain" currently means *reference* ontologies serialized into the Tier-2 prompt (`serialize_multi_domain_context`), **not** topic detection in the source document. FR-2.15 closes that gap. Q13 is resolved to **A-now / C-next**: ship the detection signal + single-ontology tagging first (no run-model change), add curator-invoked split-into-umbrella second (reuses Stream 1).

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| DD.1 | Domain-segmentation step | Backend | **DONE (Phase 1)** | Pre-extraction node `domain_segmenter_node` (`app/extraction/agents/domain_segmenter.py`), wired between `strategy_selector` and `extractor`, clusters `document_chunks` into topical domains via an LLM classification pass (`domain_segmentation` prompt) and emits `domain_segments: list[{domain, chunk_ids, confidence}]` into pipeline state. Gated behind `settings.domain_detection_enabled` (default OFF, mirroring belief-revision / structural-gate); transparent single-pass-through no-op when disabled. Evenly samples chunks above `domain_detection_max_chunks` and expands the sampled domains back over the full document. Any LLM/parse failure degrades to no segments (never fails the run). Shared LLM factory extracted to `app/extraction/llm.py`. Embedding-cluster corroboration remains an optional follow-up (LLM-only is sufficient for Phase 1). |
| DD.2 | `detected_domains` + per-class `domain_tag` | Backend | **DONE** | `ExtractedClass.domain_tag` added (default `None`, carried through consistency merge by majority vote). `app/services/domain_detection.py` derives run-level `detected_domains` (persisted to `extraction_runs.stats.detected_domains`) and stamps each class's `domain_tag` by majority vote of its evidence `source_chunk_ids` → domain map (fallback to dominant domain), before store + materialization. Persisted onto the stored class document conditionally (absent when detection is off → byte-identical). |
| DD.3 | Multi-domain warning (non-blocking, pre-commit) | Backend | **DONE** | `build_multi_domain_warning` appends a `type: "multi_domain"` entry to `stats.warnings[]` (same surface as IMG.7 `visual_heavy_orphans`) with `detected_domains`, per-domain chunk counts, and per-domain class counts when `len(detected_domains) > 1`. **Phase 1 (Option A) complete** — mixed extraction lands in the single target ontology, cross-domain edges preserved, each class tagged. |
| DD.4 | "Split by domain" umbrella action (Option C) | Backend + Frontend | PLANNED | Curator-invoked action on a multi-domain run: create N per-domain staging ontologies (one per `detected_domains` entry, routing each domain's classes via `domain_tag`) + an umbrella ontology that `owl:imports` them, wiring `imports` edges via the shipped `sync_owl_imports_edges`. Cross-domain edges resolve through the `/effective` graph. A toggle drops the umbrella (Option B). Surfaced from the run/warning context menu per `ui-architecture.mdc` (no new route; overlay + undo-toast). Never auto-applied. |
| DD.5 | Tests | Backend + Frontend | **DONE (Phase 1)** | `test_domain_detection.py` (helpers), `test_domain_segmenter.py` (node: disabled pass-through, no-chunks, LLM success, graceful failure, parse coverage, sampling/expansion), plus `test_extraction_service.py::TestDomainDetectionStats` (detected_domains + multi_domain warning + in-place tagging) and `_materialize_to_graph` domain_tag persist/omit tests, and updated pipeline-topology / event tests. Phase-2 split-action tests land with DD.4. |

**Exit Criteria:** A mixed-domain document (e.g. a multi-topic deck) produces a non-blocking `multi_domain` warning with `detected_domains` and per-class `domain_tag` **before** commit, without changing single-domain behavior (Phase 1); a curator can then opt into "Split by domain" to get clean per-domain ontologies under an umbrella that composes via the existing imports / `/effective` machinery (Phase 2). Splitting is never automatic.

---

### Stream 17: Structure-Aware Chunking
**PRD:** §6.1 FR-1.2, FR-1.16, FR-1.17
**Priority:** P2 — quality lever for decks / mixed-structure documents; prerequisite sharpener for Stream 16 segmentation
**Dependencies:** none hard; pairs with Stream 13 (image-aware) and Stream 16 (topic units feed segmentation)
**Team Size:** 1 developer

**Framing — what exists vs. the gap.** Chunking is **512 tokens, no overlap, section-aware** (`chunk_document` in `services/ingestion.py`, tiktoken `cl100k_base`), and **happens at ingestion time, before strategy selection** — so the component that knows "this is a deck" (`strategy.py`) cannot influence chunk shape. PPTX is parsed **one `Section` per slide** (`parse_pptx`), but `chunk_document` can still split a large slide across chunks *and* the extractor batches 3–8 consecutive chunks by raw index (`_batch_chunks`), so **multiple slides routinely land in one LLM call** with no 1-slide-1-chunk guarantee. Chunk size/overlap are **hardcoded constants** (not in `Settings`). (**`doc_format` persistence was the one stale gap here — closed by CH.1 in `eed591a`**, so the classifier now detects text-only decks in production; the chunk-shape items CH.2–CH.5 remain.)

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| CH.1 | Persist `doc_format` + slide/page index on chunks | Backend | **DONE** (`eed591a`) | `doc_format` now flows through the `Chunk` dataclass and `_build_chunk_dicts()` into stored `chunks` (persisted only when non-empty), with a legacy fallback in `_load_document_chunks` that backfills `doc_format` from the parent document's MIME type for pre-existing chunks. Closes the `strategy._is_visual_heavy()` production gap: a majority of presentation-formatted chunks now flips a text-only deck to `visual_heavy_presentation`/`tier1_visual_aware` even without visual assets. Covered by new tests in `test_ingestion.py`, `test_tasks.py`, `test_strategy_selector.py`, and `test_extraction_service.py`. |
| CH.2 | Slide-boundary-preserving chunker | Backend | PLANNED | A deck-aware chunk mode (selected by category — CH.4): never merge two slides into one chunk; never split a slide mid-bullet across chunks (split only when a single slide exceeds `max_tokens`, and record the split); emit speaker notes as a distinct chunk linked to their slide. Configurable target size + optional overlap via `Settings`. |
| CH.3 | Slide-grouping for spanning topics → topic units | Backend | PLANNED | Detect continuation across consecutive slides (repeated or `(cont'd)` titles, running section headers) and group them into a **topic unit**; the extractor batches by topic unit, not raw chunk index (`_batch_chunks` change). These units double as a finer-grained input for Stream 16 segmentation. |
| CH.4 | Categorize-then-chunk ordering + config knobs | Backend | PLANNED | Promote document categorization (deck / tabular / narrative / technical) to run **before** chunking so category selects the chunk strategy (today `strategy.py` runs post-chunk and only sets prompt/batch/passes). Move chunk size / overlap / per-format toggles into `Settings` (currently `_DEFAULT_MAX_TOKENS=512` is a module constant). Keep the default path byte-stable for non-deck documents. |
| CH.5 | Tests | Backend | PLANNED | Deck fixture: 1 slide ≥ 1 chunk, never 2 slides in 1 chunk; oversized slide splits and is recorded; notes are a distinct linked chunk; spanning-topic slides group into one unit and batch together; `doc_format`/slide index persisted; non-deck documents chunk byte-identically to today; config knobs honored. |

**Exit Criteria:** A multi-topic deck chunks with slide boundaries preserved, speaker notes separated, and topics that span slides grouped into a single extraction unit; `doc_format` + slide index are persisted so strategy selection detects decks in production; chunk size/overlap are `Settings`-configurable; non-deck documents are unchanged.

---

### Stream 18: Relational Schema → Ontology  (**COMPLETE — v1.1.0**)
**PRD:** §6.9 (extends schema extraction beyond ArangoDB)
**Priority:** P3 — value-add for RDBMS users
**Dependencies:** ~~BLOCKED on extraction of a standalone `relational-schema-analyzer` library from the `r2g` project.~~ **Unblocked** — the library was extracted and is now an optional, import-guarded dependency.
**Team Size:** 1 developer

**Framing.** `r2g` (local `~/code/r2g`) does relational→graph migration for ArangoDB but does **not** natively emit OWL/ontologies; the schema-introspection logic is the reusable piece, extracted into a clean `relational-schema-analyzer` library consumed the same way Thread A consumes `arango-schema-analyzer`. Stream 18 mirrors Stream 5: introspect the RDBMS schema (tables → classes, FKs → object properties with domain/range, columns → datatype properties, constraints → SHACL) → emit TTL → `import_from_file`. Shipped end-to-end and verified against a real DuckDB database.

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| RS.1 | Adopt `relational-schema-analyzer` | Backend | **DONE** | Optional, import-guarded dependency mirroring `arango-schema-analyzer`. `backend/app/services/relational_schema_extraction.py` (`_introspect` helper, `create_connector`, connect-config host/db/user/password/dialect). |
| RS.2 | Relational → OWL direct mapping | Backend | **DONE** | Tables → `owl:Class`; FKs → `owl:ObjectProperty` (`rdfs:domain`/`rdfs:range`); columns → `owl:DatatypeProperty` (SQL type → XSD); NOT NULL / UNIQUE / CHECK → SHACL (reuses Stream 3 importer). `list_relational_tables` read-only preview + `extract_relational_schema`. API sub-router `app/api/ontology/schema_relational.py` (`POST .../schema/relational/tables` + `.../extract`); MCP tools `preview_relational_schema` + `extract_relational_schema`. |
| RS.3 | LLM enrichment + domain description | Backend | DEFERRED → Stream 5 PR 4 | Same additive-enrichment pattern as Stream 5 PR 4 (never replaces the direct mapping). Tracked under the shared Schema-Analyzer LLM enrichment task so ArangoDB and relational enrichment ship together. |
| RS.4 | "Extract from relational DB…" overlay + tests | Backend + Frontend | **DONE** | `RelationalExtractionOverlay.tsx` (connect → preview → result), wired via `contextMenus/canvas.ts` "Extract from Relational DB…" + `page.tsx`. Unit tests: service, API (`test_schema_relational_api.py`), MCP (`test_mcp.py`), overlay + canvas menu. Real DuckDB e2e verified. |

**Exit Criteria (when unblocked):** A relational database can be reverse-engineered into an imported ontology with FK-derived object properties, column-derived datatype properties, constraint-derived SHACL, per-class provenance, and optional LLM-generated domain description — surfaced from a workspace overlay, mirroring the ArangoDB path.

---

### Stream 19: LLM-Assisted Release Governance (Release Readiness Review + autonomy policy)
**PRD:** §6.8a FR-8a.13–8a.14
**Priority:** P2 — governance + autonomy story; composes gates we already shipped
**Dependencies:** Stream 3 (rule engine / constraints) ✓; Stream 4 (quality metrics + gold-standard recall) ✓; Stream 15 (structural gate ✓; SO.3 surgeon for auto-fix — PLANNED); release process §6.8a ✓
**Team Size:** 1 developer

**Framing.** The release boundary (`ontology_releases`, UC-12) is where governance belongs, and AOE already computes nearly every signal a reviewer needs — they're just wired for extraction-time (`quality_judge`, `semantic_validator`, `structural_gate`) and on-demand use (`ontology_rule_engine`, `quality_metrics`, gold-standard recall). Stream 19 composes them into a single **Release Readiness Review** at RC creation, adds an LLM critic that turns raw signals into ranked findings, and gates publication by a **configurable autonomy policy** — turning "human-in-the-loop" into "human-on-the-loop." Faithfulness stays a non-waivable floor and every release is revertible, so autonomy is never a one-way door. Addresses the positioning concern that mandatory per-item human curation reads as "doesn't scale."

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| RR.1 | Readiness aggregator (no LLM) | Backend | PLANNED | At RC creation, evaluate rule-engine violations + `quality_metrics` + gold-standard recall + breaking-change report **at the RC snapshot timestamp** and assemble a structured readiness report (deterministic findings with severity). Stored on the release record. |
| RR.2 | LLM critic pass | Backend | PLANNED | Feed the ontology + RR.1 signals to an LLM critic that emits findings tagged `blocking`/`warning`/`info`, each with evidence and (where deterministically repairable) a suggested fix linked to the structural gate / SO.3 surgeon. Bounded + cost-capped (cf. belief-revision circuit breaker). |
| RR.3 | Release autonomy policy | Backend | PLANNED | Per-org / per-ontology policy: `advisory` (default) / `gated_autonomous` / `supervised_autonomous` + thresholds (faithfulness floor, max breaking severity, rule-engine criticals = 0). `GET`/`PUT /ontology/{id}/release-policy`, role-gated + audit-logged. Faithfulness floor is non-waivable. |
| RR.4 | Gated publish + escalation | Backend | PLANNED | Wire the policy into the publish path: `gated_autonomous` auto-publishes iff zero `blocking` + thresholds clear, else routes to a human; `supervised_autonomous` auto-publishes + notifies. All auto-publishes recorded as release events and revertible via FR-8a.8. |
| RR.5 | RC review UI | Frontend | PLANNED | Surface the readiness report in the RC review surface (workspace overlay per `ui-architecture.mdc`): findings grouped by severity, evidence, one-click "apply suggested fix" where the structural gate / SO.3 can, and the active autonomy level. |
| RR.6 | Tests | Backend + Frontend | PLANNED | Aggregator math pins; critic findings schema; policy thresholds (gated auto-publish vs escalate vs supervised); faithfulness floor cannot be waived; an auto-published release is revertible; advisory mode never auto-publishes. |

**Exit Criteria:** Creating a release candidate produces a Release Readiness Review (deterministic signals + LLM-critic findings) visible in the RC review UI; an org can set an autonomy policy so clean candidates auto-publish while anything with a `blocking` finding or a sub-threshold metric escalates to a human; faithfulness is a non-waivable floor and every auto-publish is revertible.

---

### Stream 20: Multi-Source Ontology Alignment (Contextual Data Fabric M3 / AOE RE-2) — NOT BUILT
**PRD:** Contextual Data Fabric **M3** (Ontology Alignment) / AOE repo-enhancement **RE-2 (P1)**. See `contextual-data-fabric/docs/architecture/module-03-ontology-alignment/specification.md` (FR-1) and `.../_repo-enhancements/ontology-extractor-structured.md` (RE-2).
**Priority:** P1 in the CDF program; **net-new in AOE**.
**Status:** **NOT BUILT.** State this plainly — alignment is a *build*, not a *confirm*.
**Dependencies:** Stream 1 (imports / effective-graph / conflict detection) ✓; Stream 2 (ER scorer + pairwise merge) ✓; Stream 18 (relational schema → ontology) ✓ — supplies the structured source ontologies to align.

**Framing.** AOE today *produces* and *curates* per-source ontologies and *composes* them **by reference** (`owl:imports` → effective-graph union) with conflict **flagging**. It has **no** primitive that takes N independently-built source ontologies and produces/refines a single reconciled **master** — the RE-2 primitive that CDF's M3 wraps (verbatim: *"given N source ontologies, compute diffs/deltas and produce/refine a master … Minimal for P1"*). The P1 bar is deliberately low: the CDF PRD (M3 FR-1 / task B2) accepts **hand-construction of a small, use-case-scoped master** with a human **"confirm ~2%"** step. So P1 is a thin orchestration + *resolution* layer over primitives AOE already has — not a greenfield ontology-matcher.

**Clarification — the structured/unstructured "split question" is answerable YES.** The CDF PRD gates Phase 1 on confirming AOE has a structured→ontology path. It does: **Stream 18** (relational SQL → OWL/SHACL) + **Stream 5** (ArangoDB schema → OWL/SHACL). AOE *owns* the SQL→OWL/SHACL mapping; `relational-schema-analyzer` is a **read-only `PhysicalSchema` introspector** (per its own 2026-06 "Boundary correction" — AOE does *not* consume its OWL). So AOE is **not** unstructured-only; RE-2 (alignment) is the genuinely missing piece, not the structured path.

| # | Task | Type | Status | Description |
|---|------|------|--------|-------------|
| AL.1 | Correspondence discovery API (N sources) | Backend | NOT BUILT | Endpoint taking N ontology ids → candidate correspondence set (equivalence / subsumption) with scores + evidence. Generalize the cross-tier scorer (`er.py::get_cross_tier_candidates`, jaro-winkler label + token-overlap) from the 2-way local↔domain restriction to N arbitrary sources. |
| AL.2 | Conflict **resolution** (not just flagging) | Backend | NOT BUILT | Extend `ontology_effective._detect_conflicts` (`duplicate_uri` / `duplicate_label` / `subclass_cycle_via_import`) from flag-only to accept/reject/merge **decisions** that write a reconciled result rather than a read-time union. |
| AL.3 | Master materialization + provenance | Backend | NOT BUILT | Create the master as a registry entry, carrying `source_ontology_id` provenance + `owl:equivalentClass` links (the data model already admits cross-ontology `equivalent_class` / `merge_candidate` edges), temporal-versioned. Supports the P1 "confirm ~2%" human step and hand-assisted small masters. |
| AL.4 | Iterative refinement (RE-3) | Backend | NOT BUILT | Re-run alignment when a source changes; dependency-directed cascade. Overlaps belief-management (RE-4). P2. |
| AL.5 | Alignment review UI | Frontend | NOT BUILT | Workspace overlay: candidate correspondences, accept/reject, conflict resolution, master preview. |
| AL.6 | Tests | Both | NOT BUILT | Correspondence scoring pins; resolution writes a correct master; provenance + equivalence links; confirm-2% flow. |

**Building blocks that already exist (what a build stands on):**

| Primitive | Where | Gap vs. alignment |
|-----------|-------|-------------------|
| Effective-graph union + conflict **flagging** | `backend/app/services/ontology_effective.py` | Read-time union for canvas/prompt; flags conflicts "for the importer to disambiguate" — does not resolve or persist a master. |
| Cross-tier overlap candidate finder | `er.py::get_cross_tier_candidates`, `POST /api/v1/er/cross-tier` | 2-ontology (local↔domain) only, candidate-listing only, marked "Partial". Closest thing to cross-ontology matching. |
| Pairwise class merge (redirects cross-ontology edges) | `er.py::execute_merge` | Class-level, not ontology-level; no N-source orchestration. |
| Cross-ontology `equivalent_class` / `merge_candidate` edges | data model (`DELETION_AND_REFERENTIAL_INTEGRITY.md`) | Links are modeled but nothing composes them into a master. |

**Exit Criteria:** Given ≥2 source ontologies (e.g. one relational-derived via Stream 18 + one unstructured-derived), AOE produces a candidate correspondence set, lets a curator accept/reject/merge, and materializes a reconciled master with source provenance + `owl:equivalentClass` links. P1 is met by a small, use-case-scoped master with a hand-assisted "confirm ~2%" step.

---

## Recommended Execution Order (refreshed v1.1.0)

Streams 1, 2, 3, 5, 6, 7, 11, 13, 18 and the Sigma.js core of Stream 8 are
**shipped**; the original Sprint A–G plan below is kept only as a historical
record. v1.0.0 (full PRD §6 scope) and v1.1.0 (chunking foundation, ontology
API split, relational schema extraction) are released. What remains is the
post-v1.1 enhancement backlog, sequenced by value × readiness × dependency.

```
DONE:  Stream 1 (Imports + Composition)   Stream 2 (Entity Resolution, hand-rolled)
       Stream 3 (Constraints — I.1–I.9)   Stream 4 (Quality Dashboard: Q.1–Q.5)
       Stream 5 (Schema Extraction)       Stream 6 (Testing & CI, 5-tier)
       Stream 7 (Production Ops)          Stream 11 (Belief Revision)
       Stream 12 (perf: T1–T5, T7–T10)    Stream 13 (Image-Aware Extraction)
       Stream 8 core (Sigma.js workspace canvas: V.1 / V.2 / V.5)
       Stream 14 CQ.1–CQ.3 (thresholds, belief-metrics wiring, ontology.py split)
       Stream 17 CH.1 (doc_format + slide/page index on chunks)
       Stream 18 (Relational Schema → Ontology — RS.1/RS.2/RS.4)   → v1.1.0

RELEASED:
  - v1.0.0 — full PRD §6 functional scope
  - v1.1.0 — CH.1 chunking foundation, CQ.3 ontology API split, Stream 18 relational

POST-v1.1 (recommended order):
  Phase 1 — Extraction depth:
    1. Stream 16 Domain Detection Phase 1 (DD.1–DD.3: segment, tag, non-blocking warning)
    2. Stream 17 CH.2–CH.5 (slide-boundary chunker, topic units — feed DD segmentation)
    3. Stream 16 DD.4–DD.5 ("split by domain" umbrella action + tests)
  Phase 2 — Polish extraction outputs:
    4. Stream 5 PR 4 / RS.3 (Schema-Analyzer LLM enrichment: domain description +
       rdfs:comment merge — applies to both ArangoDB and relational output)
    5. Stream 14 CQ.5 (wire EditableLabel rename + ReparentSelect/DnD reparent)
  Phase 3 — Trust & autonomy:
    6. Stream 19 (Release Governance: RR.1 aggregator → RR.2 critic → RR.3/4 policy+gate → RR.5 UI)
  Phase 4 — Visualization & cleanup:
    7. Stream 8 editor panels (V.3/V.4/V.6/V.7/V.8/V.9) + W.8 minimap
    8. Stream 14 CQ.4(b) collection-allowlist consolidation
    9. Legacy-route removal (/curation, /ontology/edit, /entity-resolution — V.10/V.11)
  Cross-program (Contextual Data Fabric), gated on the CDF roadmap:
    - Stream 20 Multi-Source Ontology Alignment (CDF M3 / RE-2, P1) — NOT BUILT.
      Net-new merge-N-sources-into-a-master primitive; builds on Stream 1/2/18.
      The structured→ontology gate the CDF PRD worries about is already met
      (Stream 18 + Stream 5) — alignment is the actually-missing piece.
  Deferred until demand justifies:
    - Stream 9 (Unified Storage spike)
    - Stream 4 RAG benchmark comparison UI (optional, needs a spec first)
    - Stream 12 T6 (WTW-switch per-stage profile capture)
```

<details><summary>Historical Sprint A–G plan (superseded — all sprints shipped)</summary>

```
Sprint A (now): Stream 4 (Quality Dashboard finishing: Q.2/Q.3/Q.4/Q.5) + Stream 12 P0/P1 (T6 WTW switch profile, T7 cost cache, T8 runs join)
Sprint B:       Stream 1 Phase 1b (Imports integration: cascade, dependency graph, base-ontology selector) + Stream 2 (ER) — in parallel
Sprint C:       Stream 1 Phase 2 (Composition: effective graph, conflict detection, drag-and-drop, import-aware extraction) + Stream 3 (Constraints) — in parallel
Sprint D:       Stream 5 (Schema Extraction) + remaining Stream 12 follow-ups from telemetry — in parallel
Sprint E:       Stream 6 (Testing & CI)
Sprint F:       Stream 7 (Production Polish)
Sprint G:       Stream 13 (Image-Aware Extraction) before additional PPTX-heavy ontology work
                → v1.0.0 Release
Post-v1.0:      Stream 8 (Sigma.js Migration) + Stream 9 (Unified Storage spike)
```

</details>

**v0.3.0 baseline** unblocked BYOC packaging; **v0.4.0-dev** closes Stream 11 Phase 3 (Belief Revision UX, consolidation, MCP tools, dashboard tile, docs). Stream 4 finishing + Stream 12 perf follow-ups are now the next user-visible priorities.

### Parallelization Opportunities

| Parallel Track A | Parallel Track B | Notes |
|-----------------|-----------------|-------|
| Stream 1 Phase 1 (Imports) — backend heavy | Stream 2 (ER) — backend heavy | No dependencies between them |
| Stream 1 Phase 2 (Composition) — backend | Stream 3 (Constraints) — backend | Composition depends on Phase 1 but not on Constraints |
| Stream 4 (Quality Dashboard) — frontend | Stream 5 Phase 1 (Schema Core) — backend | No overlap |
| Stream 5 Phase 2 (Named Graph) — backend | Stream 4 (Quality Dashboard) — frontend | Schema depends on Stream 1 for imports integration |
| Stream 11 Phase 1 (IBR Substrate) — backend | Stream 1 Phase 1 + Stream 2 — backend | IBR substrate is self-contained; no dependency on other streams |
| Stream 11 Phase 2 (Per-doc revision) — backend | Stream 1 Phase 2 (Composition) + Stream 3 (Constraints) — backend | IBR Phase 2 reads `ontology_constraints` if present (Stream 3) but does not require it; both can be developed in parallel and integrate via the rule engine (IBR.4) |
| Stream 11 Phase 3 (UX + Consolidation) — backend + frontend | Stream 4 (Quality Dashboard) — frontend | Stream 11's revision tiles (IBR.19) reuse Stream 4's tile components; coordinate on shared components |

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
| Stream 11: Runaway LLM revision cost | Per-doc cost spike | Phase 2 mechanical verdicts handle the easy 80% (REINFORCED + REFINED + GAP-FILLING + REDUNDANT); Phase 3 only fires on CONTRADICTED + UNCERTAIN. Circuit breaker (IBR.18) halts the LLM agent above 50 revisions/min (configurable). Per-org token budget enforced. |
| Stream 11: Bad auto-applied revision damages curated content | User trust loss | Published-item protection (IBR.18) blocks structural auto-revisions on `status: approved` classes. Every revision is reversible via temporal revert (existing infrastructure). Every revision carries `revision_meta` with the agent's justification for spot-check audit. |
| Stream 11: Curator overload from large Revisions Inbox | UX friction | Default sort by impact (revisions touching the most-referenced beliefs first) so high-leverage revisions get attention. Configurable confidence threshold for auto-apply. Stream 11 Phase 3 includes telemetry to detect inbox growth and alert before it becomes unmanageable. |
| Stream 11: Confidence decay drifts users' mental model | Confidence scores look "wrong" | UI separates `extraction_confidence` (frozen at extraction time) from `current_confidence` (with decay). Tooltip explains the difference. Decay is configurable per-ontology and disabled by default until explicitly enabled. |
| Stream 11: Background consolidation job is new infrastructure | Operational complexity | Admin-triggered first (IBR.17 ships without a scheduler); scheduled second (post-v1.0). Cursor-based resumption from day one means failures don't lose progress. Dry-run mode means impact can be previewed before applying. |

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
