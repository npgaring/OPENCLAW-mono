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
    uato_decision: Optional[str] = Field(default=None)
    uato_reason_codes: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    uato_trust_level: Optional[str] = Field(default=None)
    uato_authority_level: Optional[str] = Field(default=None)
    uato_decision_version: Optional[str] = Field(default=None)
    uato_input_hash: Optional[str] = Field(default=None, index=True)
    uato_evaluated_at: Optional[datetime] = Field(default=None)
    invariant_e_decision: Optional[str] = Field(default=None)
    invariant_e_reason_codes: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    invariant_e_decision_version: Optional[str] = Field(default=None)
    invariant_e_input_hash: Optional[str] = Field(default=None, index=True)
    invariant_e_evaluated_at: Optional[datetime] = Field(default=None)
    execution_envelope_hash: Optional[str] = Field(default=None, index=True)
    requested_capabilities_json: List[Any] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    allowed_capabilities_json: List[Any] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    budget_limit_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    dispatch_blocked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
