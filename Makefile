BACKEND_DIR := backend
FRONTEND_DIR := frontend
UV_RUN := uv run --directory $(BACKEND_DIR)
NPM := npm --prefix $(FRONTEND_DIR)
SCENARIO ?= balanced
SEED ?= 42

.DEFAULT_GOAL := help

.PHONY: help setup backend-setup frontend-setup \
	lint backend-lint frontend-lint format \
	test backend-test frontend-test test-azure \
	build audit backend-audit frontend-audit secrets-scan schemas sim

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: backend-setup frontend-setup ## Install all dependencies and git hooks
	$(UV_RUN) pre-commit install

backend-setup: ## Install backend dependencies from the lockfile
	uv sync --directory $(BACKEND_DIR) --locked

frontend-setup: ## Install frontend dependencies from the lockfile
	$(NPM) ci

lint: backend-lint frontend-lint ## Lint and typecheck everything

backend-lint: ## Ruff lint, format check and pyright
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) pyright

frontend-lint: ## ESLint and TypeScript typecheck
	$(NPM) run lint
	$(NPM) run typecheck

format: ## Auto-format and auto-fix the backend
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .

test: backend-test frontend-test ## Run all offline test suites

backend-test: ## Pytest with coverage, Azure tests excluded
	$(UV_RUN) pytest --cov

frontend-test: ## Vitest
	$(NPM) test

test-azure: ## Run tests against real Azure resources
	$(UV_RUN) pytest -m azure

sim: ## Simulate a scenario into data/samples (SCENARIO=balanced SEED=42)
	$(UV_RUN) matchlens sim --scenario $(SCENARIO) --seed $(SEED)

schemas: ## Regenerate JSON Schemas for the data contracts
	$(UV_RUN) matchlens schemas export --output-dir ../docs/schemas

build: ## Production build of the frontend
	$(NPM) run build

audit: backend-audit frontend-audit ## Audit dependencies for known vulnerabilities

backend-audit:
	$(UV_RUN) pip-audit --skip-editable

frontend-audit:
	$(NPM) audit --audit-level=high

secrets-scan: ## Scan the full git history for secrets with gitleaks
	gitleaks git --redact --verbose
