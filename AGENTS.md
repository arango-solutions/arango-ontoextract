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

## Engineering rules

These are the working rules for anyone — human or agent — changing this repo.
They are mirrored from `.cursor/rules/*.mdc` so that agents which read
`AGENTS.md` (Claude Code, Codex) get the same instructions Cursor gets; Cursor
does not read this file and Claude does not read `.cursor/rules/`. **Both copies
are tracked — if you change a rule, change it in both places.**

### Read before write
Match the codebase, don't fight it. Before writing anything, search for how it is
already done: existing patterns, utilities, similar types, endpoint shapes, test
helpers, error conventions. If a helper exists, call it — don't write a second
one. Reuse the established naming, file organisation, error handling and logging
style. Your job is to make the codebase *more* consistent, not less.

### Surface, don't guess
A wrong guess implemented is worse than an honest question asked. Try to resolve
uncertainty yourself first (codebase, docs, tests). If it is still unclear —
ambiguous requirements, several valid approaches, a breaking change, an
architectural choice, unclear scope — state what you understand, what is
unclear, and the options with trade-offs, then wait. Confidence is not a
substitute for the user's knowledge.

### Incremental over atomic
Small steps that individually work beat large steps that eventually work. Each
increment must be verifiable, reversible, reviewable in under five minutes, and
deployable on its own. At every checkpoint the tree must compile, pass tests and
be functional. Refactor by adding alongside, migrating callers one at a time,
then removing the old. Warning signs: more than ~5 files at once, an hour with no
commit, or a change you cannot describe in one sentence — slice smaller.

### Test what you touch
Changed code means changed behaviour, and behaviour needs a test. New function →
unit test. New endpoint → integration test. Bug fix → a regression test that
would have caught it. Refactor → existing tests must pass, and if they don't
cover the path, add coverage *first*. For every file you modify, check there is a
test file, that it covers what you changed, and that you actually ran it. Tests
must be deterministic, fast, isolated, clearly named, and assert behaviour rather
than absence of a crash. "I tested manually" and "I'll add tests later" are not
acceptable.

### Verify before claiming done
If you didn't run it, you didn't ship it. Before saying work is complete: build
it, test it, actually exercise the changed path, and look at the output. Frontend:
`npm run type-check`, `lint`, `test`, `build`. Backend: the test suite, `ruff`,
`mypy`. Claiming "I've implemented X" without verifying X works is not a mistake,
it's a false statement.

### Comprehensiveness over simplification
This is production software; simplification is the enemy of completeness. Every
change must address error handling (no swallowed errors — every handler does
something, with messages saying what failed, with what input, and why), edge
cases (empty/nil, boundaries, invalid input, unicode, concurrency), configuration
rather than hardcoding for anything that could differ across environments, test
completeness, observability (structured logging, metrics, health), security
(validate at boundaries, no secrets in code or logs, authz checks), documentation,
UI states (loading / error / empty / success, plus accessibility), data integrity
(validation, constraints, transactions, idempotency) and performance (pagination,
caching, indexing). Never ship happy-path-only, empty catch blocks, magic numbers,
copy-paste divergence, or `console.log` debugging.

### Wiring over deletion
Unused code usually means a missing feature, not garbage. A linter warning about
an unused import, variable or parameter is a request to *finish the
implementation*, not to delete it. Do not delete "unused" code without proving it
is genuinely obsolete. An unused `ctx` gets passed down; an unused `err` gets
handled; an unused prop gets wired to rendering or logic; a `useEffect` missing
dependencies gets a stabilised dependency via `useCallback`/`useMemo` — never an
`eslint-disable`. Anything added in the previous turn is mandatory to use. A
passing lint check on a broken feature is a failure.

### Modularity and structure
Everything has a place. Size limits: source 1500 lines, tests 2000, config 500,
docs 1000 — past that, split. Split also when you cannot find things without
searching or the file holds unrelated concerns. Placement: shared types in the
core/types module, tests beside their source (except E2E), configs in `configs/`,
scripts in `scripts/` — not the repo root. Each module should have one
responsibility, a minimal public API, hidden internals, and be independently
testable. A new developer should be able to find any file from what it does,
without searching.

