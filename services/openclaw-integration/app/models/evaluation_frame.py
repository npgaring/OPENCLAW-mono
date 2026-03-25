"""Public API models for the shared evaluation frame contract."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class InvariantCFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


class UatoFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)
    approval_required: bool = False


class InvariantEFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


class EvaluationFrameResponse(BaseModel):
    """
    Authoritative grouped representation of frame-level admissibility semantics for clients.

    Existing top-level response fields remain for backward compatibility.
    """

    model_config = ConfigDict(extra="forbid")

    shared_state_hash: Optional[str] = None
    frame_status: Optional[Literal["PASS", "APPROVAL_REQUIRED", "ESCALATED", "BLOCKED"]] = None
    reason_codes: list[str] = Field(default_factory=list)
    invariant_c_result: Optional[InvariantCFrameResult] = None
    uato_result: Optional[UatoFrameResult] = None
    invariant_e_result: Optional[InvariantEFrameResult] = None
    approval_required: bool = False
    approval_request_id: Optional[str] = None
    governance_reached: Optional[bool] = None
    dispatch_reached: Optional[bool] = None
