.PHONY: help setup dev infra backend frontend test test-unit test-integration test-all test-infra-up test-infra-down lint format typecheck type-check clean migrate docker-build docker-up docker-down docker-unified-build docker-unified-run docker-unified-up docker-unified-down package-arango-manual package-arango-manual-all sync-requirements check-requirements install-git-hooks pre-commit-run-all pre-commit-run-pre-push smoke-test setup-branch-protection

# Optional repo-root .env (BACKEND_PORT, etc.). Safe if missing.
-include .env

# Default 8010 so port 8000 can stay free for other tools (e.g. Arango Cypher Transpiler).
# Override: `make backend BACKEND_PORT=8000`
BACKEND_PORT ?= 8010

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: install-git-hooks ## First-time project setup (venv + deps + .env + git hooks)
	@test -f .env || cp .env.example .env && echo "==> Created .env from .env.example"
	@echo "==> Done. Run 'make infra' to start ArangoDB + Redis."

# Split out so install-git-hooks can depend on the venv + frontend deps without
# `setup` having to repeat itself. Detects uv (preferred — `make setup` and
# entrypoint both use uv) and falls back to python -m pip via ensurepip.
.PHONY: ensure-deps
ensure-deps:
	@echo "==> Ensuring Python venv + dev deps..."
	@bash scripts/ensure-backend-deps.sh
	@echo "==> Ensuring frontend deps..."
	cd frontend && npm install

dev: ## API + Next in one terminal (Ctrl+C stops both). Uses BACKEND_PORT (default 8010).
	@BACKEND_PORT=$(BACKEND_PORT) bash scripts/dev-local.sh

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

infra: ## Start ArangoDB + Redis (docker compose)
	docker compose up -d

infra-down: ## Stop infrastructure
	docker compose down

infra-reset: ## Stop infrastructure and delete volumes
	docker compose down -v

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

backend: ## Run backend dev server (port from BACKEND_PORT, default 8010; set in .env or CLI)
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

migrate: ## Apply pending database migrations
	cd backend && .venv/bin/python -m migrations.runner

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

frontend: ## Run frontend dev server
	cd frontend && npm run dev

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

test: ## Run all backend tests
	cd backend && .venv/bin/pytest tests/ -v

test-unit: ## Run backend unit tests only
	cd backend && python -m pytest tests/unit/ -v

test-integration: ## Run backend integration tests (requires Docker test services)
	cd backend && python -m pytest tests/integration/ -v

test-all: test-unit test-integration ## Run unit then integration tests

test-infra-up: ## Start test ArangoDB + Redis containers
	docker compose -f docker-compose.test.yml up -d

test-infra-down: ## Stop test containers
	docker compose -f docker-compose.test.yml down

lint: ## Lint backend code
	cd backend && .venv/bin/ruff check . && .venv/bin/mypy app/ --ignore-missing-imports

format: ## Format backend code
	cd backend && .venv/bin/ruff format app/ tests/

typecheck: ## Type-check backend
	cd backend && .venv/bin/mypy app/

type-check: ## Type-check backend + frontend
	cd backend && .venv/bin/mypy app/ --ignore-missing-imports && cd ../frontend && npx tsc --noEmit

# ---------------------------------------------------------------------------
# Benchmarks (Ontology Extraction)
# ---------------------------------------------------------------------------

benchmark-tests: ## Run unit tests for the benchmark harness (no corpora needed)
	backend/.venv/bin/pytest benchmarks/ontology_extraction/tests/ -v

fetch-corpora: ## Download minimal benchmark corpora into samples/corpora/external/
	./scripts/fetch-corpora.sh

fetch-corpora-full: ## Download full benchmark corpora (several GB)
	./scripts/fetch-corpora.sh --full

benchmark: ## Run Re-DocRED benchmark with the mock adapter (CI-friendly, requires fetch-corpora)
	backend/.venv/bin/python -m benchmarks.ontology_extraction.run_benchmark \
		--dataset redocred --adapter mock --limit 20

benchmark-full: ## Run WebNLG benchmark with the real AOE adapter (requires backend + infra + LLM keys)
	backend/.venv/bin/python -m benchmarks.ontology_extraction.run_benchmark \
		--dataset webnlg --adapter aoe --limit 100

