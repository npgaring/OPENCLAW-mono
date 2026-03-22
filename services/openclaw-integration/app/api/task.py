"""POST /task — submit task, gate, token, executor call; POST /task/{id}/continue — follow-up."""
import logging
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.errors import ErrorCodes
from app.core.trace_id import normalize_trace_id
from app.db.session import get_session
from app.models import Task, TaskContinueRequest, TaskStatus, TaskSubmitRequest, TaskSubmitResponse
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
    task_id: UUID,
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
