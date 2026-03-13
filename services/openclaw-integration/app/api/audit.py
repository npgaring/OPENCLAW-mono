"""POST /audit — receive callbacks, update task + AuditEvent."""
import datetime
from sqlalchemy import select

from app.core.errors import task_not_found
from app.db.session import get_session
from app.gate.policy import POLICY_VERSION
from app.models import AuditEvent, AuditAck, AuditRequest, GateDecisionRecord, Task
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

router = APIRouter()


@router.post("/audit", response_model=AuditAck)
async def receive_audit(
    body: AuditRequest,
    session: AsyncSession = Depends(get_session),
):
    if not body.task_id:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAYLOAD", "message": "task_id required"})
    if not body.status:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAYLOAD", "message": "status required"})
    task = await session.get(Task, body.task_id)
    if not task:
        raise HTTPException(**task_not_found())
    result = await session.execute(
        select(GateDecisionRecord)
        .where(GateDecisionRecord.task_id == body.task_id)
        .order_by(GateDecisionRecord.created_at.desc())
        .limit(1)
    )
    gate_record = result.scalars().first()
    payload = body.to_payload()
    if gate_record:
        payload["ocgg_identity"] = gate_record.ocgg_identity
        payload["input_spec_hash"] = task.spec_hash
        payload["plan_hash"] = gate_record.plan_hash
        payload["policy_version"] = gate_record.policy_version
        payload["gate_outcome"] = gate_record.outcome
        payload["reason_codes"] = gate_record.reason_codes
        payload["approval_reference"] = gate_record.approval_reference
        payload["execution_token_hash"] = gate_record.execution_token_hash
    if task.policy_version != POLICY_VERSION:
        payload["policy_version_delta"] = True
    task.status = body.status
    task.audit_history = task.audit_history or []
    task.audit_history.append({
        "event_type": body.event_type or "audit",
        "payload": payload,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    })
    flag_modified(task, "audit_history")
    session.add(AuditEvent(task_id=body.task_id, event_type=body.event_type or "audit", payload=payload))
    await session.commit()
    return AuditAck()
