# Arango-OntoExtract (AOE) — Comprehensive System Review Report

**Review Date:** June 11, 2026 (revised same day after code verification)
**System Version:** v0.4.0
**Completion Status:** ~95% of PRD (15 feature sections, 6 work streams, 95+ tasks)
**Reviewer Scope:** Architecture, features, design quality, gaps, and roadmap to excellence

---

## Executive Summary

Arango-OntoExtract is a **sophisticated, production-ready ontology extraction and curation platform** with exceptional architectural foundations. The system combines LLM-driven extraction, human-in-the-loop curation, belief-revision substrate, constraint support, and temporal versioning into a coherent whole. The engineering quality is **high**: careful error handling, comprehensive test coverage (84%+ backend, deliberate frontend coverage thresholds), and extensive documentation of complex decisions.

**Status:** The project has achieved ~95% of its PRD requirements. The remaining 5% is primarily:
- **UI polish** (Stream 8 editor panels: semantic zoom, property matrix, restriction editor)
- **Legacy route cleanup** (deferred deprecation of `/curation` routes in favor of workspace-centric UI)
- **Minor feature gaps** (mutation API for constraint curation, background consolidation scheduler)

Not counted in the PRD percentage but required before exposed deployments: **RBAC wiring across all routers** and the **security/backup items in §2.1.4**.

**Strengths:** Temporal versioning with referential integrity, belief-revision substrate, effective ontology composition, entity resolution, and production-ops readiness (TTL GC, tracing, alerting).

**Gaps to Excellence:** Below, organized by criticality and strategic importance.

---

## Part 1: Strengths & Accomplishments

### 1.1 Architectural Excellence

#### Multi-Model Ontology System
The **two-tier ontology model** (Tier 1: Domain / Tier 2: Localized Extensions) is well-founded:
- **Linked via standard OWL constructs** (`rdfs:subClassOf`, `owl:equivalentClass`, `owl:imports`) rather than forks or copies
- **Import-aware extraction** — LLM sees the effective ontology (own + imports) and is instructed to reuse/extend rather than duplicate
- **Conflict detection on import merge** — duplicate URIs, duplicate labels (case-insensitive), and subclass cycles via import are flagged
- **Composition overlay** (`ImportsDependencyOverlay.tsx`) visualizes the dependency DAG (ancestors left, self center, dependents right)

**Why this matters:** Prevents the "fragmentation" problem where every organization maintains incompatible copies of the same domain schema. Real-world impact: standards bodies can maintain Tier 1 (Dublin Core, FIBO, Schema.org), organizations extend Tier 2 without forking.

#### PGT-Aligned Property Collections (Stream 0 / ADR-006) — shipped
The extraction and ArangoRDF import paths share one schema (migrations `017_pgt_collections.py` + `018_migrate_properties.py`):
- `ontology_object_properties` and `ontology_datatype_properties` are **separate collections**, preserving OWL 2's ObjectProperty/DatatypeProperty distinction
- Domain/range are expressed as `rdfs_domain` / `rdfs_range_class` **edges**
- Extraction prompts request `attributes` and `relationships` separately (`ExtractedAttribute` / `ExtractedRelationship` models); materialization writes each to the correct collection
- Quality metrics (connectivity, completeness) compute over the new edge collections

**Why this matters:** Imported and extracted ontologies are structurally identical, so queries, quality metrics, and the UI need only one code path. (An earlier draft of this report listed this as an open critical gap — that was wrong; it is verified shipped in the codebase.)

#### Temporal Versioning with Referential Integrity
**Edge-interval time travel** with `created`/`expired` timestamps:
- MDI-prefixed indexes on `[created, expired]` enable snapshot queries at any point in time
- TTL indexes with `sys.maxsize` sentinel (`NEVER_EXPIRES`) for automatic GC of historical versions
- **Curation reject cascade** — rejecting a class expires it + cascades to all dependent edges
- **Soft-delete with cross-ontology cascade** — deprecating an ontology cleanly removes it from other ontologies' imports graphs
- Comprehensive **referential-integrity matrix** documented in `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md`

**Why this matters:** Curators can trust that approval/rejection decisions are reversible and auditable. Undoing a decision requires finding the prior version + restoring it, not destructive in-place edits.

#### Belief Revision Substrate (Iterative Refinement)
**Phase 1–4 ABD (Abductive Belief Refinement)**:
1. **Touchpoint discovery** (mechanical) — find candidate existing classes via embedding similarity + label match
2. **Mechanical verdict** (rule + score) — classify each touchpoint into `REINFORCE | REFINE | RETRACT | MERGE | FLAG_FOR_CURATION`
3. **LLM revision agent** (semantic) — LLM judges hard cases where rules + scores are ambiguous
4. **Background consolidation** (periodic) — sweep the ontology for stale cross-document contradictions

**Why this matters:** Ontologies built incrementally (multiple documents over time) accumulate errors without this. Document `D2` may provide evidence that contradicts `D1`, refines it, or supersedes it. Without belief revision, curators manually re-review all prior decisions.

