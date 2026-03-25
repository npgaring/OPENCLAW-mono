"""Approval request persistence, hashing, and resume orchestration."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select

from app.core.config import settings
from app.models.approval_request import ApprovalRequest, ApprovalSourceLayer, ApprovalStatus
from app.models.task import Task, TaskStatus, TaskSubmitRequest

logger = logging.getLogger(__name__)


def canonical_snapshot_hash(payload: dict[str, Any]) -> str:
    """Deterministic hash for checkpoint integrity (no snapshot_hash field inside payload)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def prod_governance_resume_snapshot_hash(body: TaskSubmitRequest, trace_id_for_body: str) -> str:
    """Snapshot for idempotent GOVERNANCE prod-deploy stops (POST /gate/evaluate + POST /task)."""
    cp = _task_checkpoint(body.model_dump(mode="json"), trace_id_for_body)
    return canonical_snapshot_hash(cp)


def _task_checkpoint(task_submit: dict[str, Any], trace_id: str) -> dict[str, Any]:
    return {
        "v": 2,
        "kind": "task_resume",
        "trace_id": trace_id,
        "task_submit": task_submit,
        "reevaluate_frame_on_resume": True,
    }


async def find_pending_governance_prod_approval(
    session: AsyncSession,
    *,
    trace_id: str,
    snapshot_hash: str,
) -> Optional[ApprovalRequest]:
    """Return an existing PENDING GOVERNANCE prod-deploy approval for the same trace + checkpoint snapshot."""
    stmt = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.trace_id == trace_id,
            ApprovalRequest.snapshot_hash == snapshot_hash,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
            ApprovalRequest.source_layer == ApprovalSourceLayer.GOVERNANCE.value,
            ApprovalRequest.reason_code == "PROD_DEPLOY_NO_APPROVAL",
        )
        .limit(1)
    )
    r = await session.execute(stmt)
    return r.scalar_one_or_none()


async def create_approval_request_for_stop(
    session: AsyncSession,
    *,
    trace_id: str,
    task_id: Optional[UUID],
    source_layer: ApprovalSourceLayer,
    reason_code: str,
    resume_from_stage: str,
    task_submit_body: TaskSubmitRequest,
    trace_id_for_body: str,
    approval_scope: str,
    requested_by: Optional[str] = None,
) -> ApprovalRequest:
    cp = _task_checkpoint(task_submit_body.model_dump(mode="json"), trace_id_for_body)
    snap = canonical_snapshot_hash(cp)
    exp = datetime.utcnow() + timedelta(hours=settings.approval_request_ttl_hours)
    ar = ApprovalRequest(
        trace_id=trace_id,
        task_id=task_id,
        source_layer=source_layer.value,
        status=ApprovalStatus.PENDING.value,
        reason_code=reason_code,
        approval_scope=approval_scope,
        snapshot_hash=snap,
        requested_by=requested_by,
        resume_from_stage=resume_from_stage,
        checkpoint_payload_json=cp,
        expires_at=exp,
    )
    session.add(ar)
    await session.flush()
    await session.refresh(ar)
    return ar


async def create_adapter_approval_request(
    session: AsyncSession,
    *,
    trace_id: str,
    reason_code: str,
    resume_from_stage: str,
    approval_scope: str,
    checkpoint: dict[str, Any],
) -> ApprovalRequest:
    snap = canonical_snapshot_hash(checkpoint)
    exp = datetime.utcnow() + timedelta(hours=settings.approval_request_ttl_hours)
    ar = ApprovalRequest(
        trace_id=trace_id,
        task_id=None,
        source_layer=ApprovalSourceLayer.ADAPTER.value,
        status=ApprovalStatus.PENDING.value,
        reason_code=reason_code,
        approval_scope=approval_scope,
        snapshot_hash=snap,
        resume_from_stage=resume_from_stage,
        checkpoint_payload_json=checkpoint,
        expires_at=exp,
    )
    session.add(ar)
    await session.flush()
    await session.refresh(ar)
    return ar


def merge_task_body_for_resume_uato(approval: ApprovalRequest) -> TaskSubmitRequest:
    cp = approval.checkpoint_payload_json
    d = dict(cp["task_submit"])
    d["trace_id"] = cp["trace_id"]
    d["approval_reference"] = str(approval.id)
    if approval.approved_by:
        d["approver_id"] = approval.approved_by
    d["uato"] = {"trust_level": "HIGH", "authority_level": "HIGH", "trust_source": "HUMAN_SUBMITTED"}
    return TaskSubmitRequest.model_validate(d)


def merge_task_body_for_resume_governance(approval: ApprovalRequest) -> TaskSubmitRequest:
    cp = approval.checkpoint_payload_json
    d = dict(cp["task_submit"])
    d["trace_id"] = cp["trace_id"]
    d["approval_reference"] = str(approval.id)
    if approval.approved_by:
        d["approver_id"] = approval.approved_by
    return TaskSubmitRequest.model_validate(d)


def _verify_snapshot(ar: ApprovalRequest) -> None:
    cp = ar.checkpoint_payload_json
    if canonical_snapshot_hash(cp) != ar.snapshot_hash:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_SNAPSHOT_MISMATCH", "message": "Checkpoint hash does not match stored snapshot_hash."})


def _approval_expired(ar: ApprovalRequest) -> bool:
    if not ar.expires_at:
        return False
    exp = ar.expires_at
    if exp.tzinfo is not None:
        exp = exp.replace(tzinfo=None)
    return datetime.utcnow() > exp


