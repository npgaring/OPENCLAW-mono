"""Execution-plan continuity lock records for governed v2 flow."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ExecutionPlanLockRecord(SQLModel, table=True):
    __tablename__ = "execution_plan_locks_v2"

    continuity_id: str = Field(primary_key=True, max_length=255)
    trace_id: str = Field(index=True, max_length=36)
    ocgg_identity: str = Field(index=True)
    build_sot_hash: str = Field(index=True, max_length=255)
    execution_plan_hash: str = Field(index=True, max_length=255)
    plan_hash: str = Field(index=True, max_length=255)
    governance_evaluation_id: str = Field(index=True, max_length=255)
    state_hash: Optional[str] = Field(default=None, index=True, max_length=255)
    status: str = Field(default="ACTIVE", index=True, max_length=32)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    used_at: Optional[datetime] = Field(default=None)

