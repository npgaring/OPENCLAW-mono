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
    REASON_CODEGEN_CONFLICT_DETECTED,
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


def test_deterministic_execute_returns_partial_with_build_state(monkeypatch):
    """execute() now returns partial status with build state for phased execution."""
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "")
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
        return _Resp(500, {"message": f"Unhandled route {method} {url}"})

    _patch_client(monkeypatch, _resolver)
    out = asyncio.run(DeterministicWebExecutor().execute(plan, task_id="task-1", trace_id="trace-1", deployment_target="preview"))

    assert out["status"] == "partial"
    assert out["build_phase"] == "architect_done"
    assert out["repository_url"] == "https://github.com/test-owner/test-site"
    assert "provision_repo" in out["steps_completed"]
    assert "architect" in out["steps_completed"]

    build_state = out["_build_state"]
    assert "blueprint" in build_state
    assert build_state["repo_info"]["owner"] == "test-owner"
    assert build_state["repo_info"]["name"] == "test-site"
    assert build_state["template_reference"]["source_repo"] == "test-owner/test-site"
    assert build_state["config"]["task_id"] == "task-1"


def test_execute_finalize_commits_and_deploys(monkeypatch):
    """execute_finalize() runs inspector, commits to GitHub, and deploys to Vercel."""
    _configure_settings(monkeypatch)
    calls: list[str] = []

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        calls.append("commit")
        return "commit-sha-final"

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        return VercelProjectResult(id="prj_abc", name=project_name)

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        calls.append("deploy")
        return VercelDeploymentResult(id="dpl_456", url="test-site-preview.vercel.app", target=target)

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)

    files = [
        GeneratedFile(path="package.json", content='{"name":"test","dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}'),
        GeneratedFile(path="src/app/page.tsx", content='export default function Home(){return <div>Home</div>;}'),
    ]
    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}

    result = asyncio.run(DeterministicWebExecutor().execute_finalize(
        all_files=files,
        blueprint={"pages": []},
        template_reference=TemplateReference(),
        plan=_plan(),
        operations=_plan()["operations"],
        repo_info=repo_info,
        task_id="task-fin",
        trace_id="trace-fin",
        deployment_target="preview",
        hosting_team_id="team_123",
        project_name="test-site",
        deploy_branch="main",
    ))

    assert result["status"] == "success"
    assert result["build_phase"] == "complete"
    assert result["deployment_url"] == "https://test-site-preview.vercel.app"
    assert result["repo_commit_sha"] == "commit-sha-final"
    assert "commit" in calls
    assert "deploy" in calls


def test_execute_finalize_includes_conflict_metadata_when_present(monkeypatch):
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_deploy_static_gate_enabled", False)

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        return "commit-sha-final"

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        return VercelProjectResult(id="prj_abc", name=project_name)

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        return VercelDeploymentResult(id="dpl_456", url="test-site-preview.vercel.app", target=target)

    def _fake_phase3_inspect(self, files, blueprint, *, template_reference=None):
        return files, ["DUPLICATE_FILE:src/app/page.tsx (2 times)"]

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._phase3_inspect", _fake_phase3_inspect)

    files = [
        GeneratedFile(path="package.json", content='{"name":"test","dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}'),
        GeneratedFile(path="src/app/page.tsx", content='export default function Home(){return <div>Home</div>;}'),
    ]
    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}

    result = asyncio.run(DeterministicWebExecutor().execute_finalize(
        all_files=files,
        blueprint={"pages": []},
        template_reference=TemplateReference(),
        plan=_plan(),
        operations=_plan()["operations"],
        repo_info=repo_info,
        task_id="task-fin-conflicts",
        trace_id="trace-fin-conflicts",
        deployment_target="preview",
        hosting_team_id="team_123",
        project_name="test-site",
        deploy_branch="main",
    ))

    assert result["status"] == "success"
    assert result["conflicts_detected"] == 1
    assert result["conflict_samples"] == ["DUPLICATE_FILE:src/app/page.tsx (2 times)"]


def test_deterministic_execute_missing_github_app_credentials_fails_fast(monkeypatch):
    plan = _plan()
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_app_id", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_private_key", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_installation_id", None)
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_owner", "template-owner")
    monkeypatch.setattr("app.services.deterministic_executor.settings.github_template_repo", "template-repo")
    monkeypatch.setattr("app.services.deterministic_executor.settings.vercel_token", "vercel-token-123")

    with pytest.raises(DeterministicExecutionError) as err:
        asyncio.run(DeterministicWebExecutor().execute(plan, task_id="task-2", trace_id="trace-2", deployment_target="preview"))
    assert err.value.reason_code == REASON_GITHUB_AUTH_FAILED