# ---------------------------------------------------------------------------
# Docker (Production)
# ---------------------------------------------------------------------------

docker-build: ## Build backend + frontend production images
	docker build -t aoe-backend:latest ./backend
	docker build -t aoe-frontend:latest ./frontend

docker-up: ## Start production stack (docker-compose.prod.yml)
	docker compose -f docker-compose.prod.yml up -d

docker-down: ## Stop production stack
	docker compose -f docker-compose.prod.yml down

# ---------------------------------------------------------------------------
# Unified Docker Image (ArangoCD Container Management)
# ---------------------------------------------------------------------------

docker-unified-build: ## Build unified AOE Docker image (backend + frontend + nginx)
	docker build -t aoe:latest -f Dockerfile .

docker-unified-run: docker-unified-build ## Build and run unified AOE image
	docker run -p 8000:8000 --env-file .env aoe:latest

docker-unified-up: ## Start unified AOE with docker-compose
	docker compose -f docker-compose.dev.yml up -d

docker-unified-down: ## Stop unified AOE with docker-compose
	docker compose -f docker-compose.dev.yml down

# ---------------------------------------------------------------------------
# Arango Container Manager — manual packaging (tar.gz + uv + pyproject.toml)
# ---------------------------------------------------------------------------

package-arango-manual: ## Build aoe-myservice.tar.gz (flat: entrypoint + pyproject at archive root). Pass PACKAGE_INCLUDE_ENV=1 to opt into bundling repo .env (default: skipped to avoid leaking secrets).
	bash scripts/package-arango-manual.sh

package-arango-manual-all: ## Same + Next static export (SERVICE_URL_PATH_PREFIX from repo .env via include). Pass PACKAGE_INCLUDE_ENV=1 to bundle .env.
	PACKAGE_INCLUDE_FRONTEND=1 SERVICE_URL_PATH_PREFIX="$(SERVICE_URL_PATH_PREFIX)" bash scripts/package-arango-manual.sh

# ---------------------------------------------------------------------------
# Git hygiene — three-tier enforcement (see docs/git-hygiene.md)
# Tier A: pre-commit hook (fast, staged files)
# Tier B: pre-push hook (unit tests + conditional Docker smoke)
# Tier C: GitHub branch protection (real enforcement; admins included)
# ---------------------------------------------------------------------------

install-git-hooks: ensure-deps ## Install pre-commit + pre-push hooks via the pre-commit framework
	chmod +x scripts/githooks/eslint-staged.sh scripts/smoke-test.sh scripts/setup-branch-protection.sh
	@# An older revision used core.hooksPath=scripts/githooks; clear it so the
	@# pre-commit framework writes hooks to the standard .git/hooks/ location.
	-git config --unset core.hooksPath 2>/dev/null || true
	backend/.venv/bin/pre-commit install --install-hooks
	@echo "==> Git hooks installed (pre-commit + pre-push). Bypass (emergency only):"
	@echo "    git commit --no-verify   /   git push --no-verify"

pre-commit-run-all: ## Run all Tier A hooks against every tracked file (use after editing .pre-commit-config.yaml)
	backend/.venv/bin/pre-commit run --all-files

pre-commit-run-pre-push: ## Run Tier B (pre-push) hooks against every tracked file
	backend/.venv/bin/pre-commit run --hook-stage pre-push --all-files

smoke-test: ## Tier B/CI: unified Docker image build + curl/WS smoke (same as CI unified-image job)
	bash scripts/smoke-test.sh

setup-branch-protection: ## Tier C: apply GitHub branch protection on `main` (requires gh + jq, repo admin)
	bash scripts/setup-branch-protection.sh

# ---------------------------------------------------------------------------
# Dependency parity (BYOC requirements.txt vs canonical backend/pyproject.toml)
# ---------------------------------------------------------------------------
# `requirements.txt` is consumed by `scripts/prepareproject.sh` (BYOC build hook).
# The canonical dependency list lives in `backend/pyproject.toml`. These targets
# keep `requirements.txt` mechanically in sync so it cannot drift.

sync-requirements: ## Regenerate requirements.txt from backend/pyproject.toml
	@bash scripts/sync-requirements.sh

check-requirements: ## Fail if requirements.txt is out of sync with backend/pyproject.toml (CI-friendly)
	@bash scripts/sync-requirements.sh --check

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next