def _ensure_not_expired(ar: ApprovalRequest) -> None:
    if _approval_expired(ar):
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_EXPIRED", "message": "Approval request has expired."})


async def approve_request(
    session: AsyncSession,
    approval_id: UUID,
    *,
    approver_id: str,
    comment: Optional[str] = None,
) -> ApprovalRequest:
    ar = await session.get(ApprovalRequest, approval_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if ar.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_NOT_PENDING", "message": f"Status is {ar.status}, expected PENDING."})
    _ensure_not_expired(ar)
    ar.status = ApprovalStatus.APPROVED.value
    ar.approved_by = approver_id
    ar.comment = comment
    ar.decided_at = datetime.utcnow()
    if ar.task_id:
        t = await session.get(Task, ar.task_id)
        if t:
            t.audit_history = t.audit_history or []
            t.audit_history.append(
                {
                    "event_type": "approval_approved",
                    "payload": {"approval_request_id": str(ar.id), "approver_id": approver_id},
                }
            )
            flag_modified(t, "audit_history")
    await session.commit()
    await session.refresh(ar)
    return ar


async def reject_request(
    session: AsyncSession,
    approval_id: UUID,
    *,
    rejected_by: str,
    comment: Optional[str] = None,
) -> ApprovalRequest:
    ar = await session.get(ApprovalRequest, approval_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if ar.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_NOT_PENDING", "message": f"Status is {ar.status}, expected PENDING."})
    ar.status = ApprovalStatus.REJECTED.value
    ar.rejected_by = rejected_by
    ar.comment = comment
    ar.decided_at = datetime.utcnow()
    if ar.task_id:
        t = await session.get(Task, ar.task_id)
        if t:
            t.audit_history = t.audit_history or []
            t.audit_history.append(
                {
                    "event_type": "approval_rejected",
                    "payload": {"approval_request_id": str(ar.id), "rejected_by": rejected_by},
                }
            )
            flag_modified(t, "audit_history")
    await session.commit()
    await session.refresh(ar)
    return ar


async def list_approvals(
    session: AsyncSession,
    *,
    status: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = 100,
) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if trace_id:
        stmt = stmt.where(ApprovalRequest.trace_id == trace_id)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(min(limit, 500))
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def resume_approved_request(
    session: AsyncSession,
    approval_id: UUID,
    *,
    actor: str,
) -> Any:
    """Backend-controlled resume: validate checkpoint, then rerun adapter conversion or full POST /task (shared-state frame + governance)."""
    from app.services.task_submission import run_task_submission

    ar = await session.get(ApprovalRequest, approval_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if ar.status == ApprovalStatus.CONSUMED.value:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_CONSUMED", "message": "Approval already consumed."})
    if ar.status != ApprovalStatus.APPROVED.value:
        raise HTTPException(
            status_code=422,
            detail={"code": "APPROVAL_NOT_APPROVED", "message": f"Cannot resume from status {ar.status}."},
        )
    _ensure_not_expired(ar)
    _verify_snapshot(ar)

    if ar.source_layer == ApprovalSourceLayer.ADAPTER.value:
        from app.api.openai_flow import resume_adapter_from_approval

        try:
            resp = await resume_adapter_from_approval(session, ar, actor=actor)
        except Exception as e:
            logger.exception("approval_resume_failed approval_id=%s", approval_id)
            raise
        ar_ad = await session.get(ApprovalRequest, approval_id)
        if ar_ad:
            ar_ad.status = ApprovalStatus.CONSUMED.value
        await session.commit()
        return resp

    if ar.task_id is None:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_TASK_MISSING", "message": "Task-scoped approval has no task_id."})

    task = await session.get(Task, ar.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found for approval")

    if ar.source_layer == ApprovalSourceLayer.UATO.value:
        body = merge_task_body_for_resume_uato(ar)
    elif ar.source_layer == ApprovalSourceLayer.GOVERNANCE.value:
        body = merge_task_body_for_resume_governance(ar)
    else:
        raise HTTPException(status_code=422, detail={"code": "APPROVAL_LAYER_UNSUPPORTED", "message": ar.source_layer})

    try:
        resp = await run_task_submission(session, body, ar.trace_id, reuse_task_id=ar.task_id)
    except Exception as e:
        logger.exception("approval_resume_failed approval_id=%s", approval_id)
        if task:
            task.audit_history = task.audit_history or []
            task.audit_history.append(
                {
                    "event_type": "evaluation_frame_resume_failed",
                    "payload": {"approval_request_id": str(approval_id), "error": str(e), "actor": actor},
                }
            )
            task.audit_history.append(
                {
                    "event_type": "approval_resume_failed",
                    "payload": {"approval_request_id": str(approval_id), "error": str(e), "actor": actor},
                }
            )
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(task, "audit_history")
            await session.commit()
        raise

    ar2 = await session.get(ApprovalRequest, approval_id)
    if ar2:
        ar2.status = ApprovalStatus.CONSUMED.value
        if not ar2.decided_at:
            ar2.decided_at = datetime.utcnow()
    task2 = await session.get(Task, ar.task_id)
    if task2:
        task2.audit_history = task2.audit_history or []
        task2.audit_history.append(
            {
                "event_type": "approval_resumed",
                "payload": {"approval_request_id": str(approval_id), "actor": actor, "source_layer": ar.source_layer},
            }
        )
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(task2, "audit_history")
    await session.commit()
    return resp
