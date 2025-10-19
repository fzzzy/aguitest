# aguitest

Learning AGUI (Agent User Interaction Protocol) SDK with Pydantic AI

## Prerequisites

**[uv](https://docs.astral.sh/uv/) is required** - A fast Python package manager

Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick Start

```bash
# Run the AG-UI agent server (automatically sets up environment)
make

# In another terminal, test the agent
uv run test_agui_client.py
```

## Development

### Available Make Targets

- `make` or `make all` - Run AG-UI agent server with auto-reload (default)
- `make check` - Run typecheck and lint
- `make typecheck` - Run mypy type checking
- `make lint` - Run ruff linter
- `make format` - Format code with ruff
- `make clean` - Remove virtual environment and lock file
- `make help` - Show all available targets

### Code Quality

All code is:
-  Type-checked with mypy
-  Linted with ruff
-  Formatted with ruff

Run all checks before committing:
```bash
make check
```

## Project Structure

- `agent_server.py` - AG-UI agent server with SSE streaming
- `test_agui_client.py` - Test client for AG-UI agent
- `main.py` - Basic AG-UI examples

## Technologies

- **Python 3.14** - Latest Python version
- **[Pydantic AI](https://ai.pydantic.dev/)** - Type-safe AI agent framework
- **[AG-UI Protocol](https://docs.ag-ui.com/)** - Agent User Interaction Protocol
- **[mumulib](../mumulib/python/)** - Minimalist ASGI application library
- **AWS Bedrock** - Claude 3.5 Sonnet model
- **uvicorn** - ASGI server
- **mypy** - Static type checking
- **ruff** - Fast Python linter and formatter