def test_deterministic_execute_template_generation_failure_maps_reason_code(monkeypatch):
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
        asyncio.run(DeterministicWebExecutor().execute(plan, task_id="task-3", trace_id="trace-3", deployment_target="preview"))
    assert err.value.reason_code == REASON_GITHUB_REPO_CREATE_FAILED


def test_execute_finalize_vercel_project_failure_maps_reason_code(monkeypatch):
    _configure_settings(monkeypatch)
    calls: list[str] = []

    async def _fake_installation_token(self, client):
        calls.append("installation_token")
        return "ghs_installation_token"

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        calls.append("commit")
        return "commit-sha"

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        raise DeterministicExecutionError(
            reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
            message="Vercel access denied while resolving project.",
            provider="vercel",
            status_code=403,
            snippet="forbidden",
            extra={"upstream_status_code": 403, "upstream_error": "forbidden"},
        )

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)

    files = [GeneratedFile(path="package.json", content='{"name":"t","dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}')]
    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}

    with pytest.raises(DeterministicExecutionError) as err:
        asyncio.run(DeterministicWebExecutor().execute_finalize(
            all_files=files, blueprint={"pages": []}, template_reference=TemplateReference(),
            plan=_plan(), operations=_plan()["operations"], repo_info=repo_info,
            task_id="t-4", trace_id="tr-4", deployment_target="preview",
            hosting_team_id="team_123", project_name="test-site", deploy_branch="main",
        ))
    assert err.value.reason_code == REASON_VERCEL_PROJECT_CREATE_FAILED
    assert "commit" not in calls


def test_execute_finalize_vercel_deploy_failure_maps_reason_code(monkeypatch):
    _configure_settings(monkeypatch)

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        return "commit-sha"

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        return VercelProjectResult(id="prj_abc", name=project_name)

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        raise DeterministicExecutionError(
            reason_code=REASON_VERCEL_DEPLOY_FAILED,
            message="Bad deployment payload",
            provider="vercel",
        )

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)

    files = [GeneratedFile(path="package.json", content='{"name":"t","dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}')]
    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}

    with pytest.raises(DeterministicExecutionError) as err:
        asyncio.run(DeterministicWebExecutor().execute_finalize(
            all_files=files, blueprint={"pages": []}, template_reference=TemplateReference(),
            plan=_plan(), operations=_plan()["operations"], repo_info=repo_info,
            task_id="t-5", trace_id="tr-5", deployment_target="preview",
            hosting_team_id="team_123", project_name="test-site", deploy_branch="main",
        ))
    assert err.value.reason_code == REASON_VERCEL_DEPLOY_FAILED


def test_github_create_empty_repo_prefers_org_endpoint_for_explicit_owner(monkeypatch):
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
    result = asyncio.run(DeterministicWebExecutor()._github_create_empty_repo(
        client=None,  # type: ignore[arg-type]
        installation_token="ghs_installation_token",
        spec=RepoSpec(owner="test-owner", name="test-site", branch="main", private=True),
    ))

    assert result is not None
    assert result.owner == "test-owner"
    assert any(url.endswith("/orgs/test-owner/repos") for url in calls)
    assert not any(url.endswith("/user/repos") for url in calls)


def test_github_create_empty_repo_rejects_owner_mismatch(monkeypatch):
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
    result = asyncio.run(DeterministicWebExecutor()._github_create_empty_repo(
        client=None,  # type: ignore[arg-type]
        installation_token="ghs_installation_token",
        spec=RepoSpec(owner="target-org", name="test-site", branch="main", private=True),
    ))

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
    assert pkg["dependencies"]["framer-motion"] == "^12.9.4"
    assert pkg["devDependencies"]["eslint-config-next"] == "^15"
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


