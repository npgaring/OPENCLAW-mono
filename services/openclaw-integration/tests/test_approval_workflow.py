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
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "PASS"
    assert ef.get("governance_reached") is True
    assert ef.get("dispatch_reached") is False


def test_dedicated_approval_demo_scenario_avoids_invariant_c_goal_mismatch(client, auth_headers):
    r = client.post(
        "/task",
        json={
            **_prod_spec(),
            "goal": "Deploy production build for recruiting applicant workflow rollout",
            "context": "This preset intentionally includes recruiting context for demo parity",
            "validation": {"approval_required_scenario": "GOVERNANCE_PROD_NO_APPROVAL_DEMO"},
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "pending_approval"
    assert data["gate_outcome"] == "BLOCK"
    assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "PASS"
    assert (ef.get("invariant_c_result") or {}).get("decision") == "PASS"
    assert "INVARIANT_C_GOAL_OBJECTIVE_MISMATCH" not in (ef.get("reason_codes") or [])
    assert ef.get("governance_reached") is True
    assert ef.get("dispatch_reached") is False


def test_prod_without_demo_scenario_can_fail_early_at_invariant_c_goal_mismatch(client, auth_headers):
    r = client.post(
        "/task",
        json={
            **_prod_spec(),
            "goal": "Deploy production build for recruiting applicant workflow rollout",
            "context": "This preset intentionally includes recruiting context for demo parity",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "BLOCKED"
    assert (ef.get("invariant_c_result") or {}).get("decision") == "BLOCK"
    assert "INVARIANT_C_GOAL_OBJECTIVE_MISMATCH" in (ef.get("reason_codes") or [])
    assert "PROD_DEPLOY_NO_APPROVAL" not in (data.get("reason_codes") or [])


def test_gate_evaluate_prod_materializes_approval_listable_by_trace(client, auth_headers):
    tid = "550e8400-e29b-41d4-a716-446655440101"
    spec = {**_prod_spec(), "trace_id": tid}
    r = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["outcome"] == "BLOCK"
    assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])
    assert data.get("trace_id") == tid
    assert data.get("approval_request_id")
    assert data.get("approval_status") == "PENDING"
    assert data.get("task_id")
    assert data.get("source_layer") == "GOVERNANCE"
    lg = client.get("/approvals/", params={"trace_id": tid}, headers=auth_headers)
    assert lg.status_code == 200
    rows = lg.json()
    assert isinstance(rows, list) and len(rows) >= 1
    match = [x for x in rows if x.get("trace_id") == tid and x.get("status") == "PENDING"]
    assert match, rows


def test_gate_then_task_same_trace_reuses_single_approval(client, auth_headers):
    tid = "550e8400-e29b-41d4-a716-446655440102"
    spec = {**_prod_spec(), "trace_id": tid}
    g = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert g.status_code == 200
    aid = g.json()["approval_request_id"]
    t = client.post("/task", json=spec, headers=auth_headers)
    assert t.status_code == 200
    assert t.json()["approval_request_id"] == aid
    assert t.json()["status"] == "pending_approval"


def test_gate_created_governance_approval_approve_resume_passes_gate(client, auth_headers):
    tid = "550e8400-e29b-41d4-a716-446655440103"
    spec = {**_prod_spec(), "trace_id": tid}
    g = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert g.status_code == 200
    aid = g.json()["approval_request_id"]
    client.post(f"/approvals/{aid}/approve", json={"approver_id": "alice"}, headers=auth_headers)
    mock_response = {"execution_id": "ex-gate-apr", "status": "completed", "message": "ok"}
    with patch("app.services.task_submission.OpenClawClient") as m:
        m.return_value.execute = AsyncMock(return_value=mock_response)
        rs = client.post(f"/approvals/{aid}/resume", json={}, headers=auth_headers)
    assert rs.status_code == 200
    assert rs.json().get("gate_outcome") == "PASS"


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
