.PHONY: build check clean fix lint typecheck test run stop tail dev run-backend run-frontend

# Set UV to use aguitest-venv instead of .venv
export UV_PROJECT_ENVIRONMENT = aguitest-venv

build: node_modules python/aguitest-venv
	npm run build

node_modules: package.json
	npm install
	@touch node_modules

python/aguitest-venv: python/pyproject.toml
	cd python && uv sync
	@touch python/aguitest-venv

check: typecheck lint test

test: python/aguitest-venv node_modules
	cd python && uv run pytest tests/ -v --cov=. --cov-report=term-missing

typecheck: python/aguitest-venv
	cd python && uv run pyright

lint: python/aguitest-venv node_modules
	cd python && uv run ruff check *.py
	npx eslint src/*.ts

fix: python/aguitest-venv node_modules
	cd python && uv run ruff check --fix *.py
	cd python && uv run ruff format *.py
	npx eslint --fix src/*.ts
	npx prettier --write src/*.ts

run: node_modules python/aguitest-venv
	@# Stop any existing processes
	@lsof -ti:5173 | xargs kill 2>/dev/null || true
	@lsof -ti:8999 | xargs kill 2>/dev/null || true
	@sleep 1
	@# Start backend
	@cd python && uv run uvicorn agent_server:app --host 0.0.0.0 --port 8999 --reload > /tmp/aguitest-backend.log 2>&1 &
	@sleep 1
	@# Start frontend
	@npm run dev > /tmp/aguitest-frontend.log 2>&1 &
	@sleep 2
	@echo ""
	@echo "Started:"
	@echo "  Backend:  http://localhost:8999"
	@echo "  Frontend: http://localhost:5173"
	@echo ""
	@echo "Logs:"
	@echo "  make tail"
	@echo ""
	@echo "Stop:"
	@echo "  make stop"

stop:
	@echo "Stopping aguitest..."
	@lsof -ti:5173 | xargs kill 2>/dev/null || true
	@lsof -ti:8999 | xargs kill 2>/dev/null || true
	@echo "Stopped."

tail:
	@tail -f /tmp/aguitest-backend.log /tmp/aguitest-frontend.log

dev: run tail

run-backend: python/aguitest-venv
	cd python && uv run uvicorn agent_server:app --host 0.0.0.0 --port 8999 --reload

run-frontend: node_modules
	npm run dev

clean:
	rm -rf python/aguitest-venv python/__pycache__ python/.mypy_cache python/.ruff_cache python/.pytest_cache
	rm -rf node_modules dist
