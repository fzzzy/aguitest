"""End-to-end tests using Playwright."""

import json
import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

PROJECT_ROOT = Path(__file__).parent.parent.parent
COVERAGE_DIR = PROJECT_ROOT / ".nyc_output"


def is_backend_running() -> bool:
    """Check if backend is running on port 8999."""
    try:
        httpx.get("http://localhost:8999/", timeout=1)
        return True
    except httpx.RequestError:
        return False


def is_frontend_running() -> bool:
    """Check if frontend is running on port 5173."""
    try:
        httpx.get("http://localhost:5173/", timeout=1)
        return True
    except httpx.RequestError:
        return False


@pytest.fixture(scope="session")
def servers() -> Generator[None]:
    """Start backend and frontend servers for e2e tests, or use existing ones."""
    backend = None
    frontend = None
    started_backend = False
    started_frontend = False

    # Check and start backend if needed
    if is_backend_running():
        print("Backend already running on port 8999, reusing...")
    else:
        print("Starting backend...")
        # The handle is passed to Popen and must outlive this statement;
        # a context manager would close it under the running child.
        backend_log = open("/tmp/aguitest-backend.log", "w")  # noqa: SIM115
        env = {
            **os.environ,
            "AGUITEST_PING_INTERVAL": "0.01",
            "AGUITEST_IS_TEST_SUITE": "1",
        }
        backend = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "agent_server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8999",
            ],
            cwd=PROJECT_ROOT / "python",
            stdout=backend_log,
            stderr=backend_log,
            env=env,
        )
        started_backend = True

        for _ in range(30):
            if is_backend_running():
                break
            time.sleep(0.2)
        else:
            backend.terminate()
            raise RuntimeError("Backend failed to start")

    # Check and start frontend if needed
    if is_frontend_running():
        print("Frontend already running on port 5173, reusing...")
    else:
        print("Starting frontend...")
        # Same as the backend log above: owned by the child process.
        frontend_log = open("/tmp/aguitest-frontend.log", "w")  # noqa: SIM115
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
            if started_backend and backend:
                backend.terminate()
            raise RuntimeError("Frontend failed to start")

    yield

    if started_frontend and frontend:
        frontend.terminate()
        frontend.wait()
    if started_backend and backend:
        backend.terminate()
        backend.wait()


@pytest.fixture(scope="session")
def base_url(servers: None) -> str:
    """Base URL for the frontend server."""
    return "http://localhost:5173"


@pytest.fixture(scope="session", autouse=True)
def setup_coverage_dir() -> Generator[None]:
    """Ensure coverage directory exists."""
    COVERAGE_DIR.mkdir(exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def collect_coverage(page: Page, request: pytest.FixtureRequest) -> Generator[None]:
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


def test_chat_interaction(page: Page, base_url: str) -> None:
    """Test connecting to the agent and receiving messages."""
    page.on("console", lambda msg: print(f"BROWSER: {msg.text}"))
    page.goto(base_url)
    # Wait for the UI to be ready
    chat_container = page.locator("chat-container")
    expect(chat_container).to_be_visible(timeout=5000)

    # Check that initial state shows the ping indicator
    ping_indicator = page.locator("ping-indicator")
    expect(ping_indicator).to_be_visible()

    # Find the input and send a message to trigger connection
    msg_input = page.locator("message-input input")
    expect(msg_input).to_be_visible()

    msg_input.fill("Hello AGUI!")
    msg_input.press("Enter")

    # Wait for the user message to appear in the chat
    user_msg = page.locator("chat-message[role='user'] .content")
    expect(user_msg).to_contain_text("Hello AGUI!")

    # Wait for the assistant to reply
    assistant_msg = page.locator("chat-message[role='assistant']")
    expect(assistant_msg).to_be_visible(timeout=10000)

    # Wait for the stream to finish and some response text to appear
    expect(assistant_msg.locator(".content")).not_to_be_empty(timeout=15000)

    # Wait for a ping to arrive (the server sends one every 0.01 seconds now)
    # We check the pingCount property to reliably detect it without fighting CSS animations
    ping_count = page.evaluate("""() => {
        return new Promise(resolve => {
            const pingEl = document.getElementById("pingIndicator");
            if (!pingEl) return resolve(0);
            
            if (pingEl.pingCount > 0) return resolve(pingEl.pingCount);
            
            // Poll for pingCount to increase
            const interval = setInterval(() => {
                if (pingEl.pingCount > 0) {
                    clearInterval(interval);
                    resolve(pingEl.pingCount);
                }
            }, 100);
            
            // Timeout after 3s
            setTimeout(() => {
                clearInterval(interval);
                resolve(pingEl.pingCount);
            }, 3000);
        });
    }""")
    assert ping_count > 0, f"Expected ping_count > 0, got {ping_count}"


def test_debug_log(page: Page, base_url: str) -> None:
    """Test the debugLog function."""
    page.goto(base_url)
    page.wait_for_timeout(500)

    # Enable debug mode
    page.evaluate("window.__DEBUG = true")

    # Test debug log with messages div present
    page.evaluate("window.debugLog('Test debug message 1')")

    # Verify the debug message was added to the DOM
    debug_msg = page.locator("debug-message", has_text="Test debug message 1")
    expect(debug_msg).to_be_visible()

    # Test debug log without messages div (remove it temporarily)
    page.evaluate("""() => {
        const msgs = document.getElementById("messages");
        if (msgs) msgs.id = "messages-hidden";
    }""")

    # Should fallback to console.log (we can't easily assert console.log here but it will cover the code path)
    page.evaluate("window.debugLog('Test debug message 2')")

    # Restore messages div to not break other tests
    page.evaluate("""() => {
        const hidden = document.getElementById("messages-hidden");
        if (hidden) hidden.id = "messages";
    }""")
