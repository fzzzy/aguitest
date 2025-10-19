# aguitest

Learning AGUI (Agent User Interaction Protocol) SDK with Pydantic AI

## Prerequisites

**[uv](https://docs.astral.sh/uv/) is required**

## Quick Start

```bash
# Run the AG-UI agent server
# automatically sets up environment and opens a web browser with the ui on macOS
# On other OS visit http://localhost:8000/

make
```

## Development

### Available Make Targets

- `make` or `make all` - Run AG-UI agent server with auto-reload (default)
- `make fix` - Run typecheck and lint, reformat code with ruff and prettier
- `make clean` - Remove virtual environment and lock file
- `make help` - Show all available targets
