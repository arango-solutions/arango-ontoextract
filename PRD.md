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
7. [API Specification](#7-api-specification-backend)
   - 7.1–7.7 Endpoint groups
   - 7.8 API Conventions (Pagination, Errors, Rate Limiting, WebSocket)
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
| `ontology_constraints` | Versioned `owl:Restriction` / cardinality / value restrictions | `_key`, `property_id`, `constraint_type` (owl:minCardinality\|owl:maxCardinality\|owl:allValuesFrom\|etc.), `constraint_value`, `created`, `expired`, `ttlExpireAt` |

#### Edge Collections (Temporal — All Edges Carry `created`/`expired`)

| Collection | From → To | Purpose |
|------------|-----------|---------|
| `subclass_of` | `ontology_classes` → `ontology_classes` | `rdfs:subClassOf` / `skos:broader` hierarchy |
| `equivalent_class` | `ontology_classes` → `ontology_classes` | `owl:equivalentClass` / `skos:exactMatch` mappings |
| `has_property` | `ontology_classes` → `ontology_properties` | `rdfs:domain` — class → property associations |
| `extends_domain` | `ontology_classes` (local) → `ontology_classes` (domain) | Tier 2 → Tier 1 linkage (specialization via `rdfs:subClassOf` or `skos:narrower`) |
| `extracted_from` | `ontology_classes` → `chunks` | Provenance: which chunk produced this class |
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
| `domain_ontology` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | `subclass_of`, `equivalent_class`, `has_property`, `related_to` | Tier 1 base ontologies (all library ontologies combined) |
| `ontology_{ontology_id}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | `subclass_of`, `equivalent_class`, `has_property`, `related_to` | Per-ontology named graph for isolation within the library |
| `local_ontology_{org_id}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | `subclass_of`, `equivalent_class`, `has_property`, `extends_domain`, `related_to` | Per-org Tier 2 extensions |
| `staging_{run_id}` | `ontology_classes`, `ontology_properties`, `ontology_constraints` | All ontology edge types | Draft graphs pending curation |

### 5.2 Ontology Library Architecture

The Domain Ontology Library is not a single monolithic graph — it is a **managed collection of distinct ontologies** that can be composed, versioned, and queried independently or together.

**Multi-Ontology Isolation Strategy:**

ArangoRDF's PGT transformation stores OWL/RDFS/SKOS ontologies in ArangoDB using an **OWL metamodel strategy**: `owl:Class` instances become documents in vertex collections, OWL predicates (`rdfs:subClassOf`, `owl:ObjectProperty`, etc.) become edges, and OWL axioms are preserved as document properties. Multiple ontologies share the same collections, distinguished by IRI namespace. Since IRI namespaces alone are insufficient for reliable isolation (ontologies may reference each other's IRIs), AOE adds an explicit **application-level isolation layer**:

| Mechanism | How It Works |
|-----------|-------------|
| **`ontology_id` field** | Every `ontology_classes` and `ontology_properties` document carries an `ontology_id` linking to `ontology_registry`. All queries filter by this field. |
| **Per-ontology named graph** | Each imported ontology gets its own ArangoDB named graph (`ontology_{id}`), enabling graph traversals scoped to a single ontology. |
| **Combined domain graph** | The `domain_ontology` graph is a union view across all active library ontologies, used when Tier 2 extraction needs full domain context. |
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
| `expired` | `float` (unix timestamp or sentinel) | When this version was superseded |

Sentinel value for "current": `NEVER_EXPIRES = sys.maxsize` (9223372036854775807)

- **Current** (active) entities: `expired == 9223372036854775807`
- **Historical** entities: `expired` is a finite timestamp

#### Versioned Entity Fields

Every `ontology_classes` and `ontology_properties` versioned document carries:

| Field | Type | Purpose |
|-------|------|---------|
| `created` | float | Unix timestamp when this version became active |
| `expired` | float | Unix timestamp when superseded (or `NEVER_EXPIRES` for current) |
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
| `expired` | float | When this edge was superseded (or `NEVER_EXPIRES` for current) |
| `ttlExpireAt` | float \| null | TTL expiration for historical edges (null for current) |

#### MDI-Prefixed Indexes (Temporal Range Optimization)

Multi-dimensional indexes accelerate point-in-time queries on `[created, expired]` intervals:

```json
{
  "type": "mdi-prefixed",
  "fields": ["created", "expired"],
  "fieldValueTypes": "double",
  "prefixFields": ["created"],
  "sparse": false,
  "name": "idx_ontology_classes_mdi_temporal"
}
```

Deployed on: all versioned vertex collections (`ontology_classes`, `ontology_properties`, `ontology_constraints`) **and** all ontology edge collections (`subclass_of`, `has_property`, `extends_domain`, `equivalent_class`, `related_to`).

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

