"""Task table and request/response models."""
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    spec_hash: Optional[str] = SqlField(default=None, index=True)
    policy_version: Optional[str] = SqlField(default=None)
    gate_outcome: Optional[str] = SqlField(default=None)
    reason_codes: List[str] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    execution_token_hash: Optional[str] = SqlField(default=None)
    approval_reference: Optional[str] = SqlField(default=None)
    plan_json: dict = SqlField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    audit_history: List[Any] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: str = SqlField(default="submitted")  # taskstatus enum in PG
    created_at: datetime = SqlField(default_factory=datetime.utcnow)
    updated_at: datetime = SqlField(default_factory=datetime.utcnow)
    execution_id: Optional[str] = SqlField(default=None, index=True)


class TaskOperation(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    op_id: Optional[str] = None
    target: Optional[str] = None
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)


class TaskSubmitRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "ocgg_identity": "W-OCGG",
                    "integration_plan_hash": "integration_plan_hash_from_dudex",
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
                    "deployment_target": "production",
                }
            ]
        },
    )

    ocgg_identity: str  # W-OCGG | R-OCGG
    plan_hash: str
    integration_plan_hash: Optional[str] = None
    operations: list[TaskOperation]
    # Optional: richer plan for OpenClaw (not part of plan_hash)
    goal: Optional[str] = None
    context: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    # Gate: production deploy requires one of these
    deployment_target: Optional[str] = None
    approval_reference: Optional[str] = None
    approver_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _alias_integration_plan_hash(cls, values):
        if isinstance(values, dict):
            if not values.get("plan_hash") and values.get("integration_plan_hash"):
                values["plan_hash"] = values["integration_plan_hash"]
        return values


class TaskSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: UUID
    execution_id: Optional[str] = None
    status: str
    execution_response: Optional[dict] = None
    gate_outcome: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)
    audit_trace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_owner: Optional[str] = None
    operator_identity: Optional[str] = None
    approver_identity: Optional[str] = None


class TaskContinueRequest(BaseModel):
    message: str
    prior_context: Optional[str] = None


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: str
    execution_id: Optional[str] = None
    audit_history: List[Any] = Field(default_factory=list)
