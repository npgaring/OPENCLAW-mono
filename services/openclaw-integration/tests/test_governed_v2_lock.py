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


def _ops_with_provisioning():
    return [
        {
            "op_id": "op-001",
            "type": "provision_repo",
            "target": "repo",
            "inputs": {"provider": "github", "name": "cdmbr-launch-site"},
            "outputs": {},
        },
        {
            "op_id": "op-002",
            "type": "create_file",
            "target": "repo",
            "inputs": {"path": "README.md", "content": "# CDMBR Launch Site"},
            "outputs": {},
        },
        {
            "op_id": "op-003",
            "type": "deploy",
            "target": "hosting/vercel",
            "inputs": {"provider": "vercel", "project": "cdmbr-launch-site"},
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

    openclaw_mock = AsyncMock(
        return_value={
            "status": "success",
            "execution_id": "ex-should-not-run",
            "message": "should not be used for deterministic",
        }
    )
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", openclaw_mock)
    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor.execute",
        AsyncMock(
            return_value={
                "status": "success",
                "execution_id": "ex-governed-v2",
                "message": "Deployment complete: https://governed-preview-123.vercel.app",
                "artifacts": [
                    {
                        "path": "https://github.com/example/cdmbr-launch-site-abc123",
                        "type": "repository",
                        "summary": "repo",
                    }
                ],
                "deployment_url": "https://governed-preview-123.vercel.app",
                "preview_url": "https://governed-preview-123.vercel.app",
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
    assert openclaw_mock.await_count == 0

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


def test_v2_execution_plan_lock_allows_template_literal_file_content(auth_headers):
    client = TestClient(app)
    ops = [
        {
            "op_id": "op-001",
            "type": "create_file",
            "target": "web/app",
            "inputs": {
                "path": "src/app/sitemap.ts",
                "content": "const sitemap = `${baseUrl}/sitemap.xml`;",
            },
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
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    lock_resp = client.post(
        "/v2/execution-plan/lock",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "96a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "build_sot_hash": "sot_abc124",
            "execution_plan_hash": "ep_xyz790",
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
    assert "SANDBOX_REJECTION" not in (lock.get("reason_codes") or [])


def test_v2_task_downgrades_success_without_repo_or_deploy_evidence(auth_headers, monkeypatch):
    client = TestClient(app)
    ops = _ops_with_provisioning()
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    lock_resp = client.post(
        "/v2/execution-plan/lock",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "98a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "build_sot_hash": "sot_abc125",
            "execution_plan_hash": "ep_xyz791",
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

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor.execute",
        AsyncMock(
            return_value={
                "status": "success",
                "execution_id": "resp_fake_001",
                "message": (
                    "The deterministic execution plan is ready. "
                    "If you'd like, I can proceed with provisioning and deploy next."
                ),
            }
        ),
    )

    task_resp = client.post(
        "/task",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "98a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "deterministic executor",
            "build_sot_hash": "sot_abc125",
            "execution_plan_hash": "ep_xyz791",
            "v2_continuity_id": lock["continuity_id"],
            "executor_contract": "deterministic_web_v1",
            "execution_plan_v2": {"commands": [{"id": "cmd-001", "type": "provision_repo"}]},
        },
        headers=auth_headers,
    )
    assert task_resp.status_code == 200, task_resp.text
    task = task_resp.json()
    assert task["status"] == "needs_review"
    assert "EXECUTION_EVIDENCE_MISSING_GITHUB_URL" in (task.get("reason_codes") or [])
    assert "EXECUTION_EVIDENCE_MISSING_DEPLOYMENT_URL" in (task.get("reason_codes") or [])


def test_v2_task_downgrades_success_with_placeholder_urls(auth_headers, monkeypatch):
    client = TestClient(app)
    ops = _ops_with_provisioning()
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    lock_resp = client.post(
        "/v2/execution-plan/lock",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "99a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "build_sot_hash": "sot_abc126",
            "execution_plan_hash": "ep_xyz792",
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

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor.execute",
        AsyncMock(
            return_value={
                "status": "success",
                "execution_id": "resp_fake_002",
                "message": "Done.",
                "deployment_url": "https://cdmbr-site-{timestamp}.vercel.app",
                "artifacts": [
                    {
                        "path": "https://github.com/Conversion-Interactive-Agency/cdmbr-site-{timestamp}",
                        "type": "repository",
                        "summary": "placeholder",
                    }
                ],
            }
        ),
    )

    task_resp = client.post(
        "/task",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "99a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "deterministic executor",
            "build_sot_hash": "sot_abc126",
            "execution_plan_hash": "ep_xyz792",
            "v2_continuity_id": lock["continuity_id"],
            "executor_contract": "deterministic_web_v1",
            "execution_plan_v2": {"commands": [{"id": "cmd-001", "type": "provision_repo"}]},
        },
        headers=auth_headers,
    )
    assert task_resp.status_code == 200, task_resp.text
    task = task_resp.json()
    assert task["status"] == "needs_review"
    assert "EXECUTION_EVIDENCE_MISSING_GITHUB_URL" in (task.get("reason_codes") or [])
    assert "EXECUTION_EVIDENCE_MISSING_DEPLOYMENT_URL" in (task.get("reason_codes") or [])


def test_v2_execution_plan_lock_prefixed_path_resolves(auth_headers):
    client = TestClient(app)
    ops = _ops()
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    lock_resp = client.post(
        "/openclaw-integration/v2/execution-plan/lock",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "97a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "build_sot_hash": "sot_prefixed_001",
            "execution_plan_hash": "ep_prefixed_001",
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


def test_task_non_deterministic_contract_still_uses_openclaw_gateway(auth_headers, monkeypatch):
    client = TestClient(app)
    ops = _ops()
    plan_hash = hash_payload({"domain": "web", "operations": ops})

    gateway_execute = AsyncMock(
        return_value={
            "status": "success",
            "execution_id": "ex-gateway-001",
            "message": "Gateway execution complete: https://governed-preview-321.vercel.app",
        }
    )
    deterministic_execute = AsyncMock(
        side_effect=AssertionError("deterministic executor should not run for non-deterministic plans")
    )
    monkeypatch.setattr("app.services.execution_client.OpenClawClient.execute", gateway_execute)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor.execute", deterministic_execute)

    task_resp = client.post(
        "/task",
        json={
            "ocgg_identity": "W-OCGG",
            "trace_id": "10a8bbd3-6e9a-4664-b8e7-7db61ca11c03",
            "plan_hash": plan_hash,
            "operations": ops,
            "deployment_target": "preview",
            "goal": "Build governed preview.",
            "context": "gateway executor",
        },
        headers=auth_headers,
    )
    assert task_resp.status_code == 200, task_resp.text
    body = task_resp.json()
    assert body["status"] == "completed"
    assert body["execution_id"] == "ex-gateway-001"
    assert gateway_execute.await_count == 1
    assert deterministic_execute.await_count == 0