**Current state:** Phases 1–3 fully shipped (v0.4.0). Phase 4 (consolidation job) partially done — admin endpoints exist, but there is **no background scheduler or task queue yet** (see 2.1.3). Phase 3 UI (Revisions Inbox overlay) is complete.

#### Entity Resolution Integration
**Hand-rolled scoring** (not library-wrapped) because the `arango-entity-resolution` library is person-record-focused:
- Topological similarity (shared properties, shared parents/children) as primary signal
- Jaro-Winkler string similarity on labels as secondary
- Union-Find clustering to group transitively-similar classes
- Golden-record creation via temporal versioning (expire old entities, create merged supertype)

**Why this matters:** The curation UI ("Find Duplicates…" overlay) surfaces merge candidates with per-pair accept/reject/explain, preventing duplicates from silently accumulating.

#### OWL Constraints & SHACL Shapes (Stream 3)
- **Extraction prompts** request explicit constraints (cardinality, range, patterns)
- **OWL import** reads `owl:Restriction` blank nodes attached via `rdfs:subClassOf` / `owl:equivalentClass`
- **SHACL import** parses `sh:NodeShape` / `sh:PropertyShape` with `sh:minCount`/`sh:maxCount`/`sh:datatype`/`sh:pattern`/`sh:nodeKind`/`sh:in`/`sh:hasValue`
- **Unified rule engine** — both OWL and SHACL cardinality constraints fire the same violation rule (strictest-wins across sources)
- **Workspace display** — `ClassConstraintsSection` in the detail panel shows all constraints grouped by property with source provenance pills
- **Export** — OWL Turtle exports `owl:Restriction` blank nodes; new SHACL shapes export via `?format=shacl`

**Why this matters:** Ontologies with formal constraints are more useful for downstream validation, schema generation, and API contract enforcement.

#### Visual Curation & Workspace
- **Sigma.js WebGL rendering** on `/workspace` for large-scale graphs (thousands of nodes)
- **React Flow rendering** on `/curation/...` for detailed curation workflows
- **VCR timeline** with play/pause/rewind for temporal navigation
- **Class detail panel** with properties, constraints, provenance, confidence scores
- **Right-click context menus** for add/edit/delete/merge/promote actions
- **Multiple graph styles** (Network circle graph vs Box & Arrow UML)
- **Asset Explorer sidebar** with search, filter by tier/tags, document/ontology browser

**Why this matters:** Non-technical domain experts need visual, interactive ways to approve/reject/edit extracted ontologies. Code-based editors are unusable for this audience.

#### Schema Extraction from ArangoDB (Stream 5)
- **Reverse-engineer ontologies** from any ArangoDB database via named-graph topology
- **Infer XSD types** from field sampling (string/integer/decimal/boolean/date/dateTime)
- **Provenance stamping** — per-class `source_db`/`source_collection`/`source_host` annotations
- **Graph filtering** — select specific named graphs, toggle inclusion of loose collections
- **Auto-imports** — declare which standard ontologies the extracted schema extends
- **Overlay UI** (`SchemaExtractionOverlay.tsx`) with connection test, graph preview, and import summary

**Why this matters:** Existing ArangoDB installations can bootstrap an ontology automatically rather than manual extraction from documents.

#### Production-Ready Operations (Stream 7)
- **OpenTelemetry tracing** across the extraction pipeline with structured logs
- **Rate limiting** via Redis with sliding-window strategy
- **TTL-based garbage collection** — historical versions aged out per configured retention
- **Visualizer auto-install** with post-extraction asset bundle deployment
- **Docker health checks** in docker-compose
- **Alerting configuration** (Prometheus + AlertManager compatible)
- **Ops benchmark harness** for performance measurement under load

**Why this matters:** Deploying to production requires visibility (tracing), control (rate limits), retention policies, and health checks.

### 1.2 Code Quality & Testing

#### Test Coverage
- **Backend:** 84%+ line coverage (1730 tests at v0.4.0)
  - Unit tests mock I/O; integration tests use Docker ArangoDB + Redis
  - Fixture-based test data (financial services domain, 5 sample documents)
  - Regression suites for known quality gaps (Q.1–Q.4 fixtures from belief revision audit)

- **Frontend:** 55–70% thresholds per file tier (jest + Playwright E2E)
  - 590+ jest tests for component logic
  - E2E tests cover critical workflows (upload → extraction → curation → promotion)

#### CI/CD Pipeline (5-tier GitHub Actions)
1. **Lint tier** — ruff + mypy (Python), eslint + tsc (JavaScript)
2. **Unit tier** — pytest (backend, `--cov-fail-under=80`), jest (frontend)
3. **Integration tier** — ArangoDB + Redis in Docker; AQL query correctness
4. **E2E tier** — Playwright workspace flows
5. **Docker tier** — image build + health check smoke test

#### Error Handling Discipline
- **Soft error swallowing** — non-fatal failures (e.g., quality snapshot write) logged but don't break the main path
- **Structured error responses** — PRD-compliant error envelopes with `code`, `message`, `details`
- **Defensive AQL** — every resolver missing an entity returns `null` + warning, never crashes
- **Pre-checks on mutation** — self-import, cycle, duplicate detection before any write

