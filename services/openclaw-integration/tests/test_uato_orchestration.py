"""UATO frame outcomes: external response stays frame-first; GRL is still evaluated in the atomic engine."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_payload
from app.gate.engine import GateEngine
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _valid_spec():
    from app.core.identity import IDENTITY_DOMAIN_MAP

    ops = [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
    }


@pytest.mark.asyncio
async def test_gate_skipped_when_uato_blocks(monkeypatch):
    called = []

    real_evaluate = GateEngine.evaluate

    def wrapped(self, spec, ocgg_identity):
        called.append((spec, ocgg_identity))
        return real_evaluate(self, spec, ocgg_identity)

    monkeypatch.setattr(GateEngine, "evaluate", wrapped)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        spec = _valid_spec()
        spec["plan_hash"] = "intentionally_wrong_hash_should_not_be_seen_if_gate_skipped"
        r = await client.post(
            "/gate/evaluate",
            json={
                "ocgg_identity": "W-OCGG",
                "plan_hash": spec["plan_hash"],
                "operations": spec["operations"],
                "uato": {"trust_level": "LOW", "authority_level": "LOW"},
            },
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("uato_skipped_gate") is True
    # Atomic cycle always evaluates GRL; mismatch may appear alongside UATO_BLOCK in reason_codes.
    assert "UATO_BLOCK_LOW_TRUST_LOW_AUTHORITY" in (data.get("reason_codes") or [])
    ef = data.get("evaluation_frame") or {}
    assert ef.get("governance_reached") is False
    assert ef.get("dispatch_reached") is False
    assert (ef.get("uato_result") or {}).get("decision") == data.get("uato_decision")
    assert len(called) == 1


@pytest.mark.asyncio
async def test_gate_runs_when_uato_passes(monkeypatch):
    called = []

    real_evaluate = GateEngine.evaluate

    def wrapped(self, spec, ocgg_identity):
        called.append(1)
        return real_evaluate(self, spec, ocgg_identity)

    monkeypatch.setattr(GateEngine, "evaluate", wrapped)

    transport = ASGITransport(app=app)
    spec = _valid_spec()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/gate/evaluate",
            json={
                "ocgg_identity": "W-OCGG",
                "plan_hash": spec["plan_hash"],
                "operations": spec["operations"],
            },
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    assert called == [1]
    data = r.json()
    assert data.get("uato_skipped_gate") is False
    assert data.get("uato_decision") == "PASS"
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "PASS"
    assert ef.get("governance_reached") is True
    assert ef.get("dispatch_reached") is False


@pytest.mark.asyncio
async def test_task_uato_require_approval_status_frame_blocks_execution(monkeypatch):
    called = []

    real_evaluate = GateEngine.evaluate

    def wrapped(self, spec, ocgg_identity):
        called.append(1)
        return real_evaluate(self, spec, ocgg_identity)

    monkeypatch.setattr(GateEngine, "evaluate", wrapped)

    transport = ASGITransport(app=app)
    spec = _valid_spec()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/task",
            json={
                **spec,
                "uato": {"trust_level": "HIGH", "authority_level": "LOW"},
            },
            headers={"Authorization": "Bearer test-integration-key"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "pending_approval"
    assert data.get("uato_decision") == "REQUIRE_APPROVAL"
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "APPROVAL_REQUIRED"
    assert ef.get("approval_required") is True
    assert ef.get("approval_request_id")
    assert ef.get("governance_reached") is False
    assert ef.get("dispatch_reached") is False
    assert len(called) == 1
