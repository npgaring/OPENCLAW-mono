"""
Gate mutation matrix — parametrised bad requests → stable BLOCK (+ reason codes).
See docs/GATE_MUTATION_MATRIX.md for the stakeholder-facing table.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-integration-key"}


def _valid_ops():
    return [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]


def _valid_spec():
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    operations = _valid_ops()
    ph = hash_payload({"domain": domain, "operations": operations})
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": operations,
    }


@pytest.mark.parametrize(
    "name,mutator,expected_codes",
    [
        ("missing_plan_hash", lambda s: {k: v for k, v in s.items() if k != "plan_hash"}, {"MISSING_FIELD"}),
        # UATO pre-gate admissibility blocks empty plan_hash / empty ops before governance (fail-closed).
        ("empty_plan_hash", lambda s: {**s, "plan_hash": ""}, {"UATO_BLOCK_MALFORMED_PLAN"}),
        ("wrong_plan_hash", lambda s: {**s, "plan_hash": "deadbeef"}, {"PLAN_HASH_MISMATCH"}),
        ("missing_operations", lambda s: {k: v for k, v in s.items() if k != "operations"}, {"MISSING_FIELD"}),
        ("empty_operations_list", lambda s: {**s, "operations": []}, {"UATO_BLOCK_MALFORMED_PLAN"}),
        ("operations_not_list", lambda s: {**s, "operations": {}}, {"INVALID_SCHEMA"}),
    ],
)
def test_task_submit_mutation_blocks(client, auth_headers, name, mutator, expected_codes):
    spec = mutator(_valid_spec())
    resp = client.post("/task", json=spec, headers=auth_headers)
    # FastAPI/Pydantic may reject before GateEngine (422) — still a deny path.
    if resp.status_code == 422:
        assert name in (
            "missing_plan_hash",
            "missing_operations",
            "operations_not_list",
        ), f"{name}: unexpected 422"
        return
    assert resp.status_code == 200, f"{name}: {resp.text}"
    data = resp.json()
    assert data.get("gate_outcome") == "BLOCK", f"{name}: {data}"
    rc = set(data.get("reason_codes") or [])
    assert expected_codes.issubset(rc), f"{name}: expected {expected_codes} subset of {rc}"


def test_prod_without_approval_blocks(client, auth_headers):
    s = _valid_spec()
    s["deployment_target"] = "production"
    resp = client.post("/task", json=s, headers=auth_headers)
    data = resp.json()
    assert data.get("gate_outcome") == "BLOCK"
    assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])


def test_gate_evaluate_returns_trace_id(client, auth_headers):
    spec = _valid_spec()
    spec["trace_id"] = "550e8400-e29b-41d4-a716-446655440000"
    resp = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("trace_id") == "550e8400-e29b-41d4-a716-446655440000"
    assert "plan_hash" in data


def test_task_submit_generates_trace_id_when_omitted(client, auth_headers):
    with patch("app.api.task.OpenClawClient") as m:
        m.return_value.execute = AsyncMock(
            return_value={"execution_id": "x", "status": "success", "message": "ok"}
        )
        s = _valid_spec()
        s["deployment_target"] = "preview"
        resp = client.post("/task", json=s, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    if data.get("gate_outcome") == "PASS":
        assert data.get("trace_id")
        assert data.get("audit_trace_id") == data.get("trace_id")
