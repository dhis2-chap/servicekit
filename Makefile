.PHONY: help install format lint test coverage migrate upgrade clean docker-build docker-run docs docs-serve docs-build

# ==============================================================================
# Venv
# ==============================================================================

UV := $(shell command -v uv 2> /dev/null)
VENV_DIR?=.venv
PYTHON := $(VENV_DIR)/bin/python

# ==============================================================================
# Targets
# ==============================================================================

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install      Install dependencies"
	@echo "  format       Format code and apply lint fixes"
	@echo "  lint         Check formatting, linting and types"
	@echo "  test         Run tests"
	@echo "  coverage     Run tests with coverage reporting"
	@echo "  migrate      Create a migration (use MSG='description')"
	@echo "  upgrade      Apply migrations up to head"
	@echo "  docs-serve   Serve documentation locally with live reload"
	@echo "  docs-build   Build documentation site"
	@echo "  docs         Alias for docs-serve"
	@echo "  docker-build Build example Docker image (use EXAMPLE='core_api')"
	@echo "  docker-run   Run example in Docker (use EXAMPLE='core_api')"
	@echo "  clean        Clean up temporary files"

install:
	@echo ">>> Installing dependencies"
	@$(UV) sync --all-extras

format:
	@echo ">>> Formatting code"
	@$(UV) run ruff format .
	@$(UV) run ruff check . --fix

lint:
	@echo ">>> Running linter"
	@$(UV) run ruff format --check .
	@$(UV) run ruff check .
	@echo ">>> Running type checker"
	@$(UV) run mypy --explicit-package-bases src tests examples
	@$(UV) run pyright

test:
	@echo ">>> Running tests"
	@$(UV) run pytest -q

coverage:
	@echo ">>> Running tests with coverage"
	@$(UV) run coverage run -m pytest -q
	@$(UV) run coverage report
	@$(UV) run coverage xml

migrate:
	@if [ -z "$(MSG)" ]; then \
		echo "Error: MSG not specified. Usage: make migrate MSG='description'"; \
		exit 1; \
	fi
	@echo ">>> Creating migration: $(MSG)"
	@$(UV) run alembic revision --autogenerate -m "$(MSG)"

upgrade:
	@echo ">>> Applying migrations"
	@$(UV) run alembic upgrade head

docs-serve:
	@echo ">>> Serving documentation at http://127.0.0.1:8000"
	@NO_MKDOCS_2_WARNING=true $(UV) run mkdocs serve

docs-build:
	@echo ">>> Building documentation site"
	@NO_MKDOCS_2_WARNING=true $(UV) run mkdocs build

docs: docs-serve

docker-build:
	@echo ">>> Building Docker image for example: $(EXAMPLE)"
	@if [ -z "$(EXAMPLE)" ]; then \
		echo "Error: EXAMPLE not specified. Usage: make docker-build EXAMPLE=core_api"; \
		exit 1; \
	fi
	@docker build -f examples/$(EXAMPLE)/Dockerfile -t servicekit-$(EXAMPLE) .

docker-run:
	@echo ">>> Running Docker container with example: $(EXAMPLE)"
	@if [ -z "$(EXAMPLE)" ]; then \
		echo "Error: EXAMPLE not specified. Usage: make docker-run EXAMPLE=core_api"; \
		exit 1; \
	fi
	@docker run --rm -p 8000:8000 servicekit-$(EXAMPLE)

clean:
	@echo ">>> Cleaning up"
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -exec rm -rf {} +
	@find . -type d -name ".mypy_cache" -exec rm -rf {} +
	@rm -rf .coverage coverage.xml htmlcov/
	@rm -rf .pytype/
	@rm -rf dist/ build/ *.egg-info
	@rm -f examples/*/uv.lock
	@find examples -type d -name ".venv" -exec rm -rf {} + 2>/dev/null || true

# ==============================================================================
# Default
# ==============================================================================

.DEFAULT_GOAL := help
