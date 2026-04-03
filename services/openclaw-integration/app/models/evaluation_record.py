"""Durable atomic evaluation snapshot (additive; tasks/gate_decisions remain primary)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class EvaluationRecord(SQLModel, table=True):
    __tablename__ = "evaluation_records"

    evaluation_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    trace_id: str = Field(index=True, max_length=36)
    state_hash: str = Field(index=True)
    task_id: Optional[str] = Field(default=None, foreign_key="tasks.task_id", index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
