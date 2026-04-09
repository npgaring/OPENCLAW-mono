"""POST /task — submit task, gate, token, executor call; POST /task/{id}/continue — follow-up; POST /task/{id}/build-phase — advance build."""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
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
    agent_phase: Optional[str] = None
    agent_role: Optional[str] = None
    files_generated: int = 0
    message: str = ""
    deployment_url: Optional[str] = None
    repository_url: Optional[str] = None
    execution_response: Optional[dict[str, Any]] = None
    reason_codes: list[str] = Field(default_factory=list)
    provider_error: Optional[dict[str, Any]] = None
    upstream_status_code: Optional[int] = None
    upstream_error: Optional[str] = None
    verifier_report: Optional[dict[str, Any]] = None
    ownership_conflicts: Optional[list[dict[str, Any]]] = None


PHASE_TRANSITIONS = {
    "planner_done": "frontend_done",
    "frontend_done": "backend_done",
    "backend_done": "verify_done",
    "verify_done": "complete",
}

PUBLIC_BUILD_PHASES = {
    "planner_done": "architect_done",
    "frontend_done": "foundation_done",
    "backend_done": "pages_done",
    "verify_done": "pages_done",
    "complete": "complete",
    "error": "error",
}

AGENT_ROLE_BY_PHASE = {
    "planner_done": "planner",
    "frontend_done": "frontend",
    "backend_done": "backend",
    "verify_done": "verifier",
    "complete": "orchestrator",
    "error": "verifier",
}

LEGACY_INTERNAL_PHASE_ALIASES = {
    "architect_done": "planner_done",
    "foundation_done": "frontend_done",
    "pages_done": "backend_done",
}


def _public_build_phase(internal_phase: str) -> str:
    return PUBLIC_BUILD_PHASES.get(internal_phase, internal_phase)


def _agent_role(internal_phase: str) -> Optional[str]:
    return AGENT_ROLE_BY_PHASE.get(internal_phase)


