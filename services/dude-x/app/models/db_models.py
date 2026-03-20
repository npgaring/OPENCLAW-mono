"""SQLModel table definitions for specs and plans."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, DateTime, JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


class SpecRecord(SQLModel, table=True):
    __tablename__ = "specs"

    spec_hash: str = Field(primary_key=True, max_length=255)
    identity: Optional[str] = Field(default=None, index=True, max_length=64)
    payload: dict[str, Any] = Field(sa_type=JSON)
    received_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PlanRecord(SQLModel, table=True):
    __tablename__ = "plans"

    plan_hash: str = Field(primary_key=True, max_length=255)
    identity: Optional[str] = Field(default=None, index=True, max_length=64)
    payload: dict[str, Any] = Field(sa_type=JSON)
    domain: str = Field(max_length=64)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
