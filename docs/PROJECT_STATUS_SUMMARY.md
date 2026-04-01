# Arango-OntoExtract (AOE) — Project Status Summary

**Date:** March 31, 2026
**Version:** v0.1.0 + 40 incremental commits
**Repository:** https://github.com/arangoml/ontology_generator

---

## What Is AOE?

AOE is an LLM-driven ontology extraction and curation platform built on ArangoDB. It takes unstructured documents (PDF, DOCX, Markdown), automatically extracts formal domain ontologies (OWL 2 / RDFS), and provides a visual interface for domain experts to review, refine, and manage the extracted knowledge.

## What's Working Now

**End-to-end workflow operational:** Upload a document → LLM extracts ontology classes, properties, and relationships → curators review and approve → ontology published to the library.

### Core Capabilities

| Capability | Status | Highlights |
|-----------|--------|------------|
| **Document Ingestion** | Complete | PDF, DOCX, Markdown upload with semantic chunking and vector embeddings |
| **LLM Extraction Pipeline** | Complete | 6-agent LangGraph pipeline: Strategy Selector → Extraction Agent → Consistency Checker → Quality Judge → Entity Resolution → Pre-Curation Filter |
| **Multi-Signal Confidence** | Complete | 7-signal scoring: cross-pass agreement, LLM-as-Judge faithfulness, semantic validity, structural quality (relationship richness), description quality, provenance strength, property agreement |
| **Visual Curation** | Complete | Interactive graph editor with node/edge actions, VCR timeline for ontology time travel, diff view, provenance display |
| **Ontology Editor** | Complete | Standalone graph editor at `/ontology/[id]/edit` with Add Class, Add Property, inline rename, reparent |
| **Pipeline Monitor** | Complete | Real-time 6-step DAG with polling, metrics (tokens, cost, entities, confidence, completeness, agreement rate), error log |
| **Ontology Library** | Complete | Browse, search (ArangoSearch full-text), filter by tier/tags, quality panel with health score, export (OWL/Turtle, JSON-LD, CSV) |
| **Multi-Document Ontologies** | Complete | Build one ontology from multiple documents; add documents incrementally |
| **Temporal Versioning** | Complete | Full version history on every class/property/edge; VCR timeline with additive entity playback |
| **ArangoDB Visualizer** | Complete | Auto-installed themes, canvas actions, saved queries (temporal-aware) per ontology graph |
| **MCP Server** | Complete | Runtime tools for AI agents to query ontologies, trigger extractions |
| **Quality Metrics** | Mostly Complete | Health score (0–100), quality panel in library; dedicated dashboard page pending |
| **Deletion & Integrity** | Complete | Temporal soft-delete with cross-ontology cascade; system reset for dev/demo |

### Architecture

```
Frontend (Next.js 15 / React / TypeScript / Tailwind)
    ↕ REST API + WebSocket
Backend (FastAPI / Python / LangGraph / LangChain)
    ↕ python-arango
ArangoDB (multi-model: document + graph + vector + search)
    ↕ MCP
AI Agents (Claude, GPT-4o, external MCP clients)
```

### Key Technical Decisions

- **Graph visualization:** Currently React Flow (prototype); target migration to Sigma.js + graphology (WebGL) for scalability
- **Vector search:** ArangoDB FAISS-based vector index (IVF) on chunk embeddings
- **Temporal model:** Edge-interval time travel with `created`/`expired` timestamps and MDI-prefixed indexes
- **Confidence scoring:** LLM-as-Judge faithfulness evaluation + semantic validation pass (domain/range, disjointness checks)
- **Concurrent extraction:** Fully async pipeline (`ainvoke`) — multiple documents can be extracted simultaneously

## What's Not Done Yet

| Area | Estimated Effort | Priority |
|------|-----------------|----------|
| Ontology Imports & Dependencies (`owl:imports`, standard catalog) | 1.5 weeks | P1 |
| Entity Resolution (real `arango-entity-resolution` integration) | 1.5 weeks | P1 |
| Quality Dashboard (`/quality` page, history, gold-standard recall) | 3 days | P1 |
| OWL Constraints & SHACL Shapes | 1 week | P2 |
| Schema Extraction from ArangoDB | 1 week | P2 |
| Ontology Release Management (semver, breaking change detection, revert) | 1 week | P1 |
| Testing & CI (GitHub Actions, coverage gates, Playwright E2E) | 1 week | P2 |
| Production Polish (OpenTelemetry, alerting, Docker, benchmarks) | 1 week | P2 |
| Sigma.js Migration (WebGL graph rendering, TopBraid-class editor) | 2–3 weeks | Future |

**Estimated remaining: ~7–8 weeks to v1.0.0**

## Key Documents

| Document | Location | Purpose |
|----------|----------|---------|
| Product Requirements | `PRD.md` | Full specification with 15 feature sections, 13 use cases, RBAC matrix |
| Remaining Work Plan | `docs/REMAINING_WORK_PLAN.md` | Detailed task breakdown for each work stream |
| Implementation Plan | `IMPLEMENTATION_PLAN.md` | Phased plan with coverage verification table |
| Deletion & Referential Integrity | `docs/DELETION_AND_REFERENTIAL_INTEGRITY.md` | Temporal soft-delete cascade rules for all mutation scenarios |
| Sample Documents | `docs/samples/` | 5 rich domain documents (1,300 lines) across finance, supply chain, healthcare |

## How to Run

```bash
# Backend (no --reload for extraction to work)
cd backend && ALLOW_SYSTEM_RESET=true .venv/bin/uvicorn app.main:app --port 8001

# Frontend
cd frontend && NEXT_PUBLIC_DEV_MODE=true npm run dev
```

- Backend: http://localhost:8001
- Frontend: http://localhost:3000
- ArangoDB: configured via `.env` (cluster or local)

## Demo Flow

1. Open http://localhost:3000 → landing page shows backend status
2. Navigate to Upload → drop `docs/samples/financial-services-domain.md`
3. Extraction auto-starts → watch progress in Pipeline Monitor (6 steps, ~3-5 min)
4. When complete, go to Ontology Library → click the ontology card
5. See class hierarchy with differentiated confidence scores (not all the same!)
6. Click "Edit Graph" → full interactive editor with Add Class, VCR timeline
7. Upload `docs/samples/financial-services-operations.md` targeting the same ontology → incremental enrichment
