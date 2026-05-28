# Agent / contributor guide

## Layout

| Area | Role |
|------|------|
| `backend/` | FastAPI API, LangGraph extraction, ArangoDB access, MCP server |
| `frontend/` | Next.js 15 workspace UI, graph canvas, curation |
| `backend/migrations/` | Ordered `NNN_description.py` modules with `up(db)` — applied via `make migrate` |
| `docs/` | PRD references, ADRs, user guide, remaining-work plans |
| `scripts/` | Tooling (e.g. ArangoDB Visualizer asset install) |

## Conventions

- **Config:** `backend/app/config.py` (`Settings`) — do not read env vars elsewhere.
- **DB:** Repositories under `backend/app/db/`; temporal mutations follow `NEVER_EXPIRES` (`sys.maxsize`).
- **UI:** Primary actions via context menus on `/workspace`; avoid new top-level routes except `/login`.
- **Tests:** Unit tests mock I/O; integration tests use Arango (see `tests/conftest.py`). Run `make test` from repo root.

## System dependencies

Pure-Python deps live in `backend/pyproject.toml`. A few formats need a host-level binary:

| Format | Backend dep | Host dep | macOS install | Debian/Ubuntu install |
| --- | --- | --- | --- | --- |
| `.pdf` | `pymupdf` | none | — | — |
| `.docx` | `python-docx` | none | — | — |
| `.pptx` | `python-pptx` | none | — | — |
| `.doc` (legacy Word) | `python-docx` (post-conversion) | LibreOffice (`soffice`) | `brew install --cask libreoffice` | `apt install libreoffice-core` |
| `.md` | (stdlib) | none | — | — |

The `.doc` parser fails loudly with an actionable install hint if `soffice` is missing — it does not silently skip.

### Optional: image-aware extraction (Stream 13)

Embedded images / scanned pages can be OCR'd or vision-captioned when
`visual_caption_provider` is set. Default is `"none"` — zero extra
host deps. Providers are lazy-loaded so the default install never
imports the SDK or probes the host binary.

| Provider | `visual_caption_provider` | Backend dep | Host dep | macOS install | Debian/Ubuntu install |
| --- | --- | --- | --- | --- | --- |
| OpenAI Vision | `openai_vision` | `openai` (already a base dep) | none | — | — |
| Tesseract OCR | `tesseract` | `pip install -e .[ocr]` (`pytesseract`) | Tesseract (`tesseract`) | `brew install tesseract` | `apt install tesseract-ocr` |

Both providers fail loudly with structured `failure_reason` values
(`missing_api_key`, `missing_package`, `missing_binary`, etc.) and a
one-shot install-hint log so missing prerequisites surface
immediately on first ingestion rather than silently degrading to
placeholders. See `backend/app/services/visual_captions_*.py` and
`docs/REMAINING_WORK_PLAN.md` Stream 13.

## Deeper docs

- `backend/AGENTS.md` — backend module boundaries
- `PRD.md` — product requirements
- `docs/REMAINING_WORK_PLAN.md` — backlog streams
- `docs/container-manager-deployment.md` — manual-packaging deployment via Arango Container Manager (`make package-arango-manual[-all]`)
- `docs/path-prefix-routing.md` — `SERVICE_URL_PATH_PREFIX` end-to-end (frontend `basePath` / `withBasePath` / `backendUrl`, backend strip middleware, `NextStaticExportApp`)
- `docs/adr/007-spa-html-fallback.md` — why `NextStaticExportApp` exists
