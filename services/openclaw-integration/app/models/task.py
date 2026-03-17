"""Task table and request/response models."""
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Enum as SaEnum, JSON, Text
from sqlmodel import Field as SqlField, SQLModel


class TaskStatus(str, Enum):
    submitted = "submitted"
    completed = "completed"
    failed = "failed"
    error = "error"
    auth_error = "auth_error"
    invalid_plan = "invalid_plan"
    domain_rejected = "domain_rejected"
    partial = "partial"
    needs_review = "needs_review"
    execution_aborted = "execution_aborted"  # F4: CPU/memory exhaustion or resource limit


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    task_id: UUID = SqlField(primary_key=True, default_factory=uuid4)
    ocgg_identity: str = SqlField(index=True)
    domain: str = SqlField()
    plan_hash: str = SqlField()
    spec_hash: str | None = SqlField(default=None, index=True)
    policy_version: str | None = SqlField(default=None)
    gate_outcome: str | None = SqlField(default=None)
    reason_codes: list[str] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    execution_token_hash: str | None = SqlField(default=None)
    approval_reference: str | None = SqlField(default=None)
    plan_json: dict[str, Any] = SqlField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    audit_history: list[Any] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: str = SqlField(default="submitted")  # taskstatus enum in PG
    created_at: datetime = SqlField(default_factory=datetime.utcnow)
    updated_at: datetime = SqlField(default_factory=datetime.utcnow)
    execution_id: str | None = SqlField(default=None, index=True)


class TaskOperation(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    op_id: str | None = None
    target: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class TaskSubmitRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "ocgg_identity": "W-OCGG",
                    "plan_hash": "plan_8e7c8b20b2",
                    "operations": [
                        {
                            "op_id": "op-001",
                            "type": "write_config",
                            "target": "web/app",
                            "inputs": {
                                "path": "app/config.json",
                                "content": "{\"featureFlags\":{\"newHomepage\":true}}",
                            },
                        },
                        {
                            "op_id": "op-002",
                            "type": "build",
                            "target": "web/app",
                            "inputs": {"command": "npm run build"},
                        },
                        {
                            "op_id": "op-003",
                            "type": "deploy",
                            "target": "web/app",
                            "inputs": {"provider": "vercel", "project": "marketing-site"},
                        },
                    ],
                }
            ]
        },
    )

    ocgg_identity: str  # W-OCGG | R-OCGG
    plan_hash: str
    operations: list[TaskOperation]
    # Optional: richer plan for OpenClaw (not part of plan_hash)
    goal: str | None = None
    context: str | None = None
    acceptance_criteria: list[str] | None = None


class TaskSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: UUID
    execution_id: str | None = None
    status: str
    execution_response: dict[str, Any] | None = None
    gate_outcome: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    audit_trace_id: str | None = None
    tenant_id: str | None = None
    artifact_id: str | None = None
    artifact_owner: str | None = None
    operator_identity: str | None = None
    approver_identity: str | None = None


class TaskContinueRequest(BaseModel):
    message: str
    prior_context: str | None = None


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: str
    execution_id: str | None = None
    audit_history: list[Any] = Field(default_factory=list)
