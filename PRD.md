# Product Requirements Document (PRD)

**Project Name:** Arango-OntoExtract (AOE)
**Document Status:** Draft v3
**Last Updated:** 2026-03-28
**Primary Tech Stack:** ArangoDB, Python, Large Language Models (LLMs), React/Next.js (Frontend), Cursor IDE, Claude (AI Agent)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [User Personas](#2-user-personas)
3. [Objectives & Success Metrics](#3-objectives--success-metrics)
4. [System Architecture](#4-system-architecture)
5. [Data Model](#5-data-model)
   - 5.1 ArangoDB Collections
   - 5.2 Ontology Library Architecture
   - 5.3 Temporal Ontology Versioning (Edge-Interval Time Travel)
6. [Core Features & Functional Requirements](#6-core-features--functional-requirements)
   - 6.1 Document Ingestion & Chunking
   - 6.2 Domain Ontology Extraction (Tier 1)
   - 6.3 Localized Ontology Extension (Tier 2)
   - 6.4 Visual Curation Dashboard (Human-in-the-Loop)
   - 6.5 Temporal Time Travel & VCR Timeline
   - 6.6 ArangoDB Graph Visualizer Customization
   - 6.7 Entity Resolution & Deduplication
   - 6.8 Import & Export
   - 6.9 Schema Extraction from ArangoDB Databases
   - 6.10 MCP Server (Runtime)
   - 6.11 Agentic Extraction Pipeline (LangGraph)
   - 6.12 Pipeline Monitor Dashboard (Agentic Workflow Visualizer)
   - 6.13 Ontology Quality Metrics
   - 6.14 Ontology Constraints (OWL Restrictions & SHACL Shapes)
   - 6.15 Ontology Imports & Dependency Management
7. [API Specification](#7-api-specification-backend)
   - 7.1–7.7 Endpoint groups
   - 7.8 Frontend Pages (Next.js Routes)
8. [Non-Functional Requirements](#8-non-functional-requirements)
   - 8.1 Performance
   - 8.2 Scalability
   - 8.3 Security
   - 8.4 Reliability
   - 8.5 Observability
   - 8.6 Deployment & Infrastructure
   - 8.7 Data Migration & Schema Evolution
   - 8.8 Notification & Event Strategy
   - 8.9 Testing & Code Quality
9. [Leveraging Existing Codebases](#9-leveraging-existing-codebases)
10. [Development Phases](#10-development-phases)
11. [Cursor & Claude Development Workflow](#11-cursor--claude-development-workflow)
12. [Open Questions & Risks](#12-open-questions--risks)
- [Appendix A: Glossary](#appendix-a-glossary)

---

## 1. Executive Summary

Arango-OntoExtract (AOE) is an LLM-driven ontology extraction and curation platform built on ArangoDB. The system ingests unstructured text (PDF, DOCX, Markdown), automatically generates formal domain ontologies expressed in OWL 2 / RDFS (with optional SKOS vocabulary support), and provides a visual curation interface for domain experts to review, refine, and promote extracted knowledge. Ontologies are stored in ArangoDB via ArangoRDF's PGT transformation, which preserves OWL metamodel semantics while leveraging ArangoDB's multi-model capabilities.

The platform supports a **two-tier architecture**:

| Tier | Purpose | Lifecycle |
|------|---------|-----------|
| **Tier 1 — Domain Ontology Library** | Standardized schemas extracted from industry-standard documents (ISO, W3C, NIST, etc.) | Curated once, shared across organizations |
| **Tier 2 — Localized Ontology Extensions** | Organization-specific sub-graphs that inherit from and extend Tier 1 | Per-organization, evolves with their documents |

The critical differentiator is that Localized Ontologies are **structurally linked** to Domain Ontologies via standard OWL/RDFS constructs (`rdfs:subClassOf`, `owl:equivalentClass`, `owl:imports`) — not forks or copies. For taxonomy-oriented use cases, SKOS relationships (`skos:broader`, `skos:narrower`, `skos:related`) are also supported.

---

## 2. User Personas

### 2.1 Domain Expert (Primary User)
- **Role:** Subject matter expert (e.g., compliance officer, data architect, risk analyst)
- **Goals:** Review extracted ontologies for accuracy, merge/split concepts, approve promotion to production
- **Pain points:** Cannot read RDF/OWL directly; needs visual graph interface with plain-language labels
- **Interactions:** Visual Curation Dashboard, entity resolution review, approval workflows

### 2.2 Ontology Engineer (Power User)
- **Role:** Maintains the Domain Ontology Library and defines extraction templates
- **Goals:** Import industry-standard ontologies, define extraction schemas, configure LLM prompts per domain
- **Pain points:** Manual ontology construction is slow; needs LLM assistance with human override
- **Interactions:** All features including prompt engineering, schema configuration, bulk import/export

### 2.3 Organization Admin
- **Role:** Manages organization settings, user access, and document collections
- **Goals:** Upload organization documents, manage who can approve ontology changes, monitor extraction pipeline status
- **Interactions:** Document upload, user management, pipeline monitoring dashboard

### 2.4 AI Agent (Cursor + Claude + Antigravity)
- **Role:** Development-time and runtime assistant
- **Goals:** Query live ArangoDB state via MCP, assist with extraction logic, suggest ontology mappings
- **Interactions:** MCP server, database introspection, code generation, Antigravity agentic workflows

### 2.5 External AI Agent (MCP Client)
- **Role:** Any AI system that consumes ontology knowledge at runtime
- **Goals:** Query domain/local ontologies, trigger extractions, retrieve entity resolution candidates via MCP tools
- **Pain points:** No standard way to programmatically access ontology knowledge; needs structured tool interface
- **Interactions:** AOE MCP Server (runtime)

---

## 2a. Use Cases & Workflows

This section defines the end-to-end workflows performed by each role. These workflows serve as the basis for integration testing, E2E test scenarios, and role-based access control (RBAC) policy definitions.

### Roles & RBAC Matrix

| Role | Code | Description | RBAC Level |
|------|------|-------------|------------|
| **Domain Expert** | `domain_expert` | Reviews extraction results, curates ontologies, approves/rejects classes | Read + Curate |
| **Ontology Engineer** | `ontology_engineer` | Full ontology management: import, edit, delete, configure extraction | Read + Write + Delete |
| **Organization Admin** | `admin` | User management, system configuration, reset, all permissions | Full |
| **Viewer** | `viewer` | Read-only access to library, pipeline status, quality metrics | Read only |
| **AI Agent (MCP)** | `agent` | Programmatic access via MCP tools | Scoped by MCP tool permissions |

### RBAC Permission Matrix

| Endpoint / Action | viewer | domain_expert | ontology_engineer | admin |
|-------------------|--------|---------------|-------------------|-------|
| View library, class hierarchies | ✅ | ✅ | ✅ | ✅ |
| View pipeline monitor, metrics | ✅ | ✅ | ✅ | ✅ |
| View quality dashboard | ✅ | ✅ | ✅ | ✅ |
| Export ontology (OWL, JSON-LD, CSV) | ✅ | ✅ | ✅ | ✅ |
| Upload documents | ❌ | ✅ | ✅ | ✅ |
| Trigger extraction | ❌ | ✅ | ✅ | ✅ |
| Curation: approve/reject classes | ❌ | ✅ | ✅ | ✅ |
| Curation: edit class properties | ❌ | ✅ | ✅ | ✅ |
| Curation: batch operations | ❌ | ✅ | ✅ | ✅ |
| Promote staging to production | ❌ | ❌ | ✅ | ✅ |
| Import standard ontology (OWL/TTL) | ❌ | ❌ | ✅ | ✅ |
| Create/edit classes in ontology editor | ❌ | ❌ | ✅ | ✅ |
| Delete class (temporal soft-delete) | ❌ | ❌ | ✅ | ✅ |
| Deprecate ontology | ❌ | ❌ | ✅ | ✅ |
| Delete document (hard delete) | ❌ | ❌ | ✅ | ✅ |
| Update ontology metadata (name, tags) | ❌ | ❌ | ✅ | ✅ |
| Execute ER merge | ❌ | ❌ | ✅ | ✅ |
| Create release candidate | ❌ | ❌ | ✅ | ✅ |
| Publish release | ❌ | ❌ | ✅ | ✅ |
| Revert ontology to previous release | ❌ | ❌ | ✅ | ✅ |
| Undo deprecation | ❌ | ❌ | ✅ | ✅ |
| View release history | ✅ | ✅ | ✅ | ✅ |
| Manage users and organizations | ❌ | ❌ | ❌ | ✅ |
| System reset (soft/full) | ❌ | ❌ | ❌ | ✅ |
| View/modify system configuration | ❌ | ❌ | ❌ | ✅ |

### Use Case Catalog

#### UC-1: Extract Ontology from Document (Domain Expert)

**Actor:** Domain Expert
**Precondition:** User is authenticated with `domain_expert` role
**Trigger:** User has a new document describing a business domain

**Main Flow:**
1. User navigates to `/upload`
2. User optionally selects a target ontology ("Create New" or existing) and base ontologies for context
3. User drops a PDF/DOCX/Markdown file onto the upload zone
4. System parses the document, creates chunks, generates embeddings
5. System auto-triggers the extraction pipeline (6-agent LangGraph)
6. User is redirected to `/pipeline` to monitor progress
7. Pipeline completes: Strategy → Extraction → Consistency → Quality Judge → ER → Filter
8. User clicks "Curate" to review results in `/curation/[runId]`
9. User reviews each class: approves, rejects, or edits
10. User clicks "Promote" to move approved classes to the ontology library

**Alternative Flows:**
- 3a. File type not supported → error message, no upload
- 5a. LLM returns empty responses → retries (up to 5) with backoff; if all fail, run marked as failed with errors
- 7a. 0 classes extracted → "No ontology data for this run" message with guidance
- 9a. User disagrees with class hierarchy → edits parent class, system creates new temporal version

**Post-conditions:** New ontology appears in library with curated classes. VCR timeline shows extraction and curation history. Quality metrics computed.

**PRD References:** §6.1 FR-1.1–1.6, §6.2 FR-2.1–2.11, §6.4 FR-4.1–4.8, §6.11, §6.12

---

#### UC-2: Extend Ontology with Additional Document (Domain Expert)

**Actor:** Domain Expert
**Precondition:** An ontology already exists in the library
**Trigger:** User has a new document that should enrich an existing ontology

**Main Flow:**
1. User navigates to `/library` and selects the target ontology
2. User clicks "+ Add Document" in the sidebar
3. User selects a file; system uploads, parses, and chunks it
4. System triggers incremental extraction with `target_ontology_id` set
5. Extraction pipeline runs with existing ontology classes injected as context (Tier 2)
6. Consistency Checker classifies new extractions: EXISTING / EXTENSION / NEW
7. User reviews in curation: only genuinely new concepts need approval
8. Approved classes merge into the existing ontology

**Alternative Flows:**
- 4a. User uploads from `/upload` page and selects the target ontology from dropdown → same result

**Post-conditions:** Ontology enriched with new classes. `extracted_from` edges link to both source documents. Timeline shows additive growth.

**PRD References:** §6.1 FR-1.7–1.8, §6.2 FR-2.12–2.13, §6.3 FR-3.1–3.5

---

#### UC-3: Curate Extraction Results (Domain Expert)

**Actor:** Domain Expert
**Precondition:** An extraction run has completed
**Trigger:** Pipeline shows "Completed" status

**Main Flow:**
1. User navigates to `/pipeline` and selects a completed run
2. User clicks "Curate" → opens `/curation/[runId]`
3. Graph canvas shows extracted classes with confidence-coded colors (red <0.5, yellow 0.5–0.7, green >0.7)
4. User clicks a class node → side panel shows: label, URI, description, properties, provenance (source chunks), confidence breakdown
5. User approves high-confidence classes (batch select → approve)
6. User rejects irrelevant classes (system expires them + connected edges)
7. User edits a misnamed class → system creates new temporal version, re-creates edges
8. User opens VCR Timeline → scrubs to see how the ontology looked before this extraction
9. User opens Diff View → sees what's new vs. existing ontology
10. User clicks "Promote" → approved entities confirmed in production ontology

**Alternative Flows:**
- 3a. No data → "No ontology data for this run" message
- 6a. Reject cascade: connected edges are expired alongside the rejected class
- 7a. Edit creates new version: old version visible in VCR timeline

**Post-conditions:** Curation decisions recorded. Quality metrics updated (acceptance rate, throughput). Ontology reflects curator's expert judgment.

**PRD References:** §6.4 FR-4.1–4.9, §6.5, §6.13 FR-13.1–13.2

---

#### UC-4: Directly Edit Ontology (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** An ontology exists in the library
**Trigger:** Engineer needs to manually add/modify classes outside of extraction

**Main Flow:**
1. User navigates to `/library` and selects an ontology
2. User clicks "Edit Graph" → opens `/ontology/[ontologyId]/edit`
3. Graph editor shows all current classes and relationships
4. User clicks "+ Add Class" → dialog: label, URI, description, parent class
5. System creates class with `source_type: "manual"`, `confidence: 1.0`
6. User selects the new class → clicks "+ Add Property" → dialog: label, range type
7. System creates property + `has_property` edge
8. User double-clicks a class label → inline edit → saves (temporal version update)
9. User changes a class's parent via "Change Parent" dropdown → old `subclass_of` edge expired, new one created
10. User opens VCR Timeline to review all changes

**Alternative Flows:**
- 4a. Class with same URI already exists → error "Active class with this URI already exists"
- 8a. Edit creates new temporal version visible in history panel

**Post-conditions:** Manually created/edited classes in the ontology. Full temporal history preserved. Quality metrics reflect manual additions (`source_type: "manual"`).

**PRD References:** §6.4 FR-4.10–4.13

---

#### UC-5: Import Standard Ontology (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** User has `ontology_engineer` role
**Trigger:** Organization needs a standard ontology (e.g., FIBO, Schema.org) as a base

**Main Flow:**
1. User navigates to `/library` or `/upload`
2. User clicks "Import Standard Ontology" → catalog browser opens
3. User selects FIBO Financial Instruments module → clicks "Import"
4. System downloads OWL file, imports via ArangoRDF PGT transformation
5. New ontology appears in library with `source_type: "import"`, `status: "active"`
6. Per-ontology named graph created with visualizer assets (themes, queries, actions)
7. `owl:imports` edges created linking to any dependencies already in the library

**Alternative Flows:**
- 2a. User uploads their own OWL/TTL file instead of using catalog
- 7a. Imported ontology references ontologies not in library → warning shown

**Post-conditions:** Standard ontology available in library. Can be selected as base for future Tier 2 extractions. Dependencies tracked via `imports` edges.

**PRD References:** §6.8 FR-8.1–8.2, FR-8.11, §6.15 FR-15.1–15.6

---

#### UC-6: Review Entity Resolution Candidates (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** ER pipeline has been run, merge candidates exist
**Trigger:** Pipeline or library shows ER candidates requiring review

**Main Flow:**
1. User navigates to `/entity-resolution`
2. User selects an ER run → sees candidate pairs with similarity scores
3. For each pair, user sees: field-by-field comparison, `explain_match` evidence, topological similarity
4. User accepts a merge → system creates golden record, expires losing entity, transfers edges
5. User rejects a candidate → marked as rejected, excluded from future suggestions
6. User skips uncertain candidates for later review

**Alternative Flows:**
- 3a. Cross-ontology candidate (local class ~ domain class) → system suggests `owl:equivalentClass` or `rdfs:subClassOf` link instead of merge

**Post-conditions:** Duplicates resolved. Merge decisions recorded. Deduplication accuracy metric updated. Ontology cleaner and more consistent.

**PRD References:** §6.7 FR-7.1–7.11

---

#### UC-7: Monitor Extraction Pipeline (Any Role)

**Actor:** Any authenticated user (viewer and above)
**Precondition:** At least one extraction run exists
**Trigger:** User wants to check pipeline status

**Main Flow:**
1. User navigates to `/pipeline`
2. Left panel shows extraction runs: document name, status (Running/Completed/Failed), chunk count, class count, duration, model
3. User selects a run → right panel shows Agent Pipeline DAG
4. DAG shows 6 steps with status: Strategy Selector → Extraction Agent → Consistency Checker → Quality Judge → Entity Resolution Agent → Pre-Curation Filter
5. Running step highlighted with animation; completed steps are green
6. Below DAG: Metrics tab (duration, tokens, cost, entities, agreement, confidence, completeness), Errors tab (with run-level errors from stats.errors), Timeline tab
7. User clicks "Curate" to review results (if `domain_expert` or above)

**Alternative Flows:**
- 4a. Pipeline still running → steps poll every 5 seconds via REST fallback
- 6a. Extraction failed → Errors tab shows details; "Retry" button available

**Post-conditions:** User informed of pipeline status. Can take action based on results.

**PRD References:** §6.12 FR-12.1–12.10

---

#### UC-8: Deprecate an Ontology (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** Ontology exists in library with `status: "active"`
**Trigger:** Ontology is obsolete or being replaced

**Main Flow:**
1. User navigates to `/library` and selects the ontology
2. User initiates deletion (e.g., settings menu or admin action)
3. System performs cascade analysis: queries `imports` graph for dependent ontologies
4. System shows confirmation: "Ontology X is imported by Y, Z. Deprecating X will affect these ontologies."
5. User confirms → system executes temporal soft-delete:
   - All classes, properties, constraints: `expired = now`
   - All scoped edges: `expired = now`
   - Cross-ontology `imports` edges to/from this ontology: `expired = now`
   - Cross-ontology `extends_domain` edges targeting this ontology's classes: `expired = now`
   - Registry entry: `status = "deprecated"` (NOT hard-deleted)
   - Per-ontology named graph: removed
6. Ontology no longer appears in active library but remains in history

**Alternative Flows:**
- 3a. No dependents → confirmation still required but no warning
- 5a. User cancels → no changes made

**Post-conditions:** Ontology deprecated. VCR timeline shows full pre-deprecation history. Dependent ontologies warned. No dangling edge references.

**PRD References:** §6.8 FR-8.13, §6.15 FR-15.4, `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`

---

#### UC-9: System Reset (Admin)

**Actor:** Organization Admin
**Precondition:** `ALLOW_SYSTEM_RESET=true` environment variable set (dev/demo only)
**Trigger:** Admin needs to start fresh for demo or testing

**Main Flow:**
1. User navigates to `/pipeline`
2. User clicks "Reset ▾" dropdown → selects "Reset Ontology Data" (soft) or "Full Reset" (hard)
3. Confirmation dialog explains what will be deleted
4. User confirms → system truncates collections, removes named graphs
5. Soft reset: documents and chunks preserved (can re-extract); Full reset: everything wiped
6. Run list refreshes showing empty state

**Alternative Flows:**
- 2a. `ALLOW_SYSTEM_RESET` not set → 403 error "System reset disabled"

**Post-conditions:** Clean slate. No temporal history (hard delete). Visualizer configuration assets preserved.

**PRD References:** §7.2.1, `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md` §3.10

---

#### UC-10: Query Ontology via MCP (AI Agent)

**Actor:** External AI Agent (MCP Client)
**Precondition:** MCP server running and agent has API key
**Trigger:** Agent needs ontology knowledge for a task

**Main Flow:**
1. Agent connects to AOE MCP server
2. Agent calls `search_similar_classes(text="financial transaction", threshold=0.8)` → gets matching classes with similarity scores
3. Agent calls `get_class_hierarchy(ontology_id="...", root_class="Transaction")` → gets subclass tree
4. Agent calls `export_ontology(ontology_id="...", format="jsonld")` → gets structured ontology data
5. Agent uses ontology knowledge to inform its own reasoning

**Alternative Flows:**
- 2a. Agent triggers extraction: `trigger_extraction(document_id="...")` → returns run_id for status polling
- 3a. Agent queries temporal snapshot: `get_snapshot(ontology_id="...", at=1774883200)` → ontology state at specific time

**Post-conditions:** Agent has ontology knowledge. No side effects on read-only queries.

**PRD References:** §6.10 FR-10.1–10.5

---

#### UC-11: Review Quality Metrics (Any Role)

**Actor:** Any authenticated user (viewer and above)
**Precondition:** At least one ontology exists with extraction history
**Trigger:** User wants to assess ontology quality

**Main Flow:**
1. User navigates to `/quality` (quality dashboard)
2. Dashboard shows aggregate metrics: avg extraction precision, curation throughput, deduplication accuracy
3. Traffic-light indicators show status vs. PRD targets (green ≥ target, yellow within 10%, red below)
4. User clicks an ontology → sees per-ontology quality: avg confidence, completeness, orphan count, cycle detection
5. User views trend sparklines showing quality over time
6. User navigates to library → QualityPanel shows inline quality summary for selected ontology

**Alternative Flows:**
- 1a. `/quality` page not yet implemented → user accesses quality via library QualityPanel

**Post-conditions:** User informed of quality status. Can prioritize curation effort on low-quality ontologies.

**PRD References:** §6.13 FR-13.1–13.10

---

#### UC-12: Create and Publish Ontology Release (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** Ontology exists with `status: "active"` and has been curated
**Trigger:** Ontology is ready for consumers to reference as a stable version

**Main Flow:**
1. User navigates to `/library` and selects the ontology
2. User clicks "Create Release" → release dialog opens
3. System runs breaking change detection against the previous release
4. System suggests version number (e.g., v1.2.0 for additive changes, v2.0.0 for breaking)
5. System shows change report: new classes added, classes removed, properties changed
6. User writes release notes (markdown) explaining the changes
7. User confirms → release candidate created, ontology enters read-only mode
8. Reviewer examines the RC: views frozen snapshot, reads change report
9. Reviewer approves → release published with `owl:versionIRI`
10. Ontology returns to editable (working) state
11. Export endpoint now serves the release: `GET /ontology/{id}/export?version=1.2.0`

**Alternative Flows:**
- 5a. Breaking changes detected but user selects MINOR version → system warns "Breaking changes detected, recommend MAJOR version"
- 9a. Reviewer rejects RC → RC discarded, ontology returns to editable, no version published
- 11a. Consumer references the release via `owl:imports` → stable, immutable reference

**Post-conditions:** Immutable release snapshot stored. Previous release marked as superseded. OWL version metadata included in exports.

**PRD References:** §6.8a FR-8a.1–8a.7

---

#### UC-13: Revert Ontology to Previous Release (Ontology Engineer)

**Actor:** Ontology Engineer
**Precondition:** Ontology has at least 2 published releases; current state has issues
**Trigger:** Recent changes or a new release introduced problems

**Main Flow:**
1. User navigates to `/library` and selects the ontology
2. User clicks "Release History" → sees list of all releases with versions, dates, change summaries
3. User identifies the last known-good release (e.g., v1.1.0)
4. User clicks "Revert to v1.1.0" → confirmation dialog shows what will change
5. System creates new current versions of all classes/properties/edges matching the v1.1.0 snapshot
6. Current (problematic) versions are expired (but preserved in history)
7. Ontology now looks like v1.1.0 but with a new temporal timestamp
8. VCR timeline shows: original → changes → revert event

**Alternative Flows:**
- 5a. Revert of a single class: user right-clicks a class → "Revert to version N" → system creates new version with historical data
- 6a. Revert is a forward operation — no history is destroyed; the revert itself is a new timeline event

**Post-conditions:** Ontology state matches the target release. All changes since that release are effectively undone but preserved in temporal history. A new release can be created from the reverted state.

**PRD References:** §6.8a FR-8a.8–8a.10, §6.5, `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`

---

### Workflow Testing Matrix

This matrix maps each use case to testable steps for E2E test scenarios:

| UC | Flow | Key Assertions | API Endpoints Tested |
|----|------|----------------|---------------------|
| UC-1 | Upload → Extract → Curate → Promote | Classes in library after promote; metrics populated; timeline has events | POST /documents/upload, POST /extraction/run, GET /extraction/runs/{id}, POST /curation/decide, POST /curation/promote/{runId} |
| UC-2 | Add doc to existing ontology | New classes merged into existing ontology; `extracted_from` edges link to both docs | POST /library/{id}/add-document, GET /library/{id}/documents |
| UC-3 | Approve, reject, edit classes | Approved: status=approved; Rejected: expired + edges expired; Edited: new version + edges re-created | POST /curation/decide, GET /ontology/{id}/classes |
| UC-4 | Add class, add property, rename, reparent | New entities with source_type=manual; temporal versions; edge updates | POST /ontology/{id}/classes, POST /ontology/{id}/properties, PUT /ontology/{id}/classes/{key} |
| UC-5 | Import OWL file | Ontology in registry; per-ontology graph created; imports edges | POST /ontology/import, GET /library/{id}/imports |
| UC-6 | Accept/reject merge candidates | Merge: losing entity expired, edges transferred; Reject: candidate excluded | POST /er/run, GET /er/runs/{id}/candidates, POST /curation/decide (merge) |
| UC-7 | View pipeline, metrics, errors | Steps populated; metrics non-zero for completed runs; errors for failed runs | GET /extraction/runs, GET /extraction/runs/{id}/cost, GET /extraction/runs/{id} |
| UC-8 | Deprecate ontology | All entities expired (not deleted); registry status=deprecated; dependent ontologies warned | DELETE /library/{id}?confirm=true, GET /library/{id} |
| UC-9 | System reset | Collections empty; named graphs removed; documents preserved (soft) or removed (full) | POST /admin/reset, POST /admin/reset/full |
| UC-10 | MCP tool calls | Correct data returned; no side effects on reads | MCP tools: search_similar_classes, get_class_hierarchy, export_ontology |
| UC-11 | Quality metrics | Health score computed; confidence values differentiated; completeness accurate | GET /quality/{id}, GET /quality/summary |
| UC-12 | Create + publish release | RC created with snapshot; breaking changes detected; release published; export serves version; previous release superseded | POST /ontology/{id}/releases, POST .../publish, GET /ontology/{id}/export?version=1.2.0 |
| UC-13 | Revert to previous release | Current state matches target release; changes preserved in history; revert appears as timeline event | POST /ontology/{id}/revert, GET /ontology/{id}/timeline |

---

## 3. Objectives & Success Metrics

### 3.1 Objectives

| ID | Objective | Measurable Outcome |
|----|-----------|-------------------|
| O1 | Automated Extraction | Extract classes, properties, relationships, and constraints from unstructured text into formal semantic structures |
| O2 | Two-Tier Ontology Management | Domain ontologies serve as base schemas; localized ontologies extend them without duplication |
| O3 | Visual Curation (Human-in-the-Loop) | Domain experts can review, approve, reject, merge, and edit LLM inferences through a graph UI |
| O4 | Entity Resolution | Automatically flag and suggest merges for overlapping concepts across tiers |
| O5 | AI-Native Development | The system is architected for Cursor + Claude development via MCP database introspection |
| O6 | Runtime MCP Server | The platform exposes ontology operations as MCP tools consumable by any AI agent |
| O7 | Agentic Extraction Pipeline | LangGraph-orchestrated agents autonomously manage extraction, entity resolution, and pre-curation filtering |

### 3.2 Success Metrics

| Metric | Target | How Measured |
|--------|--------|-------------|
| Extraction precision | ≥ 80% of LLM-extracted classes accepted by domain expert without edits | Acceptance rate in curation dashboard |
| Extraction recall | ≥ 70% of manually-identified concepts found by LLM | Comparison against gold-standard ontologies |
| Curation throughput | Domain expert can review 50+ concepts/hour | Time tracking in curation UI |
| Deduplication accuracy | ≥ 85% of suggested merges are correct | Expert approval rate on merge suggestions |
| Time to first ontology | < 30 minutes from document upload to draft ontology | Pipeline end-to-end timing |

---

## 4. System Architecture

### 4.1 High-Level Architecture

```
                    ┌──────────────────────┐
                    │  External AI Agents  │
                    │  (any MCP client)    │
                    └──────────┬───────────┘
                               │ MCP Protocol
┌──────────────────────────────┼──────────────────────────────────┐
│                        Frontend (React/Next.js)                 │
│  ┌──────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ Document  │  │ Visual Curation  │  │ Pipeline Monitor      │  │
│  │ Upload    │  │ Dashboard        │  │ Dashboard             │  │
│  └──────────┘  └──────────────────┘  └───────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST / WebSocket
┌──────────────────────────┴──────────────────────────────────────┐
│                     Backend (Python / FastAPI)                   │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │         LangGraph Agentic Orchestration Layer              │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐    │  │
│  │  │ Ingestion│  │ Extraction   │  │ Entity Resolution │    │  │
│  │  │ Agent    │  │ Agent        │  │ Agent             │    │  │
│  │  └──────────┘  └──────────────┘  └───────────────────┘    │  │
│  │  ┌──────────────────┐  ┌──────────────────────────────┐   │  │
│  │  │ Pre-Curation     │  │ Strategy Selection           │   │  │
│  │  │ Filter Agent     │  │ Agent                        │   │  │
│  │  └──────────────────┘  └──────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ Ingestion│  │ Extraction   │  │ Entity  │  │ Curation    │  │
│  │ Service  │  │ Service      │  │ Resol.  │  │ Service     │  │
│  └──────────┘  └──────────────┘  └─────────┘  └─────────────┘  │
│  ┌──────────────────────┐  ┌────────────────────────────────┐   │
│  │ ArangoRDF Bridge     │  │ MCP Server (dev + runtime)     │   │
│  └──────────────────────┘  └────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ArangoDB Python Driver
┌──────────────────────────┴──────────────────────────────────────┐
│                     ArangoDB (Multi-Model)                       │
│  ┌──────────┐  ┌──────────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ Document  │  │ Graph (OWL   │  │ Vector  │  │ Search/     │  │
│  │ Store     │  │ via PGT)     │  │ Index   │  │ ArangoSearch│  │
│  └──────────┘  └──────────────┘  └─────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Tech Stack Detail

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Database | ArangoDB 3.12+ | Multi-model (document + graph + vector + search) in single engine |
| Ontology Bridge | `ArangoRDF` | Stores OWL/RDFS ontologies in ArangoDB via PGT, preserving OWL metamodel semantics |
| LLM Orchestration | LangChain with structured outputs | Enforced JSON schema outputs for extraction |
| LLM Provider | Claude 3.5 Sonnet (primary), GPT-4o (fallback) | Best-in-class structured extraction |
| Backend Framework | FastAPI (Python 3.11+) | Async, Pydantic-native, OpenAPI auto-docs |
| Task Queue | Celery + Redis (or ARQ) | Async document processing pipeline |
| Frontend | React 18 + Next.js 14 | SSR, file-based routing, React Server Components |
| Graph Visualization | React Flow (native React) or Cytoscape.js via `react-cytoscapejs` | **Must be React-compatible** — renders as React components within the Next.js curation dashboard; supports interactive node/edge manipulation, custom node renderers, and layout algorithms |
| Vector Embeddings | OpenAI `text-embedding-3-small` or local model | Chunk embeddings for RAG + entity resolution |
| Agentic Orchestration | LangGraph | Stateful multi-step agent graphs with checkpointing and human-in-the-loop |
| MCP Server | `mcp` Python SDK | Exposes ontology tools to any MCP-compatible AI agent |
| Dev Tooling | Cursor IDE + Claude via MCP | AI-native development with live DB introspection |

---

## 5. Data Model

### 5.1 ArangoDB Collections

#### Document Collections (Non-Temporal)

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `documents` | Uploaded source documents | `_key`, `filename`, `mime_type`, `upload_date`, `org_id`, `status`, `metadata` |
| `chunks` | Semantic chunks of documents | `_key`, `doc_id`, `text`, `chunk_index`, `embedding` (vector), `token_count` |
| `extraction_runs` | Pipeline execution records | `_key`, `doc_id`, `model`, `prompt_version`, `started_at`, `completed_at`, `status`, `stats` |
| `curation_decisions` | Audit trail of expert decisions | `_key`, `entity_id`, `entity_type`, `action` (approve\|reject\|merge\|edit), `user_id`, `timestamp`, `before`, `after` |
| `notifications` | In-app notification queue | `_key`, `user_id`, `org_id`, `event_type`, `title`, `body`, `read`, `created_at`, `entity_ref` |
| `organizations` | Organization / tenant records | `_key`, `name`, `slug`, `selected_ontologies` (list of registry IDs), `settings`, `created_at` |
| `users` | User accounts and roles | `_key`, `email`, `display_name`, `org_id`, `role` (admin\|ontology_engineer\|domain_expert\|viewer), `created_at` |
| `_system_meta` | Internal metadata (schema version, migration state) | `_key` ("schema_version"), `version`, `applied_migrations`, `updated_at` |

#### Versioned Vertex Collections (Temporal — `created`/`expired` Interval Semantics)

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `ontology_classes` | Versioned `owl:Class` / `rdfs:Class` / `skos:Concept` instances | `_key`, `uri`, `rdf_type` (owl:Class\|skos:Concept), `label`, `description`, `tier` (domain\|local), `ontology_id` (FK to registry), `org_id`, `status` (draft\|approved\|deprecated), `version`, `created`, `expired`, `created_by`, `change_type`, `change_summary`, `ttlExpireAt` |
| `ontology_properties` | Versioned `owl:ObjectProperty` / `owl:DatatypeProperty` instances | `_key`, `uri`, `rdf_type`, `label`, `domain_class` (denormalized from `has_property` edge for query convenience), `range` (URI or datatype), `ontology_id`, `tier`, `status`, `version`, `created`, `expired`, `created_by`, `change_type`, `change_summary`, `ttlExpireAt` |
| `ontology_constraints` | Versioned OWL restrictions and SHACL shapes | `_key`, `ontology_id`, `constraint_type` (owl:Restriction\|sh:NodeShape\|sh:PropertyShape), `property_id`, `on_class` (target class), `restriction_type` (owl:allValuesFrom\|owl:someValuesFrom\|owl:minCardinality\|owl:maxCardinality\|owl:hasValue), `restriction_value`, `shape_uri`, `severity` (sh:Violation\|sh:Warning\|sh:Info), `sh_path`, `sh_datatype`, `sh_min_count`, `sh_max_count`, `sh_pattern`, `sh_in`, `message`, `created`, `expired`, `ttlExpireAt` |

#### Edge Collections (Temporal — All Edges Carry `created`/`expired`)

| Collection | From → To | Purpose |
|------------|-----------|---------|
| `subclass_of` | `ontology_classes` → `ontology_classes` | `rdfs:subClassOf` / `skos:broader` hierarchy |
| `equivalent_class` | `ontology_classes` → `ontology_classes` | `owl:equivalentClass` / `skos:exactMatch` mappings |
| `has_property` | `ontology_classes` → `ontology_properties` | `rdfs:domain` — class → property associations |
| `extends_domain` | `ontology_classes` (local) → `ontology_classes` (domain) | Tier 2 → Tier 1 linkage (specialization via `rdfs:subClassOf` or `skos:narrower`) |
| `extracted_from` | `ontology_classes` → `documents` | Provenance: which source document produced this class (links to the document, not individual chunks) |
| `has_chunk` | `documents` → `chunks` | Links source documents to their semantic text chunks (process graph) |
| `produced_by` | `ontology_registry` → `extraction_runs` | Links registered ontologies to the extraction run that created them (process graph) |
| `related_to` | `ontology_classes` → `ontology_classes` | `skos:related` / `owl:ObjectProperty` general semantic relationships |
| `merge_candidate` | `ontology_classes` → `ontology_classes` | Entity resolution suggestions (scored) |
| `imports` | `ontology_registry` → `ontology_registry` | `owl:imports` — ontology-level dependency tracking |

All ontology edge collections carry `created` and `expired` fields (same interval semantics as vertices). When a relationship changes (e.g., a class is reclassified under a different parent), the old edge is expired and a new edge is inserted. This enables point-in-time graph traversals that filter both vertices and edges by timestamp.

#### Ontology Library Registry

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `ontology_registry` | Catalog of all imported/extracted ontologies in the library | `_key`, `ontology_uri` (canonical namespace URI), `label`, `description`, `ontology_type` (owl\|rdfs\|skos\|mixed), `source_type` (import\|extraction\|schema_reverse), `source_file`, `version`, `iri_prefix`, `pgt_graph_name`, `owl_imports` (list of dependent ontology URIs), `status` (draft\|active\|deprecated), `created_at`, `created_by`, `class_count`, `property_count` |

Each ontology in the library gets a registry entry. All `ontology_classes` and `ontology_properties` documents carry an `ontology_id` foreign key linking back to this registry, enabling filtering and isolation.

#### Entity Resolution Collections (from `arango-entity-resolution`)

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `similarTo` | Edges between candidate pairs with similarity scores | `_from`, `_to`, `score`, `field_scores`, `strategy` |
| `entity_clusters` | WCC cluster membership | `_key`, `cluster_id`, `representative_key`, `member_keys`, `score` |
| `golden_records` | Merged/consolidated ontology records | `_key`, `source_keys`, `merge_strategy`, `merged_at` |

#### Named Graphs

| Graph | Vertex Collections | Edge Collections | Purpose |
|-------|-------------------|-------------------|---------|
| `domain_ontology` | `ontology_classes`, `ontology_properties`, `ontology_constraints`, `documents` | `subclass_of`, `equivalent_class`, `has_property`, `related_to`, `extracted_from` | Tier 1 base ontologies with provenance links to source documents |
| `aoe_process` | `documents`, `chunks`, `ontology_classes`, `ontology_properties`, `ontology_registry`, `extraction_runs` | `has_chunk`, `extracted_from`, `has_property`, `subclass_of`, `produced_by` | End-to-end pipeline graph showing the full data flow from document ingestion through extraction to the resulting ontology |
| `ontology_{name_slug}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | `subclass_of`, `equivalent_class`, `has_property`, `related_to`, `extracted_from` | Per-ontology named graph for isolation within the library. Name is derived from the human-readable ontology name (e.g., "Financial Services Domain" → `ontology_financial_services_domain`). |
| `local_ontology_{org_id}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | `subclass_of`, `equivalent_class`, `has_property`, `extends_domain`, `related_to` | Per-org Tier 2 extensions |
| `staging_{run_id}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | All ontology edge types | Draft graphs pending curation |
| `ontology_imports` | `ontology_registry` | `imports` | Ontology-level dependency graph showing `owl:imports` relationships between registered ontologies. Traversable to find upstream dependencies and downstream dependents. |

##### Process Graph (`aoe_process`)

The `aoe_process` graph provides a unified view of the entire extraction pipeline, enabling visual exploration in the ArangoDB Graph Visualizer of how documents flow through the system:

```
documents ──has_chunk──→ chunks
    ↑
    └──extracted_from── ontology_classes ──has_property──→ ontology_properties
                            │
                            └──subclass_of──→ ontology_classes
                            
ontology_registry ──produced_by──→ extraction_runs
```

**Additional Edge Collections (Process Graph):**

| Edge Collection | From | To | Purpose |
|----------------|------|-----|---------|
| `has_chunk` | `documents` | `chunks` | Links source documents to their semantic chunks |
| `produced_by` | `ontology_registry` | `extraction_runs` | Links registered ontologies to the extraction run that created them |

These edge collections complement the existing ontology edges (`subclass_of`, `has_property`, `extracted_from`) to form a complete traversable graph of the extraction pipeline. This enables AQL queries like "given a class, which document was it extracted from and what chunks contributed to its definition?"

### 5.2 Ontology Library Architecture

The Domain Ontology Library is not a single monolithic graph — it is a **managed collection of distinct ontologies** that can be composed, versioned, and queried independently or together.

**Multi-Ontology Isolation Strategy:**

ArangoRDF's PGT transformation stores OWL/RDFS/SKOS ontologies in ArangoDB using an **OWL metamodel strategy**: `owl:Class` instances become documents in vertex collections, OWL predicates (`rdfs:subClassOf`, `owl:ObjectProperty`, etc.) become edges, and OWL axioms are preserved as document properties. Multiple ontologies share the same collections, distinguished by IRI namespace. Since IRI namespaces alone are insufficient for reliable isolation (ontologies may reference each other's IRIs), AOE adds an explicit **application-level isolation layer**:

| Mechanism | How It Works |
|-----------|-------------|
| **`ontology_id` field** | Every `ontology_classes` and `ontology_properties` document carries an `ontology_id` linking to `ontology_registry`. All queries filter by this field. |
| **Per-ontology named graph** | Each ontology gets its own ArangoDB named graph with a human-readable slug name derived from the ontology's `name` field (e.g., `ontology_financial_services_domain`). This enables graph traversals scoped to a single ontology and provides clear identification in the ArangoDB UI. |
| **Combined domain graph** | The `domain_ontology` graph is the single composite view across all active library ontologies, used when Tier 2 extraction needs full domain context. There is no separate "all ontologies" graph — `domain_ontology` serves this purpose. |
| **IRI prefix tracking** | Each registry entry records its `iri_prefix` (e.g., `http://xmlns.com/foaf/0.1/`). Cross-ontology references are detectable by IRI prefix mismatch. |
| **ArangoRDF `uri_map_collection_name`** | Used during import to enable incremental multi-file imports and track URI-to-collection mappings across ontologies. |

**Ontology Lifecycle:**

```
Import/Extract → Draft → Review → Active → (Deprecated)
                    ↓
              Staging Graph → Curation → Promote to Library
```

**Composition Model:**

Organizations select which domain ontologies apply to them. A Tier 2 local ontology declares its **base ontologies** (one or more entries from the registry). The extraction agent injects only the relevant base ontologies as context.

### 5.3 Temporal Ontology Versioning (Edge-Interval Time Travel)

AOE uses **edge-interval time travel** to track the full history of every ontology concept and relationship. Both vertices and edges carry `created`/`expired` timestamp intervals, enabling point-in-time snapshots, version diffs, and the VCR timeline slider in the curation dashboard.

#### How It Works

```
  ┌──────────────────┐   subclass_of (v0)    ┌──────────────────┐
  │  ontology_classes │   created: t0         │  ontology_classes │
  │  "Vehicle" v0     │   expired: NEVER      │  "Thing" v0       │
  │  created: t0      │──────────────────────►│  created: t0      │
  │  expired: NEVER   │                       │  expired: NEVER   │
  └──────────────────┘                        └──────────────────┘

  After renaming "Vehicle" → "Transport" at time t1:

  ┌──────────────────┐                        ┌──────────────────┐
  │  "Vehicle" v0     │   (edge also expired)  │  "Thing" v0       │
  │  created: t0      │   subclass_of (v0)     │  created: t0      │
  │  expired: t1  ◄───│   created: t0          │  expired: NEVER   │
  └──────────────────┘   expired: t1           └──────────────────┘
  ┌──────────────────┐                              ▲
  │  "Transport" v1   │   subclass_of (v1)          │
  │  created: t1      │   created: t1               │
  │  expired: NEVER   │   expired: NEVER ───────────┘
  └──────────────────┘
```

When an ontology entity changes:
1. The current vertex gets its `expired` set to `now` (becomes historical).
2. A new vertex document is inserted with `created = now` and `expired = NEVER_EXPIRES`.
3. All edges pointing to/from the old vertex are expired (`expired = now`).
4. New edges are created pointing to/from the new vertex with `created = now` and `expired = NEVER_EXPIRES`.

This is simpler than the proxy pattern (no proxy collections needed) at the cost of re-creating edges on vertex changes. For ontologies — which change infrequently and have moderate edge counts — this trade-off is appropriate.

> **Advanced alternative (Phase 6):** The immutable-proxy pattern (ProxyIn/Entity/ProxyOut with `hasVersion` edges) avoids edge re-creation by routing topology through stable proxy anchors. See Phase 6 in Section 10 and the reference implementation in Section 9.8.

#### Interval Semantics

Every versioned vertex and edge carries two numeric fields:

| Field | Type | Meaning |
|-------|------|---------|
| `created` | `float` (unix timestamp) | When this version became active |
| `expired` | `float` (unix timestamp) | When this version was superseded. `NEVER_EXPIRES = sys.maxsize` (9223372036854775807) for current/active entities. |

Sentinel value for "current": `NEVER_EXPIRES = sys.maxsize` (9223372036854775807). All `created` and `expired` fields store Unix timestamps as integers/floats.

- **Current** (active) entities: `expired == NEVER_EXPIRES` (9223372036854775807)
- **UI display**: Timestamps should be rendered in human-readable format (e.g., "2026-03-28 14:30 UTC"). `NEVER_EXPIRES` should be displayed as "Current" or "Active" in the UI, never as the raw integer.
- **Historical** entities: `expired` is a finite timestamp

#### Versioned Entity Fields

Every `ontology_classes` and `ontology_properties` versioned document carries:

| Field | Type | Purpose |
|-------|------|---------|
| `created` | float | Unix timestamp when this version became active |
| `expired` | float | Unix timestamp when superseded (`NEVER_EXPIRES` for current) |
| `version` | integer | Monotonically increasing version counter |
| `created_by` | string | User or system that created this version |
| `change_type` | enum | `initial` \| `edit` \| `promote` \| `merge` \| `deprecate` |
| `change_summary` | string | Human-readable description of what changed |
| `status` | enum | `draft` → `approved` → `deprecated` |
| `ttlExpireAt` | float \| null | TTL expiration timestamp for historical versions (null for current) |

#### Versioned Edge Fields

Every ontology edge (`subclass_of`, `has_property`, `extends_domain`, etc.) carries:

| Field | Type | Purpose |
|-------|------|---------|
| `created` | float | When this edge became active |
| `expired` | float | When this edge was superseded (`NEVER_EXPIRES` for current) |
| `ttlExpireAt` | float \| null | TTL expiration for historical edges (null for current) |

#### MDI-Prefixed Indexes (Temporal Range Optimization)

Multi-dimensional indexes accelerate point-in-time queries on `[created, expired]` intervals. The `prefixFields` provide an equality-match prefix (narrowing by `ontology_id` first), and the `fields` enable multi-dimensional range queries on the temporal interval:

```json
{
  "type": "mdi-prefixed",
  "prefixFields": ["ontology_id"],
  "fields": ["created", "expired"],
  "fieldValueTypes": "double",
  "sparse": false,
  "name": "idx_ontology_classes_mdi_temporal"
}
```

This enables efficient point-in-time snapshot queries of the form:

```aql
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
    AND cls.created <= @t
    AND (cls.expired == 9223372036854775807 OR cls.expired > @t)
  RETURN cls
```

The index first narrows by `ontology_id` (equality prefix), then efficiently intersects the 2D `[created, expired]` range — avoiding full collection scans even with millions of historical versions.

Deployed on: all versioned vertex collections (`ontology_classes`, `ontology_properties`, `ontology_constraints`) **and** all ontology edge collections (`subclass_of`, `has_property`, `extends_domain`, `equivalent_class`, `related_to`, `merge_candidate`, `imports`).

#### TTL Aging for Historical Versions

Historical versions are automatically garbage-collected via TTL indexes:

| Strategy | Rule | Default TTL |
|----------|------|-------------|
| `HISTORICAL_ONLY` | Only documents with `expired != NEVER_EXPIRES` receive `ttlExpireAt` | 90 days (production), 5 min (demo) |
| Sparse TTL index | `ttlExpireAt` field, `sparse: true` — skips current documents | — |
| Excluded from TTL | `ontology_registry`, `documents`, `chunks`, `extraction_runs` | — |

#### AQL Time Travel Patterns

**Point-in-time vertex snapshot** (show ontology classes at any timestamp):
```aql
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @ontologyId
  FILTER cls.created <= @timestamp
  FILTER cls.expired > @timestamp
  RETURN cls
```

**Point-in-time graph traversal** (follow only edges that were active at the same timestamp):
```aql
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @ontologyId
  FILTER cls.created <= @timestamp AND cls.expired > @timestamp
  FOR parent, edge IN 1..10 OUTBOUND cls subclass_of
    FILTER edge.created <= @timestamp AND edge.expired > @timestamp
    FILTER parent.created <= @timestamp AND parent.expired > @timestamp
    RETURN { class: cls.label, parent: parent.label }
```

**Version history for a class** (all versions sharing the same `uri`):
```aql
FOR cls IN ontology_classes
  FILTER cls.uri == @classUri
  FILTER cls.ontology_id == @ontologyId
  SORT cls.created DESC
  RETURN {
    version: cls.version,
    label: cls.label,
    created: cls.created,
    expired: cls.expired,
    isCurrent: cls.expired == 9223372036854775807,
    change_type: cls.change_type,
    change_summary: cls.change_summary
  }
```

**Temporal diff** (what changed between two timestamps):
```aql
LET before = (
  FOR cls IN ontology_classes
    FILTER cls.ontology_id == @ontologyId
    FILTER cls.created <= @t1 AND cls.expired > @t1
    RETURN cls
)
LET after = (
  FOR cls IN ontology_classes
    FILTER cls.ontology_id == @ontologyId
    FILTER cls.created <= @t2 AND cls.expired > @t2
    RETURN cls
)
RETURN { before, after }
```

---

## 6. Core Features & Functional Requirements

### 6.1 Document Ingestion & Chunking

**Description:** Upload pipeline for PDF, DOCX, and Markdown files with semantic chunking and vector embedding.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-1.1 | Support PDF, DOCX, and Markdown upload | Each format parsed without data loss; tables and headings preserved |
| FR-1.2 | Semantic chunking that respects document structure | Chunks align with section/paragraph boundaries; no mid-sentence splits |
| FR-1.3 | Vector embeddings generated per chunk | Each chunk has a stored embedding; similarity search returns relevant chunks |
| FR-1.4 | Chunk metadata preserves provenance | Each chunk links back to source document, page number, section heading |
| FR-1.5 | Duplicate document detection | SHA-256 hash check prevents re-ingestion of identical files |
| FR-1.6 | Upload progress and status tracking | UI shows upload → parsing → chunking → embedding → ready pipeline stages |
| FR-1.7 | Multiple documents per ontology | A single ontology can be constructed from multiple source documents. The extraction run accepts a list of `doc_ids`, and all extracted concepts are tagged with the same `ontology_id`. Subsequent documents can be added to an existing ontology via "Add Document to Ontology" — triggering incremental extraction that merges new concepts into the existing ontology rather than creating a new one. |
| FR-1.8 | Add document to existing ontology | UI provides an "Add Document" action on an existing ontology in the library. This triggers extraction with the existing ontology passed as context (like Tier 2), classifying new concepts as EXISTING (already present), EXTENSION (refines existing), or NEW (novel). Results go through curation before merging into the target ontology. |
| FR-1.9 | Full CRUD on documents | Documents support: create (upload), read (metadata + chunks), update (re-upload with versioning — old version soft-deleted, new version linked), and hard-delete. Hard-delete of a document removes its chunks and marks `extracted_from` provenance edges as expired but does **not** automatically delete the ontology classes — they may have been curated, promoted, or referenced by other ontologies. A warning is displayed listing affected ontologies. |
| FR-1.10 | Document–ontology relationship is many-to-many | A document can contribute to multiple ontologies (extracted separately into each). An ontology can be built from multiple documents. The `extracted_from` edge tracks which specific document produced which class, maintaining provenance even in multi-document ontologies. |

### 6.2 Domain Ontology Extraction (Tier 1)

**Description:** LLM-driven generation of core industry ontologies from standard documents.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-2.1 | LLM output enforced via strict JSON schema mapping to OWL constructs | Output validates against Pydantic models representing `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`, `rdfs:subClassOf`, and optionally `skos:Concept` |
| FR-2.2 | Extraction schema supports OWL 2 / RDFS / SKOS constructs and constraints | `owl:Class`, `rdfs:subClassOf`, `owl:equivalentClass`, `owl:ObjectProperty`, `owl:DatatypeProperty`, OWL restrictions (`owl:Restriction`, cardinality, `owl:allValuesFrom`, `owl:someValuesFrom`), and optionally `skos:Concept`, `skos:broader`, `skos:prefLabel` for taxonomy-style ontologies. SHACL shapes (`sh:NodeShape`, `sh:PropertyShape`) are also extractable when the source document describes validation rules or data constraints (see §6.14). |
| FR-2.3 | Multi-pass extraction with self-consistency check | LLM runs N passes; only concepts appearing in ≥ M passes are included (configurable) |
| FR-2.4 | RAG-augmented extraction | LLM prompt includes relevant chunks retrieved via vector similarity for context |
| FR-2.5 | Import via ArangoRDF PGT transformation | Generated OWL/RDFS → ArangoDB via `ArangoRDF.rdf_to_arangodb_by_pgt()`, preserving OWL class hierarchy, property domains/ranges, and constraints |
| FR-2.6 | Extraction results land in staging graph | Never written directly to production; always to `staging_{run_id}` first |
| FR-2.7 | Each extracted ontology registered in library | New `ontology_registry` entry created with source metadata; all classes/properties tagged with `ontology_id` |
| FR-2.8 | Extraction results materialized into graph collections | After successful extraction, classes are written to `ontology_classes`, properties to `ontology_properties`, and edges (`has_property`, `subclass_of`, `extracted_from`) are created to form a traversable graph. The `aoe_process` graph edges (`has_chunk`, `produced_by`) are also populated to maintain the full pipeline lineage. |
| FR-2.9 | Process graph provides end-to-end lineage | The `aoe_process` named graph connects `documents` → `chunks` (via `has_chunk`), `ontology_classes` → `documents` (via `extracted_from`), `ontology_classes` → `ontology_properties` (via `has_property`), and `ontology_registry` → `extraction_runs` (via `produced_by`), enabling full provenance tracing from any ontology concept back to its source document and chunks. |
| FR-2.10 | Per-ontology graph auto-created | After extraction, a per-ontology named graph (`ontology_{name_slug}`) is automatically created with a human-readable name derived from the ontology's registry name (e.g., "Supply Chain Domain" → `ontology_supply_chain_domain`). |
| FR-2.11 | Visualizer assets auto-installed | After per-ontology graph creation, ArangoDB Visualizer customizations (theme, canvas actions, saved queries, viewpoint links) are deployed for the new graph so it is immediately explorable in the ArangoDB UI. |
| FR-2.12 | Incremental extraction into existing ontology | When a new document is added to an existing ontology (FR-1.8), the extraction pipeline runs with the existing ontology classes injected as context. The Consistency Checker compares new extractions against existing classes to avoid duplication. New classes are tagged with the same `ontology_id` and go through curation before being merged. |
| FR-2.13 | Multi-document extraction run | The extraction API accepts `doc_ids: list[str]` (multiple documents) and an optional `target_ontology_id`. Chunks from all documents are batched and processed together. All extracted concepts share the target ontology_id. |

**ArangoRDF Import Detail:**

The ArangoRDF library (`arango_rdf`) is the engine for importing ontologies into ArangoDB. The import path is:

```
Source (OWL/TTL/RDF/SKOS)
    ↓  rdflib.Graph.parse()
rdflib Graph (in-memory OWL/RDFS/SKOS)
    ↓  ArangoRDF.rdf_to_arangodb_by_pgt(name=..., uri_map_collection_name=...)
ArangoDB Collections (OWL metamodel: owl:Class → collection, predicates → edges)
    ↓  AOE post-processing
Tag all imported docs with ontology_id, create per-ontology named graph
```

| ArangoRDF Concept | AOE Usage |
|-------------------|-----------|
| `name` parameter | Per-ontology PGT graph name (e.g., `"foaf"`, `"schema_org"`) |
| `uri_map_collection_name` | Shared URI→collection map enabling incremental multi-ontology imports without collisions |
| `adb_col_statements` | Optional custom collection mapping for ontologies with unusual RDF structure |
| PGT vertex/edge collections | Shared across ontologies; AOE distinguishes via `ontology_id` field + per-ontology named graphs |

**Multi-Ontology Import Strategy:**

ArangoRDF merges all imports into shared collections distinguished by IRI namespace. Since IRI-only isolation is fragile, AOE applies a post-import tagging step:

1. Import ontology via PGT with a unique `name` per ontology
2. After import, query for all documents whose `_uri` matches the ontology's IRI prefix
3. Set `ontology_id` on each document, linking to the `ontology_registry` entry
4. Create a per-ontology named graph (`ontology_{name_slug}`, e.g., `ontology_financial_services_domain`) scoping only this ontology's vertices and edges
5. Add the ontology to the combined `domain_ontology` graph for cross-ontology queries

### 6.3 Localized Ontology Extension (Tier 2)

**Description:** Context-aware extraction from organization-specific documents that extends (not duplicates) the base Domain Ontology.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-3.1 | LLM receives existing Domain Ontology as context | Prompt includes serialized class hierarchy from Tier 1 |
| FR-3.2 | Extracted entities classified as EXISTING, EXTENSION, or NEW | LLM output tags each concept with its relationship to the domain ontology |
| FR-3.3 | Extensions linked via `extends_domain` edges | Local classes that specialize domain classes have explicit subClassOf edges |
| FR-3.4 | Organization isolation | Org A's local ontology is invisible to Org B |
| FR-3.5 | Conflict detection | System flags when a local extraction contradicts a domain class definition |

**Conflict Resolution Protocol:**

| Conflict Type | System Behavior |
|--------------|-----------------|
| Local class has same URI as domain class | Flag for review; suggest `owl:equivalentClass` or rename |
| Local property contradicts domain property range | Flag for review; domain property takes precedence unless overridden |
| Local class redefines domain class hierarchy | Block automatic promotion; require expert approval |

### 6.4 Visual Curation Dashboard (Human-in-the-Loop)

**Description:** A **standalone React/Next.js application** (within the `frontend/` module of the monorepo) that provides an interactive graph-based UI for ontology review, editing, and promotion. This is a custom-built web application — entirely separate from the ArangoDB built-in Graph Visualizer (see Section 6.6).

**Relationship to ArangoDB Graph Visualizer (6.6):**

| | Visual Curation Dashboard (this section) | ArangoDB Graph Visualizer (6.6) |
|---|---|---|
| **What** | Custom React web application | Built-in ArangoDB web UI feature |
| **Audience** | Domain experts, curators | Ontology engineers, developers |
| **Purpose** | Guided approval workflow with VCR timeline | Ad-hoc graph exploration and debugging |
| **Codebase** | `frontend/` — React 18 / Next.js 14 / TypeScript | ArangoDB server (no custom code; configured via themes, actions, queries) |
| **Graph library** | React-compatible: Cytoscape.js (`react-cytoscapejs`) or React Flow | ArangoDB's built-in D3-based renderer |
| **Deployment** | Served as a web app (separate from ArangoDB) | Accessed via ArangoDB's web console |

**React Compatibility Requirement:**

All graph visualization and UI libraries used in the curation dashboard **must be React-compatible** (i.e., provide React components or have maintained React wrappers). This includes:

| Library Category | Candidates | React Integration |
|-----------------|-----------|-------------------|
| Graph rendering | **Sigma.js** via `@react-sigma/core` (target) or **Cytoscape.js** via `react-cytoscapejs` | Both provide React component APIs |
| Graph data model | **graphology** (typed multigraph with attributes, subgraphs, algorithms) | Used by Sigma.js natively |
| Layout algorithms | `graphology-layout-forceatlas2` (GPU-accelerated), `graphology-layout-noverlap`, dagre, ELK | Computed on graphology graph, rendered by Sigma |
| Timeline slider (VCR) | Custom component using `react-slider` or `@radix-ui/react-slider` | Native React |
| Diff visualization | Built on top of the graph renderer with overlay layers | React state-driven |

**Graph Library Evolution — React Flow → Sigma.js + graphology:**

The initial v0.1.0 prototype uses React Flow for graph rendering. React Flow is a DOM-based flowchart library that is adequate for small graphs but has fundamental limitations for ontology visualization at scale:

| Concern | React Flow (current) | Sigma.js + graphology (target) |
|---------|---------------------|-------------------------------|
| Rendering engine | DOM elements (one `<div>` per node) | WebGL (GPU-accelerated canvas) |
| Scalability | Degrades > 100 nodes | Handles 100,000+ nodes smoothly |
| Layout quality | Basic dagre (tree-only) | ForceAtlas2, force-directed, circular, hierarchical, noverlap |
| Semantic zoom | Not supported | Built-in: show/hide labels, cluster by type at different zoom levels |
| Edge rendering | Simple straight/step/bezier paths | WebGL edges with bundling, curved paths, variable width/color |
| Node styling | CSS on DOM elements (slow updates) | WebGL shaders (instant batch updates) |
| Interaction | Standard DOM events | GPU-based hit detection, lasso selection, hover halos |
| Graph data model | Flat arrays of nodes + edges | `graphology` typed multigraph with rich attribute model, subgraph views, algorithms |
| React integration | Native (heavy re-renders) | `@react-sigma/core` wrapper (render once, update via graphology) |

**Target architecture:** Replace the `GraphCanvas` component (currently React Flow) with a Sigma.js-backed renderer using `@react-sigma/core` and `graphology`. The graph data model should use graphology natively throughout the application, replacing the current flat `classes[]` + `edges[]` arrays. This enables efficient subgraph operations, traversal algorithms, and layout computations without converting data structures.

**Full Ontology Editor Vision (TopBraid Composer-class):**

The ontology editor should evolve beyond a simple graph visualization into a comprehensive OWL ontology authoring environment comparable to TopBraid Composer. The target feature set includes:

| Panel | Function | Implementation |
|-------|----------|---------------|
| **Class Tree Browser** | Hierarchical class tree with search, drag-to-reparent, multi-select | Left sidebar, driven by `subclass_of` edge traversal |
| **Graph Visualization** | Interactive Sigma.js/graphology canvas showing class relationships | Center viewport with ForceAtlas2 / hierarchical layouts |
| **Property Matrix** | Tabular view of all properties across classes (domain × range) | Spreadsheet-style panel, sortable/filterable |
| **Class Form Editor** | Structured form for editing class metadata (label, URI, description, annotations) | Right sidebar, activated on class selection |
| **Restriction Editor** | Visual builder for OWL restrictions (cardinality, value, has-value, qualified) | Modal or right panel, generates `owl:Restriction` constructs |
| **SHACL Shapes Panel** | View/edit SHACL shapes for validation rules | Tabbed panel with shape graph preview |
| **Namespace Manager** | Manage ontology prefixes and namespaces | Settings dialog |
| **Import/Export Panel** | Load/save ontologies in multiple serializations (Turtle, RDF/XML, JSON-LD, N-Triples) | File menu or toolbar actions |
| **Diff/Merge View** | Side-by-side comparison of ontology versions with merge controls | Split view using temporal snapshots |
| **VCR Timeline** | Temporal slider for ontology time travel | Bottom bar with playback controls |
| **Validation Console** | Real-time OWL consistency checking and SHACL validation results | Bottom panel with error/warning list |

This evolution should be planned as a separate phase after the current extraction-focused MVP stabilizes.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-4.1 | Render staging graph as interactive React component | Nodes = classes, edges = relationships; zoom, pan, filter by type/tier. **Target renderer:** Sigma.js via `@react-sigma/core` with `graphology` data model (WebGL, scales to 100K+ nodes). Current v0.1.0 prototype uses React Flow (DOM-based, adequate for small graphs). |
| FR-4.2 | Node actions: approve, reject, rename, edit properties, merge | Each action recorded in `curation_decisions` with before/after state |
| FR-4.3 | Edge actions: approve, reject, retype, reverse direction | Edge modifications validated against ontology constraints |
| FR-4.4 | Batch operations | Select multiple nodes/edges for bulk approve/reject |
| FR-4.5 | Diff view between staging and production | Side-by-side or overlay showing what's new, changed, removed |
| FR-4.6 | Promote staging → production | One-click promotion of approved entities from staging to production graph |
| FR-4.7 | Provenance display | Clicking a node shows which document chunk(s) it was extracted from, with highlighted source text |
| FR-4.8 | Confidence scores | Each extracted entity displays LLM confidence; low-confidence entities visually highlighted |
| FR-4.9 | All visualization libraries are React-compatible | No vanilla JS graph libraries that require manual DOM manipulation; all rendering through React component tree. Sigma.js qualifies via `@react-sigma/core`. |
| FR-4.10 | Standalone ontology graph viewer/editor (not tied to extraction run) | The curation dashboard is accessible in two modes: (1) **Staging mode** (`/curation/[runId]`) for reviewing extraction results, and (2) **Ontology mode** (`/ontology/[ontologyId]/edit`) for directly viewing and editing any approved ontology in the library. Ontology mode loads all current classes, properties, and edges for the ontology, supports the same graph visualization, node/edge actions, VCR timeline, and diff view. Enables ongoing ontology management beyond initial extraction. **Long-term target:** TopBraid Composer-class editing environment with class tree browser, property matrix, restriction editor, SHACL shapes panel, namespace manager, and validation console (see "Full Ontology Editor Vision" above). |
| FR-4.11 | Direct class/property creation in the editor | In ontology mode, users can manually add new classes, properties, and edges directly in the graph editor without needing an extraction run. New entities are created with `source_type: "manual"` and go through the same temporal versioning. Useful for filling gaps LLM extraction missed. |
| FR-4.12 | Drag-and-drop reparenting | Users can drag a class node onto another class to create or change a `subclass_of` relationship. The old edge is expired and a new edge created (temporal versioning). Visual feedback shows valid drop targets. |
| FR-4.13 | Library-to-editor navigation | Clicking "Edit" on an ontology card in the library page opens the ontology graph editor. Clicking a class in the class hierarchy opens the editor scrolled/zoomed to that class. |

### 6.5 Temporal Time Travel & VCR Timeline (Ontology History)

**Description:** AOE maintains full version history of every ontology concept using edge-interval time travel (see Section 5.3). The curation dashboard includes a **VCR-style timeline slider** that enables users to scrub through ontology evolution — viewing the graph state at any point in time, playing history forward/backward, and comparing snapshots side-by-side.

**Why?** Ontologies are living artifacts. Classes get renamed, properties get added, hierarchies get restructured, merges happen, tiers get promoted. Without temporal support, these changes are destructive — the previous state is lost. With the temporal pattern, every past state is recoverable, auditable, and visualizable.

**VCR Timeline Slider (Curation Dashboard):**

The React curation dashboard renders a timeline control at the bottom of the graph viewport:

```
 ◄◄  ◄  ▶  ►►  ║▬▬▬▬▬▬▬●▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬║  2026-03-15 14:32
                     ↑
               Drag to any point in time
```

| Control | Function |
|---------|----------|
| Timeline slider | Drag to any timestamp; graph re-renders showing only entities active at that moment |
| Play forward (▶) | Animate ontology evolution forward, showing changes as they happened |
| Play backward (◄) | Reverse through history |
| Fast forward / rewind (►►/◄◄) | Jump between discrete change events (versions) |
| Speed control | Adjustable playback speed |
| Timestamp display | Current timeline position shown as human-readable datetime |
| Change event markers | Tick marks on the timeline at each version creation point |

**Temporal Operations:**

| Operation | Description | API Pattern |
|-----------|-------------|-------------|
| **Point-in-time snapshot** | Show ontology state at timestamp T | `GET /api/v1/ontology/{id}/snapshot?at={timestamp}` |
| **Version history** | List all versions of a class/property | `GET /api/v1/ontology/class/{key}/history` |
| **Temporal diff** | Compare two timestamps, showing added/removed/changed entities | `GET /api/v1/ontology/{id}/diff?t1={ts1}&t2={ts2}` |
| **Revert to version** | Create a new version that restores a historical state | `POST /api/v1/ontology/class/{key}/revert?to_version={n}` |
| **Timeline events** | List all change events for an ontology (for timeline tick marks) | `GET /api/v1/ontology/{id}/timeline` |

**VCR Visualization Modes:**

| Mode | Description |
|------|-------------|
| **Snapshot** | Static view at a single point in time — default mode |
| **Diff** | Two-pane or overlay comparison between two timestamps; added nodes in green, removed in red, changed in yellow |
| **Playback** | Animated scrub through change events; nodes/edges appear and disappear as time advances |
| **Entity Focus** | Select a single class; see its full version history as a vertical timeline with diffs between each version |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-5.1 | Edge-interval time travel on all ontology vertices and edges | All `ontology_classes`, `ontology_properties`, `ontology_constraints`, and ontology edge collections carry `created`/`expired` interval fields |
| FR-5.2 | Every ontology mutation creates a new version | Edits, promotions, merges, and deprecations produce new versioned vertex documents; old vertex gets `expired = now`; edges to/from old vertex are expired and re-created for the new vertex |
| FR-5.3 | MDI-prefixed indexes on all versioned collections | `[created, expired]` temporal range indexes on all vertex and edge collections enable efficient point-in-time queries |
| FR-5.4 | Point-in-time snapshot API | `/snapshot?at={timestamp}` returns the complete ontology graph (vertices + edges) as it existed at any past moment |
| FR-5.5 | Version history API per class/property | `/history` returns ordered list of all versions (by `uri`) with change metadata |
| FR-5.6 | Temporal diff API | `/diff?t1=&t2=` returns added, removed, and changed entities between two timestamps |
| FR-5.7 | VCR timeline slider in curation dashboard | Interactive slider with play/pause/rewind/fast-forward controls; graph re-renders on timeline position change |
| FR-5.8 | Timeline event markers | Discrete change events displayed as tick marks on the timeline; clicking a tick jumps to that version |
| FR-5.9 | Diff visualization overlay | Added entities highlighted green, removed red, changed yellow in the graph viewport |
| FR-5.10 | TTL aging for historical versions | Configurable TTL (default 90 days production, 5 min demo) with `HISTORICAL_ONLY` strategy; sparse TTL index on `ttlExpireAt` |
| FR-5.11 | Revert-to-version capability | Creating a new "current" version that restores a historical state; does not delete intermediate history |

### 6.6 ArangoDB Graph Visualizer Customization

**Description:** In addition to the custom curation dashboard (6.4, 6.5), AOE configures the **ArangoDB built-in Graph Visualizer** with ontology-specific themes, canvas actions, and saved queries. This provides Ontology Engineers with a native ArangoDB exploration interface without requiring the React frontend.

**Why both?** The curation dashboard (6.4/6.5) serves domain experts with a guided approval workflow and VCR timeline. The ArangoDB Graph Visualizer serves ontology engineers and developers who need to explore, debug, and understand ontology graphs directly in ArangoDB's web UI.

**Customization Assets:**

#### Themes (`_graphThemeStore`)

Each ontology graph gets a custom theme that visually distinguishes OWL/RDFS/SKOS node types:

| Node Type | Color | Icon | Label Field |
|-----------|-------|------|-------------|
| `owl:Class` / `Class` | Blue | `fa6-solid:shapes` | `label` or `rdfs:label` |
| `owl:ObjectProperty` | Purple | `fa6-solid:arrow-right-arrow-left` | `label` |
| `owl:DatatypeProperty` | Green | `fa6-solid:font` | `label` |
| `skos:Concept` | Teal | `fa6-solid:tag` | `skos:prefLabel` |
| `owl:Restriction` | Orange | `fa6-solid:lock` | `constraint_type` |
| `owl:Ontology` | Gold | `fa6-solid:book` | `label` |

Edge styling by relationship type:

| Edge Type | Color | Arrow |
|-----------|-------|-------|
| `rdfs:subClassOf` / `skos:broader` | Dark blue | Triangle (target) |
| `owl:equivalentClass` / `skos:exactMatch` | Green, dashed | None (bidirectional) |
| `rdfs:domain` | Gray | Triangle (target) |
| `rdfs:range` | Gray, lighter | Triangle (target) |
| `owl:imports` | Gold | Diamond (target) |

#### Canvas Actions (`_canvasActions`)

Right-click actions for ontology exploration in the Graph Visualizer:

| Action | Description | Query Pattern |
|--------|-------------|---------------|
| Expand Class Hierarchy | Show subclasses and superclasses of selected class (current edges only) | `FOR v, e IN 1..3 ANY node subclass_of FILTER e.expired == 9223372036854775807 RETURN e` |
| Show Properties | Show all properties with domain or range on selected class | `FOR v, e IN 1..1 OUTBOUND node has_property FILTER e.expired == 9223372036854775807 RETURN e` |
| Show Domain Ontology Context | Show which domain ontology classes a local class extends | `FOR v, e IN 1..1 OUTBOUND node extends_domain FILTER e.expired == 9223372036854775807 RETURN e` |
| Show Provenance | Trace selected class back to source document chunks | `FOR v, e IN 1..1 OUTBOUND node extracted_from RETURN e` |
| Show Merge Candidates | Show entity resolution suggestions for selected class | `FOR v, e IN 1..1 ANY node merge_candidate RETURN e` |
| Full Neighborhood | Expand all current relationships 1-2 hops from selected node | `FOR v, e IN 1..2 ANY node GRAPH @graphName FILTER e.expired == 9223372036854775807 RETURN e` |
| **Show Version History** | Find all versions of selected class by matching `uri` | `FOR cls IN ontology_classes FILTER cls.uri == node.uri SORT cls.created DESC RETURN cls` |

#### Saved Queries (`_queries` + `_editor_saved_queries`)

Pre-built AQL queries for common ontology operations:

| Query | Description |
|-------|-------------|
| Class Hierarchy Tree | Full `rdfs:subClassOf` tree from root classes (current edges only: `expired == NEVER_EXPIRES`) |
| Orphan Classes | Current classes with no current `subClassOf` parent and no current `has_property` edges |
| Cross-Tier Extensions | All current local classes linked to domain classes via current `extends_domain` edges |
| Recent Extractions | Classes from the most recent extraction run with confidence scores |
| Merge Candidates by Score | Entity resolution suggestions sorted by combined similarity score |
| Ontology Summary Stats | Current class/property/edge counts per ontology in the library |
| SKOS Concept Scheme | Full current `skos:broader`/`skos:narrower` hierarchy for taxonomy ontologies |
| **Point-in-Time Snapshot** | All classes active at `@timestamp` (`created <= @timestamp AND expired > @timestamp`) — parameterized for time travel |
| **Version History for Class** | All versions of a class by `uri`, sorted by `created` DESC |
| **Recently Changed Classes** | Classes with `created` in the last N days (configurable), showing what changed and who changed it |
| **Historical Versions (Expiring Soon)** | Classes approaching TTL expiration — useful for auditing before garbage collection |

#### Viewpoints and Linking

Each ontology named graph gets a programmatically created viewpoint (`_viewpoints`) with edges in `_viewpointActions` and `_viewpointQueries` linking the canvas actions and saved queries to the graph.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-6.1 | Ontology-specific theme auto-installed for each ontology graph | Theme with OWL/RDFS/SKOS node type colors and icons; `isDefault: true`; plain "Default" theme also installed |
| FR-6.2 | Canvas actions installed for ontology exploration | Right-click menu shows ontology-specific traversal actions; actions scoped to ontology collections only |
| FR-6.3 | Saved queries installed for common ontology operations | Queries appear in both the Graph Visualizer "Queries" panel and the global Query Editor |
| FR-6.4 | Viewpoint auto-created per ontology graph | `ensure_default_viewpoint()` creates viewpoint programmatically; actions and queries linked via `_viewpointActions` / `_viewpointQueries` edges |
| FR-6.5 | Visualizer assets versioned in repo | Theme, query, and action definitions stored as JSON in `docs/visualizer/` and installed via idempotent scripts |
| FR-6.6 | Assets survive database recreation | Install scripts are re-runnable; part of deployment pipeline |
| FR-6.7 | Themes pruned to actual graph collections | `prune_theme()` removes config for collections not present in the specific ontology graph |
| FR-6.8 | Temporal canvas actions and queries installed | Version history, point-in-time snapshot, and recently changed queries available in Graph Visualizer |
| FR-6.9 | Canvas actions filter by current edges | Default traversal actions include `FILTER e.expired == 9223372036854775807` to show only current graph state |
| FR-6.10 | Temporal snapshot saved query per graph | Each ontology graph has an "Ontology at Point in Time" saved query with a `@snapshot_time` bind variable (defaults to `0` = current time). Users can set a past Unix timestamp to view the ontology state at any historical moment. The query returns classes, properties, and edges alive at `@snapshot_time` using `FILTER created <= t AND (expired == NEVER_EXPIRES OR expired > t)`. Timestamps displayed in human-readable ISO 8601 format alongside raw Unix values. |
| FR-6.11 | Changes-since saved query per graph | Each ontology graph has an "Ontology Changes Since" saved query with a `@since_time` bind variable showing all classes and properties created or expired since that time — useful for reviewing diffs and audit trails. |
| FR-6.12 | ArangoDB Visualizer URL convention | Frontend links to the ArangoDB Graph Visualizer use the **Platform UI** pattern `https://{host}/ui/{database}/graphs/{graph_name}` with a fallback link to the **Database UI** pattern `https://{host}/_db/{database}/_admin/aardvark/index.html#graph/{graph_name}` for environments where the Platform UI is not installed. Both links rendered side-by-side. |

**Temporal Display Convention:** All `created` and `expired` fields store Unix timestamps (integers/floats) in the database. The UI must display these in human-readable format (e.g., ISO 8601: "2026-03-28T14:30:00Z"). The `NEVER_EXPIRES` sentinel should be displayed as "Current" or "Active", never as the raw integer. Saved AQL queries include `DATE_ISO8601(timestamp * 1000)` alongside raw values for readability. **Future enhancement:** A global "time of interest" setting so all ontology queries are automatically time-scoped.

### 6.7 Entity Resolution & Deduplication

**Description:** Automated detection and suggested merging of overlapping ontology concepts across tiers and extraction runs. Built on the **`arango-entity-resolution`** library, which already implements blocking, similarity scoring, clustering, merging, and MCP tooling for ArangoDB.

**Leveraged Library: `arango-entity-resolution`**

The library provides a config-driven pipeline (`ConfigurableERPipeline`) with pluggable strategies at each stage. AOE configures it for ontology concept matching rather than building ER from scratch.

**Blocking Stage** (candidate pair generation):

AOE uses the library's blocking strategies to narrow the search space before expensive pairwise scoring:

| Strategy | Library Class | AOE Usage |
|----------|--------------|-----------|
| **Vector ANN** | `VectorBlockingStrategy` + `ANNAdapter` | Primary: cosine similarity on class label/description embeddings via ArangoDB FAISS-based vector index (`type: "vector"`, `metric: "cosine"`). ArangoDB's vector index is powered by FAISS and supports factory strings: `IVF,Flat` (default), `IVF_HNSW,Flat` (HNSW coarse quantizer), `IVF,PQ` (product quantization). The base must be IVF. Parameters: `nLists`/`nProbe` tuned dynamically based on collection size. Index requires training data (created post-ingestion). |
| **BM25 (ArangoSearch)** | `BM25BlockingStrategy` | Secondary: text-based candidate retrieval on class labels and descriptions |
| **BM25 + Levenshtein hybrid** | `HybridBlockingStrategy` | Catches near-miss label variants (e.g., "CustomerAccount" vs "Customer_Account") |
| **Graph traversal** | `GraphTraversalBlockingStrategy` | Ontology-specific: finds classes sharing properties, parents, or domain/range patterns |
| **LSH on embeddings** | `LSHBlockingStrategy` | Scalable approximate blocking for large ontology libraries |
| **Exact composite keys** | `CollectBlockingStrategy` | Fast pre-filter on `ontology_id` + `rdf_type` to restrict comparisons within compatible entity types |

Strategy orchestration via `MultiStrategyOrchestrator` (union or intersection of candidate sets).

**Similarity Scoring Stage:**

| Technique | Library Class | AOE Configuration |
|-----------|--------------|-------------------|
| **Weighted field similarity** | `WeightedFieldSimilarity` | Jaro-Winkler on `label`, Levenshtein on `description`, Jaccard on tokenized labels |
| **Phonetic transforms** | `metaphone` transform (via `jellyfish`) | Catches phonetically similar class names (e.g., "Catalog" vs "Catalogue") |
| **Vector cosine similarity** | `ANNAdapter` | Cosine similarity on sentence-transformer embeddings (`all-MiniLM-L6-v2` or similar) |
| **Combined scoring** | `BatchSimilarityService` | Configurable per-field weights: `final_score = w1 * label_sim + w2 * desc_sim + w3 * vector_sim + w4 * topo_sim` |

Topological similarity (graph neighborhood comparison — shared properties, shared parents) is AOE-specific and layered on top of the library's scoring framework.

**Clustering Stage:**

| Algorithm | Library Class | Notes |
|-----------|--------------|-------|
| **Weakly Connected Components (WCC)** | `WCCClusteringService` | Groups similar entities into clusters; multiple backends available |
| Backend: Union-Find | `PythonUnionFindBackend` | Fast in-memory clustering |
| Backend: AQL graph | `AQLGraphBackend` | Server-side traversal of similarity edges |
| Backend: Graph Analytics Engine | `GAEWCCBackend` | For large-scale clustering |
| Backend selection | `auto` mode | Chooses backend based on edge count heuristics |

**Merging Stage:**

| Capability | Library Class | AOE Usage |
|------------|--------------|-----------|
| **Golden record creation** | `GoldenRecordService` | Field-level merge strategies: `most_complete_with_quality`, `highest_quality`, `most_frequent` |
| **Merge execution** | `merge_entities` (MCP tool) | Strategies: `most_complete`, `newest`, `first` |
| **Persistence** | `GoldenRecordPersistenceService` | Stores merged results back to ArangoDB |

**ArangoDB Collections (ER-specific):**

| Collection | Purpose |
|------------|---------|
| `similarTo` (default) or `{collection}_similarity_edges` | Edges between candidate pairs with similarity scores |
| `entity_clusters` | WCC cluster membership |
| `golden_records` | Merged/consolidated records |

**MCP Tools (from `arango-entity-resolution`):**

The library's MCP server (`arango-er-mcp`) runs as a separate process alongside AOE's own MCP server. AOE's MCP server proxies ER-specific tool calls to `arango-er-mcp`, providing a unified MCP interface to external clients. For internal use (LangGraph agents, curation dashboard), the backend calls the `arango-entity-resolution` Python API directly — the MCP layer is for external agent consumption.

| MCP Tool | Purpose |
|----------|---------|
| `find_duplicates` | Find duplicate candidates in a collection |
| `resolve_entity` | Resolve a single entity against a collection |
| `resolve_entity_cross_collection` | Cross-collection resolution (Tier 1 ↔ Tier 2 matching) |
| `explain_match` | Explain why two records are considered duplicates |
| `get_clusters` | Retrieve entity clusters |
| `merge_entities` | Execute a merge with configurable strategy |
| `recommend_resolution_strategy` | AI-assisted strategy recommendation based on data profiling |
| `estimate_feature_weights` | Estimate optimal field weights for scoring |
| `evaluate_blocking_plan` | Evaluate a blocking configuration before running |
| `profile_dataset` | Profile a collection to understand data quality and distribution |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-7.1 | Multi-strategy blocking via `arango-entity-resolution` | At least vector + BM25 blocking configured; `MultiStrategyOrchestrator` combines candidates |
| FR-7.2 | Weighted field similarity scoring | `WeightedFieldSimilarity` configured for ontology fields (label, description, uri) with Jaro-Winkler + Levenshtein + Jaccard |
| FR-7.3 | Vector cosine similarity on class embeddings | `ANNAdapter` with ArangoDB FAISS-based vector index (`type: "vector"`, cosine metric); threshold configurable (default ≥ 0.85). ArangoDB vector indexes are FAISS-powered with IVF base (supports `IVF,Flat`, `IVF_HNSW,Flat`, `IVF,PQ` factory strings). Index requires training data — created after embeddings are ingested. |
| FR-7.4 | Topological similarity scoring (AOE-specific) | Graph neighborhood comparison (shared properties, shared parents) as additional scoring dimension |
| FR-7.5 | Combined score with configurable weights | `final_score = w1 * label_sim + w2 * desc_sim + w3 * vector_sim + w4 * topo_sim`; weights tunable per domain |
| FR-7.6 | WCC clustering on similarity edges | `WCCClusteringService` groups duplicate candidates; auto backend selection |
| FR-7.7 | Merge suggestions surfaced in curation UI | Candidate pairs/clusters with scores and `explain_match` evidence displayed |
| FR-7.8 | Merge execution preserves provenance | `GoldenRecordService` creates merged entity; losing entity gets `deprecated` status with temporal `expired` timestamp; edge history preserved |
| FR-7.9 | Cross-tier resolution | `resolve_entity_cross_collection` matches local concepts against domain ontology; suggests `owl:equivalentClass` or `rdfs:subClassOf` links |
| FR-7.10 | ER pipeline configurable via `ERPipelineConfig` | Blocking strategy, similarity weights, clustering backend, and merge strategy all configurable per extraction run |
| FR-7.11 | ER MCP tools available at runtime | `arango-entity-resolution` MCP server integrated; external agents can trigger resolution and inspect results |

### 6.8 Import & Export

**Description:** Bi-directional interoperability with standard ontology formats, powered by ArangoRDF for import and rdflib for export.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-8.1 | Import OWL/TTL/RDF/SKOS files as Domain Ontologies via ArangoRDF | Standard ontologies (FOAF, Schema.org, custom OWL, SKOS taxonomies) importable via `rdf_to_arangodb_by_pgt()` with automatic `ontology_registry` entry creation and `ontology_id` tagging |
| FR-8.2 | Import multiple ontologies into the same database | Each import creates a separate `ontology_registry` entry and per-ontology named graph; shared collections use `ontology_id` for isolation |
| FR-8.3 | Ontology Library browser in UI | List all registered ontologies with stats (class count, property count, status); drill into any ontology's class hierarchy. Clicking a class shows inline detail panel with description, URI, confidence, RDF type, all properties (with range types), and a link to the ArangoDB Graph Visualizer for the per-ontology graph. |
| FR-8.4 | Ontology composition for organizations | Organizations select which domain ontologies from the library apply to them; Tier 2 extraction uses only selected base ontologies as context |
| FR-8.5 | Export ontology to OWL/TTL/SKOS | Any approved ontology graph exportable as valid OWL 2 Turtle (or SKOS if taxonomy-style) via rdflib serialization |
| FR-8.6 | Export to JSON-LD | For web/API consumption |
| FR-8.7 | Export to CSV/Excel | For non-technical stakeholders |
| FR-8.8 | Cross-ontology dependency tracking via `owl:imports` | When ontology A references classes from ontology B (via `owl:imports` or cross-namespace URIs), the dependency is recorded as an `imports` edge between their `ontology_registry` entries. The `ontology_registry` document stores an `owl_imports` list of dependent ontology URIs. |
| FR-8.9 | Ontology imports graph visualization | The `imports` edges between `ontology_registry` entries form a traversable dependency graph. This graph is queryable via AQL (`FOR v, e IN 1..N OUTBOUND reg imports ...`) and visualizable in the ArangoDB Visualizer and the frontend Ontology Library as a dependency tree. Users can see which ontologies depend on which others. |
| FR-8.10 | Upper/domain ontology selection in UI | When creating or extending an ontology, the UI provides a searchable selector showing all ontologies in the library. Users can select one or more upper/domain ontologies to serve as the base. Selected ontologies are: (a) passed as context to the extraction LLM, (b) recorded as `imports` edges, and (c) used for cross-tier entity resolution. |
| FR-8.11 | Import existing standard ontologies (FIBO, Schema.org, FOAF, etc.) | The import endpoint accepts any valid OWL/TTL/RDF/SKOS file, including large industry-standard ontologies like FIBO (Financial Industry Business Ontology), Schema.org, Dublin Core, PROV-O, etc. The ArangoRDF PGT import handles arbitrarily large ontologies. A built-in catalog of common ontology URLs (FIBO, Schema.org, FOAF, Dublin Core) is provided for one-click import from the UI. |
| FR-8.12 | Full CRUD on ontologies | Ontologies support: **Create** (via import or extraction), **Read** (library detail, class hierarchy, graph exploration), **Update** (add documents, curate classes, change metadata, re-extract), and **Delete** (deprecation with cascade analysis). |
| FR-8.13 | Ontology deletion with cascade analysis | Deleting (deprecating) an ontology requires analysis: if other ontologies import it (via `imports` edges), the system warns and requires confirmation. Deleting an ontology expires all its classes, properties, and edges (temporal deletion, not hard delete), removes the per-ontology named graph, and marks the registry entry as `deprecated`. The `domain_ontology` composite graph automatically excludes deprecated entities via `expired` filter. |
| FR-8.14 | Document deletion does not cascade to ontology | Deleting a document soft-deletes the document and its chunks. It does **not** delete ontology classes that were extracted from it — those classes may have been curated, approved, or enriched from other documents. The `extracted_from` provenance edges are expired. A warning lists which ontologies were sourced from the deleted document. |
| FR-8.15 | Ontology Library search | The library supports full-text search across ontology names, descriptions, class labels, and property labels via ArangoSearch. Results are ranked by relevance. Search works across all ontologies in the library regardless of tier or organization. |
| FR-8.16 | Ontology Library taxonomy organization | Ontologies in the library are organized hierarchically using the `imports` dependency graph as the primary structure. Domain ontologies appear as top-level entries; local extensions appear nested under their parent domain ontologies. Users can also filter by tier (domain/local), status (active/deprecated), source type (import/extraction/schema), and tags. |

### 6.8a Ontology Release Management & Revert

**Description:** Ontologies are living artifacts that evolve continuously through extraction, curation, manual editing, and entity resolution. Release management provides formal version control at the ontology level — enabling consumers to reference stable, reproducible snapshots of an ontology, and enabling engineers to revert to a prior release when problems are discovered.

**Why?** Without release management, downstream systems consuming an ontology (via export, MCP, or `owl:imports`) see a constantly moving target. A data pipeline built against "Financial Services Domain" might break when a class is renamed or deprecated. Releases provide stable reference points. Revert provides safety nets.

**Ontology Release Lifecycle:**

```
  Working Copy ──→ Release Candidate ──→ Released ──→ (Superseded)
       ↑                                     │
       └─────────── Revert ◄─────────────────┘
```

| State | Description | Editable? | Visible to consumers? |
|-------|-------------|-----------|----------------------|
| **Working** | Active ontology being edited, extracted into, curated | Yes | Only to editors/curators |
| **Release Candidate (RC)** | Frozen snapshot proposed for release; under review | No (read-only) | To reviewers only |
| **Released** | Immutable, named, versioned snapshot | No | Yes — this is what consumers reference |
| **Superseded** | A released version that has been replaced by a newer release | No | Yes (for backward compatibility) |

**Semantic Versioning for Ontologies:**

Ontology releases follow semantic versioning (`MAJOR.MINOR.PATCH`):

| Change Type | Version Bump | Examples |
|-------------|-------------|---------|
| **MAJOR** (breaking) | v1.0.0 → v2.0.0 | Class removed, class URI changed, property domain/range narrowed, required property removed |
| **MINOR** (additive) | v1.0.0 → v1.1.0 | New classes added, new properties added, new subclass relationships, description changes |
| **PATCH** (editorial) | v1.0.0 → v1.0.1 | Typo fixes in labels/descriptions, confidence recalculation, metadata updates |

**OWL Version Metadata:**

Each release carries standard OWL 2 versioning annotations:

| OWL Property | Purpose | Example |
|-------------|---------|---------|
| `owl:versionIRI` | Unique IRI for this specific version | `http://example.org/ontology/financial-services/1.2.0` |
| `owl:versionInfo` | Human-readable version string | `"1.2.0"` |
| `owl:priorVersion` | Link to previous release | `http://example.org/ontology/financial-services/1.1.0` |
| `owl:backwardCompatibleWith` | Previous version that this release is backward-compatible with | Set for MINOR/PATCH bumps |
| `owl:incompatibleWith` | Previous version that this release breaks compatibility with | Set for MAJOR bumps |

**Data Model:**

| Collection | Purpose | Key Fields |
|-----------|---------|-----------|
| `ontology_releases` | Immutable release records | `_key` (auto), `ontology_id` (FK to registry), `version` (semver string), `version_major`/`minor`/`patch` (integers for sorting), `release_status` (candidate/released/superseded), `snapshot_timestamp` (the temporal `created` cutoff), `release_notes` (markdown), `released_by` (user), `released_at` (timestamp), `class_count`, `property_count`, `edge_count`, `owl_version_iri`, `breaking_changes` (list), `created_at` |

A release is an immutable pointer to a **temporal snapshot** — it records the `snapshot_timestamp` at which the ontology state should be frozen. Querying a release means querying with `created <= snapshot_timestamp AND expired > snapshot_timestamp`, which the existing temporal infrastructure already supports.

**Breaking Change Detection:**

When creating a release, the system compares the current state against the previous release and automatically detects:

| Change Type | Detection Method | Severity |
|-------------|-----------------|----------|
| Class removed (expired) | Class in previous release not in current | MAJOR |
| Class URI changed | Same label but different URI vs. previous | MAJOR |
| Property removed from class | `has_property` edge expired, no replacement | MAJOR |
| Property range narrowed | Range type changed to a more restrictive type | MAJOR |
| New class added | Class in current not in previous | MINOR |
| New property added | New `has_property` edge | MINOR |
| New subclass relationship | New `subclass_of` edge | MINOR |
| Label or description changed | Field value differs | PATCH |
| Confidence score changed | Confidence value differs | PATCH |

The system suggests a version bump level based on detected changes and warns if the user tries to create a MINOR release with breaking changes.

**Release Workflow:**

1. **Create Release Candidate** — Ontology engineer initiates a release from the library. System:
   - Captures current `snapshot_timestamp = time.time()`
   - Runs breaking change detection against previous release
   - Suggests version number (auto-increment based on change severity)
   - Creates `ontology_releases` record with `release_status: "candidate"`
   - Ontology enters read-only mode (edits blocked until RC is released or discarded)

2. **Review Release Candidate** — Reviewers can:
   - View the frozen snapshot (same VCR timeline at the snapshot timestamp)
   - Read release notes and breaking change report
   - Approve or reject the RC

3. **Publish Release** — On approval:
   - `release_status` set to `"released"`, `released_at` set
   - Previous release (if any) set to `"superseded"`
   - OWL version metadata (`owl:versionIRI`, `owl:priorVersion`) attached
   - Ontology returns to editable (working) state
   - Export endpoint can serve a specific release version: `GET /ontology/{id}/export?version=1.2.0`

4. **Discard Release Candidate** — If RC is rejected:
   - RC record deleted or marked discarded
   - Ontology returns to editable state
   - No version published

**Revert:**

Revert creates a new release that restores the ontology to a previous state. It does NOT destructively undo changes — it uses the temporal infrastructure to create new versions that match a historical snapshot.

| Revert Scope | How It Works | Use Case |
|-------------|-------------|----------|
| **Revert ontology to release** | For each current class/property/edge: expire it. For each class/property/edge that was active at the release's `snapshot_timestamp`: create a new current version with the same data. | "Release v2.0 broke things, go back to v1.3" |
| **Revert single entity** | Expire current version. Create new version matching the entity's state at a given timestamp. Re-create connected edges. | "This class edit was wrong, undo it" |
| **Undo deprecation** | Change registry status from `deprecated` back to `active`. For each expired entity: create a new current version with the pre-deprecation data. | "We deprecated this ontology by mistake" |

**Important:** Revert is always a **forward operation** — it creates NEW temporal versions that happen to contain old data. It never modifies or deletes historical records. The VCR timeline shows: original state → changes → revert (as a new event).

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-8a.1 | Create release candidate from current ontology state | System captures snapshot timestamp, detects breaking changes, suggests version number, creates RC record. Ontology becomes read-only during RC review. |
| FR-8a.2 | Semantic versioning with auto-suggestion | Version auto-incremented based on detected change severity (MAJOR/MINOR/PATCH). User can override. Previous releases listed for comparison. |
| FR-8a.3 | Breaking change detection | System compares current state vs. previous release: removed classes, changed URIs, removed properties, narrowed ranges flagged as breaking. Report included in RC. |
| FR-8a.4 | Release approval workflow | RC can be approved or rejected. On approval: published with OWL version metadata. On rejection: discarded, ontology returns to editable. |
| FR-8a.5 | OWL version metadata on releases | Each release includes `owl:versionIRI`, `owl:versionInfo`, `owl:priorVersion`, and compatibility annotations. Exported OWL files include these annotations. |
| FR-8a.6 | Export specific release version | `GET /ontology/{id}/export?version=1.2.0` serves the ontology as it was at the release's snapshot timestamp. Default (no version param) serves the latest release or current working state. |
| FR-8a.7 | Release history and changelog | `GET /ontology/{id}/releases` returns all releases with version, date, release notes, and change summary. UI shows release timeline in library detail. |
| FR-8a.8 | Revert ontology to a previous release | `POST /ontology/{id}/revert?to_version=1.2.0` creates new current versions matching the release snapshot. All changes since that release are effectively undone (but preserved in history). Requires `ontology_engineer` role. |
| FR-8a.9 | Revert single entity to a previous version | `POST /ontology/class/{key}/revert?to_version={n}` creates a new current version matching the historical version. Connected edges re-created. |
| FR-8a.10 | Undo ontology deprecation | `POST /ontology/{id}/undeprecate` restores a deprecated ontology by creating new current versions from the pre-deprecation state. Registry status returns to `active`. Per-ontology named graph re-created. |
| FR-8a.11 | Release distribution with stable URIs | Each release is accessible via a stable URI pattern: `/ontology/{id}/releases/{version}`. Can be referenced by `owl:imports` in other ontologies. |
| FR-8a.12 | Release notes (markdown) | Engineer can write release notes (markdown) describing what changed and why. Stored on the release record. Displayed in library UI and included in exported OWL as `rdfs:comment`. |

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/ontology/{id}/releases` | Create a release candidate (captures snapshot, detects breaking changes) |
| `GET` | `/api/v1/ontology/{id}/releases` | List all releases with version, status, date, change summary |
| `GET` | `/api/v1/ontology/{id}/releases/{version}` | Get specific release details including breaking change report |
| `POST` | `/api/v1/ontology/{id}/releases/{version}/publish` | Approve and publish a release candidate |
| `DELETE` | `/api/v1/ontology/{id}/releases/{version}` | Discard a release candidate (only allowed for `candidate` status) |
| `POST` | `/api/v1/ontology/{id}/revert` | Revert ontology to a previous release version |
| `POST` | `/api/v1/ontology/{id}/undeprecate` | Restore a deprecated ontology |
| `GET` | `/api/v1/ontology/{id}/export?version={semver}` | Export a specific release version |

### 6.9 Schema Extraction from ArangoDB Databases

**Description:** Extract ontologies from existing ArangoDB database schemas using `arango-schema-mapper`. This provides a "reverse engineering" path — organizations that already have data in ArangoDB can generate ontologies from their live database structure rather than from documents.

**How it works:**

The `arango-schema-mapper` library (`arangodb-schema-analyzer`) introspects a live ArangoDB database and produces a conceptual model:

```
Live ArangoDB Database
    ↓  snapshot_physical_schema()
Physical Schema Snapshot (collections, edges, named graphs, sampled docs, indexes)
    ↓  AgenticSchemaAnalyzer (optional LLM for semantic inference)
Conceptual Model (entities, relationships, properties, mappings)
    ↓  export_conceptual_model_as_owl_turtle()
OWL/Turtle Output
    ↓  ArangoRDF PGT import (into AOE)
Ontology in the AOE Library
```

**What it extracts:**

| Database Feature | Ontology Concept |
|-----------------|------------------|
| Document collections | Classes (entities) |
| Edge collections | Object properties (relationships) |
| Document fields (sampled) | Datatype properties |
| Named graph definitions | Relationship scoping |
| Collection indexes | Constraints / key properties |
| Field value frequencies | Enumeration candidates |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-9.1 | Connect to any ArangoDB instance and extract schema | User provides connection URL + credentials; system produces physical schema snapshot |
| FR-9.2 | Optional LLM enhancement for semantic inference | Without LLM: deterministic baseline from heuristics. With LLM: semantic entity naming, relationship labeling, pattern detection |
| FR-9.3 | Schema snapshot cacheable and diffable | Physical schema fingerprinted; re-extraction only triggers on structural changes |
| FR-9.4 | Extracted conceptual model importable as ontology | OWL/Turtle export from schema-mapper feeds into AOE's ArangoRDF import pipeline |
| FR-9.5 | Schema extraction results land in staging | Same human-in-the-loop curation as document-extracted ontologies |
| FR-9.6 | Provenance tracks source database | Extracted classes link back to source database URL + collection name, not document chunks |
| FR-9.7 | Validate against tool contract v1 | Uses arango-schema-mapper's structured JSON request/response contract for integration |

**Use Cases:**

| Scenario | Value |
|----------|-------|
| Organization has existing ArangoDB data but no formal ontology | Generate ontology from their live schema, curate, and use as Tier 2 base |
| Compare extracted schema against imported industry standard | Entity resolution between schema-derived ontology and domain ontology reveals alignment gaps |
| Schema evolution tracking | Re-extract periodically; diff against previous extraction to detect schema drift |

### 6.10 MCP Server (Runtime)

**Description:** AOE exposes its ontology operations as an MCP (Model Context Protocol) server, enabling any AI agent — not just Cursor/Claude — to query ontologies, trigger extractions, and retrieve entity resolution candidates at runtime.

**Modes:**

| Mode | When | How |
|------|------|-----|
| **Development-time** | During coding in Cursor | Cursor connects to AOE MCP server; Claude can inspect live DB state, query the Domain Ontology Library, and understand the schema before writing code |
| **Runtime** | In production or integration | Any MCP-compatible AI agent connects and uses ontology tools programmatically |

**MCP Tools Exposed:**

| Tool | Description | Parameters |
|------|-------------|------------|
| `query_domain_ontology` | Search domain ontology classes by label, URI, or description | `query: str`, `limit: int` |
| `get_class_hierarchy` | Return the subClassOf tree for a given class | `class_uri: str`, `depth: int` |
| `get_class_properties` | List properties defined on a class | `class_uri: str` |
| `search_similar_classes` | Vector similarity search across classes | `text: str`, `threshold: float` |
| `get_local_ontology` | Retrieve an organization's localized ontology | `org_id: str` |
| `trigger_extraction` | Start an extraction run on a document | `doc_id: str`, `tier: str` |
| `get_extraction_status` | Check status of an extraction run | `run_id: str` |
| `get_merge_candidates` | Retrieve entity resolution suggestions | `run_id: str`, `min_score: float` |
| `get_provenance` | Trace an ontology class back to its source chunks | `class_key: str` |
| `export_ontology` | Export ontology subgraph in OWL/TTL/JSON-LD | `graph: str`, `format: str` |
| `get_ontology_snapshot` | Point-in-time snapshot of an ontology at a given timestamp | `ontology_id: str`, `at: float` |
| `get_class_history` | Full version history of a class | `class_key: str` |
| `get_ontology_diff` | Temporal diff between two timestamps | `ontology_id: str`, `t1: float`, `t2: float` |

**MCP Resources Exposed:**

| Resource URI | Description |
|-------------|-------------|
| `aoe://ontology/domain/summary` | Summary stats of the domain ontology (class count, property count, depth) |
| `aoe://ontology/local/{org_id}/summary` | Summary stats of a localized ontology |
| `aoe://extraction/runs/recent` | List of recent extraction runs with status |
| `aoe://system/health` | System health and readiness status |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-10.1 | MCP server runs as a standalone process alongside FastAPI | Can be started independently; connects to same ArangoDB instance |
| FR-10.2 | All MCP tools validate inputs and return structured errors | Invalid parameters return MCP-compliant error responses |
| FR-10.3 | MCP tools respect organization isolation | `get_local_ontology` only returns data for the authorized org |
| FR-10.4 | MCP server supports stdio and SSE transports | Works with Cursor (stdio) and remote agents (SSE) |
| FR-10.5 | Tool schemas are auto-generated from Pydantic models | Single source of truth for parameter definitions |

### 6.11 Agentic Extraction Pipeline (LangGraph)

**Description:** The extraction pipeline is orchestrated as a LangGraph stateful agent graph. Instead of a rigid sequential pipeline, agents autonomously decide extraction strategy, self-correct on errors, run entity resolution, and pre-filter low-quality results before surfacing to human curators.

**Agent Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph: Extraction Pipeline                │
│                                                                 │
│  ┌───────────┐    ┌──────────────┐    ┌───────────────────┐     │
│  │ Strategy   │───▶│ Extraction   │───▶│ Consistency       │     │
│  │ Selector   │    │ Agent        │    │ Checker           │     │
│  └───────────┘    └──────────────┘    └───────┬───────────┘     │
│       │                                       │                 │
│       │ picks model,         runs N passes,   │ filters by      │
│       │ prompt template,     self-corrects     │ agreement       │
│       │ chunk strategy       on parse errors   │ threshold       │
│       │                                       ▼                 │
│       │                              ┌───────────────────┐      │
│       │                              │ Entity Resolution │      │
│       │                              │ Agent             │      │
│       │                              └───────┬───────────┘      │
│       │                                      │                  │
│       │                   vector + topo       │ flags merges,    │
│       │                   similarity          │ auto-links       │
│       │                                      ▼ to domain tier   │
│       │                              ┌───────────────────┐      │
│       │                              │ Pre-Curation      │      │
│       │                              │ Filter Agent      │      │
│       │                              └───────┬───────────┘      │
│       │                                      │                  │
│       │                   removes noise,     │ annotates with   │
│       │                   duplicates,        │ confidence,      │
│       │                   low-confidence     │ provenance       │
│       │                                      ▼                  │
│       │                              ┌───────────────────┐      │
│       │                              │ Staging            │      │
│       │                              │ (ready for human   │      │
│       │                              │  curation)         │      │
│       │                              └───────────────────┘      │
│       │                                      │                  │
│       │         human-in-the-loop ───────────┘                  │
│       │         (curation dashboard)                            │
└───────┼─────────────────────────────────────────────────────────┘
        │
        ▼ checkpointed state (LangGraph persistence)
```

**Agents:**

| Agent | Responsibility | Inputs | Outputs |
|-------|---------------|--------|---------|
| **Strategy Selector** | Analyzes document type, length, domain; picks extraction model, prompt template, and chunking strategy | Document metadata, first N chunks | Extraction config (model, prompt, chunk params) |
| **Extraction Agent** | Runs N-pass LLM extraction with self-correction; retries on parse failures; validates output against Pydantic schemas | Chunks, extraction config, domain ontology context (for Tier 2) | Raw extracted classes + properties per pass |
| **Consistency Checker** | Compares results across passes; keeps only concepts appearing in ≥ M of N passes; assigns confidence scores | Multi-pass extraction results | Filtered, scored extraction result |
| **Entity Resolution Agent** | Invokes `arango-entity-resolution` pipeline (`ConfigurableERPipeline`) for vector + field similarity + topological scoring against existing ontologies; flags merge candidates via WCC clustering; auto-links EXTENSION classes to domain parents using `CrossCollectionMatchingService` | Filtered extraction, domain ontology, local ontology | Extraction + merge candidates + `extends_domain` edges |
| **Pre-Curation Filter** | Removes obvious noise (generic terms, duplicates within run); annotates remaining entities with provenance links and confidence tiers (high/medium/low) | Extraction + merge candidates | Clean staging graph ready for human review |

**LangGraph State Schema:**

```python
class ExtractionPipelineState(TypedDict):
    doc_id: str
    chunks: list[dict]
    extraction_config: dict            # model, prompt, chunk strategy
    pass_results: list[ExtractionResult]
    filtered_result: ExtractionResult  # after consistency check
    merge_candidates: list[dict]       # entity resolution output
    staging_entities: list[dict]       # final pre-curated output
    errors: list[str]                  # accumulated errors
    current_step: str                  # for checkpoint/resume
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-11.1 | Pipeline orchestrated as a LangGraph StateGraph | Graph definition with typed state, conditional edges, and named nodes |
| FR-11.2 | Checkpointed state for resume on failure | If extraction agent fails mid-run, pipeline resumes from last checkpoint |
| FR-11.3 | Strategy Selector adapts to document type | Different prompt templates selected for standards docs vs. technical manuals vs. policy documents |
| FR-11.4 | Extraction Agent self-corrects on parse errors | If LLM output fails Pydantic validation, agent re-prompts with the validation error (up to 3 retries) |
| FR-11.5 | Consistency Checker is configurable | N (passes) and M (agreement threshold) are configurable per extraction run |
| FR-11.6 | Entity Resolution Agent runs cross-tier matching via `arango-entity-resolution` | For Tier 2 extractions, agent uses `CrossCollectionMatchingService` and `resolve_entity_cross_collection` to compare against Tier 1 domain ontology and suggest `subClassOf`/`equivalentClass` links |
| FR-11.7 | Pre-Curation Filter reduces human review burden | At least 20% of raw LLM output filtered as noise before reaching curation dashboard |
| FR-11.8 | All agents emit structured logs with trace context | Each agent step logged with run_id, step name, duration, token usage |
| FR-11.9 | Human-in-the-loop breakpoint after pre-curation | Pipeline pauses and waits for curation decisions before final promotion |
| FR-11.10 | Pipeline observable via API | `/api/v1/extraction/runs/{run_id}` returns current agent step, progress, and any errors |

### 6.12 Pipeline Monitor Dashboard (Agentic Workflow Visualizer)

**Description:** A **React frontend module** that provides real-time visibility into the LangGraph agentic extraction pipeline, entity resolution runs, and schema extraction jobs. This is the UI backing the "Pipeline Monitor Dashboard" shown in the architecture diagram (Section 4.1) and referenced by the Organization Admin persona (Section 2.3).

**Why?** Agentic workflows are multi-step, non-deterministic, and can fail at any node. Without a visual dashboard, users are blind to what the system is doing — they submit a document and wait with no feedback. The competition provides visual agent workflow status, and AOE's own architecture already produces all the telemetry needed (WebSocket events, structured agent logs, LangGraph checkpoints). This dashboard consumes that data.

**What It Visualizes:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  Pipeline Monitor Dashboard                                         │
│                                                                     │
│  Active Runs (3)    │  Run: extract_2026-03-28_001                  │
│  ─────────────────  │  ┌─────────────────────────────────────────┐  │
│  ▶ doc_report.pdf   │  │  LangGraph Agent DAG                    │  │
│    Running (Step 3) │  │                                         │  │
│  ✓ doc_policy.docx  │  │  ┌──────────┐    ┌──────────────┐      │  │
│    Completed 2m ago │  │  │ Strategy  │───▶│ Extraction   │      │  │
│  ✗ doc_spec.md      │  │  │ Selector  │    │ Agent        │      │  │
│    Failed (retry?)  │  │  │ ✓ 12s     │    │ ▶ Pass 2/3   │      │  │
│                     │  │  └──────────┘    └──────┬───────┘      │  │
│  Recent Runs (47)   │  │                         │              │  │
│  ─────────────────  │  │                    ┌────▼─────────┐    │  │
│  ...                │  │                    │ Consistency  │    │  │
│                     │  │                    │ Checker      │    │  │
│  Filters:           │  │                    │ ○ Pending    │    │  │
│  [Status ▼]         │  │                    └──────┬───────┘    │  │
│  [Date range]       │  │                           │            │  │
│  [Org ▼]            │  │  ┌────────────┐    ┌──────▼───────┐   │  │
│                     │  │  │ Pre-Curation│◀──│ Entity Res.  │   │  │
│                     │  │  │ Filter      │    │ Agent        │   │  │
│                     │  │  │ ○ Pending   │    │ ○ Pending    │   │  │
│                     │  │  └─────┬──────┘    └──────────────┘   │  │
│                     │  │        │                               │  │
│                     │  │  ┌─────▼──────┐                       │  │
│                     │  │  │ Staging     │                       │  │
│                     │  │  │ ○ Pending   │                       │  │
│                     │  │  └────────────┘                       │  │
│                     │  │                                       │  │
│                     │  │  Run Metrics:                          │  │
│                     │  │  Duration: 1m 42s │ Tokens: 12,450    │  │
│                     │  │  Cost: $0.18      │ Entities: 34      │  │
│                     │  └─────────────────────────────────────┘  │  │
└─────────────────────────────────────────────────────────────────────┘
```

**Dashboard Panels:**

| Panel | Content | Data Source |
|-------|---------|-------------|
| **Run List** | All extraction/ER/schema runs with status badges (queued, running, completed, failed), sortable/filterable by date, org, status, type | `GET /api/v1/extraction/runs`, `GET /api/v1/er/runs`, `GET /api/v1/schema/extract/{run_id}` |
| **Agent DAG** | Visual directed graph of the LangGraph pipeline; each node shows agent name, status (pending/running/completed/failed), and elapsed time | WebSocket `ws://host/ws/extraction/{run_id}` events + `extraction_runs.stats` |
| **Node Detail** | Click an agent node to see: input/output summary, LLM prompt/response (truncated), validation errors, retry count | `GET /api/v1/extraction/runs/{run_id}` with `?detail=agent_steps` |
| **Run Metrics** | Total duration, LLM token usage (prompt + completion), estimated cost, entity counts (classes/properties extracted), pass agreement rates | `extraction_runs.stats` |
| **Error Log** | Timestamped list of errors and warnings per agent step; expandable stack traces for failures | Structured logs via `extraction_runs.stats.errors` |
| **Run Timeline** | Horizontal timeline showing when each agent step started and ended (Gantt-style) | Agent step timestamps from `extraction_runs.stats` |

**Agent Node States:**

| State | Visual | Meaning |
|-------|--------|---------|
| Pending | Gray circle (○) | Not yet reached in the pipeline |
| Running | Blue spinning indicator (▶) | Currently executing |
| Completed | Green checkmark (✓) | Finished successfully |
| Failed | Red cross (✗) | Failed; may be retryable |
| Skipped | Gray dashed circle (⊘) | Skipped due to conditional edge |
| Paused | Yellow pause (⏸) | Waiting for human input (curation breakpoint) |

**Real-Time Updates:**

The dashboard subscribes to WebSocket events per active run:

| WebSocket Event | Dashboard Action |
|----------------|------------------|
| `step_started` | Transition agent node from Pending → Running; start elapsed timer |
| `step_completed` | Transition agent node to Completed; update metrics panel |
| `step_failed` | Transition agent node to Failed; populate error log |
| `pipeline_paused` | Show Paused state on pre-curation node; prompt user to open curation dashboard |
| `completed` | All nodes green; show completion summary; link to staging graph |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-12.1 | Visual agent DAG rendered as React component | LangGraph pipeline displayed as directed graph with nodes for each agent; layout matches the pipeline definition in Section 6.11 |
| FR-12.2 | Real-time node status via WebSocket | Agent nodes transition states (pending → running → completed/failed) within 1 second of backend event emission |
| FR-12.3 | Run list with filtering | List all extraction, ER, and schema extraction runs; filter by status, date range, organization; sort by recency |
| FR-12.4 | Per-run metrics panel | Display duration, token usage, estimated LLM cost, entity counts, pass agreement rate |
| FR-12.5 | Error log with retry action | Failed runs display error details; one-click retry button triggers `POST /api/v1/extraction/runs/{run_id}/retry` |
| FR-12.6 | Agent node drill-down | Click any agent node to see input summary, output summary, LLM token counts, and validation errors for that step |
| FR-12.7 | Run timeline (Gantt chart) | Horizontal timeline showing agent step start/end times; visually reveals bottleneck steps |
| FR-12.8 | Paused pipeline notification | When pipeline reaches human-in-the-loop breakpoint, dashboard shows prominent call-to-action linking to curation dashboard for the staging graph |
| FR-12.9 | Cost tracking | Aggregate LLM cost per run (tokens × price-per-token by model); cumulative cost per organization visible to admins |
| FR-12.10 | ER and schema extraction monitoring | Same visual pattern applied to entity resolution runs and schema extraction runs (different agent DAGs, same status/metrics panels) |

**Graph Rendering:**

The agent DAG is a small, fixed-topology graph (5–6 nodes) — unlike the ontology graph which can be large. This makes React Flow the natural choice since the same library is already used in the curation dashboard:

| Aspect | Implementation |
|--------|---------------|
| Library | React Flow (already in project for curation dashboard) |
| Layout | Fixed/static layout matching the LangGraph definition; no dynamic layout needed |
| Node renderer | Custom React Flow node component with status icon, agent name, elapsed time |
| Edge renderer | Conditional edges styled differently (dashed for conditional, solid for always) |
| Interactivity | Click node → detail panel; hover → tooltip with summary |

### 6.13 Ontology Quality Metrics

**Description:** The system computes, tracks, and displays ontology quality metrics to measure extraction effectiveness, curation efficiency, and structural integrity. These metrics directly correspond to the success criteria defined in §3.2.

**Metric Categories:**

| Category | Metrics | Source Data |
|----------|---------|-------------|
| **Extraction Quality** | Precision (acceptance rate), recall (vs gold standard), multi-signal confidence | `curation_decisions`, `ontology_classes`, reference ontologies |
| **Curation Efficiency** | Throughput (concepts/hour), time-to-first-ontology | `curation_decisions` timestamps, `documents.uploaded_at`, `extraction_runs.completed_at` |
| **Deduplication Quality** | Merge suggestion accuracy (accepted vs rejected) | `curation_decisions` on merge candidates |
| **Structural Quality** | Completeness (classes with properties), coherence (cycle-free hierarchy), coverage (concepts per source chunk), orphan ratio, property richness | `ontology_classes`, `ontology_properties`, `has_property`, `subclass_of` edges |
| **Composite Quality** | Ontology Health Score (0–100) | Weighted blend of all structural and confidence metrics |

#### 6.13.1 Multi-Signal Per-Class Confidence

**Problem:** A single-signal confidence score (e.g., cross-pass agreement alone) produces identical values for all classes that clear the consistency threshold (e.g., every class shows 67%). This provides no differentiation and no actionable signal to curators.

**Solution:** Each class receives a **multi-signal confidence score** that blends seven independent quality signals into a single value:

| Signal | Weight | What it measures | Range | Source |
|--------|--------|-----------------|-------|--------|
| **Cross-pass agreement** | 0.20 | How consistently the LLM extracts this class across N passes | 0.0–1.0 | `pass_count / total_passes` from consistency checker |
| **Faithfulness (LLM-as-Judge)** | 0.20 | Whether the class is grounded in the source text vs. hallucinated or inferred beyond the evidence | 0.0–1.0 | Post-extraction LLM judge pass (see below) |
| **Semantic validity** | 0.15 | Whether the class's properties and relationships are logically consistent (domain/range correctness, no disjointness violations) | 0.0–1.0 | LLM-based semantic validation pass (see below) |
| **Structural quality** | 0.15 | Graph connectivity including hierarchy AND relationship richness | 0.0–1.0 | Differentiated scoring for object vs. datatype properties (see below) |
| **Description quality** | 0.10 | Does the class have a meaningful description? Is it distinct from other classes? | 0.0–1.0 | `min(len(description) / 100, 1.0) * 0.7 + uniqueness * 0.3` where uniqueness penalizes near-duplicate descriptions |
| **Provenance strength** | 0.10 | How many distinct source chunks support this class? More evidence = higher confidence | 0.0–1.0 | `min(supporting_chunk_count / 3, 1.0)` — 3+ chunks = full score |
| **Cross-pass property agreement** | 0.10 | How consistently the class's properties are extracted across passes | 0.0–1.0 | Jaccard similarity of property URIs across passes |

**Formula:** `confidence = 0.20 * agreement + 0.20 * faithfulness + 0.15 * semantic_validity + 0.15 * structural + 0.10 * description + 0.10 * provenance + 0.10 * property_agreement`

**Signal Details:**

**Faithfulness (LLM-as-Judge):** Replaces the naive "LLM self-reported confidence" (which is poorly calibrated — LLMs tend to be overconfident). After extraction, a separate LLM call evaluates each class against the source chunks:

```
For each extracted class, given the original source text:
1. Is this class explicitly mentioned in the text? (EXPLICIT = 1.0)
2. Is it reasonably inferred from the text? (INFERRED = 0.7)
3. Is it a reasonable domain concept but not grounded in the text? (PLAUSIBLE = 0.4)
4. Is it hallucinated / not supported? (HALLUCINATED = 0.1)
```

This is the RAG Faithfulness pattern: the judge LLM assesses grounding in source material, producing calibrated scores that differentiate well-grounded classes from speculative ones.

**Semantic Validity (LLM-based):** After extraction, a validation pass checks each class for OWL-level logical consistency:

| Check | Penalty | Example |
|-------|---------|---------|
| **Domain/range mismatch** | −0.3 | A property claims `domain: Customer, range: Temperature` — semantically nonsensical |
| **Disjointness violation** | −0.4 | A class is declared as subclass of two classes that should be disjoint |
| **Circular dependency** | −0.5 | A is subClassOf B which is subClassOf A |
| **Range type mismatch** | −0.2 | An object property points to an XSD datatype, or a datatype property points to a class |

The validation is performed by an LLM prompt that reviews the extracted class in context of its properties and relationships. Future enhancement: formal OWL reasoner (owlready2 or HermiT) for provably correct validation.

**Structural Quality (Relationship Richness):** The structural score now differentiates between hierarchy edges (vertical) and object property edges (lateral):

| Component | Contribution | Why |
|-----------|-------------|-----|
| Has datatype properties | +0.15 | Basic data modeling |
| Has object properties (relationships to other classes) | +0.30 | Lateral connections are the most valuable ontological structure |
| Has `subclass_of` parent | +0.20 | Vertical hierarchy placement |
| Has `subclass_of` children | +0.15 | Acts as a useful generalization |
| Has `related_to` or `extends_domain` edges | +0.20 | Cross-cutting relationships |

An orphan class with only datatype properties scores 0.15. A well-connected class with object properties, a parent, and lateral edges scores 0.85–1.0.

**Expected outcomes:**
- A well-grounded class appearing in all passes, faithfulness=EXPLICIT, semantically valid, with object properties and hierarchy placement: confidence ≈ 0.85–0.95
- A class from 2/3 passes, faithfulness=INFERRED, some properties but orphan: confidence ≈ 0.50–0.60
- A hallucinated class from 1 pass with domain/range mismatches: confidence ≈ 0.15–0.25

**When computed:** Multi-signal confidence is calculated in two phases:
1. **During pipeline execution** (after consistency checker): The faithfulness judge and semantic validator run as sub-steps, producing per-class scores stored alongside the extraction results.
2. **During materialization** (`_materialize_to_graph()`): Structural, description, and provenance signals are computed from the graph, and the final blended score is written to each class document.

#### 6.13.2 Composite Ontology Health Score

**Problem:** Individual quality metrics (completeness, orphan count, cycles) require expertise to interpret. A domain expert reviewing the ontology library needs a quick "is this ontology good?" signal.

**Solution:** A single **Ontology Health Score** (0–100) blending six dimensions:

| Dimension | Weight | Scoring | Example |
|-----------|--------|---------|---------|
| **Completeness** | 0.20 | `classes_with_properties / total_classes` | 4/6 classes have props → 0.67 |
| **Connectivity** | 0.20 | `classes_with_object_property_relationships / total_classes` — classes connected to other classes via `related_to` edges | 0/6 classes connected → 0.0 (flat taxonomy penalty) |
| **Coherence** | 0.15 | `1.0` if no cycles detected, `0.0` if cycles exist | Clean hierarchy → 1.0 |
| **Avg confidence** | 0.20 | Mean of multi-signal per-class confidence scores | Mean 0.72 → 0.72 |
| **Property richness** | 0.15 | `min(avg_properties_per_class / 3, 1.0)` — richer classes = better ontology | Avg 3.3 props → 1.0 |
| **Coverage** | 0.10 | `min(chunk_count / 5, 1.0)` — source chunk support | 8 chunks → 1.0 |

**Why Connectivity matters:** An ontology with only `rdfs:subClassOf` hierarchy and datatype properties (e.g., `Customer` has `name: xsd:string`) but no inter-class relationships (e.g., `Customer holds Account`) is essentially a flat taxonomy — not a true ontology. The connectivity dimension ensures that ontologies without object property relationships between classes score significantly lower.

**Formula:** `health_score = round((0.20 * completeness + 0.20 * connectivity + 0.15 * coherence + 0.20 * avg_confidence + 0.15 * property_richness + 0.10 * coverage) * 100)`

**Traffic-light display:**
- Green (≥ 70): Healthy ontology — well-structured, confident, complete
- Yellow (50–69): Needs attention — missing properties, some orphans, or low confidence
- Red (< 50): Poor quality — many orphans, incomplete, low confidence, cycles

**Where displayed:** Ontology cards in the library, quality dashboard, pipeline run metrics (for the run's target ontology).

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-13.1 | Extraction precision computed automatically | System aggregates curation decisions: `acceptance_rate = accepted / (accepted + rejected + edited)` per ontology and per extraction run. Displayed in library detail and pipeline run metrics. |
| FR-13.2 | Curation throughput tracked per session | Each curation decision records `decided_at` timestamp. System computes `concepts_per_hour` per curator session. Live counter displayed in curation dashboard header. |
| FR-13.3 | Deduplication accuracy computed from ER decisions | System tracks accepted/rejected merge suggestions. `dedup_accuracy = accepted_merges / total_merge_suggestions`. Displayed in ER dashboard and quality summary. |
| FR-13.4 | Time-to-first-ontology measured | Computed as elapsed time from `documents.uploaded_at` to `extraction_runs.completed_at`. Per-run value displayed in pipeline metrics; aggregate average in quality dashboard. |
| FR-13.5 | Gold-standard recall comparison | User can upload a reference OWL/TTL file; system computes `recall = |extracted ∩ reference| / |reference|` using fuzzy label matching. Results displayed alongside the ontology detail. |
| FR-13.6 | Structural quality analysis per ontology | System computes: (a) **Completeness** — % of classes with ≥1 property, % of properties with defined domain+range; (b) **Coherence** — cycle detection in `subclass_of` hierarchy; (c) **Orphan count** — classes with no parent and not designated as root; (d) **Avg confidence** — mean of multi-signal per-class confidence across all current classes. |
| FR-13.7 | Quality dashboard page | Dedicated `/quality` route showing aggregate metrics across all ontologies with traffic-light indicators against PRD targets (green ≥ target, yellow within 10%, red below). Trend sparklines from quality history. |
| FR-13.8 | Quality history over time | Quality metrics stored with timestamps so trends can be tracked. Leverages temporal snapshot infrastructure for historical quality snapshots. |
| FR-13.9 | Low-confidence visual highlighting in curation graph | Nodes in the curation graph canvas are color-coded by multi-signal confidence: red border < 0.5, yellow 0.5–0.7, green > 0.7. Enables curators to focus on uncertain entities first. |
| FR-13.10 | Quality-oriented ArangoDB Visualizer queries | Saved queries for: "Low Confidence Classes" (below threshold), "Orphan Classes" (no hierarchy edges), "Classes Without Properties" (incomplete definitions). |
| FR-13.11 | Multi-signal per-class confidence | Each class's `confidence` field is computed as a weighted blend of 7 signals: cross-pass agreement, LLM-as-Judge faithfulness, semantic validity, structural quality (relationship richness), description quality, provenance strength, and property agreement (see §6.13.1). |
| FR-13.12 | Composite ontology health score | Each ontology receives a 0–100 health score blending completeness, connectivity, coherence, avg confidence, property richness, and coverage (see §6.13.2). Displayed on ontology cards with traffic-light color coding. |
| FR-13.13 | Provenance strength in confidence | Per-class confidence includes a provenance strength signal based on the number of distinct source chunks supporting the class via `extracted_from` edges. |
| FR-13.14 | Connectivity metric (relationship richness) | Percentage of classes with at least one `related_to` edge connecting them to another class (inter-class object property relationship). An ontology with 0% connectivity is flagged as a flat taxonomy. Connectivity is a 20% weight in the health score. |
| FR-13.15 | Inter-class relationship extraction | Object properties extracted by the LLM with `property_type: "object"` and a class URI as `range` automatically generate `related_to` edges between domain and range classes during materialization. The extraction prompt explicitly instructs the LLM to extract inter-class relationships. |
| FR-13.16 | OntoQA/OQuaRE-aligned schema metrics | The quality system computes established ontology evaluation metrics from the OntoQA and OQuaRE frameworks, adapted for LLM-extracted ontologies. See §6.13.3. |

#### 6.13.3 OntoQA/OQuaRE-Aligned Schema Metrics

**Background:** The OntoQA framework (Tartir et al.) and OQuaRE framework (Duque-Ramos et al., based on ISO/IEC 25000 SQuaRE) define established metrics for ontology quality evaluation. AOE adapts the most relevant schema metrics for LLM-extracted ontologies, providing industry-standard quality assessment alongside AOE-specific metrics.

**Schema Metrics (per ontology):**

| Metric | OntoQA Name | Formula | What it reveals | Range |
|--------|-------------|---------|-----------------|-------|
| **Relationship Richness** | Schema: Relationship Richness | `non_subclass_edges / total_edges` | Ratio of relationship types beyond pure inheritance. An ontology relying solely on `subclass_of` scores 0.0; diverse relationships (holds, contains, produces) push toward 1.0. | 0.0–1.0 |
| **Attribute Richness** | Schema: Attribute Richness | `total_properties / total_classes` | Average properties per class. Higher = more knowledge per concept. | 0.0–∞ (typical 2–10) |
| **Inheritance Richness** | Schema: Inheritance Richness | `total_subclass_edges / classes_with_children` | Average subclasses per parent class. Indicates hierarchy breadth. High values suggest wide, shallow hierarchies; low values suggest deep, narrow ones. | 0.0–∞ |
| **Max Depth** | Structural: Depth | `max(traversal_depth(root, subclass_of))` | Deepest path from any root class to a leaf. Ontologies with depth 0–1 are flat; depth 3+ indicates meaningful specialization. | 0–∞ |
| **Annotation Completeness** | — (AOE-specific) | `classes_with_nonempty_description / total_classes` | Percentage of classes with a meaningful description (>20 chars). Incomplete annotations make ontologies harder to curate and use. | 0.0–1.0 |
| **Relationship Diversity** | — (AOE-specific) | `distinct_edge_labels / total_related_to_edges` | Number of unique relationship types (e.g., "holds", "contains", "produces"). Higher diversity = more expressive ontology. | 0–∞ |
| **Average Connectivity Degree** | — (graph theory) | `(total_subclass_edges + total_related_to_edges) / total_classes` | Average edges per class across all relationship types. Higher degree = richer graph structure. | 0.0–∞ |
| **URI Consistency** | — (AOE-specific) | `classes_in_primary_namespace / total_classes` | Percentage of classes using a consistent URI namespace. Mixed namespaces suggest poorly organized extraction or cross-contamination from multiple imports. | 0.0–1.0 |

**How these feed the health score:** The metrics above are informational (displayed in the quality panel and quality dashboard). The health score (§6.13.2) uses the derived dimensions (completeness, connectivity, coherence, confidence, property richness, coverage) which are computed from these underlying metrics.

**Comparison to established frameworks:**

| AOE Dimension | OntoQA Equivalent | OQuaRE Equivalent |
|---------------|-------------------|-------------------|
| Completeness | Attribute Richness | Functional Adequacy |
| Connectivity | Relationship Richness | Structural |
| Coherence | — (cycle detection) | Consistency |
| Confidence | — (LLM-specific) | Reliability |
| Property Richness | Attribute Richness | Functional Adequacy |
| Annotation Completeness | — | Understandability |
| Inheritance Richness | Inheritance Richness | Structural |

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/quality/{ontology_id}` | Returns all computed quality scores including health score, connectivity, and OntoQA-aligned schema metrics for an ontology |
| `GET` | `/api/v1/quality/{ontology_id}/history` | Quality metrics over time (leverages temporal snapshots) |
| `GET` | `/api/v1/quality/summary` | Aggregate quality scores across all ontologies |
| `POST` | `/api/v1/quality/recall` | Upload a reference OWL/TTL file to compute recall against extracted ontology |

### 6.14 Ontology Constraints (OWL Restrictions & SHACL Shapes)

**Description:** The system supports two complementary constraint frameworks for expressing validation rules and structural restrictions on ontology entities:

1. **OWL Restrictions** — Embedded within the ontology itself as `owl:Restriction` individuals, expressing class-level constraints like cardinality (`owl:minCardinality`, `owl:maxCardinality`, `owl:cardinality`), value restrictions (`owl:allValuesFrom`, `owl:someValuesFrom`, `owl:hasValue`), and qualified cardinality restrictions (`owl:minQualifiedCardinality`).

2. **SHACL Shapes** — External validation shapes (`sh:NodeShape`, `sh:PropertyShape`) that define data quality rules, value patterns, and structural constraints independently of the ontology itself. SHACL shapes can validate data against the ontology.

**Data Model:**

The existing `ontology_constraints` collection (§5.1) stores both OWL restrictions and SHACL shapes:

| Constraint Source | Stored As | Key Fields |
|-------------------|-----------|------------|
| OWL Restriction | `constraint_type: "owl:Restriction"` | `property_id`, `on_class`, `restriction_type` (allValuesFrom\|someValuesFrom\|minCardinality\|maxCardinality\|hasValue), `restriction_value`, `ontology_id` |
| SHACL NodeShape | `constraint_type: "sh:NodeShape"` | `target_class`, `shape_uri`, `severity` (sh:Violation\|sh:Warning\|sh:Info), `message`, `ontology_id` |
| SHACL PropertyShape | `constraint_type: "sh:PropertyShape"` | `path` (property URI), `datatype`, `min_count`, `max_count`, `pattern` (regex), `in` (allowed values), `node` (nested shape), `ontology_id` |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-14.1 | Extract OWL restrictions from source documents | LLM extraction identifies cardinality constraints, value restrictions, and type restrictions expressed in source text (e.g., "each Account must have exactly one holder") and maps them to `owl:Restriction` entries in `ontology_constraints` |
| FR-14.2 | Import OWL restrictions from OWL files | When importing an OWL file via ArangoRDF, `owl:Restriction` blank nodes are parsed and stored as `ontology_constraints` documents linked to their property and class |
| FR-14.3 | Import SHACL shapes from Turtle/TTL files | SHACL shapes graphs (separate from the ontology) can be imported and stored as `ontology_constraints`. Each shape links to its target class via `target_class` |
| FR-14.4 | Display constraints in curation UI | When viewing a class in the curation dashboard or library detail, associated constraints (OWL and SHACL) are displayed alongside properties — showing cardinality, allowed values, patterns, and severity levels |
| FR-14.5 | Export constraints in OWL and SHACL formats | OWL export includes `owl:Restriction` constructs inline. SHACL shapes can be exported as a separate shapes graph in Turtle format. |
| FR-14.6 | Constraints are temporally versioned | Like classes and properties, constraints carry `created`/`expired` timestamps and participate in temporal snapshots and time-travel queries |
| FR-14.7 | SHACL validation execution (future) | The system can validate instance data against SHACL shapes, reporting violations. *(Deferred — requires integration with a SHACL validator like pySHACL or ArangoDB's native validation)* |

**Relationship to existing data model:**

The `ontology_constraints` collection already exists in §5.1 with fields for `owl:Restriction` types. This section extends it to also cover SHACL shapes and defines the full lifecycle (extraction, import, display, export, temporal versioning).

### 6.15 Ontology Imports & Dependency Management

**Description:** Ontologies rarely exist in isolation. Real-world ontologies build on each other via `owl:imports` declarations (e.g., a Financial Services ontology imports Dublin Core for metadata properties and FIBO for financial concepts). The system must represent, track, and visualize these inter-ontology dependencies.

**Import Dependency Model:**

```
            ┌──────────────────┐
            │  FIBO Foundation  │  (Tier 1 — imported standard)
            └────────┬─────────┘
                     │ imports
        ┌────────────┼────────────┐
        ↓            ↓            ↓
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ FIBO Business │ │ Dublin   │ │ Schema.org   │  (Tier 1 — imported standards)
│ Entities     │ │ Core     │ │              │
└──────┬───────┘ └────┬─────┘ └──────┬───────┘
       │              │              │
       └──────┬───────┘              │
              ↓                      ↓
   ┌────────────────────┐    ┌──────────────┐
   │ Financial Services │    │ Supply Chain │  (Tier 1 — extracted from docs)
   │ Domain             │    │ Domain       │
   └────────┬───────────┘    └──────────────┘
            │ imports
            ↓
   ┌────────────────────┐
   │ Acme Corp Banking  │  (Tier 2 — org-specific extension)
   │ Extension          │
   └────────────────────┘
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-15.1 | `owl:imports` recorded as `imports` edges | When ontology A declares `owl:imports` of ontology B, an `imports` edge is created from A's `ontology_registry` entry to B's entry. If B is not in the library, the system warns and optionally offers to import it. |
| FR-15.2 | Import dependency graph visualizable | A dedicated view in the library page shows the imports graph — a DAG of ontology dependencies. Users can click any node to drill into that ontology. The same graph is available in the ArangoDB Visualizer. |
| FR-15.3 | Upper ontology selection in extraction UI | The upload/extraction UI provides a searchable "Base Ontologies" selector. Selected ontologies are: (a) injected as LLM context during extraction, (b) used for cross-tier entity resolution, (c) recorded as `imports` dependencies on the resulting ontology. |
| FR-15.4 | Cascade warnings on ontology deletion | When deprecating an ontology, the system traverses the `imports` graph to find all downstream dependents. A confirmation dialog lists them: "Ontology X is imported by Y, Z. Deprecating X will affect these ontologies." |
| FR-15.5 | Import resolution during OWL file import | When importing an OWL file that contains `owl:imports` declarations, the system checks if each imported ontology exists in the library. If not, it offers to: (a) auto-import from URL if the import IRI is resolvable, (b) skip and warn, or (c) block import until dependencies are satisfied. |
| FR-15.6 | Standard ontology catalog | The system provides a built-in catalog of commonly used upper ontologies with one-click import: FIBO (modular — user selects which modules), Schema.org, Dublin Core (DC Terms), FOAF, PROV-O, SKOS Core, OWL-Time, GeoSPARQL. Catalog entries include description, module count, and approximate class count. |

---

## 7. API Specification (Backend)

### 7.1 Document Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/upload` | Upload document; returns `doc_id` and starts async processing |
| `GET` | `/api/v1/documents/{doc_id}` | Get document metadata and processing status |
| `GET` | `/api/v1/documents/{doc_id}/chunks` | List chunks with optional embedding similarity search |
| `GET` | `/api/v1/documents` | List all documents (paginated, filterable by org/status) |
| `DELETE` | `/api/v1/documents/{doc_id}` | Soft-delete document and associated chunks; returns list of affected ontologies |
| `PUT` | `/api/v1/documents/{doc_id}` | Re-upload/update a document (old version soft-deleted, new version linked) |
| `GET` | `/api/v1/documents/{doc_id}/ontologies` | List ontologies that were extracted from this document |

### 7.2 Extraction Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/extraction/run` | Trigger extraction; accepts `document_id` or `doc_ids[]` and optional `target_ontology_id` for incremental extraction into an existing ontology |
| `GET` | `/api/v1/extraction/runs` | List all extraction runs (paginated, filterable by status/org/date). Each entry includes: `document_name`, `chunk_count`, `classes_extracted`, `properties_extracted`, `edge_count`, `duration_ms`, `model`, `error_count`. Resolved by joining against the `documents` collection and `stats` on the run document. |
| `GET` | `/api/v1/extraction/runs/{run_id}` | Get extraction run status, current agent step, and summary stats |
| `GET` | `/api/v1/extraction/runs/{run_id}/steps` | Get per-agent-step detail: inputs, outputs, token usage, errors, duration |
| `GET` | `/api/v1/extraction/runs/{run_id}/results` | Get extracted entities from a run |
| `POST` | `/api/v1/extraction/runs/{run_id}/retry` | Retry a failed extraction run |
| `DELETE` | `/api/v1/extraction/runs/{run_id}` | Delete an extraction run and its associated `results_*` document. Does **not** delete the ontology or its classes — those are managed via the ontology lifecycle. Returns `{ deleted: true, run_id }`. |
| `GET` | `/api/v1/extraction/runs/{run_id}/cost` | Get LLM cost breakdown: tokens by model, estimated cost |

### 7.2.1 System Administration Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/admin/reset` | **Development/demo only.** Purges all extracted data: truncates `ontology_classes`, `ontology_properties`, `ontology_constraints`, all edge collections (`subclass_of`, `has_property`, `has_constraint`, `extracted_from`, `extends_domain`, `related_to`, `imports`, `has_chunk`, `produced_by`), `extraction_runs`, `ontology_registry`, `curation_decisions`, `quality_history`. Removes all per-ontology named graphs (`ontology_*`). Preserves `documents` and `chunks` so re-extraction can be triggered without re-upload. Preserves ArangoDB Visualizer configuration assets (`_graphThemeStore`, `_editor_saved_queries`, `_canvasActions`, `_viewpoints`). Requires `ALLOW_SYSTEM_RESET=true` in environment. Returns `{ reset: true, collections_truncated: [...], graphs_removed: [...] }`. |
| `POST` | `/api/v1/admin/reset/full` | **Development/demo only.** Full purge: same as soft reset plus documents and chunks. Removes all per-ontology named graphs. Requires `ALLOW_SYSTEM_RESET=true`. |

**Deletion Context Summary:**

| Context | Method | Scope | History Preserved? | Use Case |
|---------|--------|-------|-------------------|----------|
| **Ontology lifecycle deletion** (FR-8.13) | Temporal soft-delete | Expire classes, properties, edges; deprecate registry entry | **Yes** — VCR timeline shows historical state | Normal ontology management |
| **Document deletion** (FR-1.9) | Hard-delete doc + chunks; expire provenance edges | Document and chunks removed; ontology classes preserved | **Partial** — classes survive, provenance edges expired | Removing a source document |
| **System reset** (§7.2.1) | Hard-delete (truncate) | All ontology data wiped; optionally documents too | **No** — fresh start, no history | Development/demo restart |

### 7.3 Ontology Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ontology/domain` | Get full domain ontology graph (paginated) |
| `GET` | `/api/v1/ontology/domain/classes` | List domain classes with filters |
| `GET` | `/api/v1/ontology/local/{org_id}` | Get organization's local ontology |
| `GET` | `/api/v1/ontology/staging/{run_id}` | Get staging graph for curation — returns `{ run_id, ontology_id, classes[], properties[], edges[] }` by resolving the ontology from the extraction run |
| `POST` | `/api/v1/ontology/staging/{run_id}/promote` | Promote approved staging entities to production |
| `GET` | `/api/v1/ontology/export` | Export ontology in OWL/TTL/JSON-LD format |
| `POST` | `/api/v1/ontology/import` | Import external ontology file (OWL/TTL/RDF) via ArangoRDF |
| `GET` | `/api/v1/ontology/library` | List all ontologies in the registry |
| `GET` | `/api/v1/ontology/library/{ontology_id}` | Get ontology detail (classes, properties, stats) |
| `PUT` | `/api/v1/ontology/library/{ontology_id}` | Update ontology metadata (name, description, tags, status) |
| `DELETE` | `/api/v1/ontology/library/{ontology_id}` | Deprecate an ontology — returns cascade analysis (dependent ontologies, affected orgs) |
| `GET` | `/api/v1/ontology/library/{ontology_id}/imports` | List ontologies this ontology imports (outbound `imports` edges) |
| `GET` | `/api/v1/ontology/library/{ontology_id}/imported-by` | List ontologies that import this one (inbound `imports` edges) |
| `POST` | `/api/v1/ontology/library/{ontology_id}/add-document` | Add a document to an existing ontology — triggers incremental extraction |
| `GET` | `/api/v1/ontology/library/{ontology_id}/documents` | List all source documents for this ontology (via `extracted_from` edges) |
| `GET` | `/api/v1/ontology/library/{ontology_id}/constraints` | List all constraints (OWL restrictions + SHACL shapes) for this ontology |
| `GET` | `/api/v1/ontology/imports-graph` | Get the full ontology imports dependency graph (all `imports` edges) |
| `GET` | `/api/v1/ontology/catalog` | List available standard ontologies for one-click import (FIBO, Schema.org, etc.) |
| `POST` | `/api/v1/ontology/catalog/{catalog_id}/import` | Import a standard ontology from the catalog |
| `GET` | `/api/v1/ontology/search` | Full-text search across ontology names, descriptions, class labels, property labels |
| `GET` | `/api/v1/ontology/graphs` | List all named graphs (system graphs + per-ontology graphs) |
| `GET` | `/api/v1/ontology/{ontology_id}/classes` | List all current classes for a specific ontology |
| `GET` | `/api/v1/ontology/{ontology_id}/properties` | List properties, with optional `?keys=` CSV filter |
| `GET` | `/api/v1/ontology/{ontology_id}/edges` | List all current edges (subclass_of, has_property, related_to, etc.) with `edge_type` field |
| `GET` | `/api/v1/ontology/{ontology_id}/snapshot` | Point-in-time snapshot — query param `at={unix_timestamp}` returns ontology state at that moment |
| `GET` | `/api/v1/ontology/{ontology_id}/timeline` | List all discrete change events (version creations) for timeline tick marks |
| `GET` | `/api/v1/ontology/{ontology_id}/diff` | Temporal diff — query params `t1={ts}&t2={ts}` returns added/removed/changed entities |
| `GET` | `/api/v1/ontology/class/{class_key}/history` | Full version history of a specific class (all versions with change metadata) |
| `POST` | `/api/v1/ontology/class/{class_key}/revert` | Revert a class to a previous version — creates a new current version restoring historical state |
| `POST` | `/api/v1/schema/extract` | Trigger schema extraction from an external ArangoDB instance |
| `GET` | `/api/v1/schema/extract/{run_id}` | Get schema extraction run status |

### 7.4 Curation Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/curation/decide` | Record curation decision (approve/reject/merge/edit) |
| `GET` | `/api/v1/curation/decisions` | List curation decisions (audit trail) |
| `POST` | `/api/v1/curation/merge` | Execute a merge between two entities |

### 7.5 Entity Resolution Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/er/run` | Trigger entity resolution pipeline on a collection or extraction run |
| `GET` | `/api/v1/er/runs/{run_id}` | Get ER run status (blocking → scoring → clustering → complete) |
| `GET` | `/api/v1/er/runs/{run_id}/candidates` | Get merge candidates with scores and explanation evidence |
| `GET` | `/api/v1/er/runs/{run_id}/clusters` | Get WCC entity clusters |
| `POST` | `/api/v1/er/explain` | Explain why two specific entities are considered duplicates |
| `POST` | `/api/v1/er/cross-tier` | Trigger cross-tier resolution (local vs. domain ontology) |
| `PUT` | `/api/v1/er/config` | Update ER pipeline config (blocking strategy, similarity weights, thresholds) |
| `GET` | `/api/v1/er/config` | Get current ER pipeline config |

### 7.6 Organization & User Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/orgs` | List organizations (admin only) |
| `POST` | `/api/v1/orgs` | Create organization |
| `GET` | `/api/v1/orgs/{org_id}` | Get organization details and settings |
| `PUT` | `/api/v1/orgs/{org_id}` | Update organization settings (selected base ontologies, ER config) |
| `GET` | `/api/v1/orgs/{org_id}/users` | List users in organization |
| `POST` | `/api/v1/orgs/{org_id}/users` | Add user to organization with role |
| `PUT` | `/api/v1/orgs/{org_id}/users/{user_id}` | Update user role |
| `DELETE` | `/api/v1/orgs/{org_id}/users/{user_id}` | Remove user from organization |

### 7.7 System Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness probe (DB connected, models loaded) |
| `GET` | `/api/v1/stats` | System statistics (documents, classes, properties, runs) |

### 7.7a Quality Metrics Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/quality/{ontology_id}` | All computed quality scores for an ontology (acceptance rate, structural quality, avg confidence, etc.) |
| `GET` | `/api/v1/quality/{ontology_id}/history` | Quality metrics over time |
| `GET` | `/api/v1/quality/summary` | Aggregate quality scores across all ontologies |
| `POST` | `/api/v1/quality/recall` | Upload reference OWL/TTL file; compute recall against extracted ontology |

### 7.8 API Conventions

**Pagination:**

All list endpoints support cursor-based pagination via query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 25 | Maximum items per page (max 100) |
| `cursor` | string | null | Opaque cursor from previous response for next page |
| `sort` | string | varies | Sort field (e.g., `created_at`, `label`) |
| `order` | enum | `asc` | Sort direction: `asc` or `desc` |

Response envelope for paginated endpoints:

```json
{
  "data": [...],
  "cursor": "eyJrZXkiOiAiYWJjMTIzIn0=",
  "has_more": true,
  "total_count": 142
}
```

**Error Response Format:**

All errors follow a consistent schema:

```json
{
  "error": {
    "code": "ENTITY_NOT_FOUND",
    "message": "Ontology class with key 'abc123' not found",
    "details": { "class_key": "abc123", "collection": "ontology_classes" },
    "request_id": "req_8f3a2b1c"
  }
}
```

| HTTP Status | Error Code Pattern | When |
|-------------|-------------------|------|
| 400 | `VALIDATION_ERROR` | Request body fails Pydantic validation |
| 401 | `UNAUTHORIZED` | Missing or invalid authentication |
| 403 | `FORBIDDEN` | Valid auth but insufficient permissions / org isolation violation |
| 404 | `ENTITY_NOT_FOUND` | Requested resource does not exist |
| 409 | `CONFLICT` | Duplicate document upload, concurrent edit conflict |
| 422 | `EXTRACTION_FAILED` | LLM extraction failed after retries |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Unhandled server error |

**Rate Limiting:**

| Scope | Limit | Window |
|-------|-------|--------|
| API (per org) | 1000 requests | per minute |
| Extraction triggers (per org) | 10 concurrent | — |
| MCP tools (per client) | 100 requests | per minute |
| Document uploads (per org) | 50 files | per hour |

**WebSocket Events:**

The architecture supports WebSocket connections for real-time updates on long-running operations:

| Event Channel | Events | Purpose |
|---------------|--------|---------|
| `ws://host/ws/extraction/{run_id}` | `step_started`, `step_completed`, `error`, `completed` | Real-time extraction pipeline progress |
| `ws://host/ws/curation/{session_id}` | `decision_made`, `entity_updated`, `merge_executed` | Collaborative curation notifications |
| `ws://host/ws/er/{run_id}` | `blocking_complete`, `scoring_progress`, `clustering_complete` | ER pipeline progress |

Clients that don't support WebSocket can poll the corresponding `GET` status endpoints instead.

### 7.8 Frontend Pages (Next.js Routes)

| Route | Page | Description |
|-------|------|-------------|
| `/` | Landing / Dashboard | Backend health status, ontology count, quick links to Upload/Library/Pipeline |
| `/upload` | Document Upload | Drag-and-drop file upload (PDF, DOCX, Markdown), recent documents list with status and chunk counts. Option to target an existing ontology or create new. Searchable "Base Ontologies" selector to choose upper/domain ontologies as extraction context. Import from standard ontology catalog (FIBO, Schema.org, etc.). |
| `/library` | Ontology Library | Browse registered ontologies with full-text search; filter by tier, status, source type; view imports dependency graph; click an ontology card to view its class hierarchy with inline class detail (properties, constraints, description, confidence, link to ArangoDB Visualizer). "Add Document" action to extend ontology with new source material. |
| `/pipeline` | Pipeline Monitor | List extraction runs, view agent DAG, metrics, errors, timeline; "Curate" button links to curation page |
| `/curation/[runId]` | Visual Curation (Staging Mode) | Interactive graph canvas showing staging graph for an extraction run, with node/edge selection, approve/reject actions, batch operations, VCR timeline, diff view, and promote panel |
| `/ontology/[ontologyId]/edit` | Ontology Graph Editor (Ontology Mode) | Full graph editor for an approved ontology — same graph canvas, VCR timeline, and node/edge actions as curation, plus direct class/property creation, drag-and-drop reparenting, and ongoing editing without requiring an extraction run. Accessible from the library page. |
| `/entity-resolution` | Entity Resolution | Run and review ER pipelines, view merge candidates and clusters |
| `/login` | Login | Authentication page; renders login form (or redirects to OIDC provider). Bypassed when `NEXT_PUBLIC_DEV_MODE=true`. |
| `/quality` | Quality Dashboard | Aggregate ontology quality metrics (extraction precision, curation throughput, structural quality) with traffic-light indicators and trend sparklines (Section 6.13). |

---

## 8. Non-Functional Requirements

### 8.1 Performance

| Requirement | Target |
|-------------|--------|
| Document upload + chunking | < 60 seconds for a 100-page PDF |
| Extraction pipeline (per document) | < 5 minutes for a 50-chunk document |
| Curation UI graph render | < 2 seconds for graphs up to 500 nodes |
| API response time (read) | p95 < 200ms |
| API response time (write) | p95 < 500ms |
| Concurrent extraction pipelines | Support ≥ 5 parallel extraction runs |

### 8.2 Scalability

| Dimension | Requirement |
|-----------|-------------|
| Documents per organization | ≥ 10,000 |
| Ontology classes (domain-wide) | ≥ 50,000 |
| Concurrent users (curation UI) | ≥ 20 |
| Organizations (multi-tenant) | ≥ 100 |

### 8.3 Security

| Requirement | Implementation |
|-------------|---------------|
| Authentication | OAuth 2.0 / OIDC (e.g., Auth0, Keycloak) |
| Authorization | RBAC: `admin`, `ontology_engineer`, `domain_expert`, `viewer` |
| Organization isolation | All queries filtered by `org_id`; ArangoDB collection-level access where possible |
| Secrets management | Environment variables or secret manager (no secrets in code/config) |
| Input validation | All API inputs validated via Pydantic; file uploads scanned for type |
| Audit logging | All curation decisions, promotions, and deletions logged with user + timestamp |
| Data encryption | TLS in transit; ArangoDB encryption at rest |

### 8.4 Reliability

| Requirement | Target |
|-------------|--------|
| Uptime (API) | 99.5% |
| Data durability | ArangoDB replication factor ≥ 2 |
| Pipeline failure recovery | Failed extraction runs retryable; partial results preserved |
| Backup frequency | Daily automated backups with 30-day retention |

### 8.5 Observability

| Component | Tool / Approach |
|-----------|----------------|
| Structured logging | Python `structlog` with JSON output |
| Metrics | Prometheus-compatible (request latency, extraction throughput, queue depth) |
| Tracing | OpenTelemetry spans across ingestion → extraction → storage |
| Alerting | Alerts on: extraction failure rate > 10%, API error rate > 1%, queue backlog > 100 |
| Health checks | `/health` and `/ready` endpoints |

### 8.6 Deployment & Infrastructure

#### ArangoDB Deployment Modes

AOE supports three ArangoDB deployment targets, controlled by the `TEST_DEPLOYMENT_MODE` environment variable. The application adapts its connection strategy, feature flags, and algorithm selection based on the active mode:

| Mode | `TEST_DEPLOYMENT_MODE` | ArangoDB Topology | Key Differences |
|------|----------------------|-------------------|-----------------|
| **Local Docker** | `local_docker` | Single server in Docker | No GAE, no SmartGraphs, no SatelliteCollections, no SSL; auto-creates database via `_system` access; WCC clustering uses in-memory Python Union-Find |
| **Self-Managed Platform** | `self_managed_platform` | Remote ArangoDB cluster (Enterprise) | GAE enabled, SmartGraphs, SatelliteCollections available; SSL/TLS; full cluster capabilities; WCC clustering uses GAE backend; auto-creates database via `_system` access |
| **Managed Platform (AMP)** | `managed_platform` | ArangoDB Managed Platform | GAE enabled; API key authentication for Graph API; database must be pre-provisioned (no `_system` access); SSL required. **Not yet available — requires ArangoDB 4.0 release** |

**Feature availability by mode:**

| Feature | `local_docker` | `self_managed_platform` | `managed_platform` |
|---------|:-:|:-:|:-:|
| Graph Analytics Engine (GAE) | — | Yes | Yes |
| SmartGraphs / EnterpriseGraphs | — | Yes | Yes |
| SatelliteCollections | — | Yes | Yes |
| Auto-create database | Yes | Yes | — |
| WCC backend | Python Union-Find | GAE | GAE |
| SSL/TLS | Optional | Required | Required |
| Auth method | Username/password | Username/password | API key + username/password |

**How it works in code:**

The `Settings` class (Pydantic) reads `TEST_DEPLOYMENT_MODE` and exposes derived properties (`is_local`, `is_cluster`, `has_gae`, `can_create_databases`, `wcc_backend_preference`, etc.) that downstream code uses to branch behavior — no feature-flag `if/else` scattered across the codebase.

The `effective_arango_host` property resolves the correct endpoint:
- `local_docker` → `ARANGO_HOST` (e.g., `http://localhost:8530`)
- `self_managed_platform` / `managed_platform` → `ARANGO_ENDPOINT` (e.g., `https://cluster-host:8529`)

#### Environments

| Environment | Infrastructure | Notes |
|-------------|---------------|-------|
| **Local dev** | Docker Compose (ArangoDB, Redis); FastAPI via `uvicorn --reload`; Next.js `next dev` | `TEST_DEPLOYMENT_MODE=local_docker`; single `make dev` starts everything |
| **CI** | Docker Compose test profile (ephemeral ArangoDB + Redis); GitHub Actions or equivalent | `TEST_DEPLOYMENT_MODE=local_docker`; disposable databases per test run |
| **Staging** | Docker Compose or Kubernetes (single-node); shared ArangoDB instance | `TEST_DEPLOYMENT_MODE=self_managed_platform`; mirrors production config; used for E2E and integration testing |
| **Production** | Kubernetes (recommended) or Docker Compose on a VM | `TEST_DEPLOYMENT_MODE=self_managed_platform` (or `managed_platform` post-4.0); ArangoDB cluster (replication factor ≥ 2); Redis Sentinel; TLS termination |

**Container Images:**

| Image | Base | Size Target |
|-------|------|-------------|
| `aoe-backend` | `python:3.11-slim` | < 500 MB |
| `aoe-frontend` | `node:20-alpine` (build) + `nginx:alpine` (serve) | < 100 MB |
| `aoe-mcp-server` | `python:3.11-slim` | < 400 MB |

**CI/CD Pipeline:**

```
Push → Lint & Type Check → Unit Tests → Build Images → Integration Tests (Docker Compose) → E2E Tests → Deploy to Staging → Manual Gate → Deploy to Production
```

| Stage | Trigger | Gate |
|-------|---------|------|
| Lint + Type Check | Every push | Zero errors |
| Unit Tests + Coverage | Every push | Coverage thresholds met |
| Integration Tests | Every push to `main` or PR | All pass |
| E2E Tests | Pre-deploy to staging | All pass |
| Staging deploy | Merge to `main` | Automated |
| Production deploy | Manual approval after staging validation | Release tag |

**Infrastructure Requirements:**

| Resource | Minimum (Dev) | Recommended (Production) |
|----------|---------------|--------------------------|
| ArangoDB | 2 GB RAM, 10 GB disk | 8 GB RAM, 100 GB SSD, 3-node cluster |
| Redis | 256 MB RAM | 1 GB RAM, Sentinel for HA |
| Backend | 1 GB RAM, 2 vCPU | 4 GB RAM, 4 vCPU, 2+ replicas |
| Frontend | 256 MB RAM (static serve) | CDN-backed static hosting |
| LLM API access | API keys for Claude / GPT-4o | Rate-limited API keys; cost monitoring |

### 8.7 Data Migration & Schema Evolution

Ontology schema evolution is inevitable as the PRD is refined and new features are added. The following strategy ensures safe, auditable migrations:

| Principle | Implementation |
|-----------|---------------|
| **Forward-only migrations** | Each schema change is a numbered migration script (e.g., `001_add_constraints_collection.py`); no destructive rollbacks |
| **Idempotent scripts** | All migration scripts check "does this collection/index already exist?" before creating; safe to re-run |
| **Versioned schema** | A `_schema_version` document in a `_system_meta` collection tracks the current schema version |
| **Pre-migration backup** | Automated backup before any production migration; restore tested before proceeding |
| **Collection-safe additions** | New collections and indexes are added without modifying existing documents (ArangoDB is schema-free for documents) |
| **Field additions** | New fields on existing documents use default values; old documents are lazily migrated on read or batch-updated |
| **Edge collection changes** | New edge types are added as new collections; existing edges are never renamed or restructured in place |
| **Temporal data preservation** | Historical versioned documents are never modified by migrations; only new document shapes apply to new versions |

**Migration Directory Structure:**

```
backend/
├── migrations/
│   ├── 001_initial_schema.py      # Collections, edges, named graphs
│   ├── 002_add_mdi_indexes.py     # MDI-prefixed temporal indexes
│   ├── 003_add_ttl_indexes.py     # TTL aging indexes
│   ├── 004_add_er_collections.py  # Entity resolution collections
│   └── runner.py                  # Applies pending migrations in order
```

### 8.8 Notification & Event Strategy

Long-running operations (extraction, entity resolution) and curation workflows require proactive notifications so users are not left polling manually.

| Event | Channel | Recipient |
|-------|---------|-----------|
| Extraction run completed | WebSocket push + in-app notification | User who triggered the extraction |
| Extraction run failed | WebSocket push + in-app notification + email (configurable) | User who triggered the extraction; org admins |
| Staging graph ready for review | In-app notification + optional email digest | Domain experts in the organization |
| Curation decision made | WebSocket push to curation session | Other curators viewing the same staging graph |
| Merge candidate clusters found | In-app notification | Domain experts; ontology engineers |
| Ontology promoted to production | In-app notification + audit log event | All org users with `domain_expert` or `ontology_engineer` role |
| TTL aging — historical versions approaching expiration | In-app alert (configurable) | Ontology engineers |
| Schema extraction completed | In-app notification | User who triggered schema extraction |

**Implementation:**

| Component | Technology |
|-----------|-----------|
| WebSocket server | FastAPI WebSocket endpoints (see Section 7.8) |
| In-app notifications | Backend writes to a `notifications` collection; frontend polls or subscribes via WebSocket |
| Email notifications | Optional integration with SMTP or transactional email service (SendGrid, SES); configurable per org |
| Event bus (internal) | Redis Pub/Sub for decoupled event emission between services (extraction service → notification service) |

### 8.9 Testing & Code Quality

**Philosophy:** Every feature must ship with tests. Untested code is unfinished code. The test suite must provide confidence that ontology extraction, curation, temporal versioning, entity resolution, and API contracts all work correctly — both in isolation and end-to-end.

#### Coverage Targets

| Scope | Minimum Coverage | Measured By |
|-------|-----------------|-------------|
| Backend (Python) overall | ≥ 80% line coverage | `pytest-cov` |
| Core services (`services/`, `extraction/`, `db/`) | ≥ 90% line coverage | `pytest-cov` with `--cov-fail-under` |
| API routes (`api/`) | ≥ 85% line coverage | `pytest-cov` |
| Frontend (React) overall | ≥ 70% line coverage | Jest + `--coverage` |
| Frontend graph components | ≥ 75% line coverage | Jest + React Testing Library |
| CI gate | Build fails if coverage drops below thresholds | CI pipeline enforced |

#### Test Pyramid

```
          ┌─────────────┐
          │   E2E Tests  │  ← Few, slow, high confidence
          │  (Playwright) │
          ├──────────────┤
          │ Integration   │  ← Moderate count, real DB
          │ Tests         │
          ├──────────────┤
          │  Unit Tests   │  ← Many, fast, mocked deps
          │               │
          └──────────────┘
```

#### Backend Testing (Python / pytest)

**Unit Tests** — fast, isolated, mocked dependencies:

| Area | What to Test | Mocking Strategy |
|------|-------------|-----------------|
| Pydantic models | Serialization, validation, edge cases | No mocks needed — pure data |
| Extraction prompts & parsers | LLM output parsing, JSON schema validation, error recovery | Mock LLM responses with fixture JSON files |
| Temporal versioning logic | Version creation, `expired` field updates, edge re-creation, `NEVER_EXPIRES` sentinel for current entities | Mock ArangoDB client (`python-arango` calls) |
| Entity resolution config | `ERPipelineConfig` construction, weight calculations, strategy selection | Mock `arango-entity-resolution` service calls |
| Service layer (`services/`) | Business logic for curation, promotion, import/export | Mock DB repository layer |
| Config & settings | `.env` parsing, defaults, validation | Override `Settings` with test values |

**Integration Tests** — real ArangoDB instance (Docker):

| Area | What to Test | Infrastructure |
|------|-------------|---------------|
| DB repository layer | CRUD operations on all collections, edge creation/deletion | Dedicated test database (auto-created, auto-dropped) |
| Temporal queries | Point-in-time snapshots, version history, temporal diffs, TTL behavior | Test database with seeded temporal data |
| ArangoRDF import | PGT transformation of OWL/TTL files into ontology collections | Test database + sample OWL files from `aws_ontology` |
| Entity resolution pipeline | Full blocking → scoring → clustering → merge flow | Test database + pre-loaded candidate pairs |
| Schema extraction | `arango-schema-mapper` against a test database | Separate source database with known schema |
| Named graph operations | Graph creation, traversal, staging → production promotion | Test database with named graphs |
| API endpoints | Full request → response cycle via `httpx.AsyncClient` (TestClient) | FastAPI `TestClient` + test database |

**Integration Test Database Management:**

```python
@pytest.fixture(scope="session")
def test_db():
    """Create a fresh test database, yield it, drop it after."""
    client = ArangoClient(hosts="http://localhost:8530")
    sys_db = client.db("_system", username="root", password="test")
    db_name = f"aoe_test_{uuid4().hex[:8]}"
    sys_db.create_database(db_name)
    db = client.db(db_name, username="root", password="test")
    init_schema(db)  # Create all collections, edges, indexes
    yield db
    sys_db.delete_database(db_name)
    client.close()
```

**Mock Strategy:**

| Dependency | Mock Approach |
|------------|--------------|
| ArangoDB | `unittest.mock.patch` on `app.db.client.get_db` for unit tests; real Docker instance for integration |
| LLM providers (Claude, GPT-4o) | Recorded response fixtures in `tests/fixtures/llm_responses/`; `unittest.mock.patch` on LangChain calls |
| Redis / Celery | `fakeredis` for unit tests; real Redis container for integration |
| External ArangoDB (schema extraction) | Dedicated test instance with seeded data |
| Embedding models | Pre-computed embeddings in fixture files; mock `EmbeddingService` |
| `arango-entity-resolution` | Mock at service boundary for unit tests; real library for integration |

**Backend Test Directory Structure:**

```
backend/tests/
├── conftest.py                    # Shared fixtures (test_db, mock_settings, etc.)
├── fixtures/
│   ├── llm_responses/             # Recorded LLM outputs for extraction tests
│   ├── ontologies/                # Sample OWL/TTL files (from aws_ontology)
│   ├── sample_documents/          # Test PDFs, DOCX, Markdown files
│   └── embeddings/                # Pre-computed vector embeddings
├── unit/
│   ├── test_models.py             # Pydantic model validation
│   ├── test_extraction_parser.py  # LLM output parsing & error recovery
│   ├── test_temporal_versioning.py # Version creation, expiration, NEVER_EXPIRES sentinel
│   ├── test_er_config.py          # Entity resolution configuration
│   ├── test_curation_service.py   # Curation business logic
│   └── test_import_export.py      # OWL/TTL serialization logic
├── integration/
│   ├── test_db_repository.py      # Collection CRUD against real ArangoDB
│   ├── test_temporal_queries.py   # Point-in-time snapshots, diffs, history
│   ├── test_arangordf_import.py   # PGT import of OWL files
│   ├── test_er_pipeline.py        # Full ER blocking → scoring → clustering
│   ├── test_schema_extraction.py  # arango-schema-mapper integration
│   ├── test_named_graphs.py       # Graph creation, traversal, promotion
│   └── test_api_endpoints.py      # Full HTTP request/response cycle
└── e2e/
    └── test_extraction_flow.py    # Document upload → extraction → staging → curation → promotion
```

#### Frontend Testing (TypeScript / Jest + React Testing Library)

**Unit Tests:**

| Area | What to Test | Approach |
|------|-------------|---------|
| React components | Rendering, props, user interactions, state changes | React Testing Library + Jest |
| Graph components | Node/edge rendering, selection, filtering | Mock graph data; test component output |
| VCR timeline | Slider interaction, timestamp display, playback controls | Simulated events + snapshot testing |
| API client | Request construction, response parsing, error handling | `msw` (Mock Service Worker) to intercept HTTP |
| Utility functions | Data transformations, formatting, validation | Direct function calls |

**Integration / Component Tests:**

| Area | What to Test | Approach |
|------|-------------|---------|
| Curation workflow | Approve → reject → merge → promote flow through UI components | Render full page components with mocked API |
| Graph + Timeline | Timeline slider changes update graph rendering | Integrated component test |
| Ontology library browser | List → drill-down → composition selection | Component test with mocked API responses |

**E2E Tests (Playwright):**

| Scenario | What to Verify |
|----------|---------------|
| Document upload flow | Upload PDF → see processing status → chunks appear |
| Extraction + curation | Trigger extraction → review staging graph → approve classes → promote |
| VCR timeline | Load ontology → drag timeline slider → verify graph changes at different timestamps |
| Ontology library | Import OWL file → see in library → drill into class hierarchy |
| Entity resolution | Review merge candidates → accept/reject → verify merge result |
| Pipeline monitor | Trigger extraction → see agent DAG update in real-time → view completed run metrics |

**Frontend Test Tooling:**

| Tool | Purpose |
|------|---------|
| Jest | Test runner + assertion library |
| React Testing Library | Component testing (user-centric, not implementation-centric) |
| `msw` (Mock Service Worker) | API mocking at the network level |
| Playwright | Cross-browser E2E testing |
| `@testing-library/jest-dom` | Extended DOM matchers |

**Frontend Test Directory Structure:**

```
frontend/
├── src/
│   ├── components/
│   │   ├── graph/
│   │   │   ├── GraphCanvas.tsx
│   │   │   └── __tests__/
│   │   │       └── GraphCanvas.test.tsx
│   │   ├── timeline/
│   │   │   ├── VCRTimeline.tsx
│   │   │   └── __tests__/
│   │   │       └── VCRTimeline.test.tsx
│   │   ├── curation/
│   │   │   └── __tests__/
│   │   └── pipeline/
│   │       ├── PipelineMonitor.tsx
│   │       ├── AgentDAG.tsx
│   │       └── __tests__/
│   │           ├── PipelineMonitor.test.tsx
│   │           └── AgentDAG.test.tsx
│   └── lib/
│       └── __tests__/
│           └── api-client.test.ts
├── e2e/
│   ├── upload.spec.ts
│   ├── curation.spec.ts
│   ├── timeline.spec.ts
│   ├── library.spec.ts
│   └── pipeline-monitor.spec.ts
└── jest.config.ts
```

#### CI Pipeline Test Requirements

| Stage | What Runs | Gate Condition |
|-------|-----------|---------------|
| **Lint & Type Check** | `ruff check`, `mypy --strict` (backend); `eslint`, `tsc --noEmit` (frontend) | Zero errors |
| **Backend Unit Tests** | `pytest tests/unit/ --cov --cov-fail-under=80` | All pass, coverage ≥ 80% |
| **Backend Integration Tests** | `pytest tests/integration/` against Docker ArangoDB + Redis | All pass |
| **Frontend Unit Tests** | `jest --coverage --coverageThreshold='{"global":{"lines":70}}'` | All pass, coverage ≥ 70% |
| **Frontend E2E Tests** | `playwright test` against running dev server + backend | All pass |
| **Full E2E** | End-to-end extraction flow against deployed services | All pass (staging/pre-prod only) |

#### Test Data Management

| Source | Purpose | Location |
|--------|---------|----------|
| `aws_ontology` (`aws.ttl`, `aws.owl`) | Gold-standard OWL ontology for import/export tests | `backend/tests/fixtures/ontologies/` |
| Recorded LLM responses | Deterministic extraction test inputs | `backend/tests/fixtures/llm_responses/` |
| Sample documents | PDF/DOCX/Markdown test files | `backend/tests/fixtures/sample_documents/` |
| Pre-computed embeddings | Vector similarity test fixtures | `backend/tests/fixtures/embeddings/` |
| Temporal test scenarios | Seeded version histories with known timestamps | Generated by `conftest.py` fixtures |

#### Quality Gates (Definition of Done)

A feature is not complete until:

- [ ] Unit tests written for all new service/model code
- [ ] Integration tests written for any new DB operations or API endpoints
- [ ] E2E test covers the user-facing workflow (if applicable)
- [ ] Coverage thresholds maintained (no regression)
- [ ] All existing tests pass
- [ ] Linting (`ruff`, `eslint`) and type checking (`mypy`, `tsc`) pass
- [ ] API changes reflected in OpenAPI spec and auto-generated client

---

## 9. Leveraging Existing Codebases

### 9.1 `arango-schema-mapper` → Schema Extraction + Document Extraction Service

**Role:** Two capabilities — (a) reverse-engineer ontologies from live ArangoDB databases, and (b) provide LLM extraction patterns for document-based extraction.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `schema_analyzer/snapshot.py` | Physical schema introspection (collections, edges, graphs, sampling) | Integrate as a service callable from AOE backend |
| `schema_analyzer/analyzer.py` | `AgenticSchemaAnalyzer` with optional LLM semantic inference | Use for schema-to-ontology reverse engineering (Section 6.9) |
| `schema_analyzer/owl_export.py` | OWL/Turtle export of conceptual model | Feed output into ArangoRDF PGT import pipeline |
| `schema_analyzer/baseline.py` | No-LLM deterministic inference from snapshot | Fallback when LLM is unavailable or for cost savings |
| `tool_contract_v1.py` | Structured JSON request/response schemas | Use for AOE ↔ schema-mapper integration contract |
| `schema_analyzer/workflow.py` | Generate → validate → repair loop for LLM outputs | Reuse pattern for document extraction agent's self-correction |
| Prompt construction (`_build_prompt`) | System prompt + snapshot → structured JSON | Adapt pattern for document-based ontology extraction prompts |

### 9.2 `ArangoRDF` → Ontology Import/Export Engine

**Role:** OWL/RDFS ontology storage in ArangoDB. ArangoRDF's PGT uses an OWL metamodel strategy — `owl:Class`, `rdfs:subClassOf`, `owl:ObjectProperty`, etc. are stored as typed documents and edges, preserving semantic structure. This is the core import engine for the Ontology Library.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `arango_rdf.rdf_to_arangodb_by_pgt()` | PGT transformation (RDF → ArangoDB collections) | Wrap as FastAPI service; add post-import `ontology_id` tagging and per-ontology named graph creation |
| `uri_map_collection_name` parameter | Multi-file/multi-ontology incremental import | Use shared URI map across all library imports to prevent collisions |
| `adb_col_statements` | Custom collection mapping for unusual RDF structures | Expose as advanced import option |
| RPT / LPGT variants | Alternative transformation strategies | Available for ontologies where PGT produces suboptimal results |

### 9.3 `semanticlayer/foafdemo` → ArangoRDF Reference Implementation

**Role:** Working examples of RPT, PGT, and LPGT transformations.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `setup_foaf_databases.py` | RPT/PGT/LPGT transformation examples | Reference for building AOE's import service |
| `fix_pgt_databases.py` | PGT post-processing patterns | Adapt for ontology_id tagging step |
| Three-DB pattern | RPT vs PGT vs LPGT comparison | Inform which transformation strategy to default to |

### 9.4 `arango-entity-resolution` → Entity Resolution Service

**Role:** Full entity resolution pipeline — blocking, similarity scoring, clustering, merging, and MCP tooling. AOE uses this library directly rather than reimplementing ER.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `ConfigurableERPipeline` + `ERPipelineConfig` | Config-driven pipeline orchestration with pluggable strategies | Configure for ontology field names (`label`, `description`, `uri`, `rdf_type`) |
| `VectorBlockingStrategy` + `ANNAdapter` | ANN cosine vector blocking (ArangoDB FAISS) | Point at ontology class embedding field; configure similarity threshold. ArangoDB vector index is FAISS-powered with IVF base — requires `nLists`, `nProbe`, `trainingIterations` parameters and training data at index creation time. Supports factory strings for HNSW coarse quantizer (`IVF_HNSW`) and product quantization (`PQ`). |
| `BM25BlockingStrategy` / `HybridBlockingStrategy` | ArangoSearch text-based candidate retrieval | Configure ArangoSearch view on `ontology_classes` collection |
| `GraphTraversalBlockingStrategy` | Graph-based blocking (shared edges/neighbors) | Configure for ontology edge collections (`subclass_of`, `has_property`) |
| `LSHBlockingStrategy` | Locality-sensitive hashing for scalable blocking | Configure hash tables for ontology embedding dimensionality |
| `MultiStrategyOrchestrator` | Combines multiple blocking strategies (union/intersection) | Configure strategy combination for ontology use case |
| `WeightedFieldSimilarity` | Jaro-Winkler, Levenshtein, Jaccard with per-field weights | Map ontology fields; add phonetic transforms for class labels |
| `BatchSimilarityService` | Batch pairwise scoring after blocking | Direct reuse |
| `WCCClusteringService` | Connected component clustering with multiple backends | Direct reuse; auto backend selection |
| `GoldenRecordService` / `GoldenRecordPersistenceService` | Field-level merge strategies and persistence | Configure merge rules for ontology fields |
| `CrossCollectionMatchingService` | Cross-collection BM25 + Levenshtein resolution | Use for Tier 1 ↔ Tier 2 cross-tier matching |
| `EmbeddingService` | Sentence-transformer embeddings | Configure model for ontology concept text |
| MCP server (`arango-er-mcp`) | 15+ MCP tools for ER operations | Integrate into AOE's MCP tool chain; expose via Cursor |
| **AOE-specific addition** | Topological similarity scoring | New: graph neighborhood comparison (shared properties, shared parents) as additional scoring dimension layered on top of library's framework |

### 9.5 `agentic-graph-analytics` → MCP Server

**Role:** AI-native development via Cursor + Claude.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `graph_analytics_ai/mcp/` | MCP tools for ArangoDB introspection | Extend with ontology-specific tools (query domain library, suggest mappings) |

### 9.6 `aws_ontology` → Test Data

**Role:** Gold-standard validation data.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `aws.ttl`, `aws.owl` | Test cases for Domain Ontology Library | Use as seed data for curation UI development |
| `import_to_arangodb.py` | Database seeding script | Integrate into test fixtures |

### 9.7 ArangoDB Graph Visualizer Customization Patterns → Ontology Visualization

**Role:** Native ArangoDB Graph Visualizer theming, canvas actions, and saved queries for ontology exploration.

| Component | Reuse | Adaptation Needed |
|-----------|-------|-------------------|
| `fraud-intelligence/scripts/install_graph_themes.py` | Theme + canvas action installer pattern, `ensure_default_viewpoint()`, `ensure_visualizer_shape()` | Adapt theme node/edge configs for OWL/RDFS/SKOS collections instead of fraud domain collections |
| `fraud-intelligence/docs/themes/ontology_theme.json` | Correct theme structure reference | Remap to ontology class/property/restriction node types |
| `ic-knowledge-graph/scripts/setup/install_graphrag_queries.py` | Saved queries + canvas actions installer pattern | Rewrite queries for ontology traversals (subClassOf hierarchy, domain/range, owl:imports) |
| `network-asset-management-demo/scripts/setup/install_visualizer.py` | Consolidated multi-graph installer with `_ensure_default_theme()` | Apply to per-ontology named graphs in the library |

### 9.8 `network-asset-management-demo` Temporal Graph Pattern → Reference for Advanced Proxy Pattern (Future Phase)

**Role:** Reference implementation for the advanced immutable-proxy time travel pattern. Not used in the initial implementation (which uses simpler edge-interval time travel), but serves as the blueprint for the Phase 6 optimization if edge re-creation becomes a performance bottleneck.

| Component | Reuse (Future) | Adaptation Needed |
|-----------|-------|-------------------|
| ProxyIn/ProxyOut/Entity architecture | Full pattern: stable proxies, versioned entities, hasVersion edges | Adapt from Device/Software to Class/Property ontology entity types |
| Interval semantics (`created`/`expired`/`NEVER_EXPIRES` for current) | **Already adopted** — same interval semantics used in edge-interval approach | None |
| MDI-prefixed index pattern | **Already adopted** — same index type deployed on vertex and edge collections | None |
| TTL aging (`HISTORICAL_ONLY` strategy) | **Already adopted** — same TTL strategy applied to historical vertices and edges | None |
| AQL time travel queries (snapshot, history, overlap) | **Already adopted** — same query patterns, adapted for edge-interval (filter both vertices and edges by timestamp) | None |

---

## 10. Development Phases

### Phase 1: Foundation (Weeks 1–3)
**Goal:** Project scaffolding, database schema, and document ingestion.

| Deliverable | Description |
|-------------|-------------|
| Monorepo structure | FastAPI backend, React frontend, shared types |
| ArangoDB schema | All vertex and edge collections with `created`/`expired` temporal fields; named graphs |
| Temporal indexes | MDI-prefixed indexes on all versioned vertex and edge collections; TTL indexes for historical version cleanup |
| Document upload API | Upload → parse → chunk → embed pipeline |
| Basic health/ready endpoints | Observability foundation |
| MCP server integration | Cursor can query ArangoDB during development |
| Test infrastructure | pytest + pytest-cov + pytest-asyncio (backend); Jest + React Testing Library + Playwright (frontend); Docker Compose test profile for ArangoDB + Redis; CI pipeline with lint/type-check/test stages; coverage thresholds configured |
| Test fixtures | Sample documents, recorded LLM responses, `aws_ontology` OWL files copied to `tests/fixtures/` |

**Exit Criteria:** Can upload a PDF and retrieve semantically chunked, embedded content via API. Edge-interval temporal schema deployed with MDI and TTL indexes. Test infrastructure running with ≥ 80% backend coverage on foundation code; CI pipeline green.

### Phase 2: Extraction Pipeline & Agentic Orchestration (Weeks 4–7)
**Goal:** LLM-driven ontology extraction orchestrated via LangGraph agents.

| Deliverable | Description |
|-------------|-------------|
| LangGraph pipeline scaffold | StateGraph with Strategy Selector → Extraction → Consistency → Staging nodes |
| Strategy Selector agent | Picks model, prompt template, chunking strategy based on document type |
| Extraction Agent | N-pass extraction with self-correction on Pydantic validation failures |
| Consistency Checker | Cross-pass agreement filtering with configurable threshold |
| RAG context injection | Relevant chunks injected into extraction prompt |
| ArangoRDF integration | Extracted OWL → ArangoDB via PGT → staging graph |
| Pipeline checkpointing | LangGraph state persistence for resume on failure |
| Extraction run tracking | Status, current agent step, stats, retry capability via API |
| **Pipeline Monitor Dashboard** | React frontend: agent DAG visualization with real-time status updates via WebSocket; run list, metrics, error log (Section 6.12) |

**Exit Criteria:** Can extract an ontology from a PDF via agentic pipeline, store it in a staging graph, and monitor progress both via API and the Pipeline Monitor Dashboard with real-time agent status.

### Phase 3: Curation Dashboard, VCR Timeline & ArangoDB Visualizer (Weeks 8–12)
**Goal:** Visual review and approval of extracted ontologies, temporal time travel, and native ArangoDB Graph Visualizer customization.

| Deliverable | Description |
|-------------|-------------|
| Graph visualization | Interactive rendering of staging graphs in React (Cytoscape.js / React Flow) |
| Node/edge actions | Approve, reject, rename, edit, merge — each creates a new temporal version |
| Provenance display | Click-through to source chunks with highlighted text |
| Diff view | Staging vs. production comparison; temporal diff between two timestamps |
| Promote workflow | Approved staging → production in one action |
| Curation audit trail | All decisions recorded with before/after state via temporal versioning |
| **VCR timeline slider** | Interactive timeline control with play/pause/rewind/fast-forward; graph re-renders at selected timestamp |
| **Point-in-time snapshot API** | `/snapshot?at={timestamp}` returns ontology state at any historical moment |
| **Version history API** | `/history` returns all versions of a class/property with change metadata |
| **Temporal diff API** | `/diff?t1=&t2=` returns added/removed/changed entities between two timestamps |
| **Timeline event markers** | Discrete change events as tick marks on the slider; clicking jumps to that version |
| **Diff visualization overlay** | Added entities in green, removed in red, changed in yellow |
| **Revert-to-version** | Create a new current version that restores a historical state |
| ArangoDB Visualizer themes | Ontology-specific themes with OWL/RDFS/SKOS node type colors and icons |
| ArangoDB Visualizer canvas actions | Right-click actions for class hierarchy expansion, property display, provenance tracing, and **version history** |
| ArangoDB Visualizer saved queries | Pre-built AQL queries for class hierarchy, orphan detection, cross-tier extensions, ontology stats, **and point-in-time snapshots** |
| Visualizer viewpoint setup | Programmatic viewpoint creation and linking of actions/queries per ontology graph |
| Visualizer install scripts | Idempotent Python scripts in `scripts/setup/`; asset definitions in `docs/visualizer/` |

**Exit Criteria:** Domain expert can visually review an extracted ontology, make edits, and promote it to production. Users can scrub the VCR timeline to see any past ontology state and compare temporal snapshots. Ontology engineers can explore ontologies natively in the ArangoDB Graph Visualizer with proper theming, canvas actions, pre-built queries, and temporal queries.

### Phase 4: Tier 2, Entity Resolution & Pre-Curation Agents (Weeks 13–16)
**Goal:** Localized ontology extensions, automated deduplication, and pre-curation filtering agents.

| Deliverable | Description |
|-------------|-------------|
| Context-aware extraction | LLM receives domain ontology as context for local extraction |
| Extension classification | Extracted entities tagged as EXISTING / EXTENSION / NEW |
| Cross-tier linking | `extends_domain` edges connecting local → domain classes |
| Entity Resolution Agent | LangGraph agent wrapping `arango-entity-resolution` pipeline: multi-strategy blocking, weighted field + vector + topological scoring, WCC clustering, cross-tier matching via `CrossCollectionMatchingService` |
| Pre-Curation Filter Agent | LangGraph agent: removes noise, annotates confidence tiers, adds provenance |
| Merge suggestions in UI | Candidate pairs with scores surfaced in curation dashboard |
| Merge execution | One-click merge with provenance preservation |

**Exit Criteria:** Can extract a local ontology that correctly extends a domain ontology, with automated duplicate detection and pre-curation filtering reducing human review burden by ≥ 20%.

### Phase 5: MCP Server & Integration (Weeks 17–19)
**Goal:** Runtime MCP server exposing ontology operations to external AI agents.

| Deliverable | Description |
|-------------|-------------|
| MCP server process | Standalone process alongside FastAPI, stdio + SSE transports |
| Ontology query tools | `query_domain_ontology`, `get_class_hierarchy`, `get_class_properties`, `search_similar_classes` |
| Pipeline tools | `trigger_extraction`, `get_extraction_status`, `get_merge_candidates` |
| Provenance + export tools | `get_provenance`, `export_ontology` |
| MCP resources | Summary stats, recent runs, health status |
| Organization-scoped auth | MCP tools respect org isolation |

**Exit Criteria:** An external AI agent (e.g., Claude Desktop, custom MCP client) can connect and query/trigger ontology operations via MCP.

### Phase 6: Polish, Production & Advanced Temporal (Weeks 20–24)
**Goal:** Import/export, auth, multi-tenancy, hardening, and optional advanced temporal optimization.

| Deliverable | Description |
|-------------|-------------|
| OWL/TTL/JSON-LD export | Export any ontology graph to standard formats |
| OWL/TTL import | Import industry-standard ontologies as Tier 1 |
| Authentication + RBAC | OAuth 2.0 with role-based access; `organizations` and `users` collections |
| Organization isolation | Multi-tenant data separation; all queries scoped by `org_id` |
| Notification system | In-app notifications, WebSocket events, optional email digests (Section 8.8) |
| Schema migration framework | Versioned, idempotent migration scripts; `_system_meta` tracking (Section 8.7) |
| Production deployment | Containerized images (backend, frontend, MCP server); Kubernetes manifests or Docker Compose production profile (Section 8.6) |
| Observability stack | Structured logging, metrics, tracing, alerting |
| Performance optimization | Cursor-based pagination, caching, index tuning, rate limiting |
| Documentation | API docs (OpenAPI), user guide, architecture decision records |
| **[Advanced] Proxy pattern migration** | If edge-interval time travel shows performance bottlenecks (excessive edge re-creation on high-frequency edits), migrate to the immutable-proxy pattern (ProxyIn/Entity/ProxyOut with `hasVersion` edges) from `network-asset-management-demo`. This eliminates edge re-creation by routing topology through stable proxy anchors. See Section 9.8 for reference implementation. |

**Exit Criteria:** Production-ready system with auth, multi-tenancy, observability, notifications, and standard ontology interoperability. Schema migration framework operational. Decision documented on whether proxy pattern migration is needed based on measured temporal query and edge-recreation performance.

---

## 11. Cursor & Claude Development Workflow

### 11.1 Repository Setup

1. **Monorepo structure:**
   ```
   ontology_generator/
   ├── backend/              # FastAPI application
   │   ├── app/
   │   │   ├── api/          # Route handlers
   │   │   ├── services/     # Business logic
   │   │   ├── models/       # Pydantic models
   │   │   ├── db/           # ArangoDB client + queries
   │   │   └── extraction/   # LLM extraction pipeline
   │   ├── tests/
   │   │   ├── conftest.py   # Shared fixtures (test DB, mock settings)
   │   │   ├── fixtures/     # LLM responses, sample docs, OWL files, embeddings
   │   │   ├── unit/         # Fast, isolated, mocked dependencies
   │   │   ├── integration/  # Real ArangoDB + Redis via Docker
   │   │   └── e2e/          # Full extraction → curation → promotion flow
   │   └── pyproject.toml
   ├── frontend/             # Visual Curation Dashboard (React/Next.js)
   │   ├── src/
   │   │   ├── components/   # React UI components (with co-located __tests__/)
   │   │   │   ├── graph/    # Graph visualization (React Flow or react-cytoscapejs)
   │   │   │   ├── timeline/ # VCR timeline slider
   │   │   │   ├── curation/ # Approval workflow UI
   │   │   │   └── pipeline/ # Pipeline Monitor Dashboard (agent DAG, run list, metrics)
   │   │   ├── pages/        # Route pages
   │   │   └── lib/          # Utilities, API client
   │   ├── e2e/              # Playwright E2E tests
   │   ├── jest.config.ts    # Jest configuration
   │   └── package.json
   ├── docs/visualizer/       # ArangoDB Graph Visualizer assets (JSON themes, queries, actions)
   ├── shared/               # Shared type definitions
   ├── scripts/              # Dev/ops scripts
   ├── configs/              # Configuration files
   ├── docs/                 # Documentation
   └── .cursor/rules/        # Cursor AI behavior rules
   ```

2. **Cursor rules (`.cursor/rules/`):** Already configured — enforce Pydantic for LLM models, ArangoDB Python Driver for queries, two-tier architecture constraints.

3. **MCP Server:** Run locally from `agentic-graph-analytics` repo. Allows Claude to query the Domain Ontology Library while writing extraction logic.

### 11.2 Development Principles

- Use Claude via MCP to inspect live ArangoDB state before writing database code
- All LLM extraction models defined as Pydantic `BaseModel` subclasses
- All database operations go through a typed repository layer (no raw AQL in route handlers)
- Frontend components are typed with TypeScript; API client auto-generated from OpenAPI spec

---

## 12. Open Questions & Risks

| ID | Question / Risk | Impact | Mitigation |
|----|----------------|--------|------------|
| R1 | LLM extraction quality may vary significantly by domain | Low precision → high curation burden | Multi-pass extraction, domain-specific prompt tuning, configurable confidence thresholds |
| R2 | ArangoRDF may not support all OWL 2 constructs | Incomplete ontology representation | Identify unsupported constructs early; supplement with custom edges |
| R3 | Graph visualization performance with large ontologies | Slow/unusable curation UI | Implement progressive loading, subgraph filtering, level-of-detail rendering |
| R4 | Entity resolution false positives | Noise in merge suggestions | Conservative default thresholds; require expert approval for all merges |
| R5 | Multi-tenancy data leakage | Security incident | Collection-level isolation where possible; mandatory `org_id` filters in repository layer |
| R6 | LLM cost at scale | Budget overrun | Batch processing, caching of repeated extractions, smaller models for simple documents |
| R7 | LangGraph pipeline complexity | Hard to debug multi-agent failures | Checkpointed state, structured logging per agent step, visual graph debugging in LangSmith |
| R8 | MCP server security exposure | Unauthorized access to ontology data | MCP tools enforce org-scoped auth; runtime MCP requires API key; no write tools exposed without explicit permission |
| R9 | Agentic pre-curation too aggressive | Useful extractions filtered out before human review | Conservative default thresholds; all filtered entities logged and recoverable; tunable per domain |
| R10 | ArangoRDF PGT merges ontologies into shared collections | Hard to distinguish ontology boundaries after import | Post-import `ontology_id` tagging + per-ontology named graphs; registry tracks IRI prefixes |
| R11 | Schema extraction from production ArangoDB | Credentials for external DBs must be handled securely; extraction load on target DB | Read-only connections; configurable sample limits; credentials stored in secret manager, not DB |
| R12 | Ontology library grows beyond manageable size | Performance degradation on cross-ontology queries | Ontology composition (orgs select relevant subset); lazy loading; ArangoSearch indexes on class labels |
| R13 | Temporal versioning storage growth | Each edit creates new vertex + edge documents; historical versions accumulate | TTL aging with configurable retention (90 days default); `HISTORICAL_ONLY` strategy ensures current data is never garbage-collected; storage monitoring alerts |
| R14 | Edge re-creation cost on vertex changes | Edge-interval approach requires expiring and re-creating all edges when a vertex is updated | Ontologies change infrequently; edge counts per class are moderate (typically < 20). If this becomes a bottleneck, migrate to the immutable-proxy pattern in Phase 6 (see Section 9.8) |
| R15 | VCR timeline performance with high-frequency changes | Large number of version events makes timeline scrubbing slow | MDI-prefixed indexes on `[created, expired]` for sub-millisecond range queries; aggregate events beyond a configurable resolution (e.g., group sub-second changes); paginate timeline events |
| R16 | Point-in-time snapshot query cost | Must filter both vertices AND edges by timestamp for graph traversals | MDI-prefixed indexes on all vertex and edge collections; per-ontology query scoping via `ontology_id` filter; materialized snapshot cache for frequently-accessed timestamps |
| R17 | Schema migration on live production data | Risk of data corruption or downtime during migrations | Forward-only idempotent migrations; pre-migration backups; schema-free document model reduces risk; new fields use defaults |
| R18 | Notification delivery reliability | Users miss critical events (extraction failures, curation readiness) | Redis Pub/Sub for internal event bus; WebSocket with reconnect logic; optional email fallback; unread notification count in UI |
| R19 | ER MCP server coordination | Two MCP processes (AOE + arango-er-mcp) create operational complexity | AOE MCP server proxies ER tool calls; single entry point for external clients; health monitoring for both processes |

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Domain Ontology** | A standardized, shared ontology representing an industry domain (e.g., financial services, healthcare) |
| **Localized Ontology** | An organization-specific extension that inherits from and extends a Domain Ontology |
| **OWL 2** | Web Ontology Language — the W3C standard for expressing ontologies with formal semantics (classes, properties, restrictions, axioms) |
| **RDFS** | RDF Schema — lightweight vocabulary for defining class hierarchies and property domains/ranges; foundation for OWL |
| **SKOS** | Simple Knowledge Organization System — W3C standard for taxonomies, thesauri, and controlled vocabularies (`skos:Concept`, `skos:broader`, `skos:prefLabel`) |
| **PGT** | Property Graph Transformation — ArangoRDF's strategy for storing OWL/RDF in ArangoDB. Uses an OWL metamodel approach: RDF types become collections, predicates become edges, OWL semantics are preserved |
| **Process Graph (`aoe_process`)** | A named graph that provides end-to-end visibility of the extraction pipeline: `documents` → `chunks` → `ontology_classes` → `ontology_properties`, with lineage edges linking ontology entries back to extraction runs. Used for debugging, provenance tracing, and visual exploration in the ArangoDB Graph Visualizer |
| **Staging Graph** | A temporary graph holding extracted entities pending human review |
| **Curation** | The process of a domain expert reviewing, editing, and approving LLM-extracted ontology elements |
| **Entity Resolution** | The process of identifying and merging duplicate or equivalent concepts |
| **MCP** | Model Context Protocol — enables AI tools (Claude) to interact with external systems (ArangoDB) |
| **RAG** | Retrieval-Augmented Generation — injecting relevant document chunks into LLM prompts |
| **LangGraph** | Framework for building stateful, multi-step agent workflows as directed graphs with checkpointing |
| **MCP Server** | A process that exposes tools and resources via Model Context Protocol for consumption by AI agents |
| **MCP Client** | An AI agent (e.g., Claude Desktop, Cursor, custom app) that connects to an MCP server and invokes its tools |
| **Agentic Pipeline** | An extraction workflow where LLM-powered agents autonomously make decisions (strategy, retries, filtering) rather than following a rigid script |
| **Ontology Registry** | A catalog collection in ArangoDB tracking all imported/extracted ontologies, their metadata, and lifecycle status |
| **Ontology Library** | The managed collection of all Domain Ontologies available for organizations to compose their Tier 2 extensions against |
| **Schema Extraction** | Reverse-engineering an ontology from a live ArangoDB database's physical structure (collections, edges, sampled documents) |
| **arango-schema-mapper** | Python library (`arangodb-schema-analyzer`) that introspects ArangoDB databases and produces conceptual models with optional LLM enhancement |
| **ArangoRDF** | Python library (`arango_rdf`) for storing OWL/RDFS/SKOS ontologies in ArangoDB via PGT/RPT/LPGT strategies, preserving OWL metamodel semantics |
| **IRI** | Internationalized Resource Identifier — the unique identifier for an ontology concept (e.g., `http://xmlns.com/foaf/0.1/Person`) |
| **ArangoDB Graph Visualizer** | Built-in web UI for exploring named graphs in ArangoDB, supporting custom themes, canvas actions (right-click menu), saved queries, and viewpoints |
| **Canvas Action** | A user-defined AQL query that appears in the Graph Visualizer's right-click menu, used for interactive graph exploration (e.g., expand neighborhood, show related entities) |
| **Viewpoint** | A named configuration scope in the ArangoDB Graph Visualizer that links a set of canvas actions and saved queries to a specific graph |
| **Temporal Graph** | A graph that tracks the full history of entity changes using versioned documents with `created`/`expired` interval semantics on both vertices and edges |
| **Edge-Interval Time Travel** | The approach used by AOE: both vertices and edges carry `created`/`expired` timestamps. When a vertex changes, its edges are expired and re-created for the new version. Simple to implement; appropriate for moderate-frequency changes |
| **Immutable-Proxy Pattern** | Advanced alternative (Phase 6): separates stable identity (ProxyIn/ProxyOut) from mutable state (versioned entities), avoiding edge re-creation at the cost of additional proxy collections. Reserved for future optimization if needed |
| **NEVER_EXPIRES** | Sentinel value (`sys.maxsize` = 9223372036854775807) stored in the `expired` field to indicate a versioned entity or edge is the current active version. The UI should display this as "Current" or "Active", not as the raw integer. |
| **MDI-Prefixed Index** | Multi-dimensional index on `[created, expired]` fields that accelerates temporal range queries (point-in-time snapshots, interval overlaps) |
| **TTL Aging** | Automatic garbage collection of historical (expired) versioned documents via ArangoDB TTL indexes on the `ttlExpireAt` field |
| **VCR Timeline** | Interactive timeline slider in the curation dashboard that enables scrubbing through ontology history, with playback controls and diff visualization |
| **Point-in-Time Snapshot** | Query returning the complete ontology state as it existed at a specific historical timestamp |
| **Golden Record** | The merged, consolidated entity created by the entity resolution process from a cluster of duplicate candidates |
| **WCC** | Weakly Connected Components — graph algorithm used to group duplicate entity candidates into clusters |
| **Cursor-Based Pagination** | Pagination using opaque cursors (tokens) rather than page numbers; more efficient for large result sets and concurrent inserts |
| **Schema Migration** | A versioned, forward-only script that modifies the ArangoDB schema (adding collections, indexes, fields); tracked via `_system_meta` |
| **ConfigurableERPipeline** | The main entry point of the `arango-entity-resolution` library — a config-driven pipeline with pluggable blocking, scoring, clustering, and merging stages |
