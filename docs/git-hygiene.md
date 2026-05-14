# Git commit hygiene — three-tier enforcement

> **"If a hook is slow, it gets bypassed. Real enforcement lives on the server."**

We use three layers, each with a clear job. Skipping any layer is a defect.

| Tier | Where | When | Purpose | Bypass |
| --- | --- | --- | --- | --- |
| A | Local pre-commit hook | every `git commit` | Fast formatters + linters on **staged files only** (~3–10s) | `git commit --no-verify` |
| B | Local pre-push hook | every `git push` | Unit tests + mypy + conditional Docker smoke (~30s–2m) | `git push --no-verify` |
| C | GitHub branch protection | every PR merge | Required CI status checks; admins included | None — server-side |

Tiers A and B are **fast feedback**. Tier C is the **real enforcement**.

## Setup

```bash
make setup              # bootstraps venv + frontend deps + hooks (one-shot)
# or, on an existing clone:
make install-git-hooks
```

`make install-git-hooks` runs `pre-commit install --install-hooks` from
`backend/.venv`, which writes both `.git/hooks/pre-commit` and
`.git/hooks/pre-push`. The hook configuration lives in
`.pre-commit-config.yaml` at the repo root.

## What runs when

### Tier A — `pre-commit` stage

Triggered by `git commit`. Operates only on staged files.

| Hook | Files | Action |
| --- | --- | --- |
| `trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`, `check-yaml`, `check-toml`, `check-json` | all | hygiene |
| `ruff` | `backend/**/*.py`, `benchmarks/**/*.py` | `ruff --fix` |
| `ruff-format` | same | format |
| `eslint` (local) | `frontend/**/*.{ts,tsx,js,jsx}` | `eslint --fix --max-warnings=0` |

If any hook fixes a file, the commit aborts and the fix is left in your working
tree — re-stage and commit again.

### Tier B — `pre-push` stage

Triggered by `git push`. Reads the diff between your branch tip and the remote
tip and only runs hooks whose `files:` regex matches at least one changed file.

| Hook | Trigger files | Action |
| --- | --- | --- |
| `jest-unit` | `frontend/**/*.{ts,tsx,js,jsx,json}` | `npm test -- --ci --coverage=false` |
| `tsc-noemit` | `frontend/**/*.{ts,tsx}` | `npx tsc --noEmit` (catches type errors ESLint cannot) |
| `pytest-unit` | `backend/**/*.py`, `benchmarks/**/*.py` | `pytest tests/unit/ -q` |
| `mypy` | `backend/**/*.py` | `mypy app/ --ignore-missing-imports` |
| `smoke-test` | `Dockerfile`, `nginx*.conf`, `backend/entrypoint`, `backend/app/main.py`, `backend/pyproject.toml`, `backend/uv.lock`, `frontend/next.config.*`, `frontend/package(-lock).json`, `scripts/smoke-test.sh` | `bash scripts/smoke-test.sh` (full Docker stack) |

The smoke test only fires when **build inputs** change. Code-only pushes skip
it locally; CI still runs the full smoke job on every PR.

### Tier C — server-side (the only real enforcement)

GitHub branch protection on `main`, configured by `scripts/setup-branch-protection.sh`.
Requires `gh` and `jq`, and must be run as a repo admin. The script supports
two profiles via the `PROFILE` env var; pick the one that matches your
team size.

#### `PROFILE=solo` (default) — minimal floor

The `solo` profile only blocks the genuinely catastrophic actions; direct
pushes by collaborators are allowed because the local pre-push hook
(`protect-upstream-push`) is the real gate. CI still runs unconditionally
and shows pass/fail badges, but does not block.

```bash
scripts/setup-branch-protection.sh           # PROFILE=solo by default
# or, if your repo lives elsewhere:
REPO=org/repo BRANCH=main scripts/setup-branch-protection.sh
```

Applies:

- `allow_force_pushes: false`
- `allow_deletions: false`
- Everything else: not enforced (no required reviews, no required CI gates)

