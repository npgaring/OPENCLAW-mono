"""Unit tests for deterministic in-service GitHub/Vercel executor."""
from __future__ import annotations

import pytest

from app.services.deterministic_executor import (
    DeterministicExecutionError,
    DeterministicWebExecutor,
    REASON_GITHUB_AUTH_FAILED,
    REASON_GITHUB_REPO_CREATE_FAILED,
    REASON_VERCEL_DEPLOY_FAILED,
    REASON_VERCEL_PROJECT_CREATE_FAILED,
)


class _Resp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or ""

    def json(self):
        return self._payload


def _plan():
    return {
        "executor_contract": "deterministic_web_v1",
        "operations": [
            {
                "op_id": "op-001",
                "type": "provision_repo",
                "target": "repo",
                "inputs": {
                    "provider": "github",
                    "owner": "test-owner",
                    "repo_name": "test-site",
                    "default_branch": "prod",
                    "visibility": "private",
                },
                "outputs": {},
            },
            {
                "op_id": "op-002",
                "type": "create_file",
                "target": "repo",
                "inputs": {"path": "app/page.tsx", "content": "export default function Page(){return null;}"},
                "outputs": {},
            },
            {
                "op_id": "op-003",
                "type": "write_config",
                "target": "repo",
                "inputs": {"path": "package.json", "content": '{"name":"test-site"}'},
                "outputs": {},
            },
            {
                "op_id": "op-004",
                "type": "provision_hosting",
                "target": "hosting/vercel",
                "inputs": {"provider": "vercel", "team_id": "team_123", "project_name": "test-site"},
                "outputs": {},
            },
            {
                "op_id": "op-005",
                "type": "deploy",
                "target": "hosting/vercel",
                "inputs": {"provider": "vercel", "team_id": "team_123", "project": "test-site", "branch": "prod"},
                "outputs": {},
            },
        ],
    }


def _configure_settings(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_app_id", "12345")
    monkeypatch.setattr(
        "app.services.deterministic_executor.settings.github_private_key",
        "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
    )
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_installation_id", "777")
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_owner", "template-owner")
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_repo", "template-repo")
    monkeypatch.setattr("app.services.deterministic_executor.settings.vercel_token", "vercel-token-123")
    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._sign_rs256",
        staticmethod(lambda payload, private_key_pem: b"signature"),
    )


def _patch_client(monkeypatch, resolver):
    calls = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, headers=None, params=None, json=None):
            calls.append({"method": method, "url": url, "params": params or {}, "json": json or {}, "headers": headers or {}})
            return resolver(method, url, params or {}, json or {}, headers or {})

    monkeypatch.setattr("app.services.deterministic_executor.httpx.AsyncClient", _Client)
    return calls


@pytest.mark.asyncio
async def test_deterministic_execute_success_returns_concrete_urls(monkeypatch):
    _configure_settings(monkeypatch)
    plan = _plan()

    def _resolver(method, url, params, body, headers):
        if method == "POST" and url.endswith("/app/installations/777/access_tokens"):
            return _Resp(201, {"token": "ghs_installation_token"})
        if method == "POST" and url.endswith("/repos/template-owner/template-repo/generate"):
            return _Resp(201, {"html_url": "https://github.com/test-owner/test-site", "default_branch": "main"})
        if method == "GET" and url.endswith("/repos/test-owner/test-site/git/ref/heads/prod"):
            return _Resp(404, {"message": "Not Found"})
        if method == "GET" and url.endswith("/repos/test-owner/test-site/git/ref/heads/main"):
            return _Resp(200, {"object": {"sha": "sha-main-1"}})
        if method == "POST" and url.endswith("/repos/test-owner/test-site/git/refs"):
            return _Resp(201, {"ref": "refs/heads/prod"})
        if method == "GET" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(404, {"message": "Not Found"})
        if method == "PUT" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(201, {"commit": {"sha": "sha-commit-1"}})
        if method == "GET" and "/v9/projects/test-site" in url:
            return _Resp(404, {"error": {"message": "missing"}})
        if method == "POST" and "/v11/projects" in url:
            return _Resp(201, {"id": "prj_abc", "name": "test-site"})
        if method == "POST" and "/v13/deployments" in url:
            return _Resp(200, {"id": "dpl_123", "url": "test-site-git.vercel.app"})
        return _Resp(500, {"message": f"Unhandled route {method} {url}"})

    calls = _patch_client(monkeypatch, _resolver)
    out = await DeterministicWebExecutor().execute(plan, task_id="task-1", trace_id="trace-1", deployment_target="preview")

    assert out["status"] == "success"
    assert out["repository_url"] == "https://github.com/test-owner/test-site"
    assert out["deployment_url"] == "https://test-site-git.vercel.app"
    assert out["preview_url"] == "https://test-site-git.vercel.app"
    assert out["repo_commit_sha"] == "sha-commit-1"
    assert any(c["method"] == "PUT" and c["url"].endswith("/contents/app/page.tsx") for c in calls)
    assert any(c["method"] == "PUT" and c["url"].endswith("/contents/package.json") for c in calls)
    assert any(c["method"] == "POST" and "/v13/deployments" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_deterministic_execute_missing_github_app_credentials_fails_fast(monkeypatch):
    plan = _plan()
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_app_id", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_private_key", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_installation_id", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_owner", "template-owner")
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_repo", "template-repo")
    monkeypatch.setattr("app.services.deterministic_executor.settings.vercel_token", "vercel-token-123")

    with pytest.raises(DeterministicExecutionError) as err:
        await DeterministicWebExecutor().execute(plan, task_id="task-2", trace_id="trace-2", deployment_target="preview")
    assert err.value.reason_code == REASON_GITHUB_AUTH_FAILED


