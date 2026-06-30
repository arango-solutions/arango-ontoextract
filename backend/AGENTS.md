# Backend — FastAPI Application

Python backend for the AOE platform. FastAPI + ArangoDB + LangGraph.

## What This Is
The server-side application: REST API, LLM extraction pipeline, database operations, MCP server, and business logic for ontology management.

## What This Is NOT
- Not the frontend (that's `frontend/`)
- Not the ArangoDB visualizer customization scripts (those go in `scripts/setup/`)
- Not a standalone CLI tool — all functionality is exposed via API or MCP

## Boundaries
- All external communication goes through `app/api/` routes or the MCP server
- Database access goes through `app/db/` — never import `python-arango` directly in routes or services
- LLM calls go through `app/extraction/` — never call LLM providers directly in routes
- Configuration comes from `app/config.py` via the `settings` singleton — never read env vars directly

## Key Invariants
- Pydantic models validate all API inputs and LLM outputs
- Every ontology mutation creates a new temporal version (never in-place updates on versioned collections)
- `org_id` filtering is mandatory on all tenant-scoped queries
- Tests live in `tests/` mirroring the `app/` structure (unit/, integration/, e2e/)

## Belief Revision (Stream 11)
The Incremental Belief Revision (IBR) substrate spans several modules:
- `app/extraction/agents/belief_revision.py` — LangGraph node (mechanical + LLM phases)
- `app/services/revision_actions.py` — accept/reject/modify business logic (IBR.16)
- `app/services/revision_safety.py` — published-item guard, circuit breaker, dry-run, consolidation cursor (IBR.18)
- `app/services/consolidation.py` — background sweep over rules + decay + stale-belief scan (IBR.17)
- `app/api/revisions.py` — REST surface for the curator inbox
- `app/api/admin.py` — admin-only consolidation + circuit breaker endpoints
- `app/mcp/tools/belief_revision.py` — six MCP tools for external agents (IBR.20)
- `app/db/repositories/temporal_revisions.py::supersede` — Levi-identity helper used by accept/modify

See `docs/adr/008-belief-revision-substrate.md` for the architectural rationale and per-task implementation status.

## Ontology API package (`app/api/ontology/`)
The ontology REST surface (~3.6k lines) is split into cohesive sub-routers
(Stream 14 CQ.3). All endpoints still mount under `/api/v1/ontology` via the
single `router` assembled in `__init__.py`.

- `library.py` — library CRUD, releases, documents, constraints, search, orgs
- `domain.py` — domain / local / staging / promote
- `entities_read.py` — class / property / edge reads + live-edge helpers
- `mutations.py` — class / property / edge create-update-delete + export
- `imports_io.py` — RDF file import jobs + create-empty
- `imports.py` — import-graph management, effective view, catalog
- `schema_temporal.py` — schema extraction/diff + temporal snapshot/diff/history
- `_shared.py` — patch-relevant deps (`get_db`, `run_aql`, `paginate`,
  `import_from_file`, the `*_repo` modules). Sub-routers call these via
  attribute access (`_shared.get_db(...)`) so a single
  `patch("app.api.ontology._shared.<name>")` rebinds them everywhere.

`include_router` order in `__init__.py` preserves the original route
precedence (static paths before `/{ontology_id}` captures); the invariant is
guarded by `tests/unit/test_ontology_router_assembly.py`. When adding an
endpoint, extend the matching sub-router — do not reintroduce a monolith.

## PRD Reference
Full spec: `PRD.md` — this backend implements Sections 6–7 (features + API spec)
