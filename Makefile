.PHONY: all clean help

# Default target - runs the main.py file
all: aguitest-venv
	uv run main.py

# Create the virtual environment from pyproject.toml
aguitest-venv: pyproject.toml
	uv sync
	@touch aguitest-venv

# Clean up the virtual environment
clean:
	rm -rf .venv aguitest-venv
	rm -rf uv.lock

# Display help information
help:
	@echo "Available targets:"
	@echo "  all              - Run main.py using uv (default)"
	@echo "  aguitest-venv    - Create/update virtual environment"
	@echo "  clean            - Remove virtual environment and lock file"
	@echo "  help             - Display this help message"
