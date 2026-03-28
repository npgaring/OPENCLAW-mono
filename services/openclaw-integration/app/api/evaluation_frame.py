"""POST /evaluation-frame/evaluate — full atomic evaluation; response filters to frame-shaped JSON."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.trace_id import normalize_trace_id
from app.evaluation.aggregator import composite_frame_from_atomic
from app.evaluation.builder import build_evaluation_state_from_shared_governable
from app.evaluation.engine import default_engine
from app.evaluation_frame import build_shared_governable_state_for_gate_payload
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.models import EvaluationFrameResponse, GateEvaluateRequest
from app.uato.normalize import minimal_plan_admissibility_issues

router = APIRouter()


@router.post(
    "/evaluate",
    response_model=EvaluationFrameResponse,
    summary="Preview evaluation (full atomic cycle; response shows frame-oriented fields)",
)
async def evaluate_frame(
    body: GateEvaluateRequest,
):
    """
    Runs the same ``EvaluationEngine.evaluate`` as /gate and /task (C, UATO, GRL, Invariant-E decision).

    The JSON contract remains the pre-governance *shape* (no gate outcome fields). ``frame_status`` follows
    authoritative ``final_decision`` (and presentation may map UATO escalation to the string ``ESCALATED``).
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
    ev_state = build_evaluation_state_from_shared_governable(shared)
    atomic = default_engine.evaluate(ev_state)
    frame = composite_frame_from_atomic(atomic)
    return to_evaluation_frame_response(
        frame,
        governance_reached=False,
        dispatch_reached=False,
        state_hash=ev_state.state_hash,
        atomic=atomic,
    )
