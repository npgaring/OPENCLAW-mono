"""Gate outcome and evaluation models."""
from dataclasses import dataclass
from enum import Enum
from typing import Any

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
    field: str | None
    message: str


@dataclass
class GateDecision:
    outcome: GateOutcome
    reason_codes: list[str]
    defect_list: list[Defect]
    policy_version: str
    spec_hash: str
    plan_hash: str
    approver_id: str | None
    execution_token: str | None = None


@dataclass
class GateEvaluation:
    decision: GateDecision
    plan_json: dict[str, Any]
    spec_hash: str
    plan_hash: str


class GateDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_codes: list[str] = []
    defect_list: list[dict[str, Any]] = []
    policy_version: str
    spec_hash: str
    plan_hash: str
    approver_id: str | None = None
    execution_token: str | None = None
