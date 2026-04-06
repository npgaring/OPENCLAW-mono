"""SQLModel for the deployments tracking table."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeploymentRecord(SQLModel, table=True):
    __tablename__ = "deployments"

    id: str = Field(primary_key=True, max_length=255)
    trace_id: str = Field(index=True, max_length=36)
    task_id: Optional[str] = Field(default=None, index=True, max_length=255)
    build_sot_hash: Optional[str] = Field(default=None, max_length=255)
    execution_plan_hash: Optional[str] = Field(default=None, max_length=255)
    project_name: str = Field(max_length=255)

    github_owner: Optional[str] = Field(default=None, max_length=255)
    github_repo_name: Optional[str] = Field(default=None, max_length=255)
    github_repo_url: Optional[str] = Field(default=None, max_length=1024)
    github_branch: Optional[str] = Field(default=None, max_length=128)
    github_commit_sha: Optional[str] = Field(default=None, max_length=64)

    vercel_project_id: Optional[str] = Field(default=None, max_length=255)
    vercel_project_name: Optional[str] = Field(default=None, max_length=255)
    vercel_deployment_id: Optional[str] = Field(default=None, max_length=255)
    vercel_deployment_url: Optional[str] = Field(default=None, max_length=1024)
    vercel_preview_url: Optional[str] = Field(default=None, max_length=1024)
    vercel_deploy_target: Optional[str] = Field(default=None, max_length=32)

    status: str = Field(default="pending", max_length=64)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    build_logs: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    fix_attempts: int = Field(default=0)
    vercel_ready_state: Optional[str] = Field(default=None, max_length=64)

    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
