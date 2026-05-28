# Contributing to Arango-OntoExtract

Thank you for your interest in contributing. This document explains
how to report issues, ask questions, and submit changes — for both
code and non-code contributions.

If you only want to **report a bug** or **ask a question**: jump to
[Reporting bugs and asking questions](#reporting-bugs-and-asking-questions).

---

## Project status and licensing

Arango-OntoExtract is currently distributed under a **private,
all-rights-reserved** license (see [`README.md`](README.md#license)).
This shapes how external contributions are accepted:

- **Anyone can file issues** — bug reports, questions, feature ideas,
  and documentation gaps are all welcome regardless of licensing.
- **Code contributions need a quick conversation first.** Open an
  issue describing what you want to work on (or comment on an
  existing one) so the maintainer can confirm scope and licensing
  posture before you invest time. Substantial PRs without a prior
  issue may be closed without review.
- **Documentation, samples, and triage contributions** are welcome
  via the normal PR flow — submitting a PR is taken as agreement
  that your contribution is released under the same terms as the
  rest of the repository.

The licensing model is expected to evolve; this section will be
updated when it does.

---

## Ways to contribute

You do **not** need to be a strong programmer to help. Useful
contributions include:

| Kind | Examples |
| --- | --- |
| Bug reports | Steps to reproduce, screenshots, log snippets, expected vs. actual behaviour |
| Questions | Anything unclear in `README.md`, `docs/user-guide.md`, the API docs, or the workspace UI |
| Documentation | Typo fixes, clarifications, missing setup steps, broken links, screenshots that no longer match the UI |
| Sample corpora | Small public-domain PDFs / DOCX / PPTX files that exercise an extraction edge case (see `samples/corpora/`) |
| Triage | Confirming someone else's bug report on your machine, adding repro details, narrowing scope |
| Tests | Adding regression tests for previously-fixed bugs, or filling coverage gaps in `backend/tests/unit/` |
| UI feedback | Findings from using the `/workspace` curation canvas — broken interactions, missing keyboard shortcuts, confusing legends |
| Code | Bug fixes, new features, refactors (please open an issue first) |

---

## Reporting bugs and asking questions

**File a GitHub Issue** in the repository:

- Browse existing issues:
  [github.com/arango-solutions/arango-ontoextract/issues](https://github.com/arango-solutions/arango-ontoextract/issues)
- Open a new issue:
  [new issue](https://github.com/arango-solutions/arango-ontoextract/issues/new)

A good bug report contains:

1. **What you did** — the smallest set of steps that reproduces the
   problem (URLs, curl commands, UI actions).
2. **What you expected** — the behaviour you thought you'd see.
3. **What actually happened** — error message, screenshot, log
   snippet. For backend errors, please include the relevant lines
   from the FastAPI log (the backend prints structured `structlog`
   output to stdout when run via `make backend`).
4. **Environment** — OS, browser (for UI bugs), Python and Node
   versions, whether you're on `main` or a release tag.

A good question is simply specific:

- ✅ "When I upload a `.pptx` with embedded charts, the
  `extraction_runs.stats.warnings` field shows `orphan_risk`. Where
  is that warning generated, and how do I tune the threshold?"
- ❌ "How does extraction work?"

For broad architectural questions or design discussions, start with
the documentation set in [`docs/`](docs/) and `PRD.md`; if those
don't answer it, open an issue and tag it `question`.

---

## Development setup

Prereqs: Python 3.11, Node 20+, Docker, `make`. macOS or Linux.
Windows users should work inside WSL2.

```bash
git clone https://github.com/arango-solutions/arango-ontoextract.git
cd arango-ontoextract
cp .env.example .env       # fill in ANTHROPIC_API_KEY / OPENAI_API_KEY
make setup                 # venv + npm install + pre-commit hooks
make infra                 # ArangoDB + Redis (Docker)
make migrate               # apply DB migrations
```

Then in two terminals:

```bash
make backend               # FastAPI on :8010 (override with BACKEND_PORT)
make frontend              # Next.js on :3000
```

The full `make` target list is `make help`. Key targets:

| Target | Purpose |
| --- | --- |
| `make setup` | First-time setup (venv + deps + hooks) |
| `make infra` / `make infra-down` | Start / stop ArangoDB + Redis |
| `make migrate` | Apply pending DB migrations |
| `make backend` / `make frontend` | Dev servers |
| `make test` | All backend tests |
| `make test-unit` | Backend unit tests only |
| `make lint` / `make format` / `make typecheck` | Backend code quality |
| `make type-check` | Backend + frontend type-check |
| `make pre-commit-run-all` | Run the Tier A hooks across the whole tree |
| `make pre-commit-run-pre-push` | Run the Tier B hooks (unit tests + mypy) |

Some uncommon document formats need a host binary; see
[`AGENTS.md` § System dependencies](AGENTS.md#system-dependencies)
for the install commands (LibreOffice for legacy `.doc`, optional
Tesseract for on-prem OCR captions).

---

## Project structure

The repo is a monorepo with two main applications plus shared docs:

```
arango-ontoextract/
├── backend/                FastAPI app, LangGraph extraction, ArangoDB access, MCP server
│   ├── app/                Source (config, db/, services/, extraction/, api/, mcp/)
│   ├── tests/              Unit / integration / e2e tests
│   └── migrations/         Numbered `NNN_description.py` modules
├── frontend/               Next.js 15 workspace UI
│   ├── src/app/            Routes (login, workspace; new workflows are overlays on /workspace)
│   ├── src/components/     React components (workspace canvas lives here)
│   └── e2e/                Playwright tests
├── docs/                   PRD, user guide, ADRs, operations runbooks, REMAINING_WORK_PLAN
├── scripts/                Tooling (smoke test, branch protection, dual-push setup)
├── configs/                Caddy + monitoring configs
├── k8s/                    Kubernetes manifests (deployment examples)
├── infra/monitoring/       Prometheus + Alertmanager rules
└── samples/corpora/        Synthetic + real test corpora for the extraction pipeline
```

The repo-level [`AGENTS.md`](AGENTS.md) is the single source of truth
for module boundaries, configuration rules, and host dependencies.
[`backend/AGENTS.md`](backend/AGENTS.md) covers backend-specific
invariants (config singleton, repository pattern, temporal
mutations).

---

## Coding conventions

Conventions are codified as Cursor rules under
[`.cursor/rules/`](.cursor/rules/). They apply whether you use
Cursor, another IDE, or no IDE at all — these are the rules
maintainers enforce in review. The most important ones:

| Rule | Summary |
| --- | --- |
| `read-before-write.mdc` | Match existing patterns. Search for a helper before writing one. |
| `modularity-and-structure.mdc` | File-size caps; tests next to source; configs under `configs/`; scripts under `scripts/` |
| `test-what-you-touch.mdc` | Every code change ships with a corresponding test change |
| `comprehensiveness-over-simplification.mdc` | Handle error paths, edge cases, empty/null inputs; don't ship happy-path-only |
| `wiring-over-deletion.mdc` | Unused vars/imports usually mean **incomplete** features — wire them up, don't delete |
| `surface-dont-guess.mdc` | When requirements are ambiguous, ask in the issue/PR instead of guessing |
| `verify-before-done.mdc` | Build, run, and exercise the code path before claiming done |
| `checkpoint-regularly.mdc` | Small commits with descriptive messages; push often |
| `incremental-over-atomic.mdc` | Small, individually-working slices over one big change |
| `mock-fidelity.mdc` | Test mocks must mirror real signatures; never use `any` or `# type: ignore` to silence them |
| `ui-architecture.mdc` | All frontend workflows are object-centric on `/workspace` — no new top-level routes for canvas-adjacent tasks |

### Backend (Python)

- Python 3.11; type-checked with `mypy --strict` via
  `make typecheck` (the pre-push hook uses `--ignore-missing-imports`).
- Linted and formatted with `ruff` (pinned in
  `backend/pyproject.toml` `[project.optional-dependencies] dev`).
- Configuration: read **only** through
  `backend/app/config.py::settings`. Do not call `os.environ`
  elsewhere.
- Database: go through `backend/app/db/` repositories. Never import
  `python-arango` directly from routes or services.
- LLM calls: go through `backend/app/extraction/`. Never call OpenAI /
  Anthropic SDKs directly from routes.

### Frontend (TypeScript / React)

- Next.js 15, React, TypeScript strict mode.
- Linted with ESLint (`--fix --max-warnings=0` in the pre-commit
  hook); type-checked with `tsc --noEmit` in the pre-push hook.
- UI workflows go on the `/workspace` canvas. New top-level routes
  are only for non-workspace surfaces (`/login`, `/logout`). See
  `.cursor/rules/ui-architecture.mdc` for the full contract.
- Mutations are initiated from **right-click context menus**;
  left-click is select-only. See the rule above for the canonical
  icon set and the per-entity menu builder pattern under
  `frontend/src/components/workspace/contextMenus/`.

### Test requirements

For any source change, the corresponding test change must:

1. **Run.** `make test-unit` (or the targeted file) must pass.
2. **Exercise the changed path.** Adding a test that asserts only
   "function does not throw" is not enough — the assertion must
   distinguish the new behaviour from the old.
3. **Cover error paths.** New `if err != nil` branches, new
   validation, new fallback logic — all need explicit tests.
4. **Stay deterministic.** No reliance on wall-clock time, network
   calls to live services, or test ordering.

Integration tests that touch ArangoDB live under
`backend/tests/integration/` and need `make test-infra-up` first.
E2E tests under `backend/tests/e2e/` and `frontend/e2e/` exercise
the full stack and run in CI; they are not required for every PR.

---

## Git workflow and commit messages

The full hook + branch-protection design lives in
[`docs/git-hygiene.md`](docs/git-hygiene.md). The short version:

1. Branch from `main`: `git checkout -b feat/short-description` or
   `fix/short-description`.
2. Commit early, push often. Each commit should be **one logical
   change** and pass tests on its own.
3. Use **conventional commit** messages:

   ```text
   type(scope): short summary in imperative mood

   Longer body explaining *why* the change is needed and what it
   does at a high level. Reference the issue number if applicable.
   ```

   Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`,
   `perf`, `ci`. Scopes are typically a module name
   (`backend`, `frontend`, `extraction`, `workspace`, `stream13`,
   `mcp`, `docs`, etc.).

4. The local hooks run automatically on commit and push:
   - **Pre-commit** (~3–10s): formatters + linters on staged files.
   - **Pre-push** (~30s–2m): unit tests + mypy + conditional Docker
     smoke. Use `git push --no-verify` only as a last resort; CI
     will still gate the PR.

5. Open a pull request:
   - **Title**: same conventional-commit format as the squash commit.
   - **Body**: summary (what + why), test plan (commands you ran
     and what you verified), screenshots for UI changes, and a link
     to the issue this closes.
   - Keep PRs **small**: under ~500 lines of diff where possible.
     If the change is bigger, split it into a stack of incremental
     PRs (`.cursor/rules/incremental-over-atomic.mdc`).

6. CI must be green before merge. The required status checks are
   listed in
   [`docs/git-hygiene.md` § PROFILE=team](docs/git-hygiene.md#profileteam--pr--status-checks-profile).

7. The maintainer (currently Arthur Keen) reviews and merges.
   Address review feedback by **adding** commits (don't squash
   during review — that loses the history); the merge will squash
   if appropriate.

---

## Working with AI coding assistants

This repo is set up to be agent-friendly:

- [`AGENTS.md`](AGENTS.md) at the repo root and inside
  `backend/` document module boundaries, invariants, and host deps.
- [`.cursor/rules/`](.cursor/rules/) encodes the coding conventions
  as machine-readable rules that Cursor (and similar agents) load
  automatically.
- The `frontend/` UI uses object-centric context menus and floating
  panels — see `.cursor/rules/ui-architecture.mdc` before
  proposing UI changes.

If you use an AI assistant for your contribution, please:

- **Verify before claiming done.** Run the tests, type-check, and
  exercise the changed feature yourself before opening the PR
  (`.cursor/rules/verify-before-done.mdc`).
- **Disclose AI-assisted contributions** in the PR description.
  This is not a barrier to merging — it's metadata that helps
  reviewers calibrate.
- **Read the diff.** You are responsible for the contents of your
  PR regardless of how it was authored.

---

## Code of conduct

Be civil, be specific, and assume good faith. Issues and PRs that
contain personal attacks, harassment, or off-topic content will be
closed.

---

## Maintainer

- Arthur Keen — primary maintainer ([@ArthurKeen](https://github.com/ArthurKeen))

For licensing or partnership conversations that don't fit a GitHub
issue, reach out through GitHub or the contact information listed
on the maintainer's profile.

---

## Acknowledgements

Thanks to everyone who has filed an issue, suggested an
improvement, or sent a fix our way. A non-exhaustive list lives in
the [commit history](https://github.com/arango-solutions/arango-ontoextract/graphs/contributors).
