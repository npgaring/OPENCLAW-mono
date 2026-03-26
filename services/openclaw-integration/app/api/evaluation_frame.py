"""POST /evaluation-frame/evaluate — side-effect-free shared frame preview."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.trace_id import normalize_trace_id
from app.evaluation_frame import build_shared_governable_state_for_gate_payload, run_evaluation_frame
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.models import EvaluationFrameResponse, GateEvaluateRequest
from app.uato.normalize import minimal_plan_admissibility_issues

router = APIRouter()


@router.post(
    "/evaluate",
    response_model=EvaluationFrameResponse,
    summary="Preview shared evaluation frame (Invariant-C + UATO + Invariant-E)",
)
async def evaluate_frame(
    body: GateEvaluateRequest,
):
    """
    Read-only frame preview over governable payload.

    This endpoint is intentionally pre-governance and pre-dispatch:
    - does not call GateEngine
    - does not create tasks or approvals
    - does not mint tokens or dispatch execution
    """
    if not body.ocgg_identity or body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail={
                "code": ErrorCodes.INVALID_PAYLOAD,
                "message": "ocgg_identity must be W-OCGG or R-OCGG",
            },
        )
    spec = body.to_payload()
    trace_id = normalize_trace_id(spec.pop("trace_id", None) if isinstance(spec, dict) else None)
    if isinstance(spec, dict):
        spec.pop("uato", None)
        spec.pop("validation", None)
    if not isinstance(spec, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "Invalid evaluation frame payload"},
        )
    if minimal_plan_admissibility_issues(spec):
        raise HTTPException(
            status_code=422,
            detail={
                "code": ErrorCodes.INVALID_PAYLOAD,
                "message": "Payload is not governable as a shared frame input.",
                "reason_codes": list(minimal_plan_admissibility_issues(spec)),
            },
        )
    try:
        shared = build_shared_governable_state_for_gate_payload(
            spec,
            body.ocgg_identity,
            trace_id,
            body.uato,
            body.validation,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": str(e)})
    frame = run_evaluation_frame(shared)
    return to_evaluation_frame_response(
        frame,
        governance_reached=False,
        dispatch_reached=False,
    )
