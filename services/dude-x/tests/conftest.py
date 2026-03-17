"""Pytest config: use in-memory SQLite so tests don't require Neon."""
import os

import pytest

# Set before any app/db import so init_db and session use in-memory DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.setdefault("INTEGRATION_API_KEY", "test-token")


@pytest.fixture
def anyio_backend():
    return "asyncio"
