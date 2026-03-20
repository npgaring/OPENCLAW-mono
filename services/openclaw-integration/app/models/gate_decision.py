"""GateDecisionRecord table."""
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class GateDecisionRecord(SQLModel, table=True):
    __tablename__ = "gate_decisions"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    task_id: UUID = Field(index=True)
    ocgg_identity: str = Field(index=True)
    outcome: str = Field()
    reason_codes: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    defect_list: List[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    policy_version: str = Field()
    spec_hash: str = Field()
    plan_hash: str = Field()
    approver_id: Optional[str] = Field(default=None)
    approval_reference: Optional[str] = Field(default=None)
    execution_token_hash: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None, max_length=36, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
