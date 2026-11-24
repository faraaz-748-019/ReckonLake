# ═══════════════════════════════════════════════════════════════════════════
# ReconLake — Makefile
# All targets are PHONY unless noted. Run `make help` to list them.
# ═══════════════════════════════════════════════════════════════════════════

SHELL         := /usr/bin/env bash
.SHELLFLAGS   := -euo pipefail -c

PROFILE       ?= core
COMPOSE_FILE  ?= infra/docker-compose.yml
PYTHON        ?= python3
PYTEST_ARGS   ?= -v
COVERAGE_MIN  ?= 70
DBT_DIR       ?= dbt
DOCS_HOST     ?= 127.0.0.1
DOCS_PORT     ?= 8000

.DEFAULT_GOAL := help

.PHONY: up
up: ## Start Docker Compose services (PROFILE=core|streaming|governance|observability|stretch)
	@echo "Starting services — profile: $(PROFILE)"
	docker compose -f $(COMPOSE_FILE) --profile $(PROFILE) up -d --build --remove-orphans

.PHONY: down
down: ## Stop and remove Docker Compose services
	docker compose -f $(COMPOSE_FILE) down --remove-orphans

.PHONY: logs
logs: ## Follow Docker Compose logs
	docker compose -f $(COMPOSE_FILE) logs -f

.PHONY: ps
ps: ## Show status of Docker Compose services
	docker compose -f $(COMPOSE_FILE) ps

.PHONY: generate-secrets
generate-secrets: ## Generate local dev secrets and TLS certs (writes to secrets/, never committed)
	bash infra/scripts/generate-secrets.sh

.PHONY: rotate-secrets
rotate-secrets: ## Rotate local/OpenBao secrets
	bash infra/scripts/rotate-secrets.sh

.PHONY: test
test: ## Run all tests with coverage
	$(PYTHON) -m pytest tests/ $(PYTEST_ARGS) \
	  --cov=generator --cov=contracts --cov=security --cov=pipelines --cov=quality \
	  --cov-report=term-missing \
	  --cov-report=xml:coverage.xml \
	  --cov-fail-under=$(COVERAGE_MIN)

.PHONY: test-unit
test-unit: ## Run unit tests only
	$(PYTHON) -m pytest tests/unit/ $(PYTEST_ARGS)

.PHONY: test-chaos
test-chaos: ## Run chaos and recovery tests
	$(PYTHON) -m pytest tests/chaos/ $(PYTEST_ARGS)

.PHONY: lint
lint: ## Lint Python (ruff) and SQL (sqlfluff)
	$(PYTHON) -m ruff check .
	@if command -v sqlfluff >/dev/null 2>&1; then sqlfluff lint $(DBT_DIR)/ --dialect postgres; fi

.PHONY: format
format: ## Auto-fix Python (ruff)
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

.PHONY: typecheck
typecheck: ## Run mypy type checker
	$(PYTHON) -m mypy contracts generator security quality pipelines

.PHONY: security
security: ## Run security scans (bandit, pip-audit, gitleaks, trivy, sbom) and write consolidated report
	$(PYTHON) scripts/security_report.py

.PHONY: demo
demo: ## Run full end-to-end ReconLake demo under 10 minutes
	$(PYTHON) scripts/demo.py

.PHONY: benchmark
benchmark: ## Run throughput and latency benchmarks
	$(PYTHON) scripts/benchmark.py

.PHONY: dbt-build
dbt-build: ## Run dbt build
	cd $(DBT_DIR) && dbt build

.PHONY: docs
docs: ## Serve MkDocs documentation locally
	$(PYTHON) -m mkdocs serve -f docs/mkdocs.yml --dev-addr $(DOCS_HOST):$(DOCS_PORT)

.PHONY: docs-build
docs-build: ## Build MkDocs static site
	$(PYTHON) -m mkdocs build -f docs/mkdocs.yml --strict

.PHONY: clean
clean: ## Remove build artefacts and caches
	rm -rf build/ dist/ *.egg-info coverage.xml htmlcov/ site/ .pytest_cache .mypy_cache .ruff_cache

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'
