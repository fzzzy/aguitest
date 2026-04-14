"""Shared pytest-playwright configuration."""

from collections.abc import Generator
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserType, Page


@pytest.fixture(scope="session")
def browser_type_launch_args(
    browser_type_launch_args: dict[str, Any],
) -> dict[str, Any]:
    return {
        **browser_type_launch_args,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--single-process",
            "--no-zygote",
        ],
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    return {**browser_context_args, "ignore_https_errors": True}


@pytest.fixture
def browser(
    browser_type: BrowserType,
    browser_type_launch_args: dict[str, Any],
) -> Generator[Browser, None, None]:
    """Launch a fresh browser per test (--single-process crashes on reuse)."""
    b = browser_type.launch(**browser_type_launch_args)
    yield b
    b.close()


@pytest.fixture
def page(
    browser: Browser,
    browser_context_args: dict[str, Any],
) -> Generator[Page, None, None]:
    """Create a fresh page per test using the per-test browser."""
    ctx = browser.new_context(**browser_context_args)
    p = ctx.new_page()
    yield p
    ctx.close()