"""Test env: in-memory SQLite, mock OpenClaw."""
import os

import pytest

# Set before app import
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENCLAW_BASE_URL"] = "https://mock-openclaw"
os.environ["OPENCLAW_API_KEY"] = "test-key"
os.environ["INTEGRATION_API_KEY"] = "test-integration-key"


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-integration-key"}
