"""Continuity helpers for governed v2 execution-plan locks."""
from __future__ import annotations

from datetime import datetime
import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_payload
from app.core.config import settings
from app.models.governed_v2_lock import ExecutionPlanLockRecord

logger = logging.getLogger(__name__)


def _trace(event: str, **fields: object) -> None:
    if settings.governed_v2_trace_logging:
        payload = {k: v for k, v in fields.items() if v is not None}
        logger.info("governed_v2.%s %s", event, payload)


def continuity_id_for_lock(
    *,
    trace_id: str,
    ocgg_identity: str,
    build_sot_hash: str,
    execution_plan_hash: str,
    plan_hash: str,
    governance_evaluation_id: str,
    state_hash: str | None,
) -> str:
    return hash_payload(
        {
            "trace_id": trace_id,
            "ocgg_identity": ocgg_identity,
            "build_sot_hash": build_sot_hash,
            "execution_plan_hash": execution_plan_hash,
            "plan_hash": plan_hash,
            "governance_evaluation_id": governance_evaluation_id,
            "state_hash": state_hash or "",
        }
    )


async def upsert_execution_plan_lock(
    session: AsyncSession,
    *,
    continuity_id: str,
    trace_id: str,
    ocgg_identity: str,
    build_sot_hash: str,
    execution_plan_hash: str,
    plan_hash: str,
    governance_evaluation_id: str,
    state_hash: str | None,
) -> ExecutionPlanLockRecord:
    rec = await session.get(ExecutionPlanLockRecord, continuity_id)
    if rec is None:
        rec = ExecutionPlanLockRecord(
            continuity_id=continuity_id,
            trace_id=trace_id,
            ocgg_identity=ocgg_identity,
            build_sot_hash=build_sot_hash,
            execution_plan_hash=execution_plan_hash,
            plan_hash=plan_hash,
            governance_evaluation_id=governance_evaluation_id,
            state_hash=state_hash,
            status="ACTIVE",
        )
        session.add(rec)
        await session.flush()
        _trace(
            "continuity.upsert.created",
            continuity_id=continuity_id,
            trace_id=trace_id,
            build_sot_hash=build_sot_hash,
            execution_plan_hash=execution_plan_hash,
        )
        return rec
    rec.trace_id = trace_id
    rec.ocgg_identity = ocgg_identity
    rec.build_sot_hash = build_sot_hash
    rec.execution_plan_hash = execution_plan_hash
    rec.plan_hash = plan_hash
    rec.governance_evaluation_id = governance_evaluation_id
    rec.state_hash = state_hash
    rec.status = "ACTIVE"
    rec.used_at = None
    await session.flush()
    _trace(
        "continuity.upsert.updated",
        continuity_id=continuity_id,
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        execution_plan_hash=execution_plan_hash,
    )
    return rec


async def verify_task_continuity_lock(
    session: AsyncSession,
    *,
    continuity_id: str,
    ocgg_identity: str,
    build_sot_hash: str,
    execution_plan_hash: str,
    plan_hash: str,
    governance_evaluation_id: str,
) -> ExecutionPlanLockRecord:
    rec = await session.get(ExecutionPlanLockRecord, continuity_id)
    if rec is None:
        _trace(
            "continuity.verify.not_found",
            continuity_id=continuity_id,
            ocgg_identity=ocgg_identity,
            build_sot_hash=build_sot_hash,
            execution_plan_hash=execution_plan_hash,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "V2_CONTINUITY_NOT_FOUND",
                "message": "v2_continuity_id does not exist.",
                "continuity_id": continuity_id,
            },
        )
    if rec.status != "ACTIVE":
        _trace(
            "continuity.verify.not_active",
            continuity_id=continuity_id,
            status=rec.status,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "V2_CONTINUITY_NOT_ACTIVE",
                "message": f"continuity record status={rec.status}; expected ACTIVE.",
                "continuity_id": continuity_id,
            },
        )
    mismatch = {}
    if rec.ocgg_identity != ocgg_identity:
        mismatch["ocgg_identity"] = {"expected": rec.ocgg_identity, "provided": ocgg_identity}
    if rec.build_sot_hash != build_sot_hash:
        mismatch["build_sot_hash"] = {"expected": rec.build_sot_hash, "provided": build_sot_hash}
    if rec.execution_plan_hash != execution_plan_hash:
        mismatch["execution_plan_hash"] = {"expected": rec.execution_plan_hash, "provided": execution_plan_hash}
    if rec.plan_hash != plan_hash:
        mismatch["plan_hash"] = {"expected": rec.plan_hash, "provided": plan_hash}
    if rec.governance_evaluation_id != governance_evaluation_id:
        mismatch["governance_evaluation_id"] = {
            "expected": rec.governance_evaluation_id,
            "provided": governance_evaluation_id,
        }
    if mismatch:
        _trace(
            "continuity.verify.mismatch",
            continuity_id=continuity_id,
            mismatch=mismatch,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "V2_CONTINUITY_MISMATCH",
                "message": "Execution plan lineage drift detected.",
                "continuity_id": continuity_id,
                "mismatch": mismatch,
            },
        )
    _trace(
        "continuity.verify.ok",
        continuity_id=continuity_id,
        trace_id=rec.trace_id,
        build_sot_hash=build_sot_hash,
        execution_plan_hash=execution_plan_hash,
    )
    return rec


async def mark_continuity_used(session: AsyncSession, rec: ExecutionPlanLockRecord) -> None:
    rec.status = "USED"
    rec.used_at = datetime.utcnow()
    await session.flush()
    _trace(
        "continuity.mark_used",
        continuity_id=rec.continuity_id,
        trace_id=rec.trace_id,
        build_sot_hash=rec.build_sot_hash,
        execution_plan_hash=rec.execution_plan_hash,
    )
