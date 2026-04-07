"""SQLModel for the task_build_state table — multi-phase deterministic build state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel
from sqlalchemy.dialects.postgresql import JSONB


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskBuildState(SQLModel, table=True):
    __tablename__ = "task_build_state"

    task_id: str = Field(primary_key=True, max_length=255, foreign_key="tasks.task_id")
    phase: str = Field(default="pending", max_length=32, index=True)

    blueprint_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )
    repo_info_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )
    template_reference_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )
    generated_files_json: Optional[list[dict[str, str]]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )
    config_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )

    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
