# api/ — REST API Route Handlers

FastAPI routers defining all HTTP endpoints.

## What This Is
Thin route handlers that validate input (via Pydantic), delegate to services, and format responses. One file per endpoint group:

- `auth.py`, `admin.py`, `orgs.py`, `notifications.py`, `metrics.py`, `rate_limit.py`
- `documents.py`, `extraction.py`, `ontology.py`, `curation.py`, `quality.py`, `er.py`
- `health.py`, `errors.py`, `dependencies.py`
- WebSocket endpoints: `ws_extraction.py`, `ws_curation.py`, `ws_broadcast.py`

## What This Is NOT
- Not where business logic lives — routes call `services/`, never implement logic directly
- Not where database queries live — routes should call repositories under `db/` (or services), never raw AQL inline
- Not the MCP server interface (that's a separate process under `app/mcp/`)

## Boundaries
- Every route function receives validated Pydantic models and returns Pydantic models or dicts
- Database access goes through repositories under `app/db/` or, preferably, a service layer; routes should not assemble raw AQL
- Exception: `health.py` may call `db.client.get_db()` directly for readiness checks
- All list endpoints must support cursor-based pagination (see PRD Section 7.8)
- All errors must use the standard error response format (see PRD Section 7.8)
- Configuration is read via `app.config.settings`, never `os.getenv` (see `app/AGENTS.md`)

## Size & complexity targets
- **Target:** route files stay under ~300 lines and individual handlers under ~50 lines.
- **Hard ceiling:** the workspace `modularity-and-structure.mdc` rule of 1500 lines applies.
- **Known exception:** `ontology.py` is currently ~2300 lines and bundles library, class CRUD, edges, properties, releases, imports, schema-extract, snapshot/diff, and search routes. It is on the cleanup backlog — when adding a new endpoint group there, prefer extracting an existing group into its own router file (`ontology_library.py`, `ontology_releases.py`, …) rather than appending another section.

## Key Invariants
- All tenant-scoped routes must accept and enforce `org_id`
- Routes must not catch and swallow exceptions — let FastAPI's exception handlers manage errors
- WebSocket endpoints for real-time updates go here too (extraction progress, curation events)

## PRD Reference
- Endpoint spec: PRD Sections 7.1–7.7
- Pagination / errors / rate limiting: PRD Section 7.8
- WebSocket events: PRD Section 7.8 (WebSocket Events table)
