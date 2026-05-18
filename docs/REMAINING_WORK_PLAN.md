# AOE — Remaining Work Plan

**Document Version:** 3.2
**Date:** May 13, 2026
**Baseline:** v0.3.0 tag (commit `4738d29`) — supersedes v0.2.0 (Stream 11 Phase 1+2 complete) and v0.1.0
**PRD Reference:** `PRD.md` — Arango-OntoExtract Product Requirements Document

---

## Executive Summary

The AOE (Arango-OntoExtract) system has a working end-to-end extraction pipeline, ontology editor, pipeline monitor, quality metrics, multi-document support, **iterative belief-revision substrate**, and **substantial workspace-load performance work**. This document details the remaining work required to achieve full PRD compliance and production readiness.

**Completed:** ~88% of PRD requirements (§6.1–6.6, §6.10–6.13 incl. quality dashboard, most of §6.8, §7.2.1, §6.16 substrate + per-doc revision Phases 1+2 **and** Phase 3 UX/consolidation/MCP tools, plus the perf streams below)
**Remaining:** ~12% across 6 work streams + 3 future / architectural streams, estimated 5–7 weeks (core) + TBD (Streams 8–9)

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
| Imports, Composition & Dependencies (§6.15, §6.8.8–8.16) | **Phase 0 + Phase 1 + Phase 2a done + H.15 in Phase 2b done (v0.4.0-dev); H.16/H.17 pending** | `owl:imports` edge tracking, imports CRUD, `ontology_imports` named graph, standard ontology catalog (`/ontology/catalog` + bundled DCMI sample), `GET /imports-graph` DAG endpoint, cascade-on-delete impact, base-ontology selector on extraction, OWL exports preserving `owl:imports`, workspace catalog-browser overlay, workspace imports-dependency overlay (DAG canvas + library deep-link), three Visualizer saved queries, effective-graph API (`GET /{id}/effective` with inline conflicts + ETag), merge-conflict detection (duplicate URI / duplicate label / subclass cycle via import), and canvas rendering of imported entities (dashed slate border + dimmed fill on Sigma + box-arrow + "Open Source Ontology" context-menu deep-link, with the legend swatch surfacing only when imports are present) are all shipped. Phase 2b remaining: drag-and-drop import composition (H.16), import-aware extraction prompts (H.17). |
| Belief Revision UX (§6.16, Stream 11 Phase 3) | **Complete (v0.4.0-dev)** | Revisions Inbox overlay (IBR.14), inline detail panel (IBR.15), accept/reject/modify REST + service (IBR.16), background consolidation + admin endpoints (IBR.17), four safety guards (IBR.18), Quality Dashboard "Revisions Activity" tile (IBR.19), six MCP tools (IBR.20), and docs cross-link (IBR.21) all shipped. See ADR-008 implementation status appendix. |
| Constraints (§6.14) | **Not Started** | No OWL restriction or SHACL shape extraction, import, display, or export |
| Schema Extraction (§6.9) | **Stub** | Service shell exists but minimal implementation. No named graph-aware extraction, no direct graph-to-ontology mapping fallback, no UI for graph selection |
| Quality Dashboard (§6.13.7) | **Mostly Done (v0.4.0-dev)** | Unified `/dashboard`, `/quality` → per-ontology tab, recharts radar, audited OntoQA metrics, connectivity metric, qualitative evaluation, live per-ontology six-dimension view, **event-tagged history tracking (Q.2)**, **trend sparklines (Q.3)**, **gold-standard recall (Q.4)**, **curation throughput timer (Q.5)**. Remaining: RAG benchmark comparison. |
| Workspace Performance (Stream 12) | **Mostly Done in v0.3.0** | T1+T2+T3+T4+T5 shipped (projections, single-item endpoints, client cache, FLATTEN consolidation, telemetry, format sniffer, UI race fixes). Remaining: T6 WTW switch profile, T7 `/runs/{id}/cost` cache, T8 `/runs` join. |
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
| H.16 | Drag-and-drop import composition | Frontend | 4h | Drag an ontology from Asset Explorer onto the canvas of an open ontology to add it as an import. Creates `imports` edge and refreshes effective graph. Context menu "Remove Import" on imported ontology groups. (FR-15.10) |
| H.17 | Import-aware extraction prompts | Backend | 4h | When extracting into a composed ontology, the LLM prompt includes the effective ontology (own + imported classes) as context. Instructions tell the LLM to reuse imported concepts via `rdfs:subClassOf` or `owl:equivalentClass` rather than duplicating. (FR-15.9) |

#### Implementation Plan — Recommended Order

| Phase | Tasks | Est. Duration | Prerequisites |
|-------|-------|---------------|---------------|
| **Phase 0 (COMPLETE)** | H.0a–H.0e | — | None |
| **Phase 1a (COMPLETE v0.4.0-dev)** | H.2, H.3 (remaining), H.5, H.6, H.9 | shipped | Phase 0 |
| **Phase 1b (COMPLETE v0.4.0-dev)** | H.4, H.7, H.8, H.10 | shipped | Phase 1a |
| **Phase 2a (COMPLETE v0.4.0-dev)** | H.12, H.13 | shipped | Phase 1 |
| **Phase 2b: Canvas & Extraction** | H.15 (DONE), H.16, H.17 | ~2 days remaining | Phase 2a |

**Parallelization:** With H.15 landed, H.16 (drag-and-drop composition) and H.17 (import-aware extraction prompts) can run fully in parallel against the now-stable effective-graph wire contract.

