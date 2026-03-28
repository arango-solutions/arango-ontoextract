.PHONY: help setup infra backend frontend test lint clean

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

backend: ## Run backend dev server
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

frontend: ## Run frontend dev server
	cd frontend && npm run dev

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

test: ## Run backend tests
	cd backend && .venv/bin/pytest tests/ -v

lint: ## Lint backend code
	cd backend && .venv/bin/ruff check app/ tests/

format: ## Format backend code
	cd backend && .venv/bin/ruff format app/ tests/

typecheck: ## Type-check backend
	cd backend && .venv/bin/mypy app/

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next
