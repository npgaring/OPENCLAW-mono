"""Governed dual-engine v2 lock endpoints."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
from app.services.deployment_tracker import (
    get_deployment_by_id,
    get_deployment_for_task,
    get_deployments_for_trace,
    list_all_deployments,
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


class DeploymentResponse(BaseModel):
    id: str
    trace_id: str
    task_id: Optional[str] = None
    build_sot_hash: Optional[str] = None
    execution_plan_hash: Optional[str] = None
    project_name: str
    github_owner: Optional[str] = None
    github_repo_name: Optional[str] = None
    github_repo_url: Optional[str] = None
    github_branch: Optional[str] = None
    github_commit_sha: Optional[str] = None
    vercel_project_id: Optional[str] = None
    vercel_project_name: Optional[str] = None
    vercel_deployment_id: Optional[str] = None
    vercel_deployment_url: Optional[str] = None
    vercel_preview_url: Optional[str] = None
    vercel_deploy_target: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    build_logs: Optional[str] = None
    fix_attempts: int = 0
    vercel_ready_state: Optional[str] = None
    created_at: str
    updated_at: str


def _deployment_to_response(rec: Any) -> DeploymentResponse:
    return DeploymentResponse(
        id=rec.id,
        trace_id=rec.trace_id,
        task_id=rec.task_id,
        build_sot_hash=rec.build_sot_hash,
        execution_plan_hash=rec.execution_plan_hash,
        project_name=rec.project_name,
        github_owner=rec.github_owner,
        github_repo_name=rec.github_repo_name,
        github_repo_url=rec.github_repo_url,
        github_branch=rec.github_branch,
        github_commit_sha=rec.github_commit_sha,
        vercel_project_id=rec.vercel_project_id,
        vercel_project_name=rec.vercel_project_name,
        vercel_deployment_id=rec.vercel_deployment_id,
        vercel_deployment_url=rec.vercel_deployment_url,
        vercel_preview_url=rec.vercel_preview_url,
        vercel_deploy_target=rec.vercel_deploy_target,
        status=rec.status,
        error_message=rec.error_message,
        build_logs=getattr(rec, "build_logs", None),
        fix_attempts=getattr(rec, "fix_attempts", 0) or 0,
        vercel_ready_state=getattr(rec, "vercel_ready_state", None),
        created_at=rec.created_at.isoformat() if rec.created_at else "",
        updated_at=rec.updated_at.isoformat() if rec.updated_at else "",
    )


@router.get("/deployments", response_model=list[DeploymentResponse])
async def list_deployments(
    trace_id: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id query parameter is required")
    records = await get_deployments_for_trace(session, trace_id)
    return [_deployment_to_response(r) for r in records]


@router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
):
    rec = await get_deployment_by_id(session, deployment_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _deployment_to_response(rec)


@router.get("/deployments/by-task/{task_id}", response_model=DeploymentResponse)
async def get_deployment_by_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    rec = await get_deployment_for_task(session, task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No deployment found for this task")
    return _deployment_to_response(rec)


@router.get("/projects", response_model=list[DeploymentResponse])
async def list_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List all deployments (acts as project history), newest first."""
    records = await list_all_deployments(session, limit=limit, offset=offset)
    return [_deployment_to_response(r) for r in records]


class RetriggerResponse(BaseModel):
    status: str
    message: str
    new_deployment_id: Optional[str] = None
    deployment_url: Optional[str] = None


@router.post("/deployments/{deployment_id}/retrigger", response_model=RetriggerResponse)
async def retrigger_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Re-deploy an existing deployment by re-triggering the Vercel file upload."""
    import httpx
    from app.services.deterministic_executor import (
        DeterministicWebExecutor,
        GeneratedFile,
        VERCEL_TIMEOUT_SECONDS,
        VERCEL_API_BASE,
    )

    rec = await get_deployment_by_id(session, deployment_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    vercel_token = (settings.vercel_token or "").strip()
    if not vercel_token:
        raise HTTPException(status_code=500, detail="Vercel token not configured")

    executor = DeterministicWebExecutor()

    try:
        async with httpx.AsyncClient(timeout=VERCEL_TIMEOUT_SECONDS) as vc_client:
            team_id = ""
            headers = {"Authorization": f"Bearer {vercel_token}"}
            resp, data = await executor._request(
                vc_client, "GET",
                f"{VERCEL_API_BASE}/v9/projects/{rec.vercel_project_name or rec.project_name}",
                headers=headers, params={"teamId": team_id} if team_id else None,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not resolve Vercel project: {resp.status_code}",
                )

            vercel_project_id = data.get("id", "")

            redeploy_resp, redeploy_data = await executor._request(
                vc_client, "POST",
                f"{VERCEL_API_BASE}/v13/deployments",
                headers=headers,
                params={"teamId": team_id} if team_id else None,
                payload={
                    "name": rec.vercel_project_name or rec.project_name,
                    "project": vercel_project_id,
                    "target": rec.vercel_deploy_target if rec.vercel_deploy_target in ("production", "staging") else "production",
                    "gitSource": {
                        "type": "github",
                        "org": rec.github_owner,
                        "repo": rec.github_repo_name,
                        "ref": rec.github_branch or "main",
                    },
                },
            )

            if redeploy_resp.status_code not in (200, 201):
                vercel_err = redeploy_data if isinstance(redeploy_data, dict) else {}
                logger.error("retrigger_deployment.vercel_error status=%s body=%s",
                             redeploy_resp.status_code, vercel_err)
                raise HTTPException(
                    status_code=502,
                    detail=f"Vercel re-deploy failed ({redeploy_resp.status_code}): "
                           f"{vercel_err.get('error', {}).get('message', redeploy_data)}",
                )

            new_deployment_id = redeploy_data.get("id", "")
            new_url = redeploy_data.get("url", "")
            if new_url and not new_url.startswith("http"):
                new_url = f"https://{new_url}"

            from app.services.deployment_tracker import record_deployment
            await record_deployment(
                session,
                result={
                    "status": "pending",
                    "message": f"Retriggered from {deployment_id}",
                    "deployment_url": new_url,
                    "deployment_id": new_deployment_id,
                    "repository_url": rec.github_repo_url,
                    "provider_ids": {"vercel_project_id": vercel_project_id},
                },
                task_id=rec.task_id or "",
                trace_id=rec.trace_id,
                project_name=rec.project_name,
            )
            await session.commit()

            return RetriggerResponse(
                status="triggered",
                message=f"Re-deployment triggered from {deployment_id}",
                new_deployment_id=new_deployment_id,
                deployment_url=new_url,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("retrigger_deployment.error deployment_id=%s", deployment_id)
        raise HTTPException(status_code=500, detail=str(exc))