### 6.2 Domain Ontology Extraction (Tier 1)

**Description:** LLM-driven generation of core industry ontologies from standard documents.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-2.1 | LLM output enforced via strict JSON schema mapping to OWL constructs | Output validates against Pydantic models representing `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`, `rdfs:subClassOf`, and optionally `skos:Concept` |
| FR-2.2 | Extraction schema supports OWL 2 / RDFS / SKOS constructs | `owl:Class`, `rdfs:subClassOf`, `owl:equivalentClass`, `owl:ObjectProperty`, `owl:DatatypeProperty`, cardinality restrictions, and optionally `skos:Concept`, `skos:broader`, `skos:prefLabel` for taxonomy-style ontologies |
| FR-2.3 | Multi-pass extraction with self-consistency check | LLM runs N passes; only concepts appearing in ≥ M passes are included (configurable) |
| FR-2.4 | RAG-augmented extraction | LLM prompt includes relevant chunks retrieved via vector similarity for context |
| FR-2.5 | Import via ArangoRDF PGT transformation | Generated OWL/RDFS → ArangoDB via `ArangoRDF.rdf_to_arangodb_by_pgt()`, preserving OWL class hierarchy, property domains/ranges, and constraints |
| FR-2.6 | Extraction results land in staging graph | Never written directly to production; always to `staging_{run_id}` first |
| FR-2.7 | Each extracted ontology registered in library | New `ontology_registry` entry created with source metadata; all classes/properties tagged with `ontology_id` |

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
4. Create a per-ontology named graph (`ontology_{id}`) scoping only this ontology's vertices and edges
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
| Graph rendering | **React Flow** (native React) or **Cytoscape.js** via `react-cytoscapejs` wrapper | Both provide React component APIs |
| Timeline slider (VCR) | Custom component using `react-slider` or `@radix-ui/react-slider` | Native React |
| Diff visualization | Built on top of the graph renderer with overlay layers | React state-driven |
| Layout algorithms | Dagre, ELK, or Cola.js (layout engines compatible with both React Flow and Cytoscape) | Layout computed, rendered via React |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-4.1 | Render staging graph as interactive React component | Nodes = classes, edges = relationships; zoom, pan, filter by type/tier; implemented as a React component using React Flow or `react-cytoscapejs` |
| FR-4.2 | Node actions: approve, reject, rename, edit properties, merge | Each action recorded in `curation_decisions` with before/after state |
| FR-4.3 | Edge actions: approve, reject, retype, reverse direction | Edge modifications validated against ontology constraints |
| FR-4.4 | Batch operations | Select multiple nodes/edges for bulk approve/reject |
| FR-4.5 | Diff view between staging and production | Side-by-side or overlay showing what's new, changed, removed |
| FR-4.6 | Promote staging → production | One-click promotion of approved entities from staging to production graph |
| FR-4.7 | Provenance display | Clicking a node shows which document chunk(s) it was extracted from, with highlighted source text |
| FR-4.8 | Confidence scores | Each extracted entity displays LLM confidence; low-confidence entities visually highlighted |
| FR-4.9 | All visualization libraries are React-compatible | No vanilla JS graph libraries that require manual DOM manipulation; all rendering through React component tree |

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

### 6.7 Entity Resolution & Deduplication

**Description:** Automated detection and suggested merging of overlapping ontology concepts across tiers and extraction runs. Built on the **`arango-entity-resolution`** library, which already implements blocking, similarity scoring, clustering, merging, and MCP tooling for ArangoDB.

**Leveraged Library: `arango-entity-resolution`**

The library provides a config-driven pipeline (`ConfigurableERPipeline`) with pluggable strategies at each stage. AOE configures it for ontology concept matching rather than building ER from scratch.

**Blocking Stage** (candidate pair generation):

AOE uses the library's blocking strategies to narrow the search space before expensive pairwise scoring:

| Strategy | Library Class | AOE Usage |
|----------|--------------|-----------|
| **Vector ANN** | `VectorBlockingStrategy` + `ANNAdapter` | Primary: cosine similarity on class label/description embeddings via ArangoDB HNSW vector search |
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
| FR-7.3 | Vector cosine similarity on class embeddings | `ANNAdapter` with ArangoDB HNSW vector search; threshold configurable (default ≥ 0.85) |
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
| FR-8.3 | Ontology Library browser in UI | List all registered ontologies with stats (class count, property count, status); drill into any ontology's class hierarchy |
| FR-8.4 | Ontology composition for organizations | Organizations select which domain ontologies from the library apply to them; Tier 2 extraction uses only selected base ontologies as context |
| FR-8.5 | Export ontology to OWL/TTL/SKOS | Any approved ontology graph exportable as valid OWL 2 Turtle (or SKOS if taxonomy-style) via rdflib serialization |
| FR-8.6 | Export to JSON-LD | For web/API consumption |
| FR-8.7 | Export to CSV/Excel | For non-technical stakeholders |
| FR-8.8 | Cross-ontology dependency tracking | When ontology A references classes from ontology B (via `owl:imports` or cross-namespace URIs), the dependency is recorded in the registry |

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

