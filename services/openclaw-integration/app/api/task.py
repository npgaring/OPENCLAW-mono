"""POST /task — submit task, gate, token, executor call; POST /task/{id}/continue — follow-up; POST /task/{id}/build-phase — advance build."""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.errors import ErrorCodes
from app.core.trace_id import normalize_trace_id
from app.db.session import get_session
from app.models import Task, TaskBuildState, TaskContinueRequest, TaskStatus, TaskSubmitRequest, TaskSubmitResponse
from app.models.deployment import DeploymentRecord
from app.services.deterministic_executor import DeterministicWebExecutor, DeterministicExecutionError
from app.services.execution_client import OpenClawClient, OpenClawError
from app.services.task_submission import _task_submit_response, run_task_submission

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/task", response_model=TaskSubmitResponse)
async def submit_task(
    body: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    trace_id = normalize_trace_id(body.trace_id)
    return await run_task_submission(session, body, trace_id)


CONTINUABLE_STATUSES = frozenset({TaskStatus.completed, TaskStatus.partial, TaskStatus.needs_review})


def _prior_context_from_audit(audit_history: list[Any]) -> str:
    """Build prior_context from last execution_response in audit (session_summary or message)."""
    for i in range(len(audit_history) - 1, -1, -1):
        entry = audit_history[i]
        if isinstance(entry, dict) and entry.get("event_type") == "execution_response":
            payload = entry.get("payload") or {}
            if isinstance(payload, dict):
                summary = payload.get("session_summary")
                if summary and isinstance(summary, str):
                    return summary
                msg = payload.get("message")
                if msg and isinstance(msg, str):
                    return msg
            break
    return ""


@router.post("/task/{task_id}/continue", response_model=TaskSubmitResponse)
async def continue_task(
    task_id: str,
    body: TaskContinueRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a follow-up message for an existing task (same Gateway user/session). Task must be completed, partial, or needs_review."""
    if not settings.allow_task_continue_route():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TASK_CONTINUE_DISABLED",
                "message": "POST /task/{id}/continue is disabled (set TASK_CONTINUE_ENABLED=true to allow).",
            },
        )
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in CONTINUABLE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": f"Task not continuable (status={task.status})"},
        )
    if not task.execution_token_hash:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CONTINUE_REQUIRES_PRIOR_EXECUTION",
                "message": "Task has no execution_token_hash; initial POST /task gated execution must have completed with a token.",
            },
        )
    if task.trace_id:
        if not body.trace_id or body.trace_id.strip() != task.trace_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "TRACE_ID_MISMATCH",
                    "message": "Provide trace_id matching this task (from compile/gate/task response) to continue the same correlation chain.",
                },
            )
    prior_context = body.prior_context if body.prior_context is not None else _prior_context_from_audit(task.audit_history or [])
    client = OpenClawClient()
    try:
        result = await client.execute_follow_up(
            task_id=str(task_id),
            domain=task.domain,
            message=body.message,
            prior_context=prior_context,
        )
    except OpenClawError as e:
        task.audit_history = (task.audit_history or []) + [
            {"event_type": "task_continue", "payload": {"message": body.message[:500]}},
            {"event_type": "execution_response", "payload": e.response},
        ]
        if e.response.get("execution_id"):
            task.execution_id = e.response["execution_id"]
        try:
            task.status = TaskStatus(e.error_type)
        except ValueError:
            task.status = TaskStatus.error
        flag_modified(task, "audit_history")
        await session.commit()
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=task.trace_id,
            execution_response=e.response,
            gate_outcome="PASS",
            reason_codes=[],
        )
    task.execution_id = result.get("execution_id")
    s = result.get("status")
    if s == "success":
        task.status = TaskStatus.completed
    elif s in ("failed", "partial", "needs_review"):
        task.status = TaskStatus(s)
    else:
        task.status = TaskStatus.failed
    task.audit_history = (task.audit_history or []) + [
        {"event_type": "task_continue", "payload": {"message": body.message[:500]}},
        {"event_type": "execution_response", "payload": result},
    ]
    flag_modified(task, "audit_history")
    await session.commit()
    return _task_submit_response(
        task_id=task.task_id,
        execution_id=task.execution_id,
        status=task.status.value,
        trace_id=task.trace_id,
        execution_response=result,
        gate_outcome="PASS",
        reason_codes=[],
    )


class BuildPhaseResponse(BaseModel):
    task_id: str
    build_phase: str
    status: str
    files_generated: int = 0
    message: str = ""
    deployment_url: Optional[str] = None
    repository_url: Optional[str] = None
    execution_response: Optional[dict[str, Any]] = None


PHASE_TRANSITIONS = {
    "architect_done": "foundation_done",
    "foundation_done": "pages_done",
    "pages_done": "complete",
}


@router.post("/task/{task_id}/build-phase", response_model=BuildPhaseResponse)
async def advance_build_phase(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Advance the deterministic build pipeline by one phase.

    Each call runs the next phase of code generation, giving each phase
    the full Vercel function timeout budget.
    """
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    build_state = await session.get(TaskBuildState, task_id)
    if not build_state:
        raise HTTPException(
            status_code=422,
            detail={"code": "NO_BUILD_STATE", "message": "No build state found. Submit the task first via POST /task."},
        )

    current_phase = build_state.phase
    if current_phase == "complete":
        raise HTTPException(
            status_code=422,
            detail={"code": "BUILD_COMPLETE", "message": "Build is already complete."},
        )
    if current_phase == "error":
        raise HTTPException(
            status_code=422,
            detail={"code": "BUILD_FAILED", "message": "Build failed. Submit a new task."},
        )
    if current_phase not in PHASE_TRANSITIONS:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PHASE", "message": f"Cannot advance from phase '{current_phase}'."},
        )

    executor = DeterministicWebExecutor()
    config = build_state.config_json or {}
    blueprint = build_state.blueprint_json or {}
    context = config.get("context", {})
    template_ref = executor.deserialize_template_reference(build_state.template_reference_json)
    repo_info = build_state.repo_info_json or {}

    try:
        if current_phase == "architect_done":
            context_data = blueprint.pop("_context", None) or config.get("context", {})
            if not context_data and build_state.config_json:
                plan_json = config.get("plan_json", {})
                operations = plan_json.get("operations", [])
                context_data = executor._build_project_context(plan_json, operations)

            files = await executor.execute_foundation(
                blueprint=blueprint,
                context=context_data,
                template_reference=template_ref,
                task_id=task_id,
            )

            build_state.generated_files_json = executor.serialize_files(files)
            build_state.phase = "foundation_done"
            build_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase="foundation_done",
                status="partial",
                files_generated=len(files),
                message=f"Foundation generated: {len(files)} files (configs, layout, components).",
                repository_url=repo_info.get("html_url"),
            )

        elif current_phase == "foundation_done":
            foundation_files = executor.deserialize_files(build_state.generated_files_json)
            context_data = config.get("context", {})
            if not context_data:
                plan_json = config.get("plan_json", {})
                operations = plan_json.get("operations", [])
                context_data = executor._build_project_context(plan_json, operations)

            all_files = await executor.execute_pages(
                blueprint=blueprint,
                context=context_data,
                foundation_files=foundation_files,
                task_id=task_id,
            )

            build_state.generated_files_json = executor.serialize_files(all_files)
            build_state.phase = "pages_done"
            build_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase="pages_done",
                status="partial",
                files_generated=len(all_files),
                message=f"Pages generated: {len(all_files)} total files.",
                repository_url=repo_info.get("html_url"),
            )

        elif current_phase == "pages_done":
            all_files = executor.deserialize_files(build_state.generated_files_json)
            plan_json = config.get("plan_json", {})
            operations = plan_json.get("operations", [])

            result = await executor.execute_finalize(
                all_files=all_files,
                blueprint=blueprint,
                template_reference=template_ref,
                plan=plan_json,
                operations=operations,
                repo_info=repo_info,
                task_id=task_id,
                trace_id=config.get("trace_id"),
                deployment_target=config.get("deployment_target", "preview"),
                hosting_team_id=config.get("hosting_team_id", ""),
                project_name=config.get("project_name", ""),
                deploy_branch=config.get("deploy_branch", "main"),
            )

            build_state.phase = "complete"
            build_state.updated_at = datetime.now(timezone.utc)

            task.status = TaskStatus.completed if result.get("status") == "success" else TaskStatus.needs_review
            task.execution_id = result.get("execution_id")
            task.audit_history = (task.audit_history or []) + [
                {"event_type": "execution_response", "payload": result},
            ]
            flag_modified(task, "audit_history")

            if result.get("status") == "success":
                try:
                    from app.services.deployment_tracker import record_deployment
                    await record_deployment(
                        session,
                        result=result,
                        task_id=task_id,
                        trace_id=config.get("trace_id"),
                        build_sot_hash=plan_json.get("build_sot_hash"),
                        execution_plan_hash=plan_json.get("execution_plan_hash"),
                        project_name=config.get("project_name"),
                    )
                except Exception:
                    logger.exception("build-phase.record_deployment_failed task_id=%s", task_id)

            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase="complete",
                status=result.get("status", "success"),
                files_generated=result.get("files_generated", 0),
                message=result.get("message", "Build complete."),
                deployment_url=result.get("deployment_url"),
                repository_url=result.get("repository_url"),
                execution_response=result,
            )

    except DeterministicExecutionError as e:
        build_state.phase = "error"
        build_state.updated_at = datetime.now(timezone.utc)
        task.status = TaskStatus.needs_review
        error_response = e.as_execution_response(execution_id=f"detexec_{task_id}")
        task.audit_history = (task.audit_history or []) + [
            {"event_type": "execution_response", "payload": error_response},
        ]
        flag_modified(task, "audit_history")
        await session.commit()

        return BuildPhaseResponse(
            task_id=task_id,
            build_phase="error",
            status="needs_review",
            message=str(e),
            repository_url=repo_info.get("html_url"),
        )
    except Exception as e:
        logger.exception("build-phase.unhandled_error task_id=%s phase=%s", task_id, current_phase)
        build_state.phase = "error"
        build_state.updated_at = datetime.now(timezone.utc)
        task.status = TaskStatus.needs_review
        task.audit_history = (task.audit_history or []) + [
            {"event_type": "execution_response", "payload": {"status": "needs_review", "message": str(e)}},
        ]
        flag_modified(task, "audit_history")
        await session.commit()

        return BuildPhaseResponse(
            task_id=task_id,
            build_phase="error",
            status="needs_review",
            message=f"Unexpected error during build phase '{current_phase}': {str(e)[:200]}",
            repository_url=repo_info.get("html_url"),
        )