Pair this with the [Solo-dev workflow](#solo-dev-workflow) section below.

#### `PROFILE=team` — PR + status-checks profile

Use once a second developer joins. Requires PR with 1 approval, all CI
checks green, conversation resolution, no force-push, admins included.

```bash
PROFILE=team scripts/setup-branch-protection.sh
```

Applies:

- **Required status checks** (must be green before merge):
  - `Lint Backend`
  - `Lint Frontend`
  - `Pre-commit hooks`
  - `Unit Tests`
  - `Frontend unit tests`
  - `Integration Tests`
  - `Unified Docker image build + smoke`
  - `Backend E2E tests`
- `strict: true` (branch must be up to date with `main` before merge)
- `enforce_admins: true` (no override)
- `required_approving_review_count: 1`
- `dismiss_stale_reviews: true`
- `required_conversation_resolution: true`
- `allow_force_pushes: false`
- `allow_deletions: false`

These names must match the `name:` fields of the jobs in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Keep them in sync.

## Solo-dev workflow

When you're the only developer on a repo, the PR-based flow is overhead
without a payoff (you're reviewing your own code). The solo-dev workflow
splits the world into two remotes and uses Tier B as the real gate:

| Remote | Role | Push frequency |
| --- | --- | --- |
| `origin` (your personal fork) | Active development scratchpad | Every commit |
| `upstream` (org/release repo) | Release artifact, externally visible | Only on tagged releases |

Daily commits flow to `origin` only. The org repo stays clean — it sees
your code only when you cut a release with `make release-to-org`.

### One-shot setup

```bash
# 1) Reconfigure remotes so `git push` only ever hits the personal fork.
make setup-dual-push-remotes
#    Detects the dual-push misconfig (origin with two push URLs) and the
#    arango-solutions remote, fixes both. Renames arango-solutions ->
#    upstream by GitHub fork-workflow convention.

# 2) Apply the minimal branch-protection profile on the org repo.
scripts/setup-branch-protection.sh        # PROFILE=solo by default
```

### Daily workflow

```bash
git commit -m "wip: trying a thing"
git push                                  # → origin (personal fork) only
```

That's it. `upstream` sees nothing.

### Cutting a release

```bash
make release-to-org TAG=v0.4.0
```

`release-to-org` is a fail-fast pipeline:

1. Refuses unless `TAG` matches `vX.Y.Z`.
2. Refuses unless on `main` with a clean working tree.
3. Refuses unless local `main` is a fast-forward of `upstream/main`
   (run `make sync-from-org` first if not).
4. Runs `make pre-commit-run-all` (Tier A) and `make pre-commit-run-pre-push`
   (Tier B: jest + tsc + pytest + mypy + smoke).
5. Creates the annotated tag (or reuses an existing one at HEAD).
6. Pushes `main` and the tag to `upstream` in a single command.

The local `protect-upstream-push` pre-push hook then verifies that the
ref being pushed is either a non-protected branch, a release-shaped tag,
or `main` with HEAD pointing at a release tag. Any other push to
`upstream` is refused.

### Pulling someone else's changes from upstream

If a collaborator merges a PR on the org repo (rare in solo mode, but
possible), pull it into your fork:

```bash
make sync-from-org
```

This fetches `upstream/main`, fast-forwards your local `main`, and pushes
the result to `origin`. Refuses non-fast-forward merges so you notice
divergence instead of papering over it.

### Escape hatch

If you really need to push to `upstream` outside the release flow (e.g. a
hotfix the framework can't model), the protect hook surfaces the bypass
in its refusal message:

```bash
ALLOW_UPSTREAM_PUSH=1 git push upstream <ref>
```

The bypass is loud (banner in stderr) so it's hard to use accidentally.

### Portability to other repos

The four files that comprise this workflow are designed to drop into any
dual-push repo:

| File | What it does | Configuration |
| --- | --- | --- |
| `scripts/setup-dual-push-remotes.sh` | Fixes remote layout | `ORIGIN_URL`, `UPSTREAM_URL`, `UPSTREAM_PROTECTED_URL_PATTERN`, `UPSTREAM_REMOTE_NAME`, `DROP_REMOTES` env vars |
| `scripts/githooks/protect-upstream-push.sh` | Pre-push gate | `UPSTREAM_PROTECTED_URL_PATTERN`, `UPSTREAM_PROTECTED_BRANCH`, `UPSTREAM_RELEASE_TAG_PATTERN` env vars |
| `Makefile` (release-to-org / sync-from-org / setup-dual-push-remotes) | Release + sync targets | `ORIGIN_REMOTE`, `UPSTREAM_REMOTE`, `RELEASE_BRANCH` env vars |
| `scripts/setup-branch-protection.sh` (`PROFILE=solo`) | Server-side floor | `REPO`, `BRANCH`, `PROFILE` env vars |

Drop them in, set the env vars to match, run the two setup commands.

## Common operations

```bash
# Run all pre-commit-stage hooks against the whole tree (e.g. after editing
# .pre-commit-config.yaml or upgrading hook versions):
make pre-commit-run-all

# Only the pre-commit (fast) hooks:
backend/.venv/bin/pre-commit run --all-files

# Only the pre-push (heavier) hooks:
backend/.venv/bin/pre-commit run --hook-stage pre-push --all-files

# Bump hook versions (then commit the change to .pre-commit-config.yaml):
backend/.venv/bin/pre-commit autoupdate

# Run only the smoke test:
make smoke-test
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pre-commit: command not found` | `cd backend && .venv/bin/pip install -e ".[dev]"` (adds `pre-commit` to dev deps) |
| ESLint hook fails with `Cannot find module` | `cd frontend && npm ci` |
| `mypy` complaints about missing stubs | the hook uses `--ignore-missing-imports`; if a real type error, fix it; if not, narrow with `# type: ignore[…]` |
| Smoke test fails with `port already in use` | something else is on `:8000` (`docker ps`); stop it and retry |
| Need to commit a WIP that fails Tier A | `git commit --no-verify` (last resort; CI will still gate the PR) |
| Need to push a WIP that fails Tier B | `git push --no-verify` (last resort; CI will still gate the PR) |
| Tier C blocks a hotfix | merge through a PR with passing CI; do **not** weaken branch protection |

## Why this design

- **Pre-commit must be fast.** Anything slower than ~10s gets bypassed reflexively.
  We keep only formatters and linters on staged files at this layer.
- **Pre-push runs once per push, not per commit.** Suitable for unit tests
  and full-package mypy, which are too slow to run on every commit.
- **Smoke test is conditional locally** to keep `git push` snappy on code-only
  changes; CI runs it unconditionally so coverage doesn't slip.
- **Branch protection is the only thing developers cannot bypass.** Both
  Tier A and Tier B are conveniences for fast feedback. Tier C is policy.

## See also

- [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) — hook configuration
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — CI gates
- [`scripts/smoke-test.sh`](../scripts/smoke-test.sh) — Docker smoke test
- [`scripts/setup-branch-protection.sh`](../scripts/setup-branch-protection.sh) — Tier C provisioning (`PROFILE=solo` or `PROFILE=team`)
- [`scripts/setup-dual-push-remotes.sh`](../scripts/setup-dual-push-remotes.sh) — solo-dev remote layout
- [`scripts/githooks/protect-upstream-push.sh`](../scripts/githooks/protect-upstream-push.sh) — solo-dev pre-push gate