#### Documentation
- **PRD (v4)** — 17 sections, 13 use cases, RBAC matrix
- **Architecture docs** — system diagram, component descriptions, tech stack rationale
- **ADRs (8 total)** — temporal versioning, graph library choice, ER integration, extraction pipeline, belief revision, PGT alignment, SPA HTML fallback, constraint substrate
- **Remaining Work Plan** — detailed stream breakdown with 95+ tasks, status, exit criteria
- **DELETION_AND_REFERENTIAL_INTEGRITY.md** — comprehensive cascade rules matrix

**Why this matters:** A system this complex REQUIRES documented architectural decisions. Every major design choice (temporal versioning, belief revision, PGT alignment) has an ADR explaining alternatives considered and rationale.

---

## Part 2: Weaknesses & Gaps

### 2.1 Critical Gaps (block multi-tenant/SaaS deployment; high-priority fixes even for single-tenant)

#### 2.1.1 **Mutation API for Constraint Curation (I.7, Stream 3)**

**Current State:**
- Constraints are **read-only** in the workspace (`ClassConstraintsSection`)
- Curators can approve/reject classes and edges, but **not constraints**
- The UI renders constraint pills but they have no context-menu actions

**Why It's Critical:**
- A curator who spots an incorrect cardinality bound cannot fix it without going to the database directly
- Constraints extracted from documents may be overly strict and need manual loosening
- Missing this creates a "second system" — curators learn to ignore the constraints section

**Estimated Effort:** 2–3 days

**Solution:**
```
POST /api/v1/ontology/library/{ontology_id}/constraints/{constraint_key}/approve
POST /api/v1/ontology/library/{ontology_id}/constraints/{constraint_key}/reject
PUT /api/v1/ontology/library/{ontology_id}/constraints/{constraint_key}
  { restriction_value: <new-value>, description: <new-description> }
```

Then wire context-menu actions in `ClassConstraintsSection`:
- Approve (non-destructive; sets `status="approved"`)
- Reject (creates temporal expire + new version with `status="rejected"`)
- Edit (inline or modal; calls the PUT endpoint)

#### 2.1.2 **Missing Authorization & RBAC Enforcement**

**Current State:**
- PRD Section 2a defines 5 roles (viewer, domain_expert, ontology_engineer, admin, agent) and a **RBAC matrix** with 30+ permissions
- The enforcement mechanism **exists** — `require_role` in `backend/app/api/dependencies.py` — but is wired into only 2 of ~15 routers (`notifications`, `orgs`)
- The ontology, extraction, curation, quality, and admin routers accept any authenticated request
- User/organization collections exist but are never consulted for access control on those routers

**Why It's Critical:**
- In a multi-organization SaaS deployment, users can read/modify other organizations' ontologies
- Users can trigger costly extraction runs (LLM tokens) without approval
- Audit trails are absent — no way to trace who made changes

**Current Implementation:**
- Minimal login stub at `backend/app/minimal_login.py`
- `Bearer <org_id>` token convention (hard-coded in tests, not validated)
- No JWT, no session, no request context middleware

**Estimated Effort:** 2–3 weeks (this is the full multi-tenant scope below, not just guard wiring — wiring alone is days, not weeks)

**Required Components:**
1. Authentication (JWT or session-based) replacing the `minimal_login` stub
2. Request context middleware extracting `user_id`, `org_id`, `role` from token
3. Wire the **existing** `require_role` guard into the remaining ~13 routers (ontology, extraction, curation, quality, admin, …)
4. Organization-scoped data filtering (all list/get endpoints must filter by `org_id`)
5. Audit logging (who, what, when, from where)

**Implications for Competition:**
- Without RBAC, the system is **single-tenant only**. SaaS competitors with proper multi-tenancy will be preferred.
- The honest path: deploy behind an API gateway (Kong, Apigee) that handles auth/RBAC, or implement it yourself before multi-tenant use.

#### 2.1.3 **Background Consolidation Job (Stream 11 Phase 4)**

**Current State:**
- Belief revision Phases 1–3 are done (touchpoint discovery, mechanical verdict, LLM agent)
- Phase 4 (periodic background sweep for ontology-wide consistency) **exists only as admin endpoints**

**Why It's Critical:**
- Without Phase 4, stale contradictions accumulate unless a new document triggers them
- If a belief is never re-touched by new evidence, it's never revisited
- Example: Document 1 establishes `Account` with no `subClassOf` parent. Document 2 provides evidence that `Checking Account` should be a subtype. Phase 3 (per-doc LLM agent) flags this. But if Document 3 arrives and never mentions checking accounts, the gap never gets a Phase 4 pass to fix it.

**Current Implementation:**
- `POST /api/v1/admin/consolidate/{ontology_id}` runs one pass (blocking HTTP request)
- No scheduler; no async task queue
- No cursor-resumable iteration (re-runs the same gap-filling logic from the start every time)

**Estimated Effort:** 1 week

**Required Components:**
1. Async task queue (Redis-based Celery or similar)
2. Scheduler (APScheduler or native Celery Beat) running consolidation every 24h per ontology
3. Cursor-resumable logic (process 100 entities per job, save cursor, resume next run)
4. Consolidation telemetry (revisions proposed, accepted, rejected, cost)
5. Admin UI to view consolidation runs and manually trigger on-demand

