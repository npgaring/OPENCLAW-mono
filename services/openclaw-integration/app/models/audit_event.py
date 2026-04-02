"""AuditEvent table."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlmodel import Field, SQLModel


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"

    id: UUID = Field(default_factory=uuid4, sa_column=Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4))
    task_id: UUID = Field(sa_column=Column(PgUUID(as_uuid=True), index=True, nullable=False))
    event_type: str = Field()
    payload: Optional[dict] = Field(default=None, sa_type=JSON)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
