"""DB models for OpenAI Vessel + Invariant-C + Substrate Adapter audit tables."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class OpenAIVesselEvent(SQLModel, table=True):
    __tablename__ = "openai_vessel_events"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    trace_id: str = Field(index=True, max_length=36)
    ocgg_identity: str = Field(index=True)
    intent: str = Field(index=True)
    request_hash: str = Field(index=True)
    candidate_plan_hash: Optional[str] = Field(default=None, index=True)
    model: str = Field()
    request_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    raw_response: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    schema_valid: bool = Field(default=False)
    outcome: str = Field(index=True)
    reason_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class InvariantCDecisionRecord(SQLModel, table=True):
    __tablename__ = "invariant_c_decisions"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    trace_id: str = Field(index=True, max_length=36)
    ocgg_identity: str = Field(index=True)
    intent: str = Field(index=True)
    candidate_plan_hash: str = Field(index=True)
    decision: str = Field(index=True)
    reason_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    check_results: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    decision_version: str = Field()
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SubstrateAdapterEvent(SQLModel, table=True):
    __tablename__ = "substrate_adapter_events"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    trace_id: str = Field(index=True, max_length=36)
    ocgg_identity: str = Field(index=True)
    intent: str = Field(index=True)
    candidate_plan_hash: str = Field(index=True)
    integration_plan_hash: Optional[str] = Field(default=None, index=True)
    outcome: str = Field(index=True)
    reason_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

