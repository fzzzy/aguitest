"""End-to-end tests using Playwright."""

import json
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

PROJECT_ROOT = Path(__file__).parent.parent.parent
COVERAGE_DIR = PROJECT_ROOT / ".nyc_output"


def is_frontend_running() -> bool:
    """Check if frontend is running on port 5173."""
    try:
        httpx.get("http://localhost:5173/", timeout=1)
        return True
    except httpx.RequestError:
        return False


@pytest.fixture(scope="session")
def server() -> Generator[None, None, None]:
    """Start frontend server for e2e tests, or use existing one."""
    frontend = None
    started_frontend = False

    if is_frontend_running():
        print("Frontend already running on port 5173, reusing...")
    else:
        print("Starting frontend...")
        frontend_log = open("/tmp/aguitest-frontend.log", "w")
        frontend = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=PROJECT_ROOT,
            stdout=frontend_log,
            stderr=frontend_log,
        )
        started_frontend = True

        for _ in range(30):
            if is_frontend_running():
                break
            time.sleep(0.5)
        else:
            frontend.terminate()
            raise RuntimeError("Frontend failed to start")

    yield

    if started_frontend and frontend:
        frontend.terminate()
        frontend.wait()


@pytest.fixture(scope="session")
def base_url(server: None) -> str:
    """Base URL for the frontend server."""
    return "http://localhost:5173"


@pytest.fixture(scope="session", autouse=True)
def setup_coverage_dir() -> Generator[None, None, None]:
    """Ensure coverage directory exists."""
    COVERAGE_DIR.mkdir(exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def collect_coverage(
    page: Page, request: pytest.FixtureRequest
) -> Generator[None, None, None]:
    """Collect coverage data after each test."""
    yield
    coverage = page.evaluate("window.__coverage__")
    if coverage:
        node_name = getattr(request.node, "name", "unknown")
        coverage_file = COVERAGE_DIR / f"coverage-{node_name}.json"
        coverage_file.write_text(json.dumps(coverage))


def test_hello_world_success(page: Page, base_url: str) -> None:
    """Test the helloWorld function exported by our TS app."""
    page.goto(base_url)
    # Give the script a moment to attach the global
    page.wait_for_timeout(500)
    
    result = page.evaluate("window.helloWorld('Playwright')")
    assert result == "Hello, Playwright!"

def test_hello_world_error(page: Page, base_url: str) -> None:
    """Test the helloWorld function error branch."""
    page.goto(base_url)
    page.wait_for_timeout(500)
    
    with pytest.raises(Exception, match="Invalid name"):
        page.evaluate("window.helloWorld('Error')")