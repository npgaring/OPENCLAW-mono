"""Test env: in-memory SQLite, mock OpenClaw. Shared memory so tests can query DB for verification."""
import os

import pytest

# Set before app import. Shared in-memory DB so test code can query same data the app wrote.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///file:openclawtest?mode=memory&cache=shared&uri=true"
os.environ["OPENCLAW_BASE_URL"] = "https://mock-openclaw"
os.environ["OPENCLAW_API_KEY"] = "test-key"
os.environ["INTEGRATION_API_KEY"] = "test-integration-key"


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-integration-key"}
