# ArtRestore Studio - common developer tasks.
#
#   make setup     install everything into .venv and node_modules
#   make dev       run the API and the web app with no extra infrastructure
#   make test      run every test suite
#
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip wheel

.PHONY: setup
setup: $(VENV) ## Install Python and Node dependencies
	$(PIP) install -e ./services/image-processing \
	               -e ./services/timelapse-renderer \
	               -e ./apps/api \
	               -e ./apps/worker
	$(PIP) install pytest pytest-cov pytest-timeout httpx httpx2 ruff black
	npm ci

.PHONY: dev-api
dev-api: ## Run the API on SQLite with filesystem storage and in-process jobs
	./scripts/dev-api.sh

.PHONY: dev-web
dev-web: ## Run the Next.js dev server
	npm run dev

.PHONY: seed
seed: ## Create the demo account and two example projects
	ARS_DATABASE_URL="sqlite:///$(PWD)/.dev-state/artrestore.db" \
	ARS_STORAGE_BACKEND=local \
	ARS_LOCAL_STORAGE_DIR="$(PWD)/.dev-state/storage" \
	$(PY) scripts/seed.py

.PHONY: assets
assets: ## Regenerate the demonstration assets
	$(PY) scripts/generate_demo_assets.py --web

.PHONY: up
up: ## Start the full Docker stack (Postgres, Redis, MinIO, API, worker, web)
	docker compose up --build

.PHONY: down
down: ## Stop the Docker stack
	docker compose down

.PHONY: migrate
migrate: ## Apply database migrations
	cd apps/api && ../../$(PY) -m alembic upgrade head

.PHONY: revision
revision: ## Create a migration from the current models (m="message")
	cd apps/api && ../../$(PY) -m alembic revision --autogenerate -m "$(m)"

.PHONY: test
test: test-py test-web ## Run every test suite

.PHONY: test-py
test-py: ## Run the Python test suites
	$(PY) -m pytest

.PHONY: test-web
test-web: ## Run the web unit, component and accessibility tests
	npm run test --workspace=@artrestore/web

.PHONY: test-e2e
test-e2e: ## Run the Playwright end-to-end tests (needs the API running)
	npm run build --workspace=@artrestore/web
	npm run test:e2e --workspace=@artrestore/web

.PHONY: lint
lint: ## Lint and typecheck everything
	$(VENV)/bin/ruff check .
	$(VENV)/bin/black --check .
	npm run format:check
	npm run lint
	npm run typecheck

.PHONY: format
format: ## Autoformat everything
	$(VENV)/bin/ruff check . --fix
	$(VENV)/bin/black .
	npm run format

.PHONY: clean
clean: ## Remove local dev state and build output
	rm -rf .dev-state apps/web/.next apps/web/test-results apps/web/playwright-report
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