def test_execute_foundation_accumulates_runtime_manifest(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")
    call_count = {"value": 0}
    manifest_snapshots: list[dict] = []

    async def _fake_chat(
        self,
        api_key,
        model,
        system_prompt,
        user_prompt,
        *,
        temperature=0.3,
        max_tokens=16000,
        manifest=None,
    ):
        manifest_snapshots.append((manifest.to_runtime_json() if manifest else {}))
        idx = call_count["value"]
        call_count["value"] += 1
        if idx == 0:
            return (
                "===FILE: package.json===\n"
                '{"name":"demo","private":true,"dependencies":{"next":"^15.5.14"}}\n'
                "===END_FILE===\n"
                "===FILE: src/app/layout.tsx===\n"
                "export default function RootLayout({children}:{children:React.ReactNode}){return <html><body>{children}</body></html>;}\n"
                "===END_FILE===\n"
            )
        return (
            "===FILE: src/components/Hero.tsx===\n"
            "export function Hero(){return <section>Hero</section>;}\n"
            "===END_FILE===\n"
        )

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._openai_chat",
        _fake_chat,
    )

    files, runtime_manifest_json = asyncio.run(
        DeterministicWebExecutor().execute_foundation(
            blueprint={
                "pages": [{"slug": "home"}, {"slug": "about"}],
                "shared_components": ["NavBar", "Footer", "Hero"],
                "design_notes": "",
                "color_palette": {},
                "content_strategy": "",
            },
            context={"goal": "Launch", "context": "Marketing site"},
            template_reference=TemplateReference(),
            task_id="task-foundation-manifest",
            runtime_manifest_json={},
        )
    )

    assert call_count["value"] == 2
    assert "home" in (manifest_snapshots[0].get("routes_created") or [])
    assert "package.json" in (manifest_snapshots[1].get("files_created") or [])
    assert any(f.path == "src/components/Hero.tsx" for f in files)
    assert runtime_manifest_json["packages"]["next"] == "^15.5.14"
    assert "src/components/Hero.tsx" in runtime_manifest_json["files_created"]


def test_execute_pages_runs_sequential_batches_and_carries_manifest(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_phase2_batch_size", 2)
    events: list[str] = []
    manifest_snapshots: list[dict] = []
    call_count = {"value": 0}

    async def _fake_chat(
        self,
        api_key,
        model,
        system_prompt,
        user_prompt,
        *,
        temperature=0.3,
        max_tokens=16000,
        manifest=None,
    ):
        idx = call_count["value"]
        call_count["value"] += 1
        events.append(f"start-{idx}")
        manifest_snapshots.append(manifest.to_runtime_json() if manifest else {})
        if idx == 0:
            await asyncio.sleep(0.03)
            events.append("end-0")
            return (
                "===FILE: src/app/page.tsx===\n"
                "export default function Page(){return <main>Home</main>;}\n"
                "===END_FILE===\n"
            )
        events.append("end-1")
        return (
            "===FILE: src/app/about/page.tsx===\n"
            "export default function AboutPage(){return <main>About</main>;}\n"
            "===END_FILE===\n"
        )

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._openai_chat",
        _fake_chat,
    )

    foundation_files = [
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
        GeneratedFile(path="src/app/layout.tsx", content="export default function RootLayout(){return null;}"),
    ]
    all_files, runtime_manifest_json = asyncio.run(
        DeterministicWebExecutor().execute_pages(
            blueprint={
                "pages": [
                    {"slug": "home", "title": "Home"},
                    {"slug": "about", "title": "About"},
                    {"slug": "pricing", "title": "Pricing"},
                    {"slug": "contact", "title": "Contact"},
                ],
                "design_notes": "",
                "color_palette": {},
                "content_strategy": "",
            },
            context={"goal": "Launch", "context": "Marketing site"},
            foundation_files=foundation_files,
            task_id="task-pages-sequential",
            runtime_manifest_json={"routes_created": ["home", "about"]},
        )
    )

    assert call_count["value"] == 2
    assert events == ["start-0", "end-0", "start-1", "end-1"]
    assert "src/app/page.tsx" in (manifest_snapshots[1].get("files_created") or [])
    assert any(f.path == "src/app/about/page.tsx" for f in all_files)
    assert "src/app/about/page.tsx" in runtime_manifest_json["files_created"]


