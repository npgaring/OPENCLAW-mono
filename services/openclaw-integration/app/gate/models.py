"""Gate outcome and evaluation models."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.evaluation_frame import EvaluationFrameResponse


class GateOutcome(str, Enum):
    PASS = "PASS"
    REFORM = "REFORM"
    CLARIFY = "CLARIFY"
    BLOCK = "BLOCK"


# Priority (worst wins): BLOCK=3, CLARIFY=2, REFORM=1, PASS=0
OUTCOME_PRIORITY = {GateOutcome.BLOCK: 3, GateOutcome.CLARIFY: 2, GateOutcome.REFORM: 1, GateOutcome.PASS: 0}


@dataclass
class Defect:
    code: str
    field: Optional[str]
    message: str


@dataclass
class GateDecision:
    outcome: GateOutcome
    reason_codes: List[str]
    defect_list: List[Defect]
    policy_version: str
    spec_hash: str
    plan_hash: str
    approver_id: Optional[str]
    execution_token: Optional[str] = None


@dataclass
class GateEvaluation:
    decision: GateDecision
    plan_json: dict[str, Any]
    spec_hash: str
    plan_hash: str


class GateDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_codes: List[str] = []
    defect_list: List[dict] = []
    policy_version: str
    spec_hash: str
    plan_hash: str
    approver_id: Optional[str] = None
    execution_token: Optional[str] = None
    trace_id: Optional[str] = None
    uato_decision: Optional[str] = None
    uato_reason_codes: List[str] = []
    uato_skipped_gate: bool = False
    # PROD_DEPLOY_NO_APPROVAL: same durable materialization as POST /task (task + GOVERNANCE approval_requests).
    task_id: Optional[UUID] = Field(
        default=None,
        description="Integration task row created or updated for this trace when PROD_DEPLOY_NO_APPROVAL is materialized.",
    )
    approval_request_id: Optional[UUID] = Field(
        default=None,
        description="PENDING GOVERNANCE approval when outcome is BLOCK for PROD_DEPLOY_NO_APPROVAL; use with POST /approvals/{id}/approve then resume.",
    )
    approval_status: Optional[str] = Field(
        default=None,
        description="e.g. PENDING when approval_request_id is set; null when no durable approval row for this response.",
    )
    approval_required: Optional[bool] = Field(
        default=None,
        description="True when a GOVERNANCE prod-deploy approval row exists for this evaluation.",
    )
    resume_available: Optional[bool] = Field(
        default=None,
        description="True when approval can be resumed via POST /approvals/{id}/resume after approve.",
    )
    source_layer: Optional[str] = Field(
        default=None,
        description="GOVERNANCE when approval_request_id refers to prod deploy governance stop.",
    )
    evaluation_frame: Optional[EvaluationFrameResponse] = Field(
        default=None,
        description="Authoritative grouped frame-level admissibility result available before governance evaluation.",
    )
