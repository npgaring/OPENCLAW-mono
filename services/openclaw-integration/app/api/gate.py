"""POST /gate/evaluate, POST /gate/verify-token."""
from datetime import datetime

from app.core.trace_id import normalize_trace_id
from app.evaluation_frame import build_shared_governable_state_for_gate_payload, run_evaluation_frame
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.evaluation_frame.state import FrameStatus
from app.gate.engine import GateEngine
from app.gate.models import GateDecisionResponse
from app.gate.token import verify_execution_token
from app.invariant_e import build_execution_envelope, to_trace_record as ie_to_trace
from app.models import GateEvaluateRequest, TaskSubmitRequest, VerifyTokenRequest, VerifyTokenResponse
from app.services.task_submission import materialize_governance_prod_deploy_stop
from app.uato import build_uato_input_from_spec, evaluate_uato, to_trace_record
from app.uato.normalize import minimal_plan_admissibility_issues
from app.uato.plan_bridge import integration_plan_preview
from app.uato.types import UATO_DECISION_VERSION
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.db.session import get_session
from app.models.evaluation_frame import EvaluationFrameResponse, UatoFrameResult

router = APIRouter()


@router.post(
    "/evaluate",
    response_model=GateDecisionResponse,
    summary="UATO + GateEngine evaluation; durable prod-deploy approval when applicable",
    openapi_extra={
        "responses": {
            "200": {
                "description": (
                    "Gate decision. After UATO PASS, if the engine blocks with PROD_DEPLOY_NO_APPROVAL, the service "
                    "persists the same task + gate_decisions + PENDING GOVERNANCE approval_requests row as POST /task "
                    "(same trace_id, idempotent on trace + checkpoint snapshot). Response includes task_id, "
                    "approval_request_id, approval_status. Other BLOCK outcomes do not create approval rows here; "
                    "clients must not assume GET /approvals?trace_id= is populated until POST /task for those cases."
                ),
            },
        },
    },
)
async def evaluate_gate(
    body: GateEvaluateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Dry-run governance + UATO for a plan-shaped payload.

    ADR: docs/adr/001-gate-evaluate-prod-deploy-approval.md

    PROD_DEPLOY_NO_APPROVAL: this endpoint is *not* a pure no-side-effect dry-run for that outcome.
    We persist the same Task + gate_decisions + approval_requests (GOVERNANCE, PENDING) as POST /task,
    keyed by (trace_id, resume checkpoint hash) so GET /approvals?trace_id= works before POST /task and
    POST /task with the same body+trace is idempotent (no second approval row).
    Other BLOCK reasons do not create approval rows unless/until POST /task runs.
    """
    if not body.ocgg_identity or body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "ocgg_identity must be W-OCGG or R-OCGG"})
    spec = body.to_payload()
    trace_id = normalize_trace_id(spec.pop("trace_id", None) if isinstance(spec, dict) else None)
    if isinstance(spec, dict):
        spec.pop("uato", None)

    if not isinstance(spec, dict):
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "Invalid gate payload"})

    if minimal_plan_admissibility_issues(spec):
        uato_in_pf = build_uato_input_from_spec(
            spec,
            ocgg_identity=body.ocgg_identity,
            trace_id=trace_id,
            uato_hints=body.uato,
        )
        uato_res_pf = evaluate_uato(uato_in_pf)
        _, plan_hash_pf, spec_hash_pf = integration_plan_preview(spec, body.ocgg_identity)
        return GateDecisionResponse(
            outcome="BLOCK",
            reason_codes=list(uato_res_pf.reason_codes),
            defect_list=[],
            policy_version=UATO_DECISION_VERSION,
            spec_hash=spec_hash_pf,
            plan_hash=plan_hash_pf,
            approver_id=None,
            execution_token=None,
            trace_id=trace_id,
            uato_decision=uato_res_pf.decision,
            uato_reason_codes=list(uato_res_pf.reason_codes),
            uato_skipped_gate=True,
            evaluation_frame=EvaluationFrameResponse(
                frame_status=None,
                reason_codes=list(uato_res_pf.reason_codes),
                uato_result=UatoFrameResult(
                    decision=uato_res_pf.decision,
                    reason_codes=list(uato_res_pf.reason_codes),
                    approval_required=uato_res_pf.decision == "REQUIRE_APPROVAL",
                ),
                approval_required=uato_res_pf.decision == "REQUIRE_APPROVAL",
                governance_reached=False,
                dispatch_reached=False,
            ),
        )

    try:
        shared = build_shared_governable_state_for_gate_payload(spec, body.ocgg_identity, trace_id, body.uato)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": str(e)})

    frame = run_evaluation_frame(shared)
    uato_in = build_uato_input_from_spec(
        shared.spec_for_gate,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        uato_hints=body.uato,
    )
    uato_res = frame.uato_result
    if frame.frame_status != FrameStatus.PASS:
        return GateDecisionResponse(
            outcome="BLOCK",
            reason_codes=list(frame.reason_codes),
            defect_list=[],
            policy_version=UATO_DECISION_VERSION,
            spec_hash=shared.spec_hash,
            plan_hash=shared.plan_hash,
            approver_id=None,
            execution_token=None,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_skipped_gate=True,
            evaluation_frame=to_evaluation_frame_response(
                frame,
                governance_reached=False,
                dispatch_reached=False,
            ),
        )

    evaluation = GateEngine().evaluate(spec, body.ocgg_identity)
    d = evaluation.decision
    approval_extras: dict = {}
    if d.outcome.value == "BLOCK" and "PROD_DEPLOY_NO_APPROVAL" in d.reason_codes:
        uato_evaluated_at = datetime.utcnow()
        uato_trace = to_trace_record(uato_in, uato_res)
        ie_env_frame = build_execution_envelope(
            spec=shared.spec_for_gate,
            ocgg_identity=body.ocgg_identity,
            trace_id=trace_id,
            task_id=None,
            governance_outcome="PENDING",
            plan_hash=shared.plan_hash,
            spec_hash=shared.spec_hash,
        )
        ie_frame_trace = ie_to_trace(ie_env_frame, frame.invariant_e_result)
        gate_payload = body.model_dump(exclude_none=True)
        gate_payload["trace_id"] = trace_id
        task_body = TaskSubmitRequest.model_validate(gate_payload)
        task, ar = await materialize_governance_prod_deploy_stop(
            session,
            task_body,
            trace_id,
            uato_in=uato_in,
            uato_res=uato_res,
            uato_evaluated_at=uato_evaluated_at,
            uato_trace=uato_trace,
            evaluation=evaluation,
            frame_shared_state_hash=frame.shared_state_hash,
            ic_res=frame.invariant_c_result,
            ie_frame_trace=ie_frame_trace,
        )
        approval_extras = {
            "task_id": task.task_id,
            "approval_request_id": ar.id,
            "approval_status": "PENDING",
            "approval_required": True,
            "resume_available": True,
            "source_layer": "GOVERNANCE",
        }
    return GateDecisionResponse(
        outcome=d.outcome.value,
        reason_codes=d.reason_codes,
        defect_list=[{"code": x.code, "field": x.field, "message": x.message} for x in d.defect_list],
        policy_version=d.policy_version,
        spec_hash=d.spec_hash,
        plan_hash=d.plan_hash,
        approver_id=d.approver_id,
        execution_token=d.execution_token,
        trace_id=trace_id,
        uato_decision="PASS",
        uato_reason_codes=list(uato_res.reason_codes),
        uato_skipped_gate=False,
        evaluation_frame=to_evaluation_frame_response(
            frame,
            governance_reached=True,
            dispatch_reached=False,
        ),
        **approval_extras,
    )


@router.post("/verify-token", response_model=VerifyTokenResponse)
async def verify_token_tenant(
    body: VerifyTokenRequest,
    session: AsyncSession = Depends(get_session),
):
    verified, payload = verify_execution_token(body.execution_token)
    if not verified or not payload:
        return VerifyTokenResponse(
            token_verified=False,
            tenant_context=body.tenant_context,
            token_tenant=None,
            result="BLOCK",
            reason="TOKEN_INVALID",
        )
    token_tenant = payload.get("ocgg_identity") or payload.get("tenant_id")
    if token_tenant != body.tenant_context:
        return VerifyTokenResponse(
            token_verified=True,
            tenant_context=body.tenant_context,
            token_tenant=token_tenant,
            result="BLOCK",
            reason="TOKEN_TENANT_MISMATCH",
        )
    return VerifyTokenResponse(
        execution_id=payload.get("execution_id"),
        token_verified=True,
        tenant_context=body.tenant_context,
        token_tenant=token_tenant,
        result="PASS",
        reason=None,
    )
