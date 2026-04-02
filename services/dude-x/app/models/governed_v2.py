"""Governed DUDE-X v2 API models (cognitive + compiler modes)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ArtifactStatus(str, Enum):
    draft = "draft"
    clarify_required = "clarify_required"
    blocked = "blocked"
    pending_sot_approval = "pending_sot_approval"
    locked = "locked"
    compiled = "compiled"
    submitted = "submitted"
    executed = "executed"


class CognitiveOutcome(str, Enum):
    PASS = "PASS"
    CLARIFY = "CLARIFY"
    BLOCK = "BLOCK"


class StageLinkage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    raw_intent_hash: Optional[str] = None
    build_sot_hash: Optional[str] = None
    governance_plan_hash: Optional[str] = None
    state_hash: Optional[str] = None
    execution_plan_hash: Optional[str] = None
    governance_evaluation_id: Optional[str] = None
    continuity_id: Optional[str] = None
    artifact_hash: Optional[str] = None


class SectionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str
    section: str
    objective: Optional[str] = None


class BuildSoTV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.0"] = "1.0"
    project_name: str = Field(min_length=1)
    site_purpose: str = Field(min_length=1)
    target_audience: list[str] = Field(default_factory=list)
    desired_tone: str = Field(min_length=1)
    page_list: list[str] = Field(default_factory=list)
    nav_structure: list[str] = Field(default_factory=list)
    section_definitions: list[SectionDefinition] = Field(default_factory=list)
    forms_ctas: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    brand_constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    deployment_target: Literal["preview", "production"] = "preview"
    acceptance_criteria: list[str] = Field(default_factory=list)
    content_blocks: dict[str, list[str]] = Field(default_factory=dict)
    unresolved_items: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    status: ArtifactStatus = ArtifactStatus.draft
    approval_required: bool = True
    approval_status: Literal["NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED"] = "NOT_REQUESTED"
    extensions: dict[str, Any] = Field(default_factory=dict)


class RawIntentSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    idea: Optional[str] = None
    voice: Optional[str] = None
    brief: Optional[dict[str, Any]] = None
    ocgg_identity: Literal["W-OCGG", "R-OCGG"] = "W-OCGG"
    intent: Literal["web-build", "web-maintenance", "recruiting-update"] = "web-build"
    deployment_target: Optional[Literal["preview", "production"]] = None
    trace_id: Optional[str] = None
    clarifications: Optional[dict[str, Any]] = None


class BuildSoTRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class BuildSoTApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    approver_id: str = Field(min_length=1)
    comment: Optional[str] = None


class BuildSoTGovernanceEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocgg_identity: Literal["W-OCGG", "R-OCGG"] = "W-OCGG"
    intent: Literal["web-build", "web-maintenance", "recruiting-update"] = "web-build"
    trace_id: Optional[str] = None


class BuildSoTEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_linkage: StageLinkage
    build_sot: BuildSoTV1
    cognitive_outcome: CognitiveOutcome


class BuildSoTGovernanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_sot_hash: str
    trace_id: str
    outcome: Literal["PASS", "CLARIFY", "REFORM", "BLOCK"]
    reason_codes: list[str] = Field(default_factory=list)
    governance_projection: dict[str, Any] = Field(default_factory=dict)
    evaluation_frame: Optional[dict[str, Any]] = None
    governance_plan_hash: Optional[str] = None
    state_hash: Optional[str] = None


class ExecutionPlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    command: Optional[str] = None
    target: Optional[str] = None


class ExecutionPlanV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    plan_version: Literal["2.0"] = "2.0"
    execution_mode: Literal["deterministic_web_v1"] = "deterministic_web_v1"
    template_family: str
    scaffold_type: str
    framework: str
    routes: list[str] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)
    file_tree: list[str] = Field(default_factory=list)
    content_blocks: dict[str, list[str]] = Field(default_factory=dict)
    schema_blocks: list[dict[str, Any]] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    env_vars: list[str] = Field(default_factory=list)
    commands: list[ExecutionPlanCommand] = Field(default_factory=list)
    smoke_expectations: list[str] = Field(default_factory=list)
    deploy_target: Literal["preview", "production"] = "preview"
    rollback_strategy: dict[str, Any] = Field(default_factory=dict)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    governance_projection: dict[str, Any] = Field(default_factory=dict)
    stage_linkage: StageLinkage
    status: ArtifactStatus = ArtifactStatus.compiled

