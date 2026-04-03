"""Unit tests for deterministic in-service GitHub/Vercel executor."""
from __future__ import annotations

import json

import pytest

from app.services.deterministic_executor import (
    DeterministicExecutionError,
    DeterministicWebExecutor,
    GeneratedFile,
    REASON_GITHUB_AUTH_FAILED,
    REASON_GITHUB_REPO_CREATE_FAILED,
    REASON_VERCEL_DEPLOY_FAILED,
    REASON_VERCEL_PROJECT_CREATE_FAILED,
    RepoSpec,
    TemplateReference,
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


@pytest.mark.asyncio
async def test_github_create_empty_repo_prefers_org_endpoint_for_explicit_owner(monkeypatch):
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_token", None)
    calls: list[str] = []

    async def _fake_request(client, method, url, *, headers, params=None, payload=None):
        calls.append(f"{method} {url}")
        if method == "POST" and url.endswith("/orgs/test-owner/repos"):
            return _Resp(
                201,
                {
                    "owner": {"login": "test-owner"},
                    "html_url": "https://github.com/test-owner/test-site",
                    "default_branch": "main",
                },
            ), {
                "owner": {"login": "test-owner"},
                "html_url": "https://github.com/test-owner/test-site",
                "default_branch": "main",
            }
        return _Resp(500, {"message": "unexpected"}), {"message": "unexpected"}

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._request",
        staticmethod(_fake_request),
    )
    result = await DeterministicWebExecutor()._github_create_empty_repo(
        client=None,  # type: ignore[arg-type]
        installation_token="ghs_installation_token",
        spec=RepoSpec(owner="test-owner", name="test-site", branch="main", private=True),
    )

    assert result is not None
    assert result.owner == "test-owner"
    assert any(url.endswith("/orgs/test-owner/repos") for url in calls)
    assert not any(url.endswith("/user/repos") for url in calls)


@pytest.mark.asyncio
async def test_github_create_empty_repo_rejects_owner_mismatch(monkeypatch):
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_token", "pat_123")

    async def _fake_request(client, method, url, *, headers, params=None, payload=None):
        if method == "POST" and url.endswith("/orgs/target-org/repos"):
            return _Resp(403, {"message": "forbidden"}), {"message": "forbidden"}
        if method == "POST" and url.endswith("/user/repos"):
            return _Resp(
                201,
                {
                    "owner": {"login": "different-owner"},
                    "html_url": "https://github.com/different-owner/test-site",
                    "default_branch": "main",
                },
            ), {
                "owner": {"login": "different-owner"},
                "html_url": "https://github.com/different-owner/test-site",
                "default_branch": "main",
            }
        return _Resp(500, {"message": "unexpected"}), {"message": "unexpected"}

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._request",
        staticmethod(_fake_request),
    )
    result = await DeterministicWebExecutor()._github_create_empty_repo(
        client=None,  # type: ignore[arg-type]
        installation_token="ghs_installation_token",
        spec=RepoSpec(owner="target-org", name="test-site", branch="main", private=True),
    )

    assert result is None


def test_ensure_scaffold_integrity_preserves_template_packages_and_adds_missing_import_deps():
    files = [
        GeneratedFile(
            path="app/page.tsx",
            content=(
                'import { motion } from "framer-motion";\n'
                "export default function Page(){return <motion.div />;}\n"
            ),
        ),
        GeneratedFile(
            path="package.json",
            content='{"name":"demo","private":true,"dependencies":{"react":"19.0.0"}}',
        ),
    ]
    template_reference = TemplateReference(
        source_repo="braieswabe/Dudex-Projects",
        source_branch="main",
        package_json={
            "dependencies": {
                "next": "15.5.14",
                "react": "19.0.0",
                "react-dom": "19.0.0",
                "tailwindcss": "^4.2.2",
                "@tailwindcss/postcss": "^4.2.2",
                "clsx": "^2.1.1",
            },
            "devDependencies": {
                "typescript": "^5.8.3",
                "eslint": "^9.39.1",
                "eslint-config-next": "15.5.14",
            },
        },
    )

    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files, template_reference=template_reference)
    package_file = next(f for f in out if f.path == "package.json")
    pkg = json.loads(package_file.content)

    assert pkg["dependencies"]["next"] == "15.5.14"
    assert pkg["dependencies"]["clsx"] == "^2.1.1"
    assert pkg["dependencies"]["framer-motion"] == "latest"
    assert pkg["devDependencies"]["eslint-config-next"] == "15.5.14"
    assert any(f.path == "app/globals.css" for f in out)


def test_build_codegen_prompt_includes_template_reference():
    template_reference = TemplateReference(
        source_repo="braieswabe/Dudex-Projects",
        source_branch="main",
        package_json={
            "dependencies": {"next": "15.5.14", "react": "19.0.0"},
            "devDependencies": {"typescript": "^5.8.3"},
        },
        key_files={"app/layout.tsx": "export default function Layout(){}"},
    )

    prompt = DeterministicWebExecutor()._build_codegen_prompt(
        context={"goal": "Launch site"},
        file_specs=[{"path": "app/page.tsx", "hint": ""}],
        template_reference=template_reference,
    )

    assert "Template Reference" in prompt
    assert "braieswabe/Dudex-Projects@main" in prompt
    assert "Template Dependencies" in prompt
    assert "Template Baseline Files Present" in prompt


def test_ensure_scaffold_integrity_normalizes_robots_metadata_key_casing():
    files = [
        GeneratedFile(
            path="src/app/robots.ts",
            content=(
                'import type { MetadataRoute } from "next";\n\n'
                "export default function robots(): MetadataRoute.Robots {\n"
                "  return {\n"
                "    rules: {\n"
                '      UserAgent: "*",\n'
                '      Disallow: "/api/",\n'
                "    },\n"
                "  };\n"
                "}\n"
            ),
        ),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
    ]

    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files)
    robots = next(f for f in out if f.path == "src/app/robots.ts").content

    assert "UserAgent:" not in robots
    assert "Disallow:" not in robots
    assert "userAgent:" in robots
    assert "disallow:" in robots