@router.post("/test/execute")
async def test_execute(
    payload: dict[str, Any] = Body(
        ...,
        examples={
            "openresponses_plan": {
                "summary": "OpenResponses plan execution",
                "value": {
                    "model": "openclaw:main",
                    "user": "project:web",
                    "instructions": "Execute the plan in the user message.",
                    "input": "{\n  \"domain\": \"web\",\n  \"plan_hash\": \"plan_8e7c8b20b2\",\n  \"operations\": [\n    {\"op_id\": \"op-001\", \"type\": \"write_config\", \"target\": \"web/app\", \"inputs\": {\"path\": \"app/config.json\", \"content\": \"{\\\"featureFlags\\\":{\\\"newHomepage\\\":true}}\"}},\n    {\"op_id\": \"op-002\", \"type\": \"deploy\", \"target\": \"web/app\", \"inputs\": {\"provider\": \"vercel\", \"project\": \"marketing-site\"}}\n  ]\n}",
                },
            }
        },
    ),
):
    """Proxy a raw OpenResponses payload to OPENCLAW_BASE_URL/v1/responses for testing."""
    if not settings.allow_test_execute_route():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TEST_EXECUTE_DISABLED",
                "message": "POST /test/execute is off in production unless TEST_EXECUTE_ENABLED=true. "
                "This route bypasses gate/token; do not expose in governed environments.",
            },
        )
    from app.client.openclaw_client import submit_execute

    try:
        return await submit_execute(payload)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail={"error": "Gateway request failed", "response": e.response.text},
        ) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": str(e)}) from e
