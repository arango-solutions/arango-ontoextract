# Arango-OntoExtract (AOE)

LLM-driven ontology extraction and curation platform built on ArangoDB.

AOE ingests unstructured documents, extracts formal domain ontologies via large language models, and provides a visual curation dashboard for domain experts to review, edit, and promote extracted knowledge into a production graph.

## Architecture

```
Frontend (React/Next.js)  →  Backend (FastAPI)  →  ArangoDB (multi-model)
                                  ↕
                          LLM (Claude / GPT)
```

**Two-tier ontology model:**

- **Tier 1 — Domain Ontologies:** Standardized industry schemas (shared across organizations)
- **Tier 2 — Localized Extensions:** Organization-specific sub-graphs linked to Tier 1 via `rdfs:subClassOf`

See [PRD.md](PRD.md) for the full product requirements document.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- An Anthropic and/or OpenAI API key

## Quick Start

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd ontology_generator

# 2. Copy environment config
cp .env.example .env
# Edit .env with your API keys and preferences

# 3. One-command setup (creates venv, installs deps, copies .env)
make setup

# 4. Start ArangoDB + Redis
make infra

# 5. Start the backend (port 8000)
make backend

# 6. In a second terminal, start the frontend (port 3000)
make frontend
```

After startup:

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Frontend | http://localhost:3000 |
| ArangoDB UI | http://localhost:8529 |

## Project Structure

```
ontology_generator/
├── backend/                  # Python / FastAPI
│   ├── app/
│   │   ├── api/              # Route handlers (health, documents, extraction, ontology, curation)
│   │   ├── db/               # ArangoDB client and schema initialization
│   │   ├── extraction/       # LLM extraction pipeline (TODO)
│   │   ├── models/           # Pydantic models (documents, ontology, curation)
│   │   ├── services/         # Business logic (TODO)
│   │   ├── config.py         # Settings from environment
│   │   └── main.py           # FastAPI app entry point
│   ├── tests/
│   └── pyproject.toml
├── frontend/                 # React / Next.js
│   ├── src/app/              # App router pages
│   ├── package.json
│   └── tsconfig.json
├── .env.example              # Environment variable template
├── docker-compose.yml        # ArangoDB + Redis
├── Makefile                  # Dev commands
└── PRD.md                    # Product requirements document
```

## Development Commands

```bash
make help        # List all commands
make setup       # First-time setup (venv + deps)
make infra       # Start ArangoDB + Redis
make infra-down  # Stop infrastructure
make infra-reset # Stop infrastructure and delete data
make backend     # Run backend dev server (hot-reload)
make frontend    # Run frontend dev server
make test        # Run backend tests
make lint        # Lint backend code
make format      # Auto-format backend code
make typecheck   # Type-check backend
make clean       # Remove caches and build artifacts
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness probe (DB connected) |
| `POST` | `/api/v1/documents/upload` | Upload a document |
| `GET` | `/api/v1/documents/{doc_id}` | Get document status |
| `GET` | `/api/v1/documents/{doc_id}/chunks` | List document chunks |
| `POST` | `/api/v1/extraction/run` | Trigger ontology extraction |
| `GET` | `/api/v1/extraction/runs/{run_id}` | Get extraction run status |
| `GET` | `/api/v1/ontology/domain` | Get domain ontology graph |
| `GET` | `/api/v1/ontology/local/{org_id}` | Get org's local ontology |
| `GET` | `/api/v1/ontology/staging/{run_id}` | Get staging graph for curation |
| `POST` | `/api/v1/ontology/staging/{run_id}/promote` | Promote staging to production |
| `POST` | `/api/v1/curation/decide` | Record a curation decision |
| `GET` | `/api/v1/curation/merge-candidates/{run_id}` | Get entity resolution suggestions |

Full interactive docs available at `/docs` when the backend is running.

## Configuration

All configuration is via environment variables (see [.env.example](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `ARANGO_HOST` | `http://localhost:8529` | ArangoDB connection URL |
| `ARANGO_DB` | `ontology_generator` | Database name |
| `ANTHROPIC_API_KEY` | — | Anthropic API key for Claude |
| `OPENAI_API_KEY` | — | OpenAI API key for embeddings |
| `LLM_EXTRACTION_MODEL` | `claude-sonnet-4-20250514` | Model for ontology extraction |
| `EXTRACTION_PASSES` | `3` | Number of LLM passes for consistency |
| `ER_VECTOR_SIMILARITY_THRESHOLD` | `0.85` | Min similarity for merge candidates |

## License

Private — all rights reserved.
