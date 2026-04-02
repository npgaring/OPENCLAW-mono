"""OpenAI Vessel + Invariant-C + Substrate Adapter API models."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.evaluation_frame import EvaluationFrameResponse
from app.models.task import UatoHints


class StepType(str, Enum):
    create_file = "create_file"
    write_config = "write_config"
    build = "build"
    deploy = "deploy"
    test = "test"
    rollback_prep = "rollback_prep"
    provision_repo = "provision_repo"
    provision_hosting = "provision_hosting"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class DependsOnInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depends_on: list[str] = Field(default_factory=list)


class CreateFileInputs(DependsOnInputs):
    path: str = Field(min_length=1)
    content: str = Field(min_length=1)


class WriteConfigInputs(DependsOnInputs):
    path: str = Field(min_length=1)
    content: Optional[str] = None


class BuildInputs(DependsOnInputs):
    command: Optional[str] = None


class DeployInputs(DependsOnInputs):
    provider: str = Field(min_length=1)
    project: str = Field(min_length=1)


class TestInputs(DependsOnInputs):
    command: Optional[str] = None


class RollbackPrepInputs(DependsOnInputs):
    artifact: Optional[str] = None
    strategy: Optional[str] = None


class ProvisionRepoInputs(DependsOnInputs):
    provider: str = Field(min_length=1)


class ProvisionHostingInputs(DependsOnInputs):
    provider: str = Field(min_length=1)
    project: Optional[str] = None


BoundedStepInputs = Union[
    CreateFileInputs,
    WriteConfigInputs,
    BuildInputs,
    DeployInputs,
    TestInputs,
    RollbackPrepInputs,
    ProvisionRepoInputs,
    ProvisionHostingInputs,
]


class CandidatePlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: StepType
    action: StepType
    target: str = Field(min_length=1)
    inputs: BoundedStepInputs

    @model_validator(mode="before")
    @classmethod
    def _coerce_inputs_for_type(cls, data: Any):
        if not isinstance(data, dict):
            return data
        step_type_raw = data.get("type")
        inputs_raw = data.get("inputs")
        if not isinstance(step_type_raw, str) or not isinstance(inputs_raw, dict):
            return data
        expected_by_type: dict[str, type[BaseModel]] = {
            StepType.create_file.value: CreateFileInputs,
            StepType.write_config.value: WriteConfigInputs,
            StepType.build.value: BuildInputs,
            StepType.deploy.value: DeployInputs,
            StepType.test.value: TestInputs,
            StepType.rollback_prep.value: RollbackPrepInputs,
            StepType.provision_repo.value: ProvisionRepoInputs,
            StepType.provision_hosting.value: ProvisionHostingInputs,
        }
        expected_type = expected_by_type.get(step_type_raw)
        if expected_type is None:
            return data
        cloned = dict(data)
        cloned["inputs"] = expected_type.model_validate(inputs_raw)
        return cloned

    @model_validator(mode="after")
    def _action_mirrors_type(self):
        if self.action != self.type:
            raise ValueError("action must mirror type")
        expected_by_type: dict[StepType, type[BaseModel]] = {
            StepType.create_file: CreateFileInputs,
            StepType.write_config: WriteConfigInputs,
            StepType.build: BuildInputs,
            StepType.deploy: DeployInputs,
            StepType.test: TestInputs,
            StepType.rollback_prep: RollbackPrepInputs,
            StepType.provision_repo: ProvisionRepoInputs,
            StepType.provision_hosting: ProvisionHostingInputs,
        }
        expected_type = expected_by_type[self.type]
        if not isinstance(self.inputs, expected_type):
            raise ValueError(f"inputs must match bounded schema for {self.type.value}")
        return self


class CandidatePlanMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requiresApproval: bool
    riskLevel: RiskLevel


class CandidatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[CandidatePlanStep] = Field(min_length=1)
    metadata: CandidatePlanMetadata


class OpenAIPlanOutput(BaseModel):
    """Locked OpenAI vessel output contract."""

    model_config = ConfigDict(extra="forbid")

    candidate_plan: CandidatePlan


class OpenAIPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocgg_identity: Literal["W-OCGG", "R-OCGG"]
    intent: Literal["web-build", "web-maintenance", "recruiting-update"]
    deployment_target: Optional[str] = None
    objective: str = Field(min_length=1)
    context: Optional[str] = None
    constraints: Optional[dict[str, Any]] = None
    approval_reference: Optional[str] = None
    approver_id: Optional[str] = None
    trace_id: Optional[str] = None


class AdapterToSubstrateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocgg_identity: Literal["W-OCGG", "R-OCGG"]
    intent: Literal["web-build", "web-maintenance", "recruiting-update"]
    deployment_target: Optional[str] = None
    candidate_plan: CandidatePlan
    objective: Optional[str] = None
    context: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    constraints: Optional[dict[str, Any]] = None
    approval_reference: Optional[str] = None
    approver_id: Optional[str] = None
    trace_id: Optional[str] = None


class SubstrateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    type: StepType
    target: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class AdapterToSubstrateResponse(BaseModel):
    """
    Substrate payload for POST /task and /gate/evaluate.

    **governance_plan_hash** is the only hash that matches ``GateEngine`` / ``hash_payload({domain, operations})``.
    Use it as ``plan_hash`` (or ``integration_plan_hash``) on task/gate requests.

    **substrate_envelope_hash** (and deprecated **plan_hash**) fingerprint the full envelope document including
    ``plan_version`` and ``rollback`` — they must **not** be used as the governance ``plan_hash``.
    """

    model_config = ConfigDict(extra="forbid")

    plan_version: Literal["1.0"] = "1.0"
    identity: Literal["W-OCGG", "R-OCGG"]
    ocgg_identity: Literal["W-OCGG", "R-OCGG"]
    domain: Literal["web", "recruiting"]
    deployment_target: Optional[str] = None
    operations: list[SubstrateOperation]
    rollback: dict[str, Any] = Field(default_factory=dict)
    governance_plan_hash: str = Field(
        description="Canonical GateEngine plan hash; use as plan_hash for POST /task and POST /gate/evaluate.",
    )
    substrate_envelope_hash: str = Field(
        description="SHA256 of the full substrate envelope (plan_version, identity, domain, operations, rollback). Not valid for GateEngine plan_hash.",
    )
    integration_plan_hash: str = Field(
        deprecated=True,
        description="Deprecated alias of governance_plan_hash; identical value. Prefer governance_plan_hash.",
    )
    plan_hash: str = Field(
        deprecated=True,
        description="Deprecated alias of substrate_envelope_hash. Do not use as GateEngine plan_hash on /task.",
    )
    goal: Optional[str] = None
    context: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    approval_reference: Optional[str] = None
    approver_id: Optional[str] = None
    uato: Optional[UatoHints] = Field(
        default=None,
        description="System-derived UATO trust/authority hints from planner/adapter metadata for downstream frame parity.",
    )
    trace_id: str
    evaluation_frame: Optional[EvaluationFrameResponse] = Field(
        default=None,
        description="Authoritative grouped frame-level admissibility result for adapter conversion.",
    )