def test_phase3_inspect_detects_conflicts_in_log_mode(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_conflict_mode", "log")
    files = [
        GeneratedFile(path="src/app/page.tsx", content="export const Hero = () => <main />;\n"),
        GeneratedFile(path="src/app/page.tsx", content="export const Hero = () => <section />;\n"),
        GeneratedFile(path="src/components/Hero.tsx", content="export const Hero = () => <div />;\n"),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
        GeneratedFile(path="packages/web/package.json", content='{"name":"demo-web","private":true}'),
    ]

    validated, conflicts = DeterministicWebExecutor()._phase3_inspect(files, blueprint={"pages": []})

    assert validated
    assert any(c.startswith("DUPLICATE_FILE:src/app/page.tsx") for c in conflicts)
    assert any(c.startswith("DUPLICATE_EXPORT:Hero") for c in conflicts)
    assert any(c.startswith("PACKAGE_FRAGMENTATION:") for c in conflicts)


def test_phase3_inspect_blocks_when_conflict_mode_is_block(monkeypatch):
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_conflict_mode", "block")
    files = [
        GeneratedFile(path="src/app/page.tsx", content="export const Hero = () => <main />;\n"),
        GeneratedFile(path="src/app/page.tsx", content="export const Hero = () => <section />;\n"),
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
    ]

    with pytest.raises(DeterministicExecutionError) as err:
        DeterministicWebExecutor()._phase3_inspect(files, blueprint={"pages": []})

    assert err.value.reason_code == REASON_CODEGEN_CONFLICT_DETECTED
    assert err.value.extra.get("conflicts_detected", 0) >= 1


def test_auto_fix_build_errors_drops_out_of_scope_patches(monkeypatch):
    async def _fake_chat(
        self,
        api_key,
        model,
        system_prompt,
        user_prompt,
        *,
        temperature=0.2,
        max_tokens=8000,
        manifest=None,
    ):
        return (
            "===FILE: src/app/page.tsx===\n"
            "export default function Page(){return <main>fixed</main>;}\n"
            "===END_FILE===\n"
            "===FILE: src/app/other.tsx===\n"
            "export function Other(){return <div>patched-out-of-scope</div>;}\n"
            "===END_FILE===\n"
        )

    monkeypatch.setattr(
        "app.services.deterministic_executor.DeterministicWebExecutor._openai_chat",
        _fake_chat,
    )

    files = [
        GeneratedFile(path="package.json", content='{"name":"demo","private":true}'),
        GeneratedFile(path="src/app/layout.tsx", content="export default function RootLayout(){return null;}"),
        GeneratedFile(path="src/app/globals.css", content='@import "tailwindcss";'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return <main>original</main>;}\n"),
        GeneratedFile(path="src/app/other.tsx", content="export function Other(){return <div>original-other</div>;}\n"),
    ]

    out = asyncio.run(
        DeterministicWebExecutor()._auto_fix_build_errors(
            "sk-test",
            "gpt-test",
            "Error in src/app/page.tsx",
            files,
        )
    )

    page = next(f for f in out if f.path == "src/app/page.tsx").content
    other = next(f for f in out if f.path == "src/app/other.tsx").content

    assert "fixed" in page
    assert "original-other" in other
    assert "patched-out-of-scope" not in other


def test_auto_fix_build_errors_ignores_package_json_changes(monkeypatch):
    async def _fake_chat(
        self,
        api_key,
        model,
        system_prompt,
        user_prompt,
        *,
        temperature=0.2,
        max_tokens=8000,
        manifest=None,
    ):
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


def test_execute_finalize_runs_local_preflight_before_commit_and_deploy(monkeypatch):
    """Local preflight (when enabled) runs inside execute_finalize before committing."""
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_enabled", True)
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")

    calls: list[str] = []
    test_files = [
        GeneratedFile(path="package.json", content='{"name":"test-site","private":true,"dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null;}\n"),
    ]

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

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

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._run_local_preflight", _fake_preflight)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)

    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}
    out = asyncio.run(DeterministicWebExecutor().execute_finalize(
        all_files=test_files, blueprint={"pages": []}, template_reference=TemplateReference(),
        plan=_plan(), operations=_plan()["operations"], repo_info=repo_info,
        task_id="task-preflight-ok", trace_id="trace-1", deployment_target="preview",
        hosting_team_id="team_123", project_name="test-site", deploy_branch="main",
    ))

    assert out["status"] == "success"
    assert out["local_preflight_fix_attempts"] == 0
    assert calls.index("preflight") < calls.index("commit") < calls.index("deploy")


def test_execute_finalize_hard_gates_on_local_preflight_failure(monkeypatch):
    """When local preflight fails repeatedly, execute_finalize returns needs_review without commit/deploy."""
    _configure_settings(monkeypatch)
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_local_preflight_enabled", True)
    monkeypatch.setattr("app.services.deterministic_executor.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.services.deterministic_executor.settings.codegen_max_fix_retries", 2)

    calls: list[str] = []
    test_files = [
        GeneratedFile(path="package.json", content='{"name":"test-site","private":true,"dependencies":{"next":"^15.5.14","react":"^19.0.0","react-dom":"^19.0.0","tailwindcss":"^4.2.2","@tailwindcss/postcss":"^4.2.2"},"devDependencies":{"typescript":"^5.8.3"}}'),
        GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null;}\n"),
    ]

    async def _fake_installation_token(self, client):
        return "ghs_installation_token"

    async def _fake_preflight(self, files):
        calls.append("preflight")
        return LocalPreflightResult(success=False, logs="local build failed")

    async def _fake_auto_fix(self, api_key, model, error_logs, files, *, template_reference=None, manifest=None):
        calls.append("autofix")
        return list(files)

    async def _fake_commit(self, client, installation_token, *, owner, repo, branch, files, message):
        calls.append("commit")
        return "sha-commit-1"

    async def _fake_deploy(self, client, team_id, project_name, files, target):
        calls.append("deploy")
        return VercelDeploymentResult(id="dpl_123", url="test-site-git.vercel.app", target=target)

    async def _fake_vercel_project(self, client, team_id, project_name, github_owner, github_repo, production_branch):
        return VercelProjectResult(id="prj_abc", name=project_name)

    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_installation_token", _fake_installation_token)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._run_local_preflight", _fake_preflight)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._auto_fix_build_errors", _fake_auto_fix)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._github_batch_commit", _fake_commit)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_create_or_resolve_project", _fake_vercel_project)
    monkeypatch.setattr("app.services.deterministic_executor.DeterministicWebExecutor._vercel_deploy_files", _fake_deploy)

    repo_info = {"owner": "test-owner", "name": "test-site", "html_url": "https://github.com/test-owner/test-site", "default_branch": "main", "branch": "main"}
    out = asyncio.run(DeterministicWebExecutor().execute_finalize(
        all_files=test_files, blueprint={"pages": []}, template_reference=TemplateReference(),
        plan=_plan(), operations=_plan()["operations"], repo_info=repo_info,
        task_id="task-preflight-fail", trace_id="trace-2", deployment_target="preview",
        hosting_team_id="team_123", project_name="test-site", deploy_branch="main",
    ))

    assert out["status"] == "needs_review"
    assert out["vercel_ready_state"] == "SKIPPED_LOCAL_PREFLIGHT_FAILED"
    assert out["local_preflight_fix_attempts"] == 1
    assert calls.count("preflight") == 2
    assert calls.count("autofix") == 1
    assert out.get("reason_codes") == ["EXECUTION_CODEGEN_AUTOFIX_STALLED"]
    assert "commit" not in calls
    assert "deploy" not in calls


