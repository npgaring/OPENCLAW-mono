"""AuditEvent table."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    task_id: UUID = Field(index=True)
    event_type: str = Field()
    payload: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
