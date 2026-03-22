"""Human approval workflow: list, detail, approve, reject, resume."""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_session
from app.models.approval_request import ApprovalRequest
from app.models.task import TaskSubmitResponse
from app.services import approvals_service

router = APIRouter(prefix="/approvals")


class ApproveRejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_id: str = Field(..., description="Auditable approver identity (caller-supplied label).")
    comment: Optional[str] = None


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: Optional[str] = Field(default=None, description="Optional actor id for audit (defaults to integration caller).")


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    task_id: Optional[UUID] = None
    source_layer: str
    status: str
    reason_code: Optional[str] = None
    approval_scope: Optional[str] = None
    snapshot_hash: str
    resume_from_stage: str
    created_at: Any
    decided_at: Optional[Any] = None
    expires_at: Optional[Any] = None


@router.get("/", response_model=list[ApprovalOut])
async def list_approvals(
    session: AsyncSession = Depends(get_session),
    status: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = 100,
):
    return await approvals_service.list_approvals(session, status=status, trace_id=trace_id, limit=limit)


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: UUID, session: AsyncSession = Depends(get_session)):
    ar = await session.get(ApprovalRequest, approval_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return ar


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: UUID,
    body: ApproveRejectBody,
    session: AsyncSession = Depends(get_session),
):
    return await approvals_service.approve_request(
        session, approval_id, approver_id=body.approver_id, comment=body.comment
    )


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: UUID,
    body: ApproveRejectBody,
    session: AsyncSession = Depends(get_session),
):
    return await approvals_service.reject_request(
        session, approval_id, rejected_by=body.approver_id, comment=body.comment
    )


@router.post("/{approval_id}/resume")
async def resume(
    approval_id: UUID,
    session: AsyncSession = Depends(get_session),
    body: ResumeBody = ResumeBody(),
):
    """Continue the pipeline from the stored checkpoint (task or adapter). Returns TaskSubmitResponse or adapter substrate JSON."""
    actor = body.actor or "integration"
    result = await approvals_service.resume_approved_request(session, approval_id, actor=actor)
    if isinstance(result, TaskSubmitResponse):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result