#### 2.1.4 **Security Posture Beyond RBAC**

The RBAC gap (2.1.2) is the headline, but three adjacent issues need attention before any deployment that is not on a trusted internal network:

**Schema extraction is an SSRF vector.** `POST /schema/extract` accepts an arbitrary `target_host` URL plus credentials, and the backend opens a connection to it (`backend/app/services/schema_extraction.py`). In a multi-tenant or internet-facing deployment this lets a caller probe internal network services from the server. Mitigation: a target-host allowlist (or at minimum denying private/link-local address ranges), plus the RBAC guard once wired.

**Admin reset endpoints are gated by an env var, not auth.** `POST /admin/reset` and `POST /admin/reset/full` truncate collections and are protected only by `ALLOW_SYSTEM_RESET=true` (`backend/app/api/admin.py`). When the flag is on, any request that reaches the API can wipe the system. Mitigation: additionally require the `admin` role.

**No backup/restore tooling exists.** The risk register (Part 5) depends on scheduled backups as a mitigation, but no backup implementation, schedule, or restore runbook exists anywhere in the repo or the plans. Add `arangodump`-based scheduled backups and a **tested** restore procedure before production.

Already in decent shape: document upload enforces a MIME-type allowlist; AQL uses bind variables throughout (spot-checked); rate limiting exists (Redis sliding window).

**Estimated Effort:** 1 week (SSRF allowlist + admin auth + backup runbook and scheduling)

### 2.2 High-Priority Gaps (Degrade User Experience)

#### 2.2.1 **Stream 8: Workspace Editor Panels (Semantic Zoom, Property Matrix, Restriction Editor)**

