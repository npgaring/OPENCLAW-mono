"""Integration checks: frame-level denials block dispatch; GRL may still run inside the atomic engine."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.gate.engine import GateEngine
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
async def test_governance_not_surfaced_when_frame_invariant_e_denies(monkeypatch):
    """Invariant-E decision denial blocks execution; response stays pre-governance-shaped (no dispatch)."""
    called: list[int] = []
    real_evaluate = GateEngine.evaluate

    def wrapped(self, spec, ocgg_identity):
        called.append(1)
        return real_evaluate(self, spec, ocgg_identity)

    monkeypatch.setattr(GateEngine, "evaluate", wrapped)
    monkeypatch.setattr(
        "app.evaluation.evaluators.invariant_e.evaluate_invariant_e_decision",
        lambda state: result_denied(state.governable.trace_id, ("IE_DENIED_FRAME_ORCHESTRATION_TEST",)),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/task",
            json=_valid_spec(),
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("gate_outcome") == "BLOCK"
    assert len(called) == 1
    assert data.get("invariant_e_decision") == "EXECUTION_DENIED"
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "BLOCKED"
    assert ef.get("governance_reached") is False
    assert ef.get("dispatch_reached") is False


@pytest.mark.asyncio
async def test_openclaw_not_called_when_frame_invariant_e_denies(monkeypatch):
    mock_execute = AsyncMock(return_value={"status": "success", "execution_id": "ex-frame"})
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", mock_execute)
    monkeypatch.setattr(
        "app.evaluation.evaluators.invariant_e.evaluate_invariant_e_decision",
        lambda state: result_denied(state.governable.trace_id, ("IE_DENIED_FRAME_ORCHESTRATION_TEST",)),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/task",
            json=_valid_spec(),
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    mock_execute.assert_not_called()
