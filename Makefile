.PHONY: help setup infra backend frontend test test-unit test-integration test-all test-infra-up test-infra-down lint format typecheck type-check clean migrate docker-build docker-up docker-down

# Optional repo-root .env (BACKEND_PORT, etc.). Safe if missing.
-include .env

# Override on the CLI: `make backend BACKEND_PORT=8010`
BACKEND_PORT ?= 8000

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: ## First-time project setup (venv + deps + .env)
	@echo "==> Creating Python venv..."
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	@echo "==> Installing frontend deps..."
	cd frontend && npm install
	@test -f .env || cp .env.example .env && echo "==> Created .env from .env.example"
	@echo "==> Done. Run 'make infra' to start ArangoDB + Redis."

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

backend: ## Run backend dev server (port from BACKEND_PORT, default 8000; set in .env or CLI)
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
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next
