"""Integration tests for POST /evaluation-frame/evaluate preview endpoint."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy import select

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.db.session import get_sessionmaker
from app.evaluation.aggregator import composite_frame_from_atomic
from app.evaluation.builder import build_evaluation_state_from_shared_governable
from app.evaluation.engine import default_engine
from app.evaluation_frame import build_shared_governable_state_for_gate_payload
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.main import app
from app.models import Task


def _valid_spec(**overrides):
    ops = [
        {"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}},
    ]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    body = {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
    }
    body.update(overrides)
    return body


def _task_count() -> int:
    async def _go() -> int:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            try:
                result = await session.execute(select(Task))
            except OperationalError:
                return 0
            return len(result.scalars().all())

    return asyncio.run(_go())


def test_evaluation_frame_evaluate_returns_first_class_frame(client, auth_headers):
    payload = _valid_spec()
    resp = client.post("/evaluation-frame/evaluate", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("shared_state_hash")
    assert data.get("frame_status") == "PASS"
    assert isinstance(data.get("reason_codes"), list)
    assert isinstance(data.get("invariant_c_result"), dict)
    assert isinstance(data.get("uato_result"), dict)
    assert isinstance(data.get("invariant_e_result"), dict)
    assert data["invariant_c_result"]["decision"] == "PASS"
    assert data["uato_result"]["decision"] == "PASS"
    assert data["invariant_e_result"]["decision"] == "EXECUTION_ALLOWED"
    assert data.get("approval_required") is False
    assert data.get("approval_request_id") is None
    assert data.get("governance_reached") is False
    assert data.get("dispatch_reached") is False


def test_evaluation_frame_evaluate_matches_internal_mapper(client, auth_headers):
    payload = _valid_spec(uato={"trust_level": "HIGH", "authority_level": "LOW"})
    resp = client.post("/evaluation-frame/evaluate", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    spec = dict(payload)
    spec.pop("trace_id", None)
    spec.pop("uato", None)
    # Rebuild with a deterministic trace id to compare mapper shape/semantics.
    shared = build_shared_governable_state_for_gate_payload(
        spec,
        payload["ocgg_identity"],
        "550e8400-e29b-41d4-a716-446655440123",
        payload.get("uato"),
    )
    ev = build_evaluation_state_from_shared_governable(shared)
    atomic = default_engine.evaluate(ev)
    expected = to_evaluation_frame_response(
        composite_frame_from_atomic(atomic),
        governance_reached=False,
        dispatch_reached=False,
        state_hash=ev.state_hash,
        atomic=atomic,
    ).model_dump(mode="json")
    for key in (
        "frame_status",
        "reason_codes",
        "invariant_c_result",
        "uato_result",
        "invariant_e_result",
        "approval_required",
        "governance_reached",
        "dispatch_reached",
    ):
        assert data[key] == expected[key]


def test_evaluation_frame_evaluate_has_no_persistence_or_dispatch_side_effects(client, auth_headers, monkeypatch):
    before = _task_count()
    mock_exec = AsyncMock(side_effect=AssertionError("OpenClaw execute must not be called"))
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", mock_exec)

    resp = client.post("/evaluation-frame/evaluate", json=_valid_spec(), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    after = _task_count()
    assert after == before
    mock_exec.assert_not_awaited()
    data = resp.json()
    assert data["governance_reached"] is False
    assert data["dispatch_reached"] is False


@pytest.mark.parametrize(
    ("uato", "expected_status"),
    [
        ({"trust_level": "HIGH", "authority_level": "LOW"}, "APPROVAL_REQUIRED"),
        ({"trust_level": "LOW", "authority_level": "HIGH"}, "ESCALATED"),
    ],
)
def test_evaluation_frame_evaluate_reflects_non_pass_statuses(client, auth_headers, uato, expected_status):
    resp = client.post("/evaluation-frame/evaluate", json=_valid_spec(uato=uato), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["frame_status"] == expected_status
    assert data["governance_reached"] is False
    assert data["dispatch_reached"] is False


def test_evaluation_frame_evaluate_reflects_blocked_status_from_invariant_e(client, auth_headers, monkeypatch):
    from app.invariant_e.types import result_denied

    monkeypatch.setattr(
        "app.evaluation.evaluators.invariant_e.evaluate_invariant_e_decision",
        lambda state: result_denied(state.governable.trace_id, ("IE_DENIED_ENDPOINT_TEST",)),
    )
    resp = client.post("/evaluation-frame/evaluate", json=_valid_spec(), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["frame_status"] == "BLOCKED"
    assert data["invariant_e_result"]["decision"] == "EXECUTION_DENIED"
    assert "IE_DENIED_ENDPOINT_TEST" in (data["invariant_e_result"]["reason_codes"] or [])


@pytest.fixture
def client():
    return TestClient(app)
