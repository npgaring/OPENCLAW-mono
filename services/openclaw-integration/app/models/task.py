"""Task table and request/response models."""
from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Enum as SaEnum, JSON, Text
from sqlmodel import Field as SqlField, SQLModel


class UatoHints(BaseModel):
    """Optional UATO admissibility overrides (trust × authority). Omitted fields use server defaults."""

    model_config = ConfigDict(extra="forbid")

    trust_level: Optional[Literal["LOW", "HIGH"]] = None
    authority_level: Optional[Literal["LOW", "HIGH"]] = None
    trust_source: Optional[str] = None
    request_source: Optional[str] = None
    tenant_id: Optional[str] = None
    evidence: Optional[List[str]] = None


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
    pending_approval = "pending_approval"  # UATO REQUIRE_APPROVAL: admissibility holds pending human approval
    uato_blocked = "uato_blocked"  # UATO BLOCK: fail-closed admissibility (not governance policy)
    invariant_e_denied = "invariant_e_denied"  # Invariant-E denied execution dispatch (governance may still be PASS)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    task_id: UUID = SqlField(primary_key=True, default_factory=uuid4)
    ocgg_identity: str = SqlField(index=True)
    domain: str = SqlField()
    plan_hash: str = SqlField()
    spec_hash: Optional[str] = SqlField(default=None, index=True)
    policy_version: Optional[str] = SqlField(default=None)
    # GateEngine outcome only (PASS/BLOCK). Not overwritten when Invariant-E denies dispatch; see dispatch_blocked.
    gate_outcome: Optional[str] = SqlField(default=None)
    governance_outcome: Optional[str] = SqlField(default=None)
    reason_codes: List[str] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    uato_decision: Optional[str] = SqlField(default=None)
    uato_reason_codes: List[str] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    uato_trust_level: Optional[str] = SqlField(default=None)
    uato_authority_level: Optional[str] = SqlField(default=None)
    uato_decision_version: Optional[str] = SqlField(default=None)
    uato_input_hash: Optional[str] = SqlField(default=None, index=True)
    uato_evaluated_at: Optional[datetime] = SqlField(default=None)
    invariant_e_decision: Optional[str] = SqlField(default=None)
    invariant_e_reason_codes: List[str] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    invariant_e_decision_version: Optional[str] = SqlField(default=None)
    invariant_e_input_hash: Optional[str] = SqlField(default=None, index=True)
    invariant_e_evaluated_at: Optional[datetime] = SqlField(default=None)
    execution_envelope_hash: Optional[str] = SqlField(default=None, index=True)
    requested_capabilities_json: List[Any] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    allowed_capabilities_json: List[Any] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    budget_limit_json: Optional[dict] = SqlField(default=None, sa_column=Column(JSON, nullable=True))
    dispatch_blocked: bool = SqlField(default=False)
    execution_token_hash: Optional[str] = SqlField(default=None)
    approval_reference: Optional[str] = SqlField(default=None)
    plan_json: dict = SqlField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    audit_history: List[Any] = SqlField(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: TaskStatus = SqlField(
        default=TaskStatus.submitted,
        sa_column=Column(SaEnum(TaskStatus, name="taskstatus"), nullable=False),
    )
    created_at: datetime = SqlField(default_factory=datetime.utcnow)
    updated_at: datetime = SqlField(default_factory=datetime.utcnow)
    execution_id: Optional[str] = SqlField(default=None, index=True)
    trace_id: Optional[str] = SqlField(default=None, index=True, max_length=36)
    approval_request_id: Optional[UUID] = SqlField(default=None, index=True)
    blocked_stage: Optional[str] = SqlField(default=None)


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
    plan_hash: str = Field(
        ...,
        description="Must equal hash_payload({domain, operations}) — the governance_plan_hash (or integration_plan_hash) from POST /adapter/to-substrate. Do not use substrate_envelope_hash or deprecated plan_hash from that response.",
    )
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
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional UUID; omit to let server generate. Pass compile response trace_id for end-to-end correlation.",
    )
    uato: Optional[UatoHints] = Field(default=None, description="Optional UATO trust/authority hints for admissibility.")

    @model_validator(mode="before")
    @classmethod
    def _alias_integration_plan_hash(cls, values):
        if isinstance(values, dict):
            if values.get("integration_plan_hash"):
                values["plan_hash"] = values["integration_plan_hash"]
        return values


class TaskSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: UUID
    execution_id: Optional[str] = None
    status: str
    execution_response: Optional[dict] = None
    # gate_outcome: effective "may dispatch" signal for backward compatibility (BLOCK if governance blocked, UATO blocked, or execution denied).
    gate_outcome: Optional[str] = None
    # governance_outcome: GateEngine PASS/BLOCK only when gate evaluated (None if stopped at UATO only).
    governance_outcome: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)
    uato_decision: Optional[str] = None
    uato_reason_codes: List[str] = Field(default_factory=list)
    invariant_e_decision: Optional[str] = None
    invariant_e_reason_codes: List[str] = Field(default_factory=list)
    dispatch_blocked: Optional[bool] = None
    trace_id: Optional[str] = None
    audit_trace_id: Optional[str] = None  # deprecated alias; same as trace_id when set
    tenant_id: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_owner: Optional[str] = None
    operator_identity: Optional[str] = None
    approver_identity: Optional[str] = None
    approval_required: Optional[bool] = None
    approval_request_id: Optional[UUID] = None
    approval_status: Optional[str] = None
    source_layer: Optional[str] = None
    resume_available: Optional[bool] = None


class TaskContinueRequest(BaseModel):
    message: str
    prior_context: Optional[str] = None
    trace_id: Optional[str] = Field(
        default=None,
        description="Must match task.trace_id when the task has one (proves same correlation chain).",
    )


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: str
    execution_id: Optional[str] = None
    governance_outcome: Optional[str] = Field(
        default=None,
        description="GateEngine PASS/BLOCK when the gate ran; null if stopped before governance (e.g. UATO-only path).",
    )
    audit_history: List[Any] = Field(default_factory=list)
