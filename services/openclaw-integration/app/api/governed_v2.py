"""Governed dual-engine v2 lock endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.trace_id import normalize_trace_id
from app.db.session import get_session
from app.evaluation import build_evaluation_state_from_shared_governable, default_engine
from app.evaluation.aggregator import composite_frame_from_atomic, stop_reason_codes_for_api
from app.evaluation.models import AtomicFinalDecision
from app.evaluation_frame import build_shared_governable_state_for_gate_payload
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.models.governed_v2 import (
    BuildSoTLockRequest,
    BuildSoTLockResponse,
    ExecutionPlanLockRequest,
    ExecutionPlanLockResponse,
)
from app.services.governed_v2_continuity import (
    continuity_id_for_lock,
    upsert_execution_plan_lock,
)
from app.services.task_submission import make_governance_evaluation_id
from app.uato.normalize import minimal_plan_admissibility_issues

router = APIRouter(prefix="/v2", tags=["governed-v2"])
logger = logging.getLogger(__name__)


def _trace(event: str, **fields: object) -> None:
    if settings.governed_v2_trace_logging:
        payload = {k: v for k, v in fields.items() if v is not None}
        logger.info("governed_v2.%s %s", event, payload)


def _ensure_v2_enabled() -> None:
    if not settings.governed_v2_enabled:
        raise HTTPException(
            status_code=404,
            detail={"code": "GOVERNED_V2_DISABLED", "message": "Governed v2 endpoints are disabled."},
        )


def _projection_spec_from_request(req: BuildSoTLockRequest) -> dict:
    spec = dict(req.governance_projection or {})
    spec["ocgg_identity"] = req.ocgg_identity
    return spec


def _spec_from_execution_plan_request(req: ExecutionPlanLockRequest) -> dict:
    spec = {
        "ocgg_identity": req.ocgg_identity,
        "plan_hash": req.plan_hash or "",
        "operations": req.operations,
        "deployment_target": req.deployment_target,
        "goal": req.goal,
        "context": req.context,
        "acceptance_criteria": req.acceptance_criteria,
    }
    return {k: v for k, v in spec.items() if v is not None}


def _to_outcome(final_decision: AtomicFinalDecision) -> str:
    if final_decision == AtomicFinalDecision.EXECUTE:
        return "PASS"
    if final_decision == AtomicFinalDecision.REQUIRE_APPROVAL:
        return "CLARIFY"
    return "BLOCK"


@router.post("/build-sot/lock", response_model=BuildSoTLockResponse)
async def lock_build_sot(
    body: BuildSoTLockRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace(
        "build_sot.lock.start",
        trace_id=body.trace_id,
        build_sot_hash=body.build_sot_hash,
        ocgg_identity=body.ocgg_identity,
        intent=body.intent,
    )
    if body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "ocgg_identity must be W-OCGG or R-OCGG"},
        )
    spec = _projection_spec_from_request(body)
    trace_id = normalize_trace_id(body.trace_id)
    if minimal_plan_admissibility_issues(spec):
        _trace(
            "build_sot.lock.blocked",
            trace_id=trace_id,
            build_sot_hash=body.build_sot_hash,
            reason_codes=list(minimal_plan_admissibility_issues(spec)),
        )
        return BuildSoTLockResponse(
            trace_id=trace_id,
            build_sot_hash=body.build_sot_hash,
            outcome="BLOCK",
            reason_codes=list(minimal_plan_admissibility_issues(spec)),
            governance_plan_hash=spec.get("plan_hash"),
            state_hash=None,
            evaluation_frame=None,
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
    _trace(
        "build_sot.lock.done",
        trace_id=trace_id,
        build_sot_hash=body.build_sot_hash,
        outcome=_to_outcome(atomic.final_decision),
        state_hash=ev_state.state_hash,
        reason_codes=stop_reason_codes_for_api(atomic),
    )
    return BuildSoTLockResponse(
        trace_id=trace_id,
        build_sot_hash=body.build_sot_hash,
        outcome=_to_outcome(atomic.final_decision),
        reason_codes=stop_reason_codes_for_api(atomic),
        governance_plan_hash=shared.plan_hash,
        state_hash=ev_state.state_hash,
        evaluation_frame=to_evaluation_frame_response(
            frame,
            governance_reached=False,
            dispatch_reached=False,
            state_hash=ev_state.state_hash,
            atomic=atomic,
        ),
    )


@router.post("/execution-plan/lock", response_model=ExecutionPlanLockResponse)
async def lock_execution_plan(
    body: ExecutionPlanLockRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace(
        "execution_plan.lock.start",
        trace_id=body.trace_id,
        build_sot_hash=body.build_sot_hash,
        execution_plan_hash=body.execution_plan_hash,
        ocgg_identity=body.ocgg_identity,
    )
    if body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "ocgg_identity must be W-OCGG or R-OCGG"},
        )
    spec = _spec_from_execution_plan_request(body)
    trace_id = normalize_trace_id(body.trace_id)
    if minimal_plan_admissibility_issues(spec):
        _trace(
            "execution_plan.lock.blocked",
            trace_id=trace_id,
            build_sot_hash=body.build_sot_hash,
            execution_plan_hash=body.execution_plan_hash,
            reason_codes=list(minimal_plan_admissibility_issues(spec)),
        )
        return ExecutionPlanLockResponse(
            trace_id=trace_id,
            build_sot_hash=body.build_sot_hash,
            execution_plan_hash=body.execution_plan_hash,
            outcome="BLOCK",
            reason_codes=list(minimal_plan_admissibility_issues(spec)),
            governance_plan_hash=spec.get("plan_hash"),
            governance_evaluation_id=None,
            continuity_id=None,
            state_hash=None,
            evaluation_frame=None,
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
    outcome = _to_outcome(atomic.final_decision)
    governance_evaluation_id = None
    continuity_id = None
    if atomic.final_decision == AtomicFinalDecision.EXECUTE:
        d = atomic.grl.decision
        governance_evaluation_id = make_governance_evaluation_id(
            state_hash=ev_state.state_hash,
            plan_hash=d.plan_hash,
            policy_version=d.policy_version,
            outcome=d.outcome.value,
            uato_decision=frame.uato_result.decision,
            reason_codes=list(d.reason_codes),
        )
        continuity_id = continuity_id_for_lock(
            trace_id=trace_id,
            ocgg_identity=body.ocgg_identity,
            build_sot_hash=body.build_sot_hash,
            execution_plan_hash=body.execution_plan_hash,
            plan_hash=shared.plan_hash,
            governance_evaluation_id=governance_evaluation_id,
            state_hash=ev_state.state_hash,
        )
        await upsert_execution_plan_lock(
            session,
            continuity_id=continuity_id,
            trace_id=trace_id,
            ocgg_identity=body.ocgg_identity,
            build_sot_hash=body.build_sot_hash,
            execution_plan_hash=body.execution_plan_hash,
            plan_hash=shared.plan_hash,
            governance_evaluation_id=governance_evaluation_id,
            state_hash=ev_state.state_hash,
        )
        await session.commit()
        _trace(
            "execution_plan.lock.continuity_created",
            trace_id=trace_id,
            build_sot_hash=body.build_sot_hash,
            execution_plan_hash=body.execution_plan_hash,
            governance_evaluation_id=governance_evaluation_id,
            continuity_id=continuity_id,
        )
    _trace(
        "execution_plan.lock.done",
        trace_id=trace_id,
        build_sot_hash=body.build_sot_hash,
        execution_plan_hash=body.execution_plan_hash,
        outcome=outcome,
        state_hash=ev_state.state_hash,
        governance_plan_hash=shared.plan_hash,
        reason_codes=stop_reason_codes_for_api(atomic),
    )
    return ExecutionPlanLockResponse(
        trace_id=trace_id,
        build_sot_hash=body.build_sot_hash,
        execution_plan_hash=body.execution_plan_hash,
        outcome=outcome,
        reason_codes=stop_reason_codes_for_api(atomic),
        governance_plan_hash=shared.plan_hash,
        governance_evaluation_id=governance_evaluation_id,
        continuity_id=continuity_id,
        state_hash=ev_state.state_hash,
        evaluation_frame=to_evaluation_frame_response(
            frame,
            governance_reached=False,
            dispatch_reached=False,
            state_hash=ev_state.state_hash,
            atomic=atomic,
        ),
    )