def _append_agent_result(
    current: Optional[dict[str, Any]],
    *,
    agent_role: str,
    summary: str,
    files: list[dict[str, str]],
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    results = dict(current or {})
    results[agent_role] = {
        "status": "completed",
        "summary": summary,
        "files_produced": [f["path"] for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)],
        "warnings": list(warnings or []),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return results


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

    current_phase = LEGACY_INTERNAL_PHASE_ALIASES.get(build_state.phase, build_state.phase)
    if current_phase != build_state.phase:
        build_state.phase = current_phase
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
    runtime_manifest_json = config.get("runtime_manifest") if isinstance(config.get("runtime_manifest"), dict) else {}
    template_ref = executor.deserialize_template_reference(build_state.template_reference_json)
    repo_info = build_state.repo_info_json or {}
    ownership_manifest = build_state.ownership_manifest_json or {}
    agent_results = build_state.agent_results_json or {}
    repair_history = build_state.repair_history_json or []

    try:
        if current_phase == "planner_done":
            context_data = blueprint.pop("_context", None) or config.get("context", {})
            if not context_data and build_state.config_json:
                plan_json = config.get("plan_json", {})
                operations = plan_json.get("operations", [])
                context_data = executor._build_project_context(plan_json, operations)

            result = await executor.execute_frontend(
                blueprint=blueprint,
                context=context_data,
                template_reference=template_ref,
                task_id=task_id,
                runtime_manifest_json=runtime_manifest_json,
            )
            files = list(result.get("files") or [])
            serialized_files = executor.serialize_files(files)

            build_state.generated_files_json = serialized_files
            build_state.phase = "frontend_done"
            config["runtime_manifest"] = result.get("runtime_manifest") or runtime_manifest_json
            build_state.config_json = config
            build_state.agent_results_json = _append_agent_result(
                agent_results,
                agent_role="frontend",
                summary=result.get("message", "Frontend agent completed."),
                files=serialized_files,
            )
            build_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase=_public_build_phase("frontend_done"),
                status="partial",
                agent_phase="frontend_done",
                agent_role="frontend",
                files_generated=len(files),
                message=result.get("message", f"Frontend agent generated {len(files)} files."),
                repository_url=repo_info.get("html_url"),
            )

        elif current_phase == "frontend_done":
            all_files = executor.deserialize_files(build_state.generated_files_json)
            plan_json = config.get("plan_json", {})

            result = await executor.execute_backend(
                all_files=all_files,
                plan=plan_json,
                runtime_manifest_json=runtime_manifest_json,
            )
            backend_files = list(result.get("files") or all_files)
            serialized_files = executor.serialize_files(backend_files)

            build_state.generated_files_json = serialized_files
            build_state.phase = "backend_done"
            config["runtime_manifest"] = result.get("runtime_manifest") or runtime_manifest_json
            build_state.config_json = config
            build_state.agent_results_json = _append_agent_result(
                agent_results,
                agent_role="backend",
                summary=result.get("message", "Backend agent completed."),
                files=serialized_files,
            )
            build_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase=_public_build_phase("backend_done"),
                status="partial",
                agent_phase="backend_done",
                agent_role="backend",
                files_generated=len(backend_files),
                message=result.get("message", "Backend agent completed."),
                repository_url=repo_info.get("html_url"),
            )

        elif current_phase == "backend_done":
            all_files = executor.deserialize_files(build_state.generated_files_json)
            plan_json = config.get("plan_json", {})
            operations = plan_json.get("operations", [])

            result = await executor.execute_verify(
                all_files=all_files,
                blueprint=blueprint,
                template_reference=template_ref,
                operations=operations,
                repo_info=repo_info,
                task_id=task_id,
                deployment_target=config.get("deployment_target", "preview"),
                hosting_team_id=config.get("hosting_team_id", ""),
                project_name=config.get("project_name", ""),
                deploy_branch=config.get("deploy_branch", "main"),
                ownership_manifest=ownership_manifest,
                runtime_manifest_json=runtime_manifest_json,
                repair_history_json=repair_history,
            )

            if result.get("status") != "partial":
                build_state.phase = "error"
                build_state.verification_json = result.get("verification_json") if isinstance(result.get("verification_json"), dict) else None
                build_state.repair_history_json = result.get("repair_history") if isinstance(result.get("repair_history"), list) else repair_history
                build_state.updated_at = datetime.now(timezone.utc)
                task.status = TaskStatus.needs_review
                task.execution_id = result.get("execution_id")
                task.audit_history = (task.audit_history or []) + [
                    {"event_type": "execution_response", "payload": result},
                ]
                flag_modified(task, "audit_history")
                await session.commit()

                return BuildPhaseResponse(
                    task_id=task_id,
                    build_phase="error",
                    status="needs_review",
                    agent_phase=result.get("agent_phase", "verify_done"),
                    agent_role=result.get("agent_role", "verifier"),
                    files_generated=result.get("files_generated", 0),
                    message=result.get("message", "Verifier blocked finalize."),
                    repository_url=result.get("repository_url") or repo_info.get("html_url"),
                    execution_response=result,
                    reason_codes=list(result.get("reason_codes") or []),
                    verifier_report=result.get("verifier_report") if isinstance(result.get("verifier_report"), dict) else None,
                    ownership_conflicts=result.get("ownership_conflicts") if isinstance(result.get("ownership_conflicts"), list) else None,
                )

            verified_files = list(result.get("files") or all_files)
            serialized_files = executor.serialize_files(verified_files)
            build_state.generated_files_json = serialized_files
            build_state.phase = "verify_done"
            config["runtime_manifest"] = result.get("runtime_manifest") or runtime_manifest_json
            build_state.config_json = config
            build_state.verification_json = result.get("verification_json") if isinstance(result.get("verification_json"), dict) else None
            build_state.repair_history_json = result.get("repair_history") if isinstance(result.get("repair_history"), list) else repair_history
            build_state.agent_results_json = _append_agent_result(
                agent_results,
                agent_role="verifier",
                summary=result.get("message", "Verifier completed."),
                files=serialized_files,
            )
            build_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return BuildPhaseResponse(
                task_id=task_id,
                build_phase=_public_build_phase("verify_done"),
                status="partial",
                agent_phase="verify_done",
                agent_role="verifier",
                files_generated=len(verified_files),
                message=result.get("message", "Verifier completed."),
                repository_url=repo_info.get("html_url"),
                verifier_report=result.get("verifier_report") if isinstance(result.get("verifier_report"), dict) else None,
                ownership_conflicts=result.get("ownership_conflicts") if isinstance(result.get("ownership_conflicts"), list) else None,
            )

        elif current_phase == "verify_done":
            all_files = executor.deserialize_files(build_state.generated_files_json)
            plan_json = config.get("plan_json", {})

            result = await executor.execute_commit_and_deploy(
                validated_files=all_files,
                repo_info=repo_info,
                task_id=task_id,
                trace_id=config.get("trace_id"),
                deployment_target=config.get("deployment_target", "preview"),
                hosting_team_id=config.get("hosting_team_id", ""),
                project_name=config.get("project_name", ""),
                deploy_branch=config.get("deploy_branch", "main"),
                verification_json=build_state.verification_json or {},
            )

            task.status = TaskStatus.completed if result.get("status") == "success" else TaskStatus.needs_review
            task.execution_id = result.get("execution_id")
            task.audit_history = (task.audit_history or []) + [
                {"event_type": "execution_response", "payload": result},
            ]
            flag_modified(task, "audit_history")
            build_state.phase = "complete"
            build_state.agent_results_json = _append_agent_result(
                build_state.agent_results_json,
                agent_role="orchestrator",
                summary=result.get("message", "Commit and deploy complete."),
                files=build_state.generated_files_json or [],
            )
            build_state.updated_at = datetime.now(timezone.utc)

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
                agent_phase=result.get("agent_phase", "complete"),
                agent_role=result.get("agent_role", "orchestrator"),
                files_generated=result.get("files_generated", 0),
                message=result.get("message", "Build complete."),
                deployment_url=result.get("deployment_url"),
                repository_url=result.get("repository_url"),
                execution_response=result,
                verifier_report=result.get("verifier_report") if isinstance(result.get("verifier_report"), dict) else None,
                ownership_conflicts=result.get("ownership_conflicts") if isinstance(result.get("ownership_conflicts"), list) else None,
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
            agent_phase=current_phase,
            agent_role=_agent_role(current_phase),
            message=str(e),
            repository_url=repo_info.get("html_url"),
            execution_response=error_response,
            reason_codes=list(error_response.get("reason_codes") or []),
            provider_error=error_response.get("provider_error") if isinstance(error_response.get("provider_error"), dict) else None,
            upstream_status_code=error_response.get("upstream_status_code") if isinstance(error_response.get("upstream_status_code"), int) else None,
            upstream_error=error_response.get("upstream_error") if isinstance(error_response.get("upstream_error"), str) else None,
            verifier_report=error_response.get("verifier_report") if isinstance(error_response.get("verifier_report"), dict) else None,
            ownership_conflicts=error_response.get("ownership_conflicts") if isinstance(error_response.get("ownership_conflicts"), list) else None,
        )
    except Exception as e:
        logger.exception("build-phase.unhandled_error task_id=%s phase=%s", task_id, current_phase)
        build_state.phase = "error"
        build_state.updated_at = datetime.now(timezone.utc)
        task.status = TaskStatus.needs_review
        error_response = {
            "status": "needs_review",
            "message": str(e),
            "reason_codes": ["EXECUTION_BUILD_PHASE_UNHANDLED_ERROR"],
        }
        task.audit_history = (task.audit_history or []) + [
            {"event_type": "execution_response", "payload": error_response},
        ]
        flag_modified(task, "audit_history")
        await session.commit()

        msg = f"Unexpected error during build phase '{current_phase}': {str(e)[:200]}"
        return BuildPhaseResponse(
            task_id=task_id,
            build_phase="error",
            status="needs_review",
            agent_phase=current_phase,
            agent_role=_agent_role(current_phase),
            message=msg,
            repository_url=repo_info.get("html_url"),
            execution_response={**error_response, "message": msg},
            reason_codes=["EXECUTION_BUILD_PHASE_UNHANDLED_ERROR"],
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
