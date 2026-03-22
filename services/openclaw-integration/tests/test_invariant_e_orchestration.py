"""Invariant-E after governance on POST /task: dispatch must not run when admission denies."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.invariant_e import reason_codes as ie_rc
from app.invariant_e.types import result_denied
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _valid_spec():
    ops = [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
    }


@pytest.mark.asyncio
async def test_openclaw_not_called_when_invariant_e_denies(monkeypatch):
    from app.services import task_submission as task_submission_module

    monkeypatch.setattr(
        task_submission_module,
        "evaluate_invariant_e",
        lambda env: result_denied(env.trace_id, (ie_rc.IE_DENIED_CAPABILITY_NOT_ALLOWED,)),
    )
    mock_execute = AsyncMock(return_value={"status": "success", "execution_id": "ex1"})
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", mock_execute)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/task",
            json=_valid_spec(),
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("invariant_e_decision") == "EXECUTION_DENIED"
    assert data.get("dispatch_blocked") is True
    assert data.get("status") == "invariant_e_denied"
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_openclaw_called_when_invariant_e_allows(monkeypatch):
    mock_execute = AsyncMock(return_value={"status": "success", "execution_id": "ex2"})
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", mock_execute)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/task",
            json=_valid_spec(),
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("invariant_e_decision") == "EXECUTION_ALLOWED"
    assert data.get("dispatch_blocked") is False
    mock_execute.assert_awaited_once()
