.PHONY: all dev clean help typecheck lint format check fix

# Default target - runs the AG-UI agent server with auto-reload
all: aguitest-venv dist
	@(sleep 2 && open http://127.0.0.1:8000/) &
	cd python && uv run uvicorn agent_server:app --host 127.0.0.1 --port 8000 --reload

# Development mode - runs server with auto-reload AND TypeScript watch mode
dev: aguitest-venv node_modules
	@echo "Starting TypeScript watch mode and Python server..."
	@(npm run watch &) && \
	(sleep 2 && open http://127.0.0.1:8000/) & \
	cd python && uv run uvicorn agent_server:app --host 127.0.0.1 --port 8000 --reload

# Build TypeScript frontend
dist: node_modules src/index.ts
	npm run build

# Install npm dependencies
node_modules: package.json
	npm install
	@touch node_modules

# Create the virtual environment from pyproject.toml
aguitest-venv: python/pyproject.toml
	cd python && uv sync
	@touch aguitest-venv

# Run type checking with mypy
typecheck: aguitest-venv
	cd python && uv run mypy *.py

# Run ruff linter
lint: aguitest-venv node_modules
	cd python && uv run ruff check *.py
	npx eslint src/**/*.ts

# Run ruff formatter
format: aguitest-venv node_modules
	cd python && uv run ruff format *.py
	npx prettier --write src/**/*.ts

# Run all checks (typecheck + lint)
check: typecheck lint

# Run checks and auto-fix issues (format after checking)
fix: check format

# Clean up build artifacts
clean:
	rm -rf .venv aguitest-venv
	rm -rf uv.lock
	rm -rf node_modules dist

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
