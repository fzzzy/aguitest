.PHONY: all dev clean help typecheck lint format check fix

# Set UV to use aguitest-venv instead of .venv
export UV_PROJECT_ENVIRONMENT = aguitest-venv

# Development mode - runs Vite dev server AND Python server
all: python/aguitest-venv node_modules
	@echo "Starting Vite dev server and Python server..."
	@(npm run dev &) && \
	(sleep 2 && open http://localhost:5173/) & \
	cd python && uv run uvicorn agent_server:app --host 127.0.0.1 --port 8999 --reload

# Build TypeScript frontend
dist: node_modules src/index.ts
	npm run build

# Install npm dependencies
node_modules: package.json
	npm install
	@touch node_modules

# Create the virtual environment from pyproject.toml
python/aguitest-venv: python/pyproject.toml
	cd python && uv sync
	@touch python/aguitest-venv

# Run type checking with mypy
typecheck: python/aguitest-venv
	cd python && uv run mypy *.py

# Run ruff linter
lint: python/aguitest-venv node_modules
	cd python && uv run ruff check *.py
	npx eslint src/*.ts

# Run ruff formatter
format: python/aguitest-venv node_modules
	cd python && uv run ruff format *.py
	npx prettier --write src/*.ts

# Run all checks (typecheck + lint)
check: typecheck lint

# Run checks and auto-fix issues (lint with --fix, then format)
fix: python/aguitest-venv node_modules
	cd python && uv run mypy *.py
	cd python && uv run ruff check --fix *.py
	npx eslint --fix src/*.ts
	cd python && uv run ruff format *.py
	npx prettier --write src/*.ts

# Clean up build artifacts
clean:
	rm -rf python/aguitest-venv
	rm -rf python/uv.lock
	rm -rf python/__pycache__ python/.mypy_cache python/.ruff_cache
	rm -rf node_modules dist

# Display help information
help:
	@echo "Available targets:"
	@echo "  all              - Run Vite dev server + Python server (default)"
	@echo "  dist             - Build TypeScript frontend for production"
	@echo "  check            - Run typecheck and lint"
	@echo "  fix              - Run check then format (recommended before commit)"
	@echo "  typecheck        - Run mypy type checking on Python files"
	@echo "  lint             - Run linter on Python and TypeScript files"
	@echo "  format           - Run formatter on Python and TypeScript files"
	@echo "  clean            - Remove build artifacts and dependencies"
	@echo "  help             - Display this help message"
