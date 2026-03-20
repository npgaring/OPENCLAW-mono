"""POST /audit — receive callbacks, update task + AuditEvent; GET reconstruct for replay."""
import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

from app.core.errors import task_not_found
from app.db.session import get_session
from app.gate.policy import POLICY_VERSION
from app.models import AuditEvent, AuditAck, AuditRequest, GateDecisionRecord, Task, TaskStatus
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

router = APIRouter()


class ReconstructResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: Optional[str] = None
    task_id: UUID
    spec_hash: Optional[str] = None
    plan_hash: str
    plan_json: dict[str, Any] = Field(default_factory=dict)
    gate_outcome: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)
    defect_list: list[dict[str, Any]] = Field(default_factory=list)
    policy_version: Optional[str] = None
    execution_token_hash: Optional[str] = None
    approval_reference: Optional[str] = None
    status: Optional[str] = None
    audit_history: list[Any] = Field(default_factory=list)
    note: str = (
        "Reconstructed from integration DB only (no browser localStorage). "
        "Compile step is not stored here; correlate via trace_id in dude-x compile_events.metadata."
    )


@router.get("/audit/reconstruct", response_model=ReconstructResponse)
async def reconstruct_audit(
    task_id: Optional[UUID] = Query(None, description="Integration task UUID"),
    trace_id: Optional[str] = Query(None, description="Correlation id from compile/gate/task"),
    session: AsyncSession = Depends(get_session),
):
    """P1: Server-side replay snapshot from DB (task + latest gate decision)."""
    if not task_id and not trace_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_QUERY", "message": "Provide task_id and/or trace_id"},
        )
    task: Optional[Task] = None
    if task_id:
        task = await session.get(Task, task_id)
    if not task and trace_id:
        result = await session.execute(select(Task).where(Task.trace_id == trace_id.strip()).limit(1))
        task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "No task for task_id/trace_id"})

    result = await session.execute(
        select(GateDecisionRecord)
        .where(GateDecisionRecord.task_id == task.task_id)
        .order_by(GateDecisionRecord.created_at.desc())
        .limit(1)
    )
    gate_record = result.scalars().first()

    return ReconstructResponse(
        trace_id=task.trace_id,
        task_id=task.task_id,
        spec_hash=task.spec_hash,
        plan_hash=task.plan_hash,
        plan_json=dict(task.plan_json or {}),
        gate_outcome=gate_record.outcome if gate_record else task.gate_outcome,
        reason_codes=list(gate_record.reason_codes or []) if gate_record else list(task.reason_codes or []),
        defect_list=list(gate_record.defect_list or []) if gate_record else [],
        policy_version=gate_record.policy_version if gate_record else task.policy_version,
        execution_token_hash=gate_record.execution_token_hash if gate_record else task.execution_token_hash,
        approval_reference=gate_record.approval_reference if gate_record else task.approval_reference,
        status=task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
        audit_history=list(task.audit_history or []),
    )


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
    try:
        task.status = TaskStatus(body.status)
    except ValueError:
        task.status = TaskStatus.error
    payload = jsonable_encoder(payload)
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
