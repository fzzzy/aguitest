.PHONY: all clean help typecheck lint format check

# Default target - runs the AG-UI agent server with auto-reload
all: aguitest-venv
	@(sleep 2 && open http://127.0.0.1:8000/chat.html) &
	uv run uvicorn agent_server:app --host 127.0.0.1 --port 8000 --reload

# Create the virtual environment from pyproject.toml
aguitest-venv: pyproject.toml
	uv sync
	@touch aguitest-venv

# Run type checking with mypy
typecheck: aguitest-venv
	uv run mypy *.py

# Run ruff linter
lint: aguitest-venv
	uv run ruff check *.py

# Run ruff formatter
format: aguitest-venv
	uv run ruff format *.py

# Run all checks (typecheck + lint)
check: typecheck lint

# Clean up the virtual environment
clean:
	rm -rf .venv aguitest-venv
	rm -rf uv.lock

# Display help information
help:
	@echo "Available targets:"
	@echo "  all              - Run agent_server.py with auto-reload (default)"
	@echo "  check            - Run typecheck and lint"
	@echo "  typecheck        - Run mypy type checking on all Python files"
	@echo "  lint             - Run ruff linter on all Python files"
	@echo "  format           - Run ruff formatter on all Python files"
	@echo "  aguitest-venv    - Create/update virtual environment"
	@echo "  clean            - Remove virtual environment and lock file"
	@echo "  help             - Display this help message"