def test_serialize_and_deserialize_files_roundtrip():
    """Files can be serialized to JSON and deserialized back."""
    files = [
        GeneratedFile(path="src/app/page.tsx", content="export default function Home(){}"),
        GeneratedFile(path="package.json", content='{"name":"test"}'),
    ]
    serialized = DeterministicWebExecutor.serialize_files(files)
    deserialized = DeterministicWebExecutor.deserialize_files(serialized)
    assert len(deserialized) == 2
    assert deserialized[0].path == "src/app/page.tsx"
    assert deserialized[1].content == '{"name":"test"}'


def test_serialize_and_deserialize_template_reference_roundtrip():
    ref = TemplateReference(source_repo="owner/repo", source_branch="main", package_json={"dependencies": {"next": "15"}}, key_files={"a.tsx": "content"})
    data = {"source_repo": ref.source_repo, "source_branch": ref.source_branch, "package_json": ref.package_json, "key_files": ref.key_files}
    restored = DeterministicWebExecutor.deserialize_template_reference(data)
    assert restored.source_repo == "owner/repo"
    assert restored.package_json["dependencies"]["next"] == "15"


def test_relocate_misplaced_app_components():
    fm = {
        "src/app/components/NavBar.tsx": GeneratedFile(
            path="src/app/components/NavBar.tsx",
            content='import { Foo } from "@/app/components/Foo";\nexport function NavBar() { return null; }\n',
        ),
    }
    DeterministicWebExecutor._relocate_misplaced_app_components(fm)
    assert "src/components/NavBar.tsx" in fm
    assert "src/app/components/NavBar.tsx" not in fm
    assert "@/components/Foo" in fm["src/components/NavBar.tsx"].content