**Exit Criteria:** `owl:imports` tracked as edges. Standard ontologies importable from catalog. Imports dependency graph visible in UI and ArangoDB Visualizer. Users can create composed ontologies that inherit imported axioms. Effective graph rendered in canvas with visual distinction for imported entities. Export preserves `owl:imports`.

**Phase 2a + H.15 status (v0.4.0-dev):** the effective-graph data layer (H.12), merge-conflict detection (H.13), and canvas rendering of imported entities (H.15) are shipped. The "effective graph rendered in canvas with visual distinction for imported entities" exit-criteria bullet is now met. H.16 (DnD composition) and H.17 (import-aware extraction prompts) remain.

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
| Q.2 | Quality history API | Backend | 4h | **DONE (v0.4.0-dev)** — `GET /quality/{ontology_id}/history` returns timestamped snapshots; `quality_history` collection (migration `022_quality_history`); `save_quality_snapshot(ontology_id, report, source=, run_id=)` accepts event-tagged sources; `record_event_snapshot()` helper called from `extraction.execute_run` (`source="extraction_completion"`) and `promotion.promote_staging` (`source="promotion"`); failures swallowed so a snapshot bug never breaks the write path. |
| Q.3 | Trend sparklines | Frontend | 3h | **DONE (v0.4.0-dev)** — `QualitySparkline` SVG component on `OntologyScoreTable` with lazy-fetch + module cache, ↑/↓/→ session-trend arrow, accent dots for `extraction_completion` (sky) and `promotion` (emerald) datapoints, loading / single-point / no-data / error fallbacks. |
| Q.4 | Gold-standard recall comparison | Backend | 4h | **DONE (v0.4.0-dev)** — `POST /api/v1/quality/recall` accepts an OWL/TTL/RDF body string, normalises labels (camelCase split, depluralisation, punctuation strip), greedy 1-to-1 best-match via `difflib.SequenceMatcher`, returns precision / recall / F1 plus per-class `matched` / `missed` / `false_positives` and an optional object-properties section. Frontend overlay (`RecallComparisonOverlay`) with file picker, threshold slider, and inline report; opened from `QualityReportOverlay`. |
| Q.5 | Curation throughput timer | Frontend | 3h | **DONE (v0.4.0-dev)** — Client measures gap between consecutive submit clicks (capped at 30 min so idle outliers don't skew session active-time); `recordCurationDecision` / `recordCurationBatchDecision` helpers send `decision_latency_ms` on every decide / batch call; backend persists it on `curation_decisions` and exposes `GET /api/v1/curation/throughput` with active-time + wall-clock fallback strategies. `CurationThroughputCounter` badge in the curation header shows session rate + trailing-10 trend hint. |

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

#### Pending (P0, data-driven)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| T6 | WTW switch ~8-9s investigation | Backend | TBD (≤ 1 day after first profile) | Stage-level logs (T3) are in place. After the next user-driven WTW switch we should have the per-stage breakdown to act on. Likely culprits: residual N+1 in something the workspace calls in parallel with `/edges`, or AQL not hitting the right index on a 1000+ class ontology. |
| T7 | `/runs/{id}/cost` ~9s | Backend | 4h | Recomputes whole-ontology quality on every call. Either cache the result on run completion (and expose a `compute_at` timestamp), or pre-compute during the Quality Judge step and store on the run document. |
| T8 | `/runs` ~3s | Backend | 3h | N+1 doc enrichment on the run list. Replace with a single AQL that joins runs to documents (or pre-stores the join document on run insert). |

#### Pending (P1, larger refactor)

| # | Task | Type | Estimate | Description |
|---|------|------|----------|-------------|
| T9 | Remove `?include=full` from canvas paths | Frontend | 2h | Audit the workspace's canvas-load fetches to confirm they all use `?include=summary`. The few that still need full payloads (provenance overlay, version history) should switch to single-item endpoints (T1.2 pattern). |
| T10 | Pagination cursor on `/classes` and `/edges` | Backend + Frontend | 1 day | For ontologies with > 5K entities, ship a cursor-based page so the workspace can render the visible viewport first and lazy-load the rest. |

**Exit Criteria:** Workspace switch on a 1000+ class ontology stays under 2s end-to-end; no API endpoint exceeds 1s p95 on demo data; per-stage telemetry remains in the logs as a permanent diagnostic surface.

---

## Recommended Execution Order (post-v0.3.0, post-Stream-11)

```
Sprint A (now): Stream 4 (Quality Dashboard finishing: Q.2/Q.3/Q.4/Q.5) + Stream 12 P0/P1 (T6 WTW switch profile, T7 cost cache, T8 runs join)
Sprint B:       Stream 1 Phase 1b (Imports integration: cascade, dependency graph, base-ontology selector) + Stream 2 (ER) — in parallel
Sprint C:       Stream 1 Phase 2 (Composition: effective graph, conflict detection, drag-and-drop, import-aware extraction) + Stream 3 (Constraints) — in parallel
Sprint D:       Stream 5 (Schema Extraction) + remaining Stream 12 follow-ups from telemetry — in parallel
Sprint E:       Stream 6 (Testing & CI)
Sprint F:       Stream 7 (Production Polish)
                → v1.0.0 Release
Post-v1.0:      Stream 8 (Sigma.js Migration) + Stream 9 (Unified Storage spike)
```

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
