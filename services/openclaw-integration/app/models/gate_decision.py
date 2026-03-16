"""GateDecisionRecord table."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class GateDecisionRecord(SQLModel, table=True):
    __tablename__ = "gate_decisions"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    task_id: UUID = Field(index=True)
    ocgg_identity: str = Field(index=True)
    outcome: str = Field()
    reason_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    defect_list: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    policy_version: str = Field()
    spec_hash: str = Field()
    plan_hash: str = Field()
    approver_id: str | None = Field(default=None)
    approval_reference: str | None = Field(default=None)
    execution_token_hash: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
