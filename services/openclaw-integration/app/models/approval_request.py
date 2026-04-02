"""First-class approval workflow records (durable pause / approve / resume)."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlmodel import Field, SQLModel


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class ApprovalSourceLayer(str, Enum):
    ADAPTER = "ADAPTER"
    UATO = "UATO"
    GOVERNANCE = "GOVERNANCE"


class ApprovalRequest(SQLModel, table=True):
    __tablename__ = "approval_requests"

    id: UUID = Field(default_factory=uuid4, sa_column=Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4))
    trace_id: str = Field(index=True, max_length=36)
    task_id: Optional[UUID] = Field(default=None, sa_column=Column(PgUUID(as_uuid=True), ForeignKey("tasks.task_id"), index=True, nullable=True))
    source_layer: str = Field(index=True)
    status: str = Field(index=True)
    reason_code: Optional[str] = Field(default=None)
    approval_scope: Optional[str] = Field(default=None)
    snapshot_hash: str = Field(index=True)
    requested_by: Optional[str] = Field(default=None)
    approved_by: Optional[str] = Field(default=None)
    rejected_by: Optional[str] = Field(default=None)
    comment: Optional[str] = Field(default=None)
    resume_from_stage: str = Field()
    checkpoint_payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
