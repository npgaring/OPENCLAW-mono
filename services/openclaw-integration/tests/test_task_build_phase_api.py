"""API tests for deterministic build-phase responses."""
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.db.init_db import ensure_db_ready
from app.db.session import get_sessionmaker
from app.main import app
from app.models import Task, TaskBuildState, TaskStatus
from app.services.deterministic_executor import (
    DeterministicExecutionError,
    REASON_VERCEL_PROJECT_CREATE_FAILED,
)


async def _seed_task_build_state(task_id: str) -> None:
    await ensure_db_ready()
    async with get_sessionmaker()() as session:
        session.add(
            Task(
                task_id=task_id,
                ocgg_identity="W-OCGG",
                domain="web",
                plan_hash="plan-hash-1",
                plan_json={"operations": []},
                status=TaskStatus.submitted,
                trace_id="trace-build-phase-1",
            )
        )
        session.add(
            TaskBuildState(
                task_id=task_id,
                phase="pages_done",
                blueprint_json={"pages": []},
                repo_info_json={
                    "owner": "test-owner",
                    "name": "test-site",
                    "html_url": "https://github.com/test-owner/test-site",
                    "branch": "main",
                },
                template_reference_json={},
                generated_files_json=[
                    {"path": "package.json", "content": '{"name":"test-site","private":true}'},
                    {"path": "src/app/layout.tsx", "content": "export default function RootLayout(){return null;}"},
                    {"path": "src/app/page.tsx", "content": "export default function Home(){return <main/>;}"},
                ],
                config_json={
                    "plan_json": {"operations": []},
                    "trace_id": "trace-build-phase-1",
                    "deployment_target": "preview",
                    "hosting_team_id": "team_123",
                    "project_name": "test-site",
                    "deploy_branch": "main",
                },
            )
        )
        await session.commit()


def test_build_phase_returns_structured_deterministic_error(auth_headers):
    task_id = "task-build-phase-structured-error"
    asyncio.run(_seed_task_build_state(task_id))

    error = DeterministicExecutionError(
        reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
        message="Vercel access denied while resolving project.",
        provider="vercel",
        status_code=403,
        snippet="forbidden",
        extra={"upstream_status_code": 403, "upstream_error": "forbidden"},
    )

    with patch("app.api.task.DeterministicWebExecutor.execute_finalize", new=AsyncMock(side_effect=error)):
        with TestClient(app) as client:
            resp = client.post(f"/task/{task_id}/build-phase", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["build_phase"] == "error"
    assert body["status"] == "needs_review"
    assert body["reason_codes"] == [REASON_VERCEL_PROJECT_CREATE_FAILED]
    assert body["provider_error"]["provider"] == "vercel"
    assert body["provider_error"]["status_code"] == 403
    assert body["upstream_status_code"] == 403
    assert body["upstream_error"] == "forbidden"
    assert body["execution_response"]["reason_codes"] == [REASON_VERCEL_PROJECT_CREATE_FAILED]
