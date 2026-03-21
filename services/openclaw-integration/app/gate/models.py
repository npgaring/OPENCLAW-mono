"""Gate outcome and evaluation models."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


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
