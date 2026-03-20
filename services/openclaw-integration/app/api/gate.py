"""POST /gate/evaluate, POST /gate/verify-token."""
from app.core.trace_id import normalize_trace_id
from app.gate.engine import GateEngine
from app.gate.models import GateDecisionResponse
from app.gate.token import verify_execution_token
from app.models import GateEvaluateRequest, VerifyTokenRequest, VerifyTokenResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCodes, invalid_payload
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.db.session import get_session

router = APIRouter()


@router.post("/evaluate", response_model=GateDecisionResponse)
async def evaluate_gate(
    body: GateEvaluateRequest,
    session: AsyncSession = Depends(get_session),
):
    if not body.ocgg_identity or body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "ocgg_identity must be W-OCGG or R-OCGG"})
    spec = body.to_payload()
    trace_id = normalize_trace_id(spec.pop("trace_id", None) if isinstance(spec, dict) else None)
    evaluation = GateEngine().evaluate(spec, body.ocgg_identity)
    d = evaluation.decision
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
