"""SQLModel tables for governed DUDE-X v2 artifacts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class RawIntentRecord(SQLModel, table=True):
    __tablename__ = "raw_intents_v2"

    raw_intent_hash: str = Field(primary_key=True, max_length=255)
    trace_id: str = Field(index=True, max_length=36)
    ocgg_identity: str = Field(index=True, max_length=64)
    intent: str = Field(index=True, max_length=64)
    status: str = Field(max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class BuildSoTRecord(SQLModel, table=True):
    __tablename__ = "build_sot_v2"

    build_sot_hash: str = Field(primary_key=True, max_length=255)
    trace_id: str = Field(index=True, max_length=36)
    raw_intent_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    parent_build_sot_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    ocgg_identity: str = Field(index=True, max_length=64)
    intent: str = Field(index=True, max_length=64)
    status: str = Field(max_length=64)
    approval_required: bool = Field(default=True)
    approval_status: str = Field(default="NOT_REQUESTED", max_length=32)
    approver_id: Optional[str] = Field(default=None, max_length=128)
    approval_comment: Optional[str] = Field(default=None, max_length=1024)
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    governance_plan_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    governance_state_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ExecutionPlanRecordV2(SQLModel, table=True):
    __tablename__ = "execution_plans_v2"

    execution_plan_hash: str = Field(primary_key=True, max_length=255)
    trace_id: str = Field(index=True, max_length=36)
    build_sot_hash: str = Field(index=True, max_length=255)
    ocgg_identity: str = Field(index=True, max_length=64)
    intent: str = Field(index=True, max_length=64)
    status: str = Field(max_length=64)
    governance_plan_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    governance_state_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    governance_evaluation_id: Optional[str] = Field(default=None, index=True, max_length=255)
    continuity_id: Optional[str] = Field(default=None, index=True, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class StageEventRecordV2(SQLModel, table=True):
    __tablename__ = "stage_events_v2"

    id: UUID = Field(default_factory=uuid4, sa_column=Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4))
    trace_id: str = Field(index=True, max_length=36)
    stage: str = Field(index=True, max_length=64)
    event_type: str = Field(index=True, max_length=64)
    status: str = Field(max_length=64)
    artifact_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    metadata_: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