**Current State:**
- Workspace canvas renders the graph but detail panels are minimal
- Property matrix missing (can't bulk-edit multiple class properties at once)
- Semantic zoom missing (no ability to expand neighborhood on hover)
- Restriction editor missing (constraints are read-only)
- Namespace manager missing (can't view/edit URIs in bulk)
- Validation console missing (can't run ontology rule engine on-demand)

**Why It Matters:**
- TopBraid-style editors have these features; users coming from TopBraid expect them
- A curator who needs to bulk-edit 10 properties across 3 classes must do it one-by-one today
- Missing semantic zoom makes large ontologies hard to navigate

**Estimated Effort:** 3 weeks (5 components)

**Components:**
1. **Semantic zoom** — on hover, expand the neighborhood (N-hop radius configurable) with dimmed outer edges
2. **Property matrix** — selected classes × all properties as a table; bulk-edit cardinality/type/required
3. **Restriction editor** — dedicated panel for viewing/editing constraint sets per class
4. **Namespace manager** — view all URIs, bulk-rename namespace prefixes
5. **Validation console** — run ontology rules on-demand, show violations

**Note:** This work is **deferred in the current roadmap** but is necessary for expert users. Consider this a "nice to have" for v1.0, critical for v1.1.

#### 2.2.2 **Pagination on `/classes` and `/edges` Endpoints**

**Current State:**
- `/ontology/{id}/classes` already supports **opt-in keyset pagination** (`?limit=` + `?cursor=`, Stream 12 T10); omitting `limit` returns the full list in the legacy shape for back-compatibility
- `/ontology/{id}/edges` and `/effective` are **intentionally unpaginated** — the canvas needs the whole graph to render correctly

**Why It Matters:**
- A large ontology with 10K+ classes will overflow the canvas and degrade browser performance
- The canvas consumes the effective-graph API; paginating it would require a "stream to canvas incrementally" architecture, which is a much bigger change than adding cursors

**Honest Assessment:**
- The remaining gap is `/edges`/`/effective` only, and pagination there is a partial solution
- A better path: keep unpaginated for small ontologies (<1K classes), revisit for large ones

**Decision:** Leave as-is for v1.0. Monitor in production; add `/edges` pagination if large-ontology requests exceed 10% of traffic.

#### 2.2.3 **Gold-Standard Recall Comparison (Stream 4 Q.4) — shipped; RAG benchmark UI remains optional/future**

**Current State:**
- Backend API shipped: `POST /api/v1/quality/recall` accepts a gold-standard OWL/TTL file and returns precision/recall/F1 with per-class matched/missed/false-positives
- Frontend overlay shipped: `RecallComparisonOverlay` with file picker + threshold slider
- Works correctly; users can test extraction quality against a gold standard
- The separate "RAG benchmark comparison UI" item in `docs/REMAINING_WORK_PLAN.md` (a deeper benchmark beyond label recall) remains an **optional future** idea, not part of the shipped Q.4 work

**Why the remaining piece is not critical:**
- Recall against a gold standard already works; a RAG-style benchmark adds depth, not coverage
- The quality dashboard already shows multi-signal confidence without needing a gold standard

**Status:** Q.4 feature-complete; possible polish: batch CSV import, charting improvements, export results as PDF.

---

### 2.3 Medium-Priority Gaps (Polish & Scalability)

#### 2.3.1 **Legacy Route Deprecation (`/curation/...`, `/ontology/edit/...`)**

**Current State:**
- Old curation routes still exist and work
- New workspace-centric UI is the primary path
- Both React Flow (legacy) and Sigma.js (new) renderers coexist

**Why It Matters:**
- Technical debt — two code paths for the same UI
- Confusion for developers — which one should they extend?
- Maintenance burden — bug fixes must land in both places

**Timeline:**
- Keep both through v1.0 for user migration grace period
- Deprecate old routes in v1.1 (show sunset warning)
- Remove in v2.0

#### 2.3.2 **Query Performance on Very Large Ontologies (100K+ classes)**

**Current State:**
- Tested at ~10K classes; query times are acceptable (500ms–2s)
- No testing at 100K+ classes
- Effective-graph computation (own + imports closure) may become slow

**Why It Matters:**
- Real-world ontologies (BFO, FIBO, Geneontology) have 10K–100K+ classes
- Slow queries degrade UX and drain LLM token budgets

**Mitigation:**
- AQL queries use **MDI indexes** on `[created, expired]` for temporal filtering
- AQL queries use `FLATTEN` aggregation to collapse multiple passes into one round-trip
- The effective-graph endpoint (`GET /{id}/effective`) uses weak ETags to short-circuit unchanged queries to `304 Not Modified`

**Not Yet Done:**
- Horizontal slicing of classes by first letter or namespace prefix (would require cache invalidation on write)
- Graph materialization (pre-compute the transitive closure; 100K+ classes ×1000+ edges per class = expensive)
- Denormalized summary caches (e.g., "class X has Y children") per ontology

**Recommendation:** Monitor in production. If 99th percentile query times exceed 5s on a 100K-class ontology, revisit.

#### 2.3.3 **LLM Extraction Cost Management**

**Current State:**
- Every extraction costs ~$5–20 in LLM tokens depending on document length
- No per-organization budget limits or quotas
- No cost estimation before extraction
- Cost tracking exists (`GET /runs/{id}/cost`) but not aggregated by user/org

**Why It Matters:**
- In a multi-tenant setup, a runaway extraction loop could cost $1000+ before being noticed
- No way to control costs or require approval before high-cost runs

**Not Yet Done:**
1. Pre-extraction cost estimate based on document length
2. Organization budget limits with warnings/blocks
3. Approval workflow for high-cost extractions
4. Cost aggregation by user/org/month

**Estimated Effort:** 1 week

**Honest Assessment:** This is important for SaaS deployments but less critical for single-tenant self-hosted. Defer unless you're building multi-tenant.

#### 2.3.4 **Visual Evidence Handling (Stream 13) — Residual Gaps**

**Current State:**
- Images in PDFs/PPTX are inventoried and sampled
- Two caption providers: OpenAI Vision (cloud) and Tesseract (on-prem)
- `tier1_visual_aware` strategy + extraction prompt include visual evidence

**Known Limitations:**
- **Scanned PDFs with text overlays** — OCR may extract garbled text; vision captions may miss details
- **Complex diagrams** — UML/ER diagrams as images lose semantic structure (become unstructured text descriptions)
- **Slide hierarchies** — PowerPoint outline/hierarchy encoded in SmartArt shapes is not extracted (only visual caption)

**Not Yet Done:**
1. Specialized diagram parser for UML/ER (extract `Entity`, `Relationship`, `Attribute` structure)
2. Hybrid OCR+vision (combine Tesseract bounding boxes with OpenAI descriptions)
3. Slide structure inference (detect title/content/hierarchy from layout positioning)

**Estimated Effort:** 2–3 weeks

**Recommendation:** These are nice-to-haves. The current approach (caption + text description) works acceptably for most documents. Revisit if extraction quality on visual-heavy documents falls below 70%.

#### 2.3.5 **MCP Server Completeness (Runtime AI Agent Tools)**

**Current State:**
- MCP server exposes 15+ tools (query_domain_ontology, run_extraction, explain_entity_match, etc.)
- Both stdio (dev) and SSE (production) transports work

**Known Limitations:**
1. **No streaming** — large query results are buffered in memory before return
2. **No subscription tools** — external agents must poll `/quality/history` for updates; no push notifications
3. **Limited authentication** — API key in SSE mode, no JWT/session support

**Estimated Effort:** 1 week (per item)

**Note:** This is important for external AI agents but less critical if the primary user is the web UI.

---

### 2.4 Design Debt & Technical Decisions to Revisit

#### 2.4.1 **Extraction Model Selection (Currently Claude Sonnet 4.6)**

**Current State:**
- Default model is `claude-sonnet-4-6` (switched from `claude-sonnet-4-20250514` which Anthropic deprecated)
- Alternative: `gpt-4o` via OpenAI

**Questions for Future Versions:**
1. **Cost vs Quality tradeoff** — is Sonnet 4.6 good enough, or should we default to GPT-4o?
2. **Fine-tuning** — should we offer fine-tuned variants for domain-specific extraction?
3. **Open-source models** — Llama 3, Mistral, etc. for self-hosted deployments?

**No Action Required Now:** Leave as configurable in `.env`. Monitor extraction quality scores (7-signal confidence) and revisit if avg < 0.7.

#### 2.4.2 **Confidence Scoring — Mechanical vs Learned**

**Current State:**
- 7-signal confidence scoring is **rule-based** (agreement rates, structure checks, faithfulness judge)
- Not machine-learned

**Why This Matters:**
- Rule-based scoring is transparent and auditable (every signal is documented)
- Learned scores (e.g., fine-tuned models on gold-standard datasets) could be more accurate
- Tradeoff: complexity vs interpretability

**Future Option:** Once the system has extracted 100+ ontologies, train a confidence predictor that learns from curator reject/approve patterns. Use as a secondary signal (ensemble with the rule-based score).

#### 2.4.3 **Graph Storage Model — PGT vs Native AQL**

**Current State:**
- Ontologies stored via ArangoRDF **PGT (Property Graph Transformation)**
- Collections: `ontology_classes`, `ontology_object_properties`, `ontology_datatype_properties`, plus edges
- ArangoRDF preserves OWL semantics (rdf:type, URI-to-concept mapping) while storing as ArangoDB documents

**Why PGT:**
- Standard approach for RDF → property-graph mapping
- Preserves OWL metamodel semantics
- Native AQL queries remain possible

**Limitation:**
- SPARQL queries require translation to AQL (not yet implemented)
- Some RDF features (named graphs within named graphs, reified statements) don't map cleanly

**No Action Needed:** PGT is the right choice. If SPARQL support becomes critical, add a translation layer or expose a SPARQL endpoint via Apache Jena or similar.

---

## Part 3: Competitive Positioning & Market Readiness

### 3.1 How AOE Compares to Competitors

| Dimension | AOE | TopBraid Enterprise | Protégé | OntoStudio |
|-----------|-----|-------------------|---------|-----------|
| **LLM-driven extraction** | ✅ Full (Claude + GPT-4o) | ⚠️ Manual + some automation | ❌ Manual | ❌ Manual |
| **Belief revision** | ✅ Phase 1–3 | ❌ | ❌ | ❌ |
| **Multi-tenant RBAC** | ❌ (mechanism exists, mostly unwired) | ✅ | ⚠️ (WebProtégé: basic sharing only) | ✅ |
| **Temporal versioning** | ✅ Edge-interval | ⚠️ (unverified) | ❌ | ❌ |
| **Open-source** | ✅ (GitHub) | ❌ | ✅ (Protégé, but dated) | ❌ |
| **Cloud-native** | ✅ Docker/K8s ready | ✅ | ❌ | ❌ |
| **Visual curation** | ✅ Sigma.js + React Flow | ✅ (proprietary) | ✅ | ✅ |
| **Constraint modeling** | ✅ OWL + SHACL | ✅ | ⚠️ OWL only | ✅ |
| **Import composition** | ✅ owl:imports + effective-graph | ✅ | ✅ | ✅ |

*Competitor-column entries are based on public marketing material and documentation and have not been independently verified; do not quote them externally without checking.*

**AOE Competitive Advantages:**
1. **LLM-powered extraction** — unique among open-source, matches TopBraid's automation level
2. **Belief revision** — no competitor offers this; critical for incremental ontology building
3. **Open-source + modern stack** — deployed as containers, scales horizontally
4. **Temporal versioning** — competitors use traditional versioning; edge-interval is novel

**AOE Gaps vs Competitors:**
1. **RBAC/multi-tenancy** — need to implement for SaaS
2. **SPARQL endpoint** — some users expect native SPARQL query
3. **Microservice architecture** — currently monolithic; scaling extraction separately from serving would help

### 3.2 Deployment Readiness

**Single-tenant self-hosted:** ✅ **Ready now** — *on a trusted internal network*
- Docker Compose setup works; all features functional
- Recommended: on-prem ArangoDB + Redis, internal network only
- Caveats before exposing beyond a trusted network: §2.1.4 (SSRF allowlist, admin-endpoint auth, backups)

**Multi-tenant SaaS:** ⚠️ **Not ready; ~4–5 weeks of sequential work (Phase 1)**
- RBAC enforcement mostly unwired (mechanism exists; see 2.1.2)
- Organization data isolation missing
- Cost accounting missing
- API rate limiting is basic (Redis only, no per-user quotas)

**Cloud-native Kubernetes:** ✅ **Mostly ready**
- Docker images build cleanly
- K8s manifests exist in `k8s/` (backend deployment, HPA, ingress)
- Needs: persistent volumes for ArangoDB and visualizer assets (session/rate-limit state lives in Redis — no additional database required)

---

## Part 4: Roadmap to Excellence

### Phase 1: Production Hardening (~4–5 weeks sequential; less with parallelization)

**Goal:** Make the system safe for multi-tenant SaaS deployment.

| Task | Effort | Criticality |
|------|--------|------------|
| **RBAC enforcement** (auth middleware, guard wiring across all routers, data isolation) | 2 weeks | **Critical** |
| **Security hardening** (SSRF allowlist for schema extraction, admin-endpoint auth, backup/restore runbook — see 2.1.4) | 1 week | **Critical** |
| **Mutation API for constraints** (approve/reject/edit endpoint + UI wiring) | 2–3 days | **Critical** |
| **Background consolidation job** (async task queue + scheduler) | 1 week | **High** |
| **Cost accounting & quotas** (per-org budget limits, pre-run estimates) | 1 week | **Medium** |

### Phase 2: Schema Alignment — ✅ SHIPPED (no roadmap time required)

PGT-aligned property collections (Stream 0, ADR-006) are already implemented: migrations `017`/`018`, split `ontology_object_properties`/`ontology_datatype_properties` collections, `rdfs_domain`/`rdfs_range_class` edges, split `attributes`/`relationships` extraction models, and the quality-metric recompute all exist in the codebase. See Part 1.

### Phase 3: UI Polish (3 weeks)

**Goal:** Full feature parity with TopBraid for ontology editing.

| Task | Effort | Criticality |
|------|--------|------------|
| **Stream 8 editor panels** (semantic zoom, property matrix, restriction editor, namespace manager) | 3 weeks | **Medium** |
| **Legacy route deprecation** (sunset `/curation/...` routes) | 1 week | **Medium** |

### Phase 4: Scalability (2 weeks)

**Goal:** Handle 100K+ class ontologies without performance degradation.

| Task | Effort | Criticality |
|------|--------|------------|
| **Query profiling on large ontologies** (identify bottlenecks) | 2 days | **Low** |
| **Materialization caching** (pre-compute summaries, invalidate on write) | 1 week | **Low** |
| **Pagination on `/edges` + `/effective`** (if large-ontology requests exceed 10% of traffic) | 1 week | **Low** |

---

## Part 5: Known Risks & Mitigations

### 5.1 Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **LLM API outage** (Anthropic/OpenAI down) | Medium | High | Retry with backoff exists. **Gap:** no offline/local-model fallback is implemented — add a work item if this risk matters for your deployment |
| **ArangoDB data corruption** | Low | Critical | **Gap:** no backup tooling exists today (see 2.1.4) — add scheduled `arangodump` + a tested restore procedure before production |
| **Runaway extraction loop** (cost $10K+) | Medium | High | Per-org budget limits + approval workflow (see 2.3.3) |
| **RBAC bypass** (authorization logic error) | Medium (if not tested) | Critical | Comprehensive RBAC tests (whitelist/blacklist matrix); pen test before SaaS launch |
| **PGT import failure** (RDF file with invalid triples) | Low | Medium | Pre-validation of RDF syntax; parse errors surface with actionable messages |

### 5.2 Data Integrity Risks

| Risk | Current Mitigation |
|------|-------------------|
| **Orphan edges** (class deleted, edge not expired) | Cascade deletion tested in 10+ scenarios; comprehensive docs in DELETION_AND_REFERENTIAL_INTEGRITY.md |
| **Temporal index corruption** (stale MDI index) | Repair migration `020_repair_mdi_temporal_indexes` runs on every startup |
| **Cross-ontology cycle on import** | Detection built into effective-graph computation; UI warns before creation |
| **Duplicate URIs in merged imports** | Conflict detection embedded in effective-graph response; canvas renders both as "conflict" pill |

---

## Part 6: Summary & Recommendations

### What's Excellent
1. **Temporal versioning with referential integrity** — industry-leading design
2. **Belief revision substrate** — unique feature enabling incremental ontology building
3. **LLM extraction + curation workflow** — seamless human-in-the-loop
4. **Test coverage & CI/CD** — production-grade quality gates
5. **Documentation & ADRs** — exceptional clarity on architectural decisions

### What Needs Work Before Production
1. **RBAC & multi-tenancy** — required for SaaS (guard exists; wiring + org isolation missing)
2. **Security hardening & backups** — SSRF allowlist, admin-endpoint auth, backup/restore runbook (§2.1.4)
3. **Constraint curation mutation API** — users can read but not edit constraints
4. **Background consolidation job** — belief revision Phase 4
5. **Cost management** — no budget limits or pre-run approval

### What Needs Work Before v1.1
1. **Stream 8 editor panels** — TopBraid-level editing experience
2. **Large-ontology testing** — validate 100K+ class performance

### Strategic Recommendation

**Target v1.0 deployment:** Single-tenant, self-hosted, internal use. Focus on Phase 1 hardening (RBAC, constraint mutation, consolidation, cost accounting) to unlock multi-tenant SaaS in v1.1.

**Value proposition for positioning:**
- *"The only open-source ontology platform with LLM-driven extraction AND belief revision, enabling incremental knowledge construction from unstructured documents."*

**Unique selling points:**
1. Belief revision (Phases 1–3 shipped; Phase 4 pending)
2. Temporal versioning with referential integrity
3. Two-tier ontology composition via owl:imports
4. Production-ready (TTL GC, tracing, alerting)
5. Modern stack (React, FastAPI, Docker, ArangoDB)

---

## Appendices

### A. Feature Completion Matrix

| Feature | Section | Status | Notes |
|---------|---------|--------|-------|
| Document ingestion | §6.1 | ✅ Complete | PDF/DOCX/PPTX/Markdown + visual asset inventory |
| LLM extraction pipeline | §6.2, §6.11 | ✅ Complete | 6-agent LangGraph with async/concurrent support |
| Tier 2 extensions | §6.3 | ✅ Complete | Domain context injection, strategy auto-detect |
| Visual curation | §6.4 | ⚠️ Partial | Workspace + curation routes; Stream 8 panels deferred |
| Temporal versioning | §6.5 | ✅ Complete | Edge-interval + VCR timeline |
| Visualizer customization | §6.6 | ✅ Complete | Themes, actions, saved queries |
| Entity resolution | §6.7 | ✅ Complete | Hand-rolled scoring + workspace overlay |
| Import/export | §6.8 | ✅ Complete | OWL/Turtle/JSON-LD/CSV export; standard catalog import |
| Deletion & soft-delete | §6.8 (referential integrity) | ✅ Complete | Cascade + temporal soft-delete |
| OWL/RDFS foundation | §6.8b | ⚠️ Partial | PGT import; rdf:type edges; no UI toggle yet |
| Schema extraction | §6.9 | ✅ Complete | Reverse-engineer from any ArangoDB |
| MCP server | §6.10 | ✅ Complete | 15+ tools; stdio + SSE transports |
| Agentic pipeline | §6.11 | ✅ Complete | Strategy/Extraction/Consistency/Quality/ER/Filter agents |
| Pipeline monitor | §6.12 | ✅ Complete | Real-time DAG + metrics + error log |
| Quality metrics | §6.13 | ✅ Complete | 7-signal scoring, health radar, history tracking, RAG recall (API + overlay all verified shipped) |
| Constraints (OWL+SHACL) | §6.14 | ⚠️ Partial | Extract/import/display/export; curation (I.7) deferred |
| Imports & composition | §6.15 | ✅ Complete | owl:imports tracking, effective-graph, catalog, conflict detection |
| Belief revision | Stream 11 | ⚠️ Partial (Phases 1–3 complete) | Phase 4 (consolidation scheduler) pending |
| Quality dashboard | Stream 4 | ✅ Complete | Unified dashboard, per-ontology quality, history, recall |
| Testing & CI | Stream 6 | ✅ Complete | 5-tier pipeline, 84%+ coverage |
| Production ops | Stream 7 | ✅ Complete | Tracing, alerting, GC, visualizer auto-install |
| Workspace (Sigma.js) | Stream 8 | ⚠️ Partial | Core rendering done; editor panels deferred |
| **OVERALL** | **PRD v4** | **~95%** | **Small tail of UI polish + RBAC** |

### B. Test Coverage Summary

| Layer | Coverage | Count | Key Suites |
|-------|----------|-------|-----------|
| **Backend units** | 84.0% | 1730 tests | extraction, temporal, constraints, ER, quality metrics |
| **Backend integration** | N/A | 120+ tests | migrations, extraction end-to-end, curation workflow |
| **Frontend units** | 55–70% | 590+ tests | components, hooks, utils (tiered by criticality) |
| **Frontend E2E** | N/A | 20+ tests | workspace flows, upload→extract→curate→promote |
| **CI pipeline** | 5 tiers | — | lint, unit, integration, E2E, Docker |

### C. Deployment Architectures

**Single-tenant (current):**
```
Frontend (Next.js) → Backend (FastAPI) → ArangoDB + Redis
```

**Multi-tenant (target v1.1):**
```
API Gateway (RBAC/auth) → Backend cluster (horizontal scaling) → ArangoDB cluster + Redis cluster
```

**Kubernetes:**
```
Ingress → Service → Deployment (replicas=3) → StatefulSet (ArangoDB) + StatefulSet (Redis)
```

---

## Conclusion

Arango-OntoExtract is a **sophisticated, well-engineered system** that advances the state of the art in LLM-driven ontology extraction. The architectural decisions (temporal versioning, belief revision, import composition) are sound and documented. The code quality is high (84%+ test coverage, comprehensive CI/CD).

**To achieve excellence** and compete with TopBraid/Protégé, the system needs:
1. **RBAC enforcement** for multi-tenant deployment
2. **Security hardening & backups** (SSRF allowlist, admin auth, restore runbook)
3. **Constraint mutation API** for curator control
4. **Stream 8 editor panels** for expert editing

**For single-tenant self-hosted deployment on a trusted internal network**, the system is **production-ready now** (with the §2.1.4 backup caveat). For SaaS, budget **~4–5 weeks** for Phase 1 hardening.

**Recommended next steps:**
1. Implement Phase 1 (RBAC wiring, security hardening + backups, constraint mutations, consolidation job)
2. Plan v1.1 roadmap around Stream 8 editor panels and large-ontology validation
3. Deploy to production staging; monitor extraction quality (aim for 7-signal confidence ≥ 0.75)
4. Gather user feedback; iterate on belief revision rules

**Market positioning:**
- "*The only open-source platform combining LLM extraction, belief revision, and temporal versioning for incremental ontology construction.*"
- Target early adopters in finance/pharma/supply-chain who value auditability and incremental refinement over speed.

---

**Report Date:** June 11, 2026
**Prepared by:** In-depth system review
**Next Steps:** User review, feedback, implementation prioritization
