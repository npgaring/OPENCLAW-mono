"""Compile event audit table."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


class CompileEvent(SQLModel, table=True):
    __tablename__ = "compile_events"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()), max_length=36)
    event_type: str = Field(max_length=32)  # COMPILE_OK | COMPILE_FAILED
    spec_hash: str = Field(max_length=255)
    plan_hash: Optional[str] = Field(default=None, max_length=255)
    timestamp: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    metadata_: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON, nullable=False))