def test_collect_deploy_quality_violations_detects_internal_anchor():
    fm = {
        "package.json": GeneratedFile(path="package.json", content='{"name":"x","private":true}'),
        "src/app/layout.tsx": GeneratedFile(path="src/app/layout.tsx", content="export default function RootLayout(){return null}"),
        "src/app/page.tsx": GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null}"),
        "src/bad.tsx": GeneratedFile(path="src/bad.tsx", content='<a href="/">x</a>'),
    }
    v = DeterministicWebExecutor._collect_deploy_quality_violations(fm)
    assert any(x.startswith("internal_html_link:") for x in v)


def test_collect_deploy_quality_violations_detects_internal_anchor_jsx_href_expression():
    fm = {
        "package.json": GeneratedFile(path="package.json", content='{"name":"x","private":true}'),
        "src/app/layout.tsx": GeneratedFile(path="src/app/layout.tsx", content="export default function RootLayout(){return null}"),
        "src/app/page.tsx": GeneratedFile(path="src/app/page.tsx", content="export default function Page(){return null}"),
        "src/bad.tsx": GeneratedFile(path="src/bad.tsx", content='<a className="x" href={"/pricing"}>pricing</a>'),
    }
    v = DeterministicWebExecutor._collect_deploy_quality_violations(fm)
    assert any(x.startswith("internal_html_link:") for x in v)


def test_rewrite_internal_anchors_to_next_link():
    """Internal / hrefs become Link to satisfy @next/next/no-html-link-for-pages."""
    fm = {
        "src/app/components/NavBar.tsx": GeneratedFile(
            path="src/app/components/NavBar.tsx",
            content='<nav><a href="/">Home</a><a className="x" href="/about">About</a></nav>',
        ),
        "src/x.tsx": GeneratedFile(
            path="src/x.tsx",
            content='<a href="https://example.com">Ext</a><a href="/pricing">Price</a>',
        ),
    }
    DeterministicWebExecutor._rewrite_internal_anchors_to_next_link(fm)
    nav = fm["src/app/components/NavBar.tsx"].content
    assert "<Link" in nav
    assert "</Link>" in nav
    assert '<a href="/"' not in nav
    x = fm["src/x.tsx"].content
    assert 'href="https://example.com"' in x
    assert "<Link" in x
    assert "Price</Link>" in x


def test_rewrite_internal_anchors_to_next_link_handles_jsx_href_expression():
    fm = {
        "src/app/components/NavBar.tsx": GeneratedFile(
            path="src/app/components/NavBar.tsx",
            content='<nav><a className="x" href={"/"}>Home</a></nav>',
        ),
    }
    DeterministicWebExecutor._rewrite_internal_anchors_to_next_link(fm)
    nav = fm["src/app/components/NavBar.tsx"].content
    assert "<Link" in nav
    assert 'href="/"' in nav
    assert 'href={"/"}' not in nav
    assert "Home</Link>" in nav


def test_ensure_scaffold_integrity_deduplicates_dev_deps():
    """Dev-only packages must not remain in dependencies after scaffold integrity."""
    files = [
        GeneratedFile(
            path="package.json",
            content=json.dumps({
                "name": "demo",
                "dependencies": {
                    "next": "^15.5.14",
                    "react": "^19.0.0",
                    "react-dom": "^19.0.0",
                    "typescript": "latest",
                    "@types/react": "latest",
                    "@types/node": "latest",
                    "tailwindcss": "^4.2.2",
                    "@tailwindcss/postcss": "^4.2.2",
                },
                "devDependencies": {
                    "typescript": "^5.8.3",
                    "@types/react": "^19",
                    "@types/node": "^22",
                },
            }),
        ),
    ]
    out = DeterministicWebExecutor()._ensure_scaffold_integrity(files)
    pkg = json.loads(next(f for f in out if f.path == "package.json").content)

    assert "typescript" not in pkg["dependencies"]
    assert "@types/react" not in pkg["dependencies"]
    assert "@types/node" not in pkg["dependencies"]
    assert pkg["devDependencies"]["typescript"] == "^5.8.3"
