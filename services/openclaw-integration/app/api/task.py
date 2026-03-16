"""POST /task — submit task, gate, token, executor call."""
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.db.session import get_session
from app.gate.engine import GateEngine
from app.gate.policy import get_policy_version_at_execution
from app.gate.token import generate_execution_token, hash_token, verify_execution_token
from app.models import GateDecisionRecord, Task, TaskSubmitRequest, TaskSubmitResponse, UsedExecutionToken
from app.services.execution_client import OpenClawClient, OpenClawError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/task", response_model=TaskSubmitResponse)
async def submit_task(
    body: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
):

    if body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "Unknown ocgg_identity"})
    domain = IDENTITY_DOMAIN_MAP[body.ocgg_identity]
    spec = body.model_dump()
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
        audit_history=[],
        status="submitted",
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
    )
    session.add(gate_record)
    await session.commit()
    await session.refresh(task)
    task.audit_history = task.audit_history or []
    task.audit_history.append({"event_type": "gate_decision", "payload": {"outcome": decision.outcome.value, "reason_codes": decision.reason_codes}})
    flag_modified(task, "audit_history")
    await session.commit()

    if decision.outcome.value != "PASS":
        return TaskSubmitResponse(
            task_id=task.task_id,
            status=task.status,
            gate_outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
        )

    execution_token = generate_execution_token({
        "spec_hash": spec_hash,
        "plan_hash": plan_hash,
        "policy_version": decision.policy_version,
        "ocgg_identity": body.ocgg_identity,
        "outcome": "PASS",
    })
    token_hash = hash_token(execution_token)
    verified, _ = verify_execution_token(execution_token)
    if not verified:
        return TaskSubmitResponse(task_id=task.task_id, status="submitted", gate_outcome="BLOCK", reason_codes=["EXECUTION_TOKEN_INVALID"])
    if get_policy_version_at_execution() != decision.policy_version:
        return TaskSubmitResponse(task_id=task.task_id, status="submitted", gate_outcome="BLOCK", reason_codes=["RE_EVALUATION_REQUIRED"])
    existing = await session.get(UsedExecutionToken, token_hash)
    if existing:
        return TaskSubmitResponse(task_id=task.task_id, status="submitted", gate_outcome="BLOCK", reason_codes=["TOKEN_ALREADY_USED"])
    used = UsedExecutionToken(token_hash=token_hash, task_id=task.task_id)
    session.add(used)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return TaskSubmitResponse(task_id=task.task_id, status="submitted", gate_outcome="BLOCK", reason_codes=["TOKEN_ALREADY_USED"])
    gate_record.execution_token_hash = token_hash
    task.execution_token_hash = token_hash
    await session.commit()

    try:
        client = OpenClawClient()
        result = await client.execute(plan_json, execution_token)
    except OpenClawError as e:
        task.status = e.error_type
        task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": e.response}]
        if e.response.get("execution_id"):
            task.execution_id = e.response["execution_id"]
        await session.commit()
        return TaskSubmitResponse(
            task_id=task.task_id,
            status=e.error_type,
            execution_response=e.response,
            gate_outcome="PASS",
            reason_codes=[],
        )
    task.execution_id = result.get("execution_id")
    task.status = "completed" if result.get("status") == "success" else "failed"
    task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": result}]
    await session.commit()
    return TaskSubmitResponse(
        task_id=task.task_id,
        execution_id=task.execution_id,
        status=task.status,
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
