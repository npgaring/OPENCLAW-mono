"""First-class approval workflow: create, approve/reject, resume, consume."""
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


def _base_spec():
    ops = [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
    }


def test_uato_require_approval_returns_approval_request(client, auth_headers):
    r = client.post(
        "/task",
        json={**_base_spec(), "uato": {"trust_level": "HIGH", "authority_level": "LOW"}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "pending_approval"
    assert data.get("approval_required") is True
    assert data.get("approval_request_id")
    assert data.get("approval_status") == "PENDING"
    assert data.get("source_layer") == "UATO"
    assert data.get("resume_available") is True


def test_uato_block_does_not_create_approval_workflow_fields(client, auth_headers):
    r = client.post(
        "/task",
        json={**_base_spec(), "uato": {"trust_level": "LOW", "authority_level": "LOW"}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "uato_blocked"
    assert data.get("approval_required") is not True
    assert data.get("approval_request_id") in (None, "")


def _prod_spec():
    ops = [
        {
            "type": "deploy",
            "op_id": "d1",
            "target": "web/app",
            "inputs": {"provider": "vercel", "project": "x"},
            "outputs": {},
        }
    ]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
        "deployment_target": "production",
    }


def test_prod_without_approval_creates_governance_approval(client, auth_headers):
    r = client.post("/task", json=_prod_spec(), headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["gate_outcome"] == "BLOCK"
    assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])
    assert data.get("approval_required") is True
    assert data.get("source_layer") == "GOVERNANCE"
    assert data.get("approval_request_id")
    assert data["status"] == "pending_approval"


def test_approve_and_reject_validate_pending(client, auth_headers):
    r0 = client.post("/task", json=_prod_spec(), headers=auth_headers)
    aid = r0.json()["approval_request_id"]
    r1 = client.post(
        f"/approvals/{aid}/approve",
        json={"approver_id": "alice", "comment": "ok"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "APPROVED"
    r2 = client.post(
        f"/approvals/{aid}/approve",
        json={"approver_id": "bob", "comment": "again"},
        headers=auth_headers,
    )
    assert r2.status_code == 422

    r3 = client.post("/task", json=_prod_spec(), headers=auth_headers)
    aid2 = r3.json()["approval_request_id"]
    r4 = client.post(
        f"/approvals/{aid2}/reject",
        json={"approver_id": "carol", "comment": "no"},
        headers=auth_headers,
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "REJECTED"
    r5 = client.post(
        f"/approvals/{aid2}/reject",
        json={"approver_id": "dave", "comment": "again"},
        headers=auth_headers,
    )
    assert r5.status_code == 422


def test_resume_consumes_and_blocks_reuse(client, auth_headers):
    spec_ok = {
        **_prod_spec(),
        "approval_reference": "human-approved-ref",
    }
    mock_response = {"execution_id": "ex-apr", "status": "completed", "message": "ok"}
    with patch("app.services.task_submission.OpenClawClient") as m:
        m.return_value.execute = AsyncMock(return_value=mock_response)
        r0 = client.post("/task", json=spec_ok, headers=auth_headers)
        assert r0.status_code == 200
        assert r0.json()["gate_outcome"] == "PASS"

    r1 = client.post("/task", json=_prod_spec(), headers=auth_headers)
    aid = r1.json()["approval_request_id"]
    client.post(f"/approvals/{aid}/approve", json={"approver_id": "alice"}, headers=auth_headers)
    with patch("app.services.task_submission.OpenClawClient") as m:
        m.return_value.execute = AsyncMock(return_value=mock_response)
        rs = client.post(f"/approvals/{aid}/resume", json={}, headers=auth_headers)
        assert rs.status_code == 200
        assert rs.json().get("gate_outcome") == "PASS"
    r2 = client.post(f"/approvals/{aid}/resume", json={}, headers=auth_headers)
    assert r2.status_code == 422


def test_list_and_get_approvals(client, auth_headers):
    client.post("/task", json=_prod_spec(), headers=auth_headers)
    lg = client.get("/approvals/", headers=auth_headers)
    assert lg.status_code == 200
    rows = lg.json()
    assert isinstance(rows, list) and len(rows) >= 1
    aid = rows[0]["id"]
    g = client.get(f"/approvals/{aid}", headers=auth_headers)
    assert g.status_code == 200
    assert g.json()["id"] == aid


def test_adapter_metadata_response_includes_approval_id(client, auth_headers):
    from tests.test_openai_flow_api import _candidate_plan

    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "production",
        "objective": "Deploy the website to production",
        "candidate_plan": _candidate_plan(requires_approval=True),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 422
    d = resp.json()["detail"]
    assert d["code"] == "METADATA_APPROVAL_REQUIRED"
    assert d.get("approval_request_id")
    assert d.get("approval_status") == "PENDING"
