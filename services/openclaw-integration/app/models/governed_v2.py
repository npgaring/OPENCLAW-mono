"""API models for governed dual-engine v2 lock endpoints."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.evaluation_frame import EvaluationFrameResponse
from app.models.task import UatoHints, ValidationControls


class BuildSoTLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_sot_hash: str = Field(min_length=1)
    trace_id: Optional[str] = None
    ocgg_identity: str = "W-OCGG"
    intent: str = "web-build"
    governance_projection: dict[str, Any] = Field(default_factory=dict)
    uato: Optional[UatoHints] = None
    validation: Optional[ValidationControls] = None


class BuildSoTLockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    build_sot_hash: str
    outcome: str
    reason_codes: List[str] = Field(default_factory=list)
    governance_plan_hash: Optional[str] = None
    state_hash: Optional[str] = None
    evaluation_frame: Optional[EvaluationFrameResponse] = None


class ExecutionPlanLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: Optional[str] = None
    ocgg_identity: str
    build_sot_hash: str = Field(min_length=1)
    execution_plan_hash: str = Field(min_length=1)
    plan_hash: Optional[str] = None
    integration_plan_hash: Optional[str] = None
    operations: List[Any] = Field(default_factory=list)
    deployment_target: Optional[str] = None
    goal: Optional[str] = None
    context: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    uato: Optional[UatoHints] = None
    validation: Optional[ValidationControls] = None

    @model_validator(mode="before")
    @classmethod
    def _alias_integration_plan_hash(cls, values):
        if isinstance(values, dict):
            if values.get("integration_plan_hash"):
                values["plan_hash"] = values["integration_plan_hash"]
        return values


class ExecutionPlanLockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    build_sot_hash: str
    execution_plan_hash: str
    outcome: str
    reason_codes: List[str] = Field(default_factory=list)
    governance_plan_hash: Optional[str] = None
    governance_evaluation_id: Optional[str] = None
    continuity_id: Optional[str] = None
    state_hash: Optional[str] = None
    evaluation_frame: Optional[EvaluationFrameResponse] = None

