"""DUDE-X governed dual-engine v2 endpoints."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload
from app.core.trace_id import normalize_trace_id
from app.db.session import get_session
from app.models.governed_v2 import (
    ArtifactStatus,
    BuildSoTApprovalRequest,
    BuildSoTEnvelope,
    BuildSoTGovernanceEvaluateRequest,
    BuildSoTGovernanceResult,
    BuildSoTRevisionRequest,
    BuildSoTV1,
    CognitiveOutcome,
    ExecutionPlanV1,
    RawIntentSubmitRequest,
    StageLinkage,
)
from app.models.governed_v2_db import (
    BuildSoTRecord,
    ExecutionPlanRecordV2,
    RawIntentRecord,
    StageEventRecordV2,
)
from app.services.governed_v2_runtime import (
    apply_build_sot_patch,
    compile_execution_plan,
    governance_projection_for_build_sot,
    run_cognitive_mode,
)

router = APIRouter(prefix="/v2", tags=["governed-v2"])
logger = logging.getLogger(__name__)


def _trace(event: str, **fields: Any) -> None:
    if settings.governed_v2_trace_logging:
        payload = {k: v for k, v in fields.items() if v is not None}
        logger.info("governed_v2.%s %s", event, payload)


def _ensure_v2_enabled() -> None:
    if not settings.dudex_v2_enabled:
        raise DUDEXError(
            ErrorCode.UNSUPPORTED_OPERATION,
            "DUDE-X v2 is disabled by feature flag",
            details={"flag": "DUDEX_V2_ENABLED"},
        )


def _build_sot_outcome(sot: BuildSoTV1) -> CognitiveOutcome:
    if sot.status == ArtifactStatus.blocked:
        return CognitiveOutcome.BLOCK
    if sot.status == ArtifactStatus.clarify_required:
        return CognitiveOutcome.CLARIFY
    return CognitiveOutcome.PASS


def _event(stage: str, event_type: str, status: str, trace_id: str, artifact_hash: str | None, metadata: dict[str, Any]) -> StageEventRecordV2:
    return StageEventRecordV2(
        trace_id=trace_id,
        stage=stage,
        event_type=event_type,
        status=status,
        artifact_hash=artifact_hash,
        metadata_=metadata,
    )


def _record_to_envelope(rec: BuildSoTRecord) -> BuildSoTEnvelope:
    build_sot = BuildSoTV1.model_validate(rec.payload)
    linkage = StageLinkage(
        trace_id=rec.trace_id,
        raw_intent_hash=rec.raw_intent_hash,
        build_sot_hash=rec.build_sot_hash,
        governance_plan_hash=rec.governance_plan_hash,
        state_hash=rec.governance_state_hash,
        artifact_hash=rec.build_sot_hash,
    )
    return BuildSoTEnvelope(
        stage_linkage=linkage,
        build_sot=build_sot,
        cognitive_outcome=_build_sot_outcome(build_sot),
    )


@router.post("/raw-intents", response_model=BuildSoTEnvelope)
async def submit_raw_intent(
    body: RawIntentSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    trace_id = normalize_trace_id(body.trace_id)
    _trace(
        "raw_intent.start",
        trace_id=trace_id,
        ocgg_identity=body.ocgg_identity,
        intent=body.intent,
        deployment_target=body.deployment_target,
    )
    result = run_cognitive_mode(body, trace_id)
    _trace(
        "raw_intent.cognitive_done",
        trace_id=trace_id,
        raw_intent_hash=result.raw_intent_hash,
        build_sot_hash=result.build_sot_hash,
        unresolved_count=len(result.build_sot.unresolved_items),
        contradictions_count=len(result.build_sot.contradictions),
        cognitive_outcome=result.cognitive_outcome.value,
    )
    existing_raw = await session.get(RawIntentRecord, result.raw_intent_hash)
    if existing_raw is None:
        session.add(
            RawIntentRecord(
                raw_intent_hash=result.raw_intent_hash,
                trace_id=trace_id,
                ocgg_identity=body.ocgg_identity,
                intent=body.intent,
                status=result.build_sot.status.value,
                payload=result.raw_payload,
            )
        )
    existing_sot = await session.get(BuildSoTRecord, result.build_sot_hash)
    if existing_sot is None:
        session.add(
            BuildSoTRecord(
                build_sot_hash=result.build_sot_hash,
                trace_id=trace_id,
                raw_intent_hash=result.raw_intent_hash,
                parent_build_sot_hash=None,
                ocgg_identity=body.ocgg_identity,
                intent=body.intent,
                status=result.build_sot.status.value,
                approval_required=True,
                approval_status=result.build_sot.approval_status,
                governance_plan_hash=None,
                governance_state_hash=None,
                payload=result.build_sot.model_dump(mode="python"),
            )
        )
    _trace(
        "raw_intent.persistence",
        trace_id=trace_id,
        raw_intent_exists=existing_raw is not None,
        build_sot_exists=existing_sot is not None,
    )
    session.add(
        _event(
            stage="RAW_INTENT",
            event_type="RAW_INTENT_RECEIVED",
            status=result.build_sot.status.value,
            trace_id=trace_id,
            artifact_hash=result.raw_intent_hash,
            metadata={"ocgg_identity": body.ocgg_identity, "intent": body.intent},
        )
    )
    session.add(
        _event(
            stage="BUILD_SOT",
            event_type="BUILD_SOT_GENERATED",
            status=result.build_sot.status.value,
            trace_id=trace_id,
            artifact_hash=result.build_sot_hash,
            metadata={
                "unresolved_items": list(result.build_sot.unresolved_items),
                "contradictions": list(result.build_sot.contradictions),
            },
        )
    )
    _trace(
        "raw_intent.commit.start",
        trace_id=trace_id,
        raw_intent_hash=result.raw_intent_hash,
        build_sot_hash=result.build_sot_hash,
    )
    try:
        await session.commit()
    except Exception:
        logger.exception(
            "governed_v2.raw_intent.commit_error",
            extra={
                "trace_id": trace_id,
                "raw_intent_hash": result.raw_intent_hash,
                "build_sot_hash": result.build_sot_hash,
            },
        )
        raise
    _trace(
        "raw_intent.commit.done",
        trace_id=trace_id,
        raw_intent_hash=result.raw_intent_hash,
        build_sot_hash=result.build_sot_hash,
    )
    _trace(
        "raw_intent.done",
        trace_id=trace_id,
        raw_intent_hash=result.raw_intent_hash,
        build_sot_hash=result.build_sot_hash,
        cognitive_outcome=result.cognitive_outcome.value,
        build_sot_status=result.build_sot.status.value,
    )
    return BuildSoTEnvelope(
        stage_linkage=result.linkage,
        build_sot=result.build_sot,
        cognitive_outcome=result.cognitive_outcome,
    )


@router.get("/build-sot/{build_sot_hash}", response_model=BuildSoTEnvelope)
async def get_build_sot(
    build_sot_hash: str,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("build_sot.get.start", build_sot_hash=build_sot_hash)
    rec = await session.get(BuildSoTRecord, build_sot_hash)
    if rec is None:
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            "Build SoT not found",
            details={"build_sot_hash": build_sot_hash},
        )
    out = _record_to_envelope(rec)
    _trace(
        "build_sot.get.done",
        trace_id=rec.trace_id,
        build_sot_hash=build_sot_hash,
        status=rec.status,
        approval_status=rec.approval_status,
    )
    return out


@router.post("/build-sot/{build_sot_hash}/revise", response_model=BuildSoTEnvelope)
async def revise_build_sot(
    build_sot_hash: str,
    body: BuildSoTRevisionRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("build_sot.revise.start", build_sot_hash=build_sot_hash, patch_keys=sorted((body.patch or {}).keys()))
    rec = await session.get(BuildSoTRecord, build_sot_hash)
    if rec is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Build SoT not found", details={"build_sot_hash": build_sot_hash})
    trace_id = normalize_trace_id(body.trace_id) if body.trace_id else rec.trace_id
    existing = BuildSoTV1.model_validate(rec.payload)
    revised = apply_build_sot_patch(existing, body.patch)
    revised_hash = hash_payload(revised.model_dump(mode="python"))
    existing_rev = await session.get(BuildSoTRecord, revised_hash)
    if existing_rev is None:
        session.add(
            BuildSoTRecord(
                build_sot_hash=revised_hash,
                trace_id=trace_id,
                raw_intent_hash=rec.raw_intent_hash,
                parent_build_sot_hash=build_sot_hash,
                ocgg_identity=rec.ocgg_identity,
                intent=rec.intent,
                status=revised.status.value,
                approval_required=True,
                approval_status="NOT_REQUESTED",
                payload=revised.model_dump(mode="python"),
            )
        )
    session.add(
        _event(
            stage="BUILD_SOT",
            event_type="BUILD_SOT_REVISED",
            status=revised.status.value,
            trace_id=trace_id,
            artifact_hash=revised_hash,
            metadata={"parent_build_sot_hash": build_sot_hash},
        )
    )
    await session.commit()
    _trace(
        "build_sot.revise.done",
        trace_id=trace_id,
        parent_build_sot_hash=build_sot_hash,
        revised_build_sot_hash=revised_hash,
        status=revised.status.value,
    )
    return BuildSoTEnvelope(
        stage_linkage=StageLinkage(
            trace_id=trace_id,
            raw_intent_hash=rec.raw_intent_hash,
            build_sot_hash=revised_hash,
            artifact_hash=revised_hash,
        ),
        build_sot=revised,
        cognitive_outcome=_build_sot_outcome(revised),
    )


async def _run_authoritative_governance(
    *,
    projection: dict[str, Any],
    build_sot_hash: str,
    trace_id: str,
    body: BuildSoTGovernanceEvaluateRequest,
) -> tuple[str, list[str], dict[str, Any] | None, str | None, str | None]:
    base = (settings.governed_v2_integration_base_url or "").rstrip("/")
    _trace(
        "build_sot.lock.governance_call.start",
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        live_governance=settings.governed_v2_live_governance,
        integration_base=base or None,
    )
    if not (settings.governed_v2_live_governance and base):
        if projection.get("operations") and not projection.get("goal", "").startswith("pending-"):
            _trace(
                "build_sot.lock.governance_call.short_circuit",
                trace_id=trace_id,
                build_sot_hash=build_sot_hash,
                outcome="PASS",
            )
            return "PASS", [], None, projection.get("plan_hash"), None
        _trace(
            "build_sot.lock.governance_call.short_circuit",
            trace_id=trace_id,
            build_sot_hash=build_sot_hash,
            outcome="CLARIFY",
            reason_code="BUILD_SOT_INCOMPLETE_FOR_GOVERNANCE",
        )
        return "CLARIFY", ["BUILD_SOT_INCOMPLETE_FOR_GOVERNANCE"], None, projection.get("plan_hash"), None

    payload = {
        "build_sot_hash": build_sot_hash,
        "trace_id": trace_id,
        "ocgg_identity": body.ocgg_identity,
        "intent": body.intent,
        "governance_projection": projection,
    }
    headers = {"Authorization": f"Bearer {settings.integration_api_key}"}
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base}/v2/build-sot/lock", json=payload, headers=headers)
    if resp.status_code >= 400:
        _trace(
            "build_sot.lock.governance_call.error",
            trace_id=trace_id,
            build_sot_hash=build_sot_hash,
            http_status=resp.status_code,
        )
        return "BLOCK", ["EXTERNAL_GOVERNANCE_UNREACHABLE"], None, projection.get("plan_hash"), None
    data = resp.json()
    _trace(
        "build_sot.lock.governance_call.done",
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        http_status=resp.status_code,
        outcome=data.get("outcome"),
    )
    return (
        data.get("outcome", "BLOCK"),
        list(data.get("reason_codes") or []),
        data.get("evaluation_frame"),
        data.get("governance_plan_hash") or projection.get("plan_hash"),
        data.get("state_hash"),
    )


@router.post("/build-sot/{build_sot_hash}/governance/evaluate", response_model=BuildSoTGovernanceResult)
async def evaluate_build_sot_governance(
    build_sot_hash: str,
    body: BuildSoTGovernanceEvaluateRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("build_sot.governance_evaluate.start", build_sot_hash=build_sot_hash)
    rec = await session.get(BuildSoTRecord, build_sot_hash)
    if rec is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Build SoT not found", details={"build_sot_hash": build_sot_hash})
    trace_id = normalize_trace_id(body.trace_id) if body.trace_id else rec.trace_id
    build_sot = BuildSoTV1.model_validate(rec.payload)
    projection, plan_hash = governance_projection_for_build_sot(
        build_sot_hash=build_sot_hash,
        trace_id=trace_id,
        build_sot=build_sot,
        ocgg_identity=body.ocgg_identity,
    )
    outcome, reason_codes, evaluation_frame, governance_plan_hash, state_hash = await _run_authoritative_governance(
        projection=projection,
        build_sot_hash=build_sot_hash,
        trace_id=trace_id,
        body=body,
    )
    rec.governance_plan_hash = governance_plan_hash
    rec.governance_state_hash = state_hash
    if outcome == "PASS":
        rec.status = ArtifactStatus.pending_sot_approval.value
        rec.approval_status = "PENDING"
        build_sot.status = ArtifactStatus.pending_sot_approval
        build_sot.approval_status = "PENDING"
    elif outcome in ("CLARIFY", "REFORM"):
        rec.status = ArtifactStatus.clarify_required.value
        build_sot.status = ArtifactStatus.clarify_required
    else:
        rec.status = ArtifactStatus.blocked.value
        build_sot.status = ArtifactStatus.blocked
    rec.updated_at = datetime.utcnow()
    rec.payload = build_sot.model_dump(mode="python")
    session.add(
        _event(
            stage="BUILD_SOT_GOVERNANCE_LOCK",
            event_type="BUILD_SOT_GOVERNANCE_EVALUATED",
            status=rec.status,
            trace_id=trace_id,
            artifact_hash=build_sot_hash,
            metadata={"outcome": outcome, "reason_codes": reason_codes},
        )
    )
    try:
        await session.commit()
    except Exception:
        logger.exception(
            "governed_v2.build_sot.governance_commit_error",
            extra={
                "trace_id": trace_id,
                "build_sot_hash": build_sot_hash,
                "outcome": outcome,
            },
        )
        raise
    _trace(
        "build_sot.governance_evaluate.done",
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        outcome=outcome,
        status=rec.status,
        approval_status=rec.approval_status,
        governance_plan_hash=governance_plan_hash or plan_hash,
        state_hash=state_hash,
    )
    return BuildSoTGovernanceResult(
        build_sot_hash=build_sot_hash,
        trace_id=trace_id,
        outcome=outcome,
        reason_codes=reason_codes,
        governance_projection=projection,
        evaluation_frame=evaluation_frame,
        governance_plan_hash=governance_plan_hash or plan_hash,
        state_hash=state_hash,
    )


@router.post("/build-sot/{build_sot_hash}/approval/decide", response_model=BuildSoTEnvelope)
async def decide_build_sot_approval(
    build_sot_hash: str,
    body: BuildSoTApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("build_sot.approval.start", build_sot_hash=build_sot_hash, decision=body.decision, approver_id=body.approver_id)
    rec = await session.get(BuildSoTRecord, build_sot_hash)
    if rec is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Build SoT not found", details={"build_sot_hash": build_sot_hash})
    build_sot = BuildSoTV1.model_validate(rec.payload)
    if rec.approval_status not in ("PENDING", "NOT_REQUESTED"):
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            "Build SoT approval already decided",
            details={"approval_status": rec.approval_status},
        )
    if body.decision == "APPROVE":
        rec.status = ArtifactStatus.locked.value
        rec.approval_status = "APPROVED"
        build_sot.status = ArtifactStatus.locked
        build_sot.approval_status = "APPROVED"
        rec.approved_at = datetime.utcnow()
    else:
        rec.status = ArtifactStatus.blocked.value
        rec.approval_status = "REJECTED"
        build_sot.status = ArtifactStatus.blocked
        build_sot.approval_status = "REJECTED"
    rec.approver_id = body.approver_id
    rec.approval_comment = body.comment
    rec.updated_at = datetime.utcnow()
    rec.payload = build_sot.model_dump(mode="python")
    session.add(
        _event(
            stage="BUILD_SOT_APPROVAL",
            event_type="BUILD_SOT_APPROVAL_DECIDED",
            status=rec.status,
            trace_id=rec.trace_id,
            artifact_hash=build_sot_hash,
            metadata={"decision": body.decision, "approver_id": body.approver_id},
        )
    )
    try:
        await session.commit()
    except Exception:
        logger.exception(
            "governed_v2.build_sot.approval_commit_error",
            extra={
                "trace_id": rec.trace_id,
                "build_sot_hash": build_sot_hash,
                "decision": body.decision,
            },
        )
        raise
    _trace(
        "build_sot.approval.done",
        trace_id=rec.trace_id,
        build_sot_hash=build_sot_hash,
        decision=body.decision,
        status=rec.status,
        approval_status=rec.approval_status,
    )
    return _record_to_envelope(rec)


@router.post("/build-sot/{build_sot_hash}/compile", response_model=ExecutionPlanV1)
async def compile_locked_build_sot(
    build_sot_hash: str,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("build_sot.compile.start", build_sot_hash=build_sot_hash)
    rec = await session.get(BuildSoTRecord, build_sot_hash)
    if rec is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Build SoT not found", details={"build_sot_hash": build_sot_hash})
    if rec.approval_status != "APPROVED":
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            "Build SoT must be approved before compile",
            details={"status": rec.status, "approval_status": rec.approval_status},
        )
    if rec.status == ArtifactStatus.compiled.value:
        stmt = (
            select(ExecutionPlanRecordV2)
            .where(ExecutionPlanRecordV2.build_sot_hash == build_sot_hash)
            .order_by(ExecutionPlanRecordV2.created_at.desc())
            .limit(1)
        )
        existing_latest = (await session.execute(stmt)).scalar_one_or_none()
        if existing_latest is not None:
            _trace(
                "build_sot.compile.cache_hit",
                trace_id=rec.trace_id,
                build_sot_hash=build_sot_hash,
                execution_plan_hash=existing_latest.execution_plan_hash,
            )
            return ExecutionPlanV1.model_validate(existing_latest.payload)
    if rec.status != ArtifactStatus.locked.value:
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            "Build SoT must be approved and locked before compile",
            details={"status": rec.status, "approval_status": rec.approval_status},
        )
    build_sot = BuildSoTV1.model_validate(rec.payload)
    plan, execution_plan_hash = compile_execution_plan(
        trace_id=rec.trace_id,
        build_sot_hash=build_sot_hash,
        build_sot=build_sot,
        ocgg_identity=rec.ocgg_identity,
        intent=rec.intent,
    )
    existing = await session.get(ExecutionPlanRecordV2, execution_plan_hash)
    if existing is None:
        session.add(
            ExecutionPlanRecordV2(
                execution_plan_hash=execution_plan_hash,
                trace_id=rec.trace_id,
                build_sot_hash=build_sot_hash,
                ocgg_identity=rec.ocgg_identity,
                intent=rec.intent,
                status=ArtifactStatus.compiled.value,
                governance_plan_hash=plan.governance_projection.get("plan_hash"),
                payload=plan.model_dump(mode="python"),
            )
        )
    rec.status = ArtifactStatus.compiled.value
    rec.updated_at = datetime.utcnow()
    build_sot.status = ArtifactStatus.compiled
    rec.payload = build_sot.model_dump(mode="python")
    session.add(
        _event(
            stage="COMPILER_MODE",
            event_type="EXECUTION_PLAN_COMPILED",
            status=ArtifactStatus.compiled.value,
            trace_id=rec.trace_id,
            artifact_hash=execution_plan_hash,
            metadata={"build_sot_hash": build_sot_hash},
        )
    )
    try:
        await session.commit()
    except Exception:
        logger.exception(
            "governed_v2.build_sot.compile_commit_error",
            extra={
                "trace_id": rec.trace_id,
                "build_sot_hash": build_sot_hash,
                "execution_plan_hash": execution_plan_hash,
            },
        )
        raise
    _trace(
        "build_sot.compile.done",
        trace_id=rec.trace_id,
        build_sot_hash=build_sot_hash,
        execution_plan_hash=execution_plan_hash,
        governance_plan_hash=plan.governance_projection.get("plan_hash"),
    )
    return plan


@router.get("/execution-plans/{execution_plan_hash}", response_model=ExecutionPlanV1)
async def get_execution_plan_v2(
    execution_plan_hash: str,
    session: AsyncSession = Depends(get_session),
):
    _ensure_v2_enabled()
    _trace("execution_plan.get.start", execution_plan_hash=execution_plan_hash)
    rec = await session.get(ExecutionPlanRecordV2, execution_plan_hash)
    if rec is None:
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            "Execution plan not found",
            details={"execution_plan_hash": execution_plan_hash},
        )
    out = ExecutionPlanV1.model_validate(rec.payload)
    _trace(
        "execution_plan.get.done",
        trace_id=rec.trace_id,
        execution_plan_hash=execution_plan_hash,
        build_sot_hash=rec.build_sot_hash,
        status=rec.status,
    )
    return out