### Mock fidelity
A test that passes against a wrong-signature mock is a test that didn't run.
Before mocking any production symbol, open the real declaration and read it; the
mock's constructor args, method signatures and field types must mirror the real
ones so a signature change breaks the test. Never infer a mock's shape from how
the test reads it, and never use `any` to make a mock "flexible" — that disables
the safety net. This rule exists because of a real bug: a mocked `ApiError` took
`(status, message)` while the real class takes `(status, body)`; every test was
internally consistent, CI was green, and the error-handling assertions proved
nothing. Jest specifics are in `frontend/AGENTS.md`.

### Checkpoint regularly
Commit early, push often; large uncommitted changesets are disasters waiting to
happen. Commit when a feature is complete, when tests pass, before a risky
refactor, before switching tasks, and before ending a session. One logical change
per commit — if you can't describe it in one line it's too big. Use scoped,
descriptive messages (`fix(curation): atomic reparent endpoint`), not "updates" or
"wip".

Frontend-specific rules — the object-centric workspace architecture (overlays not
routes, left-click selects / right-click acts, lens-vs-layout separation) and the
Arango brand palette — live in `frontend/AGENTS.md`.

> Not mirrored here: `.cursor/rules/workflow.mdc` (PRD-drift and shared-memory
> protocol) is already covered for Claude by `CLAUDE.md` and its hooks, so
> mirroring it would create a third copy.

## Remotes: the org repo is primary (changed 2026-09-08)

| Remote | URL | Role |
|---|---|---|
| `origin` | `arango-solutions/arango-ontoextract` | **primary** — fetch/pull source, and the first of two push URLs |
| `fork` | `ArthurKeen/arango-ontoextract` | mirror — second push URL on `origin`, plus a remote of its own |

`origin` is configured with **two push URLs**, so a single `git push` lands on the
org repo *and* the fork. `main` tracks `origin/main`, so `git pull` and `git status`
read from arango-solutions. Run `bash scripts/setup-dual-push-remotes.sh` to
(re)establish this layout; it is idempotent.

> **This reverses the previous model.** Until 2026-09-08 `origin` was the personal
> fork, `upstream` was the org repo, and a `protect-upstream-push` pre-push hook
> refused any push of `main` to arango-solutions unless HEAD sat on a `vX.Y.Z` tag —
> so the org repo only ever saw tagged milestones. That hook is now **unwired** (the
> block is kept, commented, in `.pre-commit-config.yaml`) because ordinary pushes are
> now *meant* to reach the org repo. If you restore it, also point `main` back at the
> fork or every push of `main` will be refused.

### Cutting a release

Releases are still tagged, and `make release-to-org TAG=vX.Y.Z` is still the way to
do it — it refuses unless `TAG` matches `vX.Y.Z`, you are on a clean `main`, and
local `main` is a fast-forward of the org remote (`make sync-from-org` first if not);
then runs the full Tier A + Tier B gates (ruff, eslint, jest, tsc, pytest, mypy,
Docker smoke), tags HEAD, and pushes `main` + tag together. What has changed is that
the org repo no longer *waits* for that: it now tracks `main` continuously, and the
tag marks the milestone rather than gating the push.

Before tagging: bump `backend/app/__init__.py` (the single source of truth for the
version) and move the `CHANGELOG.md` `[Unreleased]` block under the new version.
A rejected `git push upstream main` is the `protect-upstream-push` hook working
as designed; do not reach for `ALLOW_UPSTREAM_PUSH=1` to get around it.

Full detail — the three enforcement tiers, branch protection profiles, and
`sync-from-org` — is in `docs/git-hygiene.md`.

## Deeper docs

- `backend/AGENTS.md` — backend module boundaries
- `docs/git-hygiene.md` — three-tier commit hygiene + the dual-remote release flow
- `PRD.md` — product requirements
- `docs/REMAINING_WORK_PLAN.md` — backlog streams
- `docs/container-manager-deployment.md` — manual-packaging deployment via Arango Container Manager (`make package-arango-manual[-all]`)
- `docs/path-prefix-routing.md` — `SERVICE_URL_PATH_PREFIX` end-to-end (frontend `basePath` / `withBasePath` / `backendUrl`, backend strip middleware, `NextStaticExportApp`)
- `docs/adr/007-spa-html-fallback.md` — why `NextStaticExportApp` exists
