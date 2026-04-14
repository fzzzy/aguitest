import pytest
from fastapi.testclient import TestClient

# Normally we'd import this from your agent_server
# from agent_server import app
# client = TestClient(app)

def test_hello_world():
    """A basic unit test to verify pytest is configured correctly."""
    assert True
    assert 1 + 1 == 2
