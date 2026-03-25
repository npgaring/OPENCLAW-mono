"""Map internal frame objects into public API response contracts."""
from __future__ import annotations

from typing import Optional

from app.evaluation_frame.state import CompositeFrameResult
from app.models.evaluation_frame import (
    EvaluationFrameResponse,
    InvariantCFrameResult,
    InvariantEFrameResult,
    UatoFrameResult,
)


def to_evaluation_frame_response(
    frame: CompositeFrameResult,
    *,
    approval_request_id: Optional[str] = None,
    governance_reached: Optional[bool] = None,
    dispatch_reached: Optional[bool] = None,
) -> EvaluationFrameResponse:
    return EvaluationFrameResponse(
        shared_state_hash=frame.shared_state_hash,
        frame_status=frame.frame_status.value,
        reason_codes=list(frame.reason_codes),
        invariant_c_result=InvariantCFrameResult(
            decision=frame.invariant_c_result.decision,
            reason_codes=list(frame.invariant_c_result.reason_codes),
        ),
        uato_result=UatoFrameResult(
            decision=frame.uato_result.decision,
            reason_codes=list(frame.uato_result.reason_codes),
            approval_required=frame.uato_result.decision == "REQUIRE_APPROVAL",
        ),
        invariant_e_result=InvariantEFrameResult(
            decision=frame.invariant_e_result.decision,
            reason_codes=list(frame.invariant_e_result.reason_codes),
        ),
        approval_required=frame.approval_required,
        approval_request_id=approval_request_id,
        governance_reached=governance_reached,
        dispatch_reached=dispatch_reached,
    )
