.PHONY: all dev clean help typecheck lint format check fix

# Set UV to use aguitest-venv instead of .venv
export UV_PROJECT_ENVIRONMENT = aguitest-venv

# Default target - runs the AG-UI agent server with auto-reload
all: python/aguitest-venv dist
	@(sleep 2 && open http://127.0.0.1:8000/) &
	cd python && uv run uvicorn agent_server:app --host 127.0.0.1 --port 8000 --reload

# Development mode - runs server with auto-reload AND TypeScript watch mode
dev: python/aguitest-venv src/node_modules
	@echo "Starting TypeScript watch mode and Python server..."
	@(cd src && npm run watch &) && \
	(sleep 2 && open http://127.0.0.1:8000/) & \
	cd python && uv run uvicorn agent_server:app --host 127.0.0.1 --port 8000 --reload

# Build TypeScript frontend
dist: src/node_modules src/index.ts
	cd src && npm run build

# Install npm dependencies
src/node_modules: src/package.json
	cd src && npm install
	@touch src/node_modules

# Create the virtual environment from pyproject.toml
python/aguitest-venv: python/pyproject.toml
	cd python && uv sync
	@touch python/aguitest-venv

# Run type checking with mypy
typecheck: python/aguitest-venv
	cd python && uv run mypy *.py

# Run ruff linter
lint: python/aguitest-venv src/node_modules
	cd python && uv run ruff check *.py
	cd src && npx eslint *.ts

# Run ruff formatter
format: python/aguitest-venv src/node_modules
	cd python && uv run ruff format *.py
	cd src && npx prettier --write *.ts

# Run all checks (typecheck + lint)
check: typecheck lint

# Run checks and auto-fix issues (lint with --fix, then format)
fix: python/aguitest-venv src/node_modules
	cd python && uv run mypy *.py
	cd python && uv run ruff check --fix *.py
	cd src && npx eslint --fix *.ts
	cd python && uv run ruff format *.py
	cd src && npx prettier --write *.ts

# Clean up build artifacts
clean:
	rm -rf python/aguitest-venv
	rm -rf python/uv.lock
	rm -rf python/__pycache__ python/.mypy_cache python/.ruff_cache
	rm -rf src/node_modules dist

# Display help information
help:
	@echo "Available targets:"
	@echo "  all              - Run agent_server.py with auto-reload (default)"
	@echo "  dev              - Run server + TypeScript watch mode for development"
	@echo "  check            - Run typecheck and lint"
	@echo "  fix              - Run check then format (recommended before commit)"
	@echo "  typecheck        - Run mypy type checking on all Python files"
	@echo "  lint             - Run ruff linter on all Python files"
	@echo "  format           - Run ruff formatter on all Python files"
	@echo "  aguitest-venv    - Create/update virtual environment"
	@echo "  clean            - Remove virtual environment and lock file"
	@echo "  help             - Display this help message"