@pytest.mark.asyncio
async def test_deterministic_execute_template_generation_failure_maps_reason_code(monkeypatch):
    _configure_settings(monkeypatch)
    plan = _plan()

    def _resolver(method, url, params, body, headers):
        if method == "POST" and url.endswith("/app/installations/777/access_tokens"):
            return _Resp(201, {"token": "ghs_installation_token"})
        if method == "POST" and url.endswith("/repos/template-owner/template-repo/generate"):
            return _Resp(422, {"message": "name already exists"})
        if method == "GET" and url.endswith("/repos/test-owner/test-site"):
            return _Resp(404, {"message": "Not Found"})
        return _Resp(500, {"message": "unexpected"})

    _patch_client(monkeypatch, _resolver)
    with pytest.raises(DeterministicExecutionError) as err:
        await DeterministicWebExecutor().execute(plan, task_id="task-3", trace_id="trace-3", deployment_target="preview")
    assert err.value.reason_code == REASON_GITHUB_REPO_CREATE_FAILED


@pytest.mark.asyncio
async def test_deterministic_execute_vercel_project_failure_maps_reason_code(monkeypatch):
    _configure_settings(monkeypatch)
    plan = _plan()

    def _resolver(method, url, params, body, headers):
        if method == "POST" and url.endswith("/app/installations/777/access_tokens"):
            return _Resp(201, {"token": "ghs_installation_token"})
        if method == "POST" and url.endswith("/repos/template-owner/template-repo/generate"):
            return _Resp(201, {"html_url": "https://github.com/test-owner/test-site", "default_branch": "prod"})
        if method == "GET" and url.endswith("/repos/test-owner/test-site/git/ref/heads/prod"):
            return _Resp(200, {"object": {"sha": "sha-prod"}})
        if method == "GET" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(404, {"message": "Not Found"})
        if method == "PUT" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(201, {"commit": {"sha": "sha-commit-1"}})
        if method == "GET" and "/v9/projects/test-site" in url:
            return _Resp(500, {"error": {"message": "vercel unavailable"}})
        return _Resp(500, {"message": "unexpected"})

    _patch_client(monkeypatch, _resolver)
    with pytest.raises(DeterministicExecutionError) as err:
        await DeterministicWebExecutor().execute(plan, task_id="task-4", trace_id="trace-4", deployment_target="preview")
    assert err.value.reason_code == REASON_VERCEL_PROJECT_CREATE_FAILED


@pytest.mark.asyncio
async def test_deterministic_execute_vercel_deploy_failure_maps_reason_code(monkeypatch):
    _configure_settings(monkeypatch)
    plan = _plan()

    def _resolver(method, url, params, body, headers):
        if method == "POST" and url.endswith("/app/installations/777/access_tokens"):
            return _Resp(201, {"token": "ghs_installation_token"})
        if method == "POST" and url.endswith("/repos/template-owner/template-repo/generate"):
            return _Resp(201, {"html_url": "https://github.com/test-owner/test-site", "default_branch": "prod"})
        if method == "GET" and url.endswith("/repos/test-owner/test-site/git/ref/heads/prod"):
            return _Resp(200, {"object": {"sha": "sha-prod"}})
        if method == "GET" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(404, {"message": "Not Found"})
        if method == "PUT" and "/repos/test-owner/test-site/contents/" in url:
            return _Resp(201, {"commit": {"sha": "sha-commit-1"}})
        if method == "GET" and "/v9/projects/test-site" in url:
            return _Resp(404, {"message": "Not Found"})
        if method == "POST" and "/v11/projects" in url:
            return _Resp(201, {"id": "prj_abc", "name": "test-site"})
        if method == "POST" and "/v13/deployments" in url:
            return _Resp(400, {"error": {"message": "bad deployment payload"}})
        return _Resp(500, {"message": "unexpected"})

    _patch_client(monkeypatch, _resolver)
    with pytest.raises(DeterministicExecutionError) as err:
        await DeterministicWebExecutor().execute(plan, task_id="task-5", trace_id="trace-5", deployment_target="preview")
    assert err.value.reason_code == REASON_VERCEL_DEPLOY_FAILED
