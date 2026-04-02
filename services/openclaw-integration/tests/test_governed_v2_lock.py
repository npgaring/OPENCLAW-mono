"""Tests for governed v2 execution-plan locks and continuity enforcement."""
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.security import hash_payload
from app.main import app


def _ops():
    return [
        {
            "op_id": "op-001",
            "type": "create_file",
            "target": "web/app",
            "inputs": {"path": "site/index.html", "content": "<h1>Hello</h1>"},
            "outputs": {},
        },
        {
            "op_id": "op-002",
            "type": "build",
            "target": "web/app",
            "inputs": {"command": "run_smoke_checks"},
            "outputs": {},
        },
    ]


def test_v2_execution_plan_lock_and_task_continuity_flow(auth_headers, monkeypatch):
    client = TestClient(app)
    ops = _ops()
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    lock_resp = client.post(
        "/v2/execution-plan/lock",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "95a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "build_sot_hash": "sot_abc123",
            "execution_plan_hash": "ep_xyz789",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "deterministic executor",
        },
        headers=auth_headers,
    )
    assert lock_resp.status_code == 200, lock_resp.text
    lock = lock_resp.json()
    assert lock["outcome"] == "PASS"
    assert lock["continuity_id"]
    assert lock["governance_evaluation_id"]

    monkeypatch.setattr(
        "app.services.execution_client.OpenClawClient.execute",
        AsyncMock(
            return_value={
                "status": "success",
                "execution_id": "ex-governed-v2",
                "message": "Deployment complete: https://governed-preview-123.vercel.app",
            }
        ),
    )

    task_resp = client.post(
        "/task",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "95a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "deterministic executor",
            "build_sot_hash": "sot_abc123",
            "execution_plan_hash": "ep_xyz789",
            "v2_continuity_id": lock["continuity_id"],
            "executor_contract": "deterministic_web_v1",
            "execution_plan_v2": {"commands": [{"id": "cmd-001", "type": "write_files"}]},
        },
        headers=auth_headers,
    )
    assert task_resp.status_code == 200, task_resp.text
    task = task_resp.json()
    assert task["status"] == "completed"
    assert task["governance_continuity_verified"] is True
    assert task["deployment_url"] == "https://governed-preview-123.vercel.app"
    assert task["preview_url"] == "https://governed-preview-123.vercel.app"

    replay_resp = client.post(
        "/task",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "95a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "deterministic executor",
            "build_sot_hash": "sot_abc123",
            "execution_plan_hash": "ep_xyz789",
            "v2_continuity_id": lock["continuity_id"],
        },
        headers=auth_headers,
    )
    assert replay_resp.status_code == 422, replay_resp.text
    detail = replay_resp.json()["detail"]
    assert detail["code"] == "V2_CONTINUITY_NOT_ACTIVE"


def test_v2_build_sot_lock_pass_path(auth_headers):
    client = TestClient(app)
    ops = _ops()
    plan_hash = hash_payload({"domain": "web", "operations": ops})
    resp = client.post(
        "/v2/build-sot/lock",
        json={
            "build_sot_hash": "sot_lock_001",
            "trace_id": "f9a7f4d7-864f-4c58-82dd-ee9089ca23f4",
            "ocgg_identity": "W-OCGG",
            "intent": "web-build",
            "governance_projection": {
                "ocgg_identity": "W-OCGG",
                "plan_hash": plan_hash,
                "operations": ops,
                "deployment_target": "preview",
                "goal": "Build SoT lock check",
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "PASS"
    assert body["governance_plan_hash"] == plan_hash
