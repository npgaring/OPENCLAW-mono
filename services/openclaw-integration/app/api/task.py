"""POST /task — submit task, gate, token, executor call; POST /task/{id}/continue — follow-up."""
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.errors import ErrorCodes
from app.core.trace_id import normalize_trace_id
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.db.session import get_session
from app.gate.engine import GateEngine
from app.gate.policy import get_policy_version_at_execution
from app.gate.token import generate_execution_token, hash_token, verify_execution_token
from app.models import GateDecisionRecord, Task, TaskContinueRequest, TaskStatus, TaskSubmitRequest, TaskSubmitResponse, UsedExecutionToken
from app.uato import build_uato_input_from_spec, evaluate_uato, to_trace_record
from app.uato.plan_bridge import integration_plan_preview
from app.uato.types import UATO_DECISION_VERSION
from app.services.execution_client import OpenClawClient, OpenClawError

logger = logging.getLogger(__name__)
router = APIRouter()


def _task_submit_response(
    *,
    task_id: UUID,
    status: str,
    trace_id: Optional[str] = None,
    uato_decision: Optional[str] = None,
    uato_reason_codes: Optional[list[str]] = None,
    **kwargs: Any,
) -> TaskSubmitResponse:
    if trace_id:
        kwargs["trace_id"] = trace_id
        kwargs["audit_trace_id"] = trace_id
    if uato_decision is not None:
        kwargs["uato_decision"] = uato_decision
    if uato_reason_codes is not None:
        kwargs["uato_reason_codes"] = uato_reason_codes
    return TaskSubmitResponse(task_id=task_id, status=status, **kwargs)


@router.post("/task", response_model=TaskSubmitResponse)
async def submit_task(
    body: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
):

    if body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "Unknown ocgg_identity"})
    domain = IDENTITY_DOMAIN_MAP[body.ocgg_identity]
    spec = body.model_dump()
    trace_id = normalize_trace_id(spec.pop("trace_id", None))
    spec.pop("uato", None)

    uato_in = build_uato_input_from_spec(
        spec,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        uato_hints=body.uato,
    )
    uato_res = evaluate_uato(uato_in)
    uato_evaluated_at = datetime.utcnow()
    uato_trace = to_trace_record(uato_in, uato_res)

    if uato_res.decision != "PASS":
        plan_json, plan_hash, spec_hash = integration_plan_preview(spec, body.ocgg_identity)
        short_status = TaskStatus.needs_review if uato_res.decision == "ESCALATE" else TaskStatus.submitted
        task = Task(
            ocgg_identity=body.ocgg_identity,
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version=UATO_DECISION_VERSION,
            gate_outcome="BLOCK",
            reason_codes=list(uato_res.reason_codes),
            plan_json=plan_json,
            audit_history=[
                {
                    "event_type": "uato_decision",
                    "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO"},
                }
            ],
            status=short_status,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
        )
        session.add(task)
        await session.flush()
        gate_record = GateDecisionRecord(
            task_id=task.task_id,
            ocgg_identity=body.ocgg_identity,
            outcome="BLOCK",
            reason_codes=list(uato_res.reason_codes),
            defect_list=[],
            policy_version=UATO_DECISION_VERSION,
            spec_hash=spec_hash,
            plan_hash=plan_hash,
            approver_id=None,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
        )
        session.add(gate_record)
        await session.commit()
        await session.refresh(task)
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=list(uato_res.reason_codes),
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )

    engine = GateEngine()
    evaluation = engine.evaluate(spec, body.ocgg_identity)
    decision = evaluation.decision
    plan_json = evaluation.plan_json
    spec_hash = evaluation.spec_hash
    plan_hash = evaluation.plan_hash

    task = Task(
        ocgg_identity=body.ocgg_identity,
        domain=domain,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        policy_version=decision.policy_version,
        gate_outcome=decision.outcome.value,
        reason_codes=decision.reason_codes,
        plan_json=plan_json,
        audit_history=[
            {
                "event_type": "uato_decision",
                "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO"},
            }
        ],
        status=TaskStatus.submitted,
        trace_id=trace_id,
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
        uato_trust_level=uato_in.trust_state.level,
        uato_authority_level=uato_in.authority_state.level,
        uato_decision_version=uato_res.decision_version,
        uato_input_hash=uato_trace["uato_input_hash"],
        uato_evaluated_at=uato_evaluated_at,
    )
    session.add(task)
    await session.flush()
    gate_record = GateDecisionRecord(
        task_id=task.task_id,
        ocgg_identity=body.ocgg_identity,
        outcome=decision.outcome.value,
        reason_codes=decision.reason_codes,
        defect_list=[{"code": d.code, "field": d.field, "message": d.message} for d in decision.defect_list],
        policy_version=decision.policy_version,
        spec_hash=spec_hash,
        plan_hash=plan_hash,
        approver_id=decision.approver_id,
        trace_id=trace_id,
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
        uato_trust_level=uato_in.trust_state.level,
        uato_authority_level=uato_in.authority_state.level,
        uato_decision_version=uato_res.decision_version,
        uato_input_hash=uato_trace["uato_input_hash"],
        uato_evaluated_at=uato_evaluated_at,
    )
    session.add(gate_record)
    await session.commit()
    await session.refresh(task)
    task.audit_history = task.audit_history or []
    task.audit_history.append({"event_type": "gate_decision", "payload": {"outcome": decision.outcome.value, "reason_codes": decision.reason_codes}})
    flag_modified(task, "audit_history")
    await session.commit()

    if decision.outcome.value != "PASS":
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )

    execution_token = generate_execution_token({
        "spec_hash": spec_hash,
        "plan_hash": plan_hash,
        "policy_version": decision.policy_version,
        "ocgg_identity": body.ocgg_identity,
        "outcome": "PASS",
        "trace_id": trace_id,
    })
    token_hash = hash_token(execution_token)
    verified, _ = verify_execution_token(execution_token)
    if not verified:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=["EXECUTION_TOKEN_INVALID"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )
    if get_policy_version_at_execution() != decision.policy_version:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=["RE_EVALUATION_REQUIRED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )
    existing = await session.get(UsedExecutionToken, token_hash)
    if existing:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=["TOKEN_ALREADY_USED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )
    used = UsedExecutionToken(token_hash=token_hash, task_id=task.task_id)
    session.add(used)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=["TOKEN_ALREADY_USED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )
    gate_record.execution_token_hash = token_hash
    task.execution_token_hash = token_hash
    await session.commit()

    try:
        client = OpenClawClient()
        result = await client.execute(plan_json, execution_token, task_id=str(task.task_id))
    except OpenClawError as e:
        try:
            task.status = TaskStatus(e.error_type)
        except ValueError:
            task.status = TaskStatus.error
        task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": e.response}]
        if e.response.get("execution_id"):
            task.execution_id = e.response["execution_id"]
        await session.commit()
        reason_codes = ["EXECUTION_ABORTED"] if e.error_type == "execution_aborted" else []
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            execution_response=e.response,
            gate_outcome="PASS",
            reason_codes=reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )
    task.execution_id = result.get("execution_id")
    s = result.get("status")
    if s == "success":
        task.status = TaskStatus.completed
    elif s in ("failed", "partial", "needs_review"):
        task.status = TaskStatus(s)
    else:
        task.status = TaskStatus.failed
    task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": result}]
    await session.commit()
    return _task_submit_response(
        task_id=task.task_id,
        execution_id=task.execution_id,
        status=task.status.value,
        trace_id=trace_id,
        execution_response=result,
        gate_outcome="PASS",
        reason_codes=[],
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
    )


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
