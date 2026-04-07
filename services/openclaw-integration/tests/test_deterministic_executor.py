"""Unit tests for deterministic in-service GitHub/Vercel executor."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services.deterministic_executor import (
    DeterministicExecutionError,
    DeterministicWebExecutor,
    GeneratedFile,
    LocalPreflightResult,
    REASON_GITHUB_AUTH_FAILED,
    REASON_GITHUB_REPO_CREATE_FAILED,
    REASON_VERCEL_DEPLOY_FAILED,
    REASON_VERCEL_PROJECT_CREATE_FAILED,
    RepoProvisionResult,
    RepoSpec,
    TemplateReference,
    VercelDeploymentResult,
    VercelProjectResult,
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
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_enabled", False)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_strict_import_graph_enabled", True)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_timeout_seconds", 30)
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

    assert pkg["dependencies"]["next"] == "^15.5.14"
    assert pkg["dependencies"]["clsx"] == "^2.1.1"
    assert pkg["dependencies"]["framer-motion"] == "latest"
    assert pkg["devDependencies"]["eslint-config-next"] == "15.5.14"
    assert any(f.path == "app/globals.css" for f in out)


def test_build_foundation_prompt_includes_template_reference():
    template_reference = TemplateReference(
        source_repo="braieswabe/Dudex-Projects",
        source_branch="main",
        package_json={
            "dependencies": {"next": "15.5.14", "react": "19.0.0"},
            "devDependencies": {"typescript": "^5.8.3"},
        },
        key_files={"app/layout.tsx": "export default function Layout(){}"},
    )

    prompt = DeterministicWebExecutor()._build_foundation_prompt(
        goal="Launch site",
        project_context="Marketing website",
        shared_components=["HeroBanner"],
        pages=[{"title": "Home", "slug": "home"}],
        design_notes="Bold hero",
        color_palette={"primary": "#111111", "secondary": "#222222", "accent": "#333333"},
        content_strategy="Conversion-focused",
        template_reference=template_reference,
    )

    assert "Template Reference: braieswabe/Dudex-Projects" in prompt


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


def test_ensure_scaffold_integrity_strips_invalid_approved_package_subpath():
    files = [
        GeneratedFile(
            path="src/app/page.tsx",
            content='import Link from "next/nonexistent";\nexport default function Page(){return null;}\n',
        ),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
    ]

    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files)
    page = next(f for f in out if f.path == "src/app/page.tsx").content

    assert not any(
        line.strip().startswith('import Link from "next/nonexistent";')
        for line in page.splitlines()
    )
    assert "[ALLOWLIST] removed" in page


def test_ensure_scaffold_integrity_repairs_existing_binding_without_creating_stub(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_strict_import_graph_enabled", True)
    files = [
        GeneratedFile(
            path="src/app/page.tsx",
            content='import { cmsClient } from "@/lib/cms";\nexport default function Page(){return null;}\n',
        ),
        GeneratedFile(
            path="src/lib/cms.ts",
            content="const client = {};\nexport default client;\n",
        ),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
    ]

    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files)
    cms_file = next(f for f in out if f.path == "src/lib/cms.ts").content

    assert "export const cmsClient = client;" in cms_file
    assert not any(f.path == "src/lib/cmsClient.ts" for f in out)


def test_ensure_scaffold_integrity_is_idempotent():
    files = [
        GeneratedFile(
            path="src/app/page.tsx",
            content=(
                'import { Hero } from "@/components/Hero";\n'
                'import Link from "next/link";\n'
                "export default function Page(){return <Hero />;}\n"
            ),
        ),
        GeneratedFile(
            path="src/components/Hero.tsx",
            content="export default function Hero(){return <div>Hero</div>;}\n",
        ),
        GeneratedFile(
            path="package.json",
            content='{"name":"demo","private":true,"dependencies":{"next":"^13.0.0","react":"^18.2.0"}}',
        ),
    ]

    executor = DeterministicWebExecutor()
    first = executor._ensure_scaffold_integrity(files)
    second = executor._ensure_scaffold_integrity(first)

    def _snapshot(items):
        return sorted((item.path, item.content) for item in items)

    assert _snapshot(first) == _snapshot(second)


def test_auto_fix_build_errors_ignores_package_json_changes(monkeypatch):
    async def _fake_chat(self, api_key, model, system_prompt, user_prompt, *, temperature=0.2, max_tokens=8000):
        return (
            "===FILE: package.json===\n"
            '{"name":"demo","private":true,"dependencies":{"next":"^13.0.0"}}\n'
            "===END_FILE===\n"
            "===FILE: src/app/page.tsx===\n"
            "export default function Page(){return <main>ok</main>;}\n"
            "===END_FILE===\n"
        )

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._openai_chat",
        _fake_chat,
    )

    files = [
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null;}\n"),
    ]

    out = asyncio.run(
        DeterministicWebExecutor()._auto_fix_build_errors(
            "sk-test",
            "gpt-test",
            "build error",
            files,
        )
    )
    pkg = json.loads(next(f for f in out if f.path == "package.json").content)

    assert pkg["dependencies"]["next"] == "^15.5.14"
    assert "13.0.0" not in next(f for f in out if f.path == "package.json").content


def test_ensure_scaffold_integrity_adds_use_client_for_interactive_component():
    files = [
        GeneratedFile(
            path="src/components/Counter.tsx",
            content=(
                'import { useState } from "react";\n'
                "export function Counter(){const [count,setCount]=useState(0);return <button onClick={()=>setCount(count+1)}>{count}</button>;}\n"
            ),
        ),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
    ]

    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files)
    counter = next(f for f in out if f.path == "src/components/Counter.tsx").content

    assert counter.startswith('"use client";')


def test_execute_runs_local_preflight_before_commit_and_deploy(monkeypatch):
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_enabled", True)
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")

    calls: list[str] = []
    generated_files = [
        GeneratedFile(path="package.json", content='{"name":"test-site","private":true}'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null;}\n"),
    ]

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_provision_repo(self, client, installation_token, spec):
        return RepoProvisionResult(
            owner=spec.owner,
            name=spec.name,
            branch=spec.branch,
            html_url=f"https://github.com/{spec.owner}/{spec.name}",
            default_branch="main",
        )

    async def _fake_ensure_branch(self, client, installation_token, *, owner, repo, target_branch, default_branch):
        calls.append("branch")

    async def _fake_template_reference(self, client, installation_token, *, owner, repo, ref):
        return TemplateReference(source_repo=f"{owner}/{repo}", source_branch=ref)

    async def _fake_generate(self, plan, operations, *, trace_id=None, template_reference=None):
        return list(generated_files)

    async def _fake_preflight(self, files):
        calls.append("preflight")
        return LocalPreflightResult(success=True, logs="ok")

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        calls.append("commit")
        return "sha-commit-1"

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        return VercelProjectResult(id="prj_abc", name=project_name)

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        calls.append("deploy")
        return VercelDeploymentResult(id="dpl_123", url="test-site-git.vercel.app", target=target)

    async def _fake_poll(self, client, team_id, deployment_id):
        return {"readyState": "READY"}

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_provision_repo", _fake_provision_repo)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_ensure_branch", _fake_ensure_branch)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_collect_template_reference", _fake_template_reference)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._generate_code_via_openai", _fake_generate)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._run_local_preflight", _fake_preflight)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_poll_deployment", _fake_poll)

    out = asyncio.run(DeterministicWebExecutor().execute(_plan(), task_id="task-preflight-ok", trace_id="trace-1", deployment_target="preview"))

    assert out["status"] == "success"
    assert out["local_preflight_fix_attempts"] == 0
    assert calls.index("preflight") < calls.index("commit") < calls.index("deploy")


def test_execute_hard_gates_on_local_preflight_failure(monkeypatch):
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_enabled", True)
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_max_fix_retries", 2)

    calls: list[str] = []
    generated_files = [
        GeneratedFile(path="package.json", content='{"name":"test-site","private":true}'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null;}\n"),
    ]

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_provision_repo(self, client, installation_token, spec):
        return RepoProvisionResult(
            owner=spec.owner,
            name=spec.name,
            branch=spec.branch,
            html_url=f"https://github.com/{spec.owner}/{spec.name}",
            default_branch="main",
        )

    async def _fake_ensure_branch(self, client, installation_token, *, owner, repo, target_branch, default_branch):
        return None

    async def _fake_template_reference(self, client, installation_token, *, owner, repo, ref):
        return TemplateReference(source_repo=f"{owner}/{repo}", source_branch=ref)

    async def _fake_generate(self, plan, operations, *, trace_id=None, template_reference=None):
        return list(generated_files)

    async def _fake_preflight(self, files):
        calls.append("preflight")
        return LocalPreflightResult(success=False, logs="local build failed")

    async def _fake_auto_fix(self, api_key, model, error_logs, files, *, template_reference=None):
        calls.append("autofix")
        return list(files)

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        calls.append("commit")
        return "sha-commit-1"

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        calls.append("deploy")
        return VercelDeploymentResult(id="dpl_123", url="test-site-git.vercel.app", target=target)

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_provision_repo", _fake_provision_repo)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_ensure_branch", _fake_ensure_branch)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_collect_template_reference", _fake_template_reference)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._generate_code_via_openai", _fake_generate)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._run_local_preflight", _fake_preflight)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._auto_fix_build_errors", _fake_auto_fix)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)

    out = asyncio.run(DeterministicWebExecutor().execute(_plan(), task_id="task-preflight-fail", trace_id="trace-2", deployment_target="preview"))

    assert out["status"] == "needs_review"
    assert out["vercel_ready_state"] == "SKIPPED_LOCAL_PREFLIGHT_FAILED"
    assert out["local_preflight_fix_attempts"] == 2
    assert calls.count("preflight") == 3
    assert calls.count("autofix") == 2
    assert "commit" not in calls
    assert "deploy" not in calls