---

## 7. API Specification (Backend)

### 7.1 Document Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/upload` | Upload document; returns `doc_id` and starts async processing |
| `GET` | `/api/v1/documents/{doc_id}` | Get document metadata and processing status |
| `GET` | `/api/v1/documents/{doc_id}/chunks` | List chunks with optional embedding similarity search |
| `GET` | `/api/v1/documents` | List all documents (paginated, filterable by org/status) |
| `DELETE` | `/api/v1/documents/{doc_id}` | Soft-delete document and associated chunks |

### 7.2 Extraction Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/extraction/run` | Trigger extraction on a document or set of chunks |
| `GET` | `/api/v1/extraction/runs` | List all extraction runs (paginated, filterable by status/org/date) |
| `GET` | `/api/v1/extraction/runs/{run_id}` | Get extraction run status, current agent step, and summary stats |
| `GET` | `/api/v1/extraction/runs/{run_id}/steps` | Get per-agent-step detail: inputs, outputs, token usage, errors, duration |
| `GET` | `/api/v1/extraction/runs/{run_id}/results` | Get extracted entities from a run |
| `POST` | `/api/v1/extraction/runs/{run_id}/retry` | Retry a failed extraction run |
| `GET` | `/api/v1/extraction/runs/{run_id}/cost` | Get LLM cost breakdown: tokens by model, estimated cost |

### 7.3 Ontology Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ontology/domain` | Get full domain ontology graph (paginated) |
| `GET` | `/api/v1/ontology/domain/classes` | List domain classes with filters |
| `GET` | `/api/v1/ontology/local/{org_id}` | Get organization's local ontology |
| `GET` | `/api/v1/ontology/staging/{run_id}` | Get staging graph for curation |
| `POST` | `/api/v1/ontology/staging/{run_id}/promote` | Promote approved staging entities to production |
| `GET` | `/api/v1/ontology/export` | Export ontology in OWL/TTL/JSON-LD format |
| `POST` | `/api/v1/ontology/import` | Import external ontology file (OWL/TTL/RDF) via ArangoRDF |
| `GET` | `/api/v1/ontology/library` | List all ontologies in the registry |
| `GET` | `/api/v1/ontology/library/{ontology_id}` | Get ontology detail (classes, properties, stats) |
| `DELETE` | `/api/v1/ontology/library/{ontology_id}` | Deprecate an ontology in the library |
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
| Temporal versioning logic | Version creation, `expired` field updates, edge re-creation, `NEVER_EXPIRES` sentinel | Mock ArangoDB client (`python-arango` calls) |
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
│   ├── test_temporal_versioning.py # Version creation, expiration, sentinel values
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
| `VectorBlockingStrategy` + `ANNAdapter` | ANN/HNSW cosine vector blocking | Point at ontology class embedding field; configure similarity threshold |
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
| Interval semantics (`created`/`expired`/`NEVER_EXPIRES`) | **Already adopted** — same interval semantics used in edge-interval approach | None |
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
| **NEVER_EXPIRES** | Sentinel value (`sys.maxsize` = 9223372036854775807) indicating a versioned entity or edge is the current active version |
| **MDI-Prefixed Index** | Multi-dimensional index on `[created, expired]` fields that accelerates temporal range queries (point-in-time snapshots, interval overlaps) |
| **TTL Aging** | Automatic garbage collection of historical (expired) versioned documents via ArangoDB TTL indexes on the `ttlExpireAt` field |
| **VCR Timeline** | Interactive timeline slider in the curation dashboard that enables scrubbing through ontology history, with playback controls and diff visualization |
| **Point-in-Time Snapshot** | Query returning the complete ontology state as it existed at a specific historical timestamp |
| **Golden Record** | The merged, consolidated entity created by the entity resolution process from a cluster of duplicate candidates |
| **WCC** | Weakly Connected Components — graph algorithm used to group duplicate entity candidates into clusters |
| **Cursor-Based Pagination** | Pagination using opaque cursors (tokens) rather than page numbers; more efficient for large result sets and concurrent inserts |
| **Schema Migration** | A versioned, forward-only script that modifies the ArangoDB schema (adding collections, indexes, fields); tracked via `_system_meta` |
| **ConfigurableERPipeline** | The main entry point of the `arango-entity-resolution` library — a config-driven pipeline with pluggable blocking, scoring, clustering, and merging stages |
