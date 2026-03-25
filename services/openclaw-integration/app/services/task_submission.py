"""Core POST /task pipeline: evaluation frame (Invariant-C + UATO + Invariant-E) → GateEngine → Invariant-E dispatch → token → OpenClaw."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select

from app.core.errors import ErrorCodes
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.evaluation_frame import build_shared_governable_state_for_task, run_evaluation_frame
from app.evaluation_frame.state import FrameStatus
from app.gate.engine import GateEngine
from app.gate.models import GateDecision, GateEvaluation
from app.gate.policy import get_policy_version_at_execution
from app.gate.token import generate_execution_token, hash_token, verify_execution_token
from app.models import GateDecisionRecord, Task, TaskStatus, TaskSubmitRequest, TaskSubmitResponse, UsedExecutionToken
from app.models.approval_request import ApprovalSourceLayer
from app.services.approvals_service import (
    create_approval_request_for_stop,
    find_pending_governance_prod_approval,
    prod_governance_resume_snapshot_hash,
)
from app.services.execution_client import OpenClawClient, OpenClawError
from app.uato import build_uato_input_from_spec, evaluate_uato, to_trace_record
from app.uato.normalize import minimal_plan_admissibility_issues
from app.uato.plan_bridge import integration_plan_preview
from app.uato.types import UATO_DECISION_VERSION
from app.invariant_e import build_execution_envelope, evaluate_invariant_e, to_trace_record as ie_to_trace


def _task_submit_response(
    *,
    task_id: UUID,
    status: str,
    trace_id: Optional[str] = None,
    uato_decision: Optional[str] = None,
    uato_reason_codes: Optional[list[str]] = None,
    governance_outcome: Optional[str] = None,
    invariant_e_decision: Optional[str] = None,
    invariant_e_reason_codes: Optional[list[str]] = None,
    dispatch_blocked: Optional[bool] = None,
    **kwargs: Any,
) -> TaskSubmitResponse:
    if trace_id:
        kwargs["trace_id"] = trace_id
        kwargs["audit_trace_id"] = trace_id
    if uato_decision is not None:
        kwargs["uato_decision"] = uato_decision
    if uato_reason_codes is not None:
        kwargs["uato_reason_codes"] = uato_reason_codes
    if governance_outcome is not None:
        kwargs["governance_outcome"] = governance_outcome
    if invariant_e_decision is not None:
        kwargs["invariant_e_decision"] = invariant_e_decision
    if invariant_e_reason_codes is not None:
        kwargs["invariant_e_reason_codes"] = invariant_e_reason_codes
    if dispatch_blocked is not None:
        kwargs["dispatch_blocked"] = dispatch_blocked
    return TaskSubmitResponse(task_id=task_id, status=status, **kwargs)


def _effective_gate_outcome_for_response(
    *,
    governance_outcome: Optional[str],
    execution_denied: bool,
) -> str:
    if governance_outcome == "BLOCK":
        return "BLOCK"
    if execution_denied:
        return "BLOCK"
    return "PASS"


def _frame_pass_audit_entries(
    *,
    trace_id: str,
    shared_state_hash: str,
    ic_res: Any,
    uato_trace: dict[str, Any],
    ie_frame_trace: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {"event_type": "shared_state_built", "payload": {"trace_id": trace_id, "shared_state_hash": shared_state_hash}},
        {
            "event_type": "invariant_c_decision",
            "payload": {
                "decision": ic_res.decision,
                "reason_codes": list(ic_res.reason_codes),
                "decision_version": ic_res.decision_version,
                "admissibility_source": "INVARIANT_C",
                "evaluation_phase": "frame",
            },
        },
        {
            "event_type": "uato_decision",
            "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO", "evaluation_phase": "frame"},
        },
        {
            "event_type": "invariant_e_decision",
            "payload": {**ie_frame_trace, "upstream_gate": "INVARIANT_E", "admissibility_source": "INVARIANT_E", "evaluation_phase": "frame"},
        },
        {"event_type": "evaluation_frame_completed", "payload": {"frame_status": "PASS", "shared_state_hash": shared_state_hash}},
    ]


async def _latest_gate_record(session: AsyncSession, task_id: UUID) -> Optional[GateDecisionRecord]:
    stmt = (
        select(GateDecisionRecord)
        .where(GateDecisionRecord.task_id == task_id)
        .order_by(GateDecisionRecord.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _sync_existing_prod_governance_materialization(
    session: AsyncSession,
    task: Task,
    gate_record: GateDecisionRecord,
    body: TaskSubmitRequest,
    trace_id: str,
    *,
    domain: str,
    uato_in: Any,
    uato_res: Any,
    uato_evaluated_at: datetime,
    uato_trace: dict[str, Any],
    decision: GateDecision,
    plan_json: dict[str, Any],
    spec_hash: str,
    plan_hash: str,
) -> None:
    task.ocgg_identity = body.ocgg_identity
    task.domain = domain
    task.plan_hash = plan_hash
    task.spec_hash = spec_hash
    task.policy_version = decision.policy_version
    task.gate_outcome = decision.outcome.value
    task.governance_outcome = decision.outcome.value
    task.reason_codes = decision.reason_codes
    task.plan_json = plan_json
    task.uato_decision = uato_res.decision
    task.uato_reason_codes = list(uato_res.reason_codes)
    task.uato_trust_level = uato_in.trust_state.level
    task.uato_authority_level = uato_in.authority_state.level
    task.uato_decision_version = uato_res.decision_version
    task.uato_input_hash = uato_trace["uato_input_hash"]
    task.uato_evaluated_at = uato_evaluated_at
    task.status = TaskStatus.pending_approval
    task.blocked_stage = "GOVERNANCE"
    gate_record.ocgg_identity = body.ocgg_identity
    gate_record.outcome = decision.outcome.value
    gate_record.reason_codes = decision.reason_codes
    gate_record.defect_list = [{"code": d.code, "field": d.field, "message": d.message} for d in decision.defect_list]
    gate_record.policy_version = decision.policy_version
    gate_record.spec_hash = spec_hash
    gate_record.plan_hash = plan_hash
    gate_record.approver_id = decision.approver_id
    gate_record.trace_id = trace_id
    gate_record.uato_decision = uato_res.decision
    gate_record.uato_reason_codes = list(uato_res.reason_codes)
    gate_record.uato_trust_level = uato_in.trust_state.level
    gate_record.uato_authority_level = uato_in.authority_state.level
    gate_record.uato_decision_version = uato_res.decision_version
    gate_record.uato_input_hash = uato_trace["uato_input_hash"]
    gate_record.uato_evaluated_at = uato_evaluated_at
    await session.flush()


async def materialize_governance_prod_deploy_stop(
    session: AsyncSession,
    body: TaskSubmitRequest,
    trace_id: str,
    *,
    uato_in: Any,
    uato_res: Any,
    uato_evaluated_at: datetime,
    uato_trace: dict[str, Any],
    evaluation: GateEvaluation,
    frame_shared_state_hash: Optional[str] = None,
    ic_res: Any = None,
    ie_frame_trace: Optional[dict[str, Any]] = None,
) -> tuple[Task, Any]:  # second: ApprovalRequest
    """
    Persist task + gate_decisions + PENDING GOVERNANCE approval for PROD_DEPLOY_NO_APPROVAL.
    Idempotent on (trace_id, resume checkpoint snapshot): reused by POST /gate/evaluate and POST /task.
    """
    decision = evaluation.decision
    plan_json = evaluation.plan_json
    spec_hash = evaluation.spec_hash
    plan_hash = evaluation.plan_hash
    domain = IDENTITY_DOMAIN_MAP[body.ocgg_identity]

    snap = prod_governance_resume_snapshot_hash(body, trace_id)
    existing_ar = await find_pending_governance_prod_approval(session, trace_id=trace_id, snapshot_hash=snap)
    if existing_ar:
        task = await session.get(Task, existing_ar.task_id)
        gate_record = await _latest_gate_record(session, task.task_id) if task else None
        if task and gate_record and (task.trace_id or "") == (trace_id or ""):
            await _sync_existing_prod_governance_materialization(
                session,
                task,
                gate_record,
                body,
                trace_id,
                domain=domain,
                uato_in=uato_in,
                uato_res=uato_res,
                uato_evaluated_at=uato_evaluated_at,
                uato_trace=uato_trace,
                decision=decision,
                plan_json=plan_json,
                spec_hash=spec_hash,
                plan_hash=plan_hash,
            )
            task.audit_history = task.audit_history or []
            task.audit_history.append(
                {
                    "event_type": "gate_decision",
                    "payload": {"outcome": decision.outcome.value, "reason_codes": decision.reason_codes},
                },
            )
            flag_modified(task, "audit_history")
            await session.commit()
            await session.refresh(task)
            return task, existing_ar

    if frame_shared_state_hash and ic_res is not None and ie_frame_trace is not None:
        initial_audit = _frame_pass_audit_entries(
            trace_id=trace_id,
            shared_state_hash=frame_shared_state_hash,
            ic_res=ic_res,
            uato_trace=uato_trace,
            ie_frame_trace=ie_frame_trace,
        )
    else:
        initial_audit = [
            {
                "event_type": "uato_decision",
                "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO"},
            }
        ]

    task = Task(
        ocgg_identity=body.ocgg_identity,
        domain=domain,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        policy_version=decision.policy_version,
        gate_outcome=decision.outcome.value,
        governance_outcome=decision.outcome.value,
        reason_codes=decision.reason_codes,
        plan_json=plan_json,
        audit_history=initial_audit,
        status=TaskStatus.submitted,
        trace_id=trace_id,
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
        uato_trust_level=uato_in.trust_state.level,
        uato_authority_level=uato_in.authority_state.level,
        uato_decision_version=uato_res.decision_version,
        uato_input_hash=uato_trace["uato_input_hash"],
        uato_evaluated_at=uato_evaluated_at,
    )
    session.add(task)
    await session.flush()
    gate_record = GateDecisionRecord(
        task_id=task.task_id,
        ocgg_identity=body.ocgg_identity,
        outcome=decision.outcome.value,
        reason_codes=decision.reason_codes,
        defect_list=[{"code": d.code, "field": d.field, "message": d.message} for d in decision.defect_list],
        policy_version=decision.policy_version,
        spec_hash=spec_hash,
        plan_hash=plan_hash,
        approver_id=decision.approver_id,
        trace_id=trace_id,
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
        uato_trust_level=uato_in.trust_state.level,
        uato_authority_level=uato_in.authority_state.level,
        uato_decision_version=uato_res.decision_version,
        uato_input_hash=uato_trace["uato_input_hash"],
        uato_evaluated_at=uato_evaluated_at,
    )
    session.add(gate_record)
    await session.commit()
    await session.refresh(task)
    task.audit_history = task.audit_history or []
    task.audit_history.append({"event_type": "gate_decision", "payload": {"outcome": decision.outcome.value, "reason_codes": decision.reason_codes}})
    flag_modified(task, "audit_history")
    await session.commit()

    ar = await create_approval_request_for_stop(
        session,
        trace_id=trace_id,
        task_id=task.task_id,
        source_layer=ApprovalSourceLayer.GOVERNANCE,
        reason_code="PROD_DEPLOY_NO_APPROVAL",
        resume_from_stage="RERUN_GOVERNANCE",
        task_submit_body=body,
        trace_id_for_body=trace_id,
        approval_scope="prod_deploy",
    )
    task.status = TaskStatus.pending_approval
    task.approval_request_id = ar.id
    task.blocked_stage = "GOVERNANCE"
    task.audit_history = task.audit_history or []
    task.audit_history.append(
        {
            "event_type": "approval_requested",
            "payload": {
                "approval_request_id": str(ar.id),
                "source_layer": "GOVERNANCE",
                "trace_id": trace_id,
            },
        },
    )
    flag_modified(task, "audit_history")
    await session.commit()
    await session.refresh(task)
    return task, ar


async def run_task_submission(
    session: AsyncSession,
    body: TaskSubmitRequest,
    trace_id: str,
    *,
    reuse_task_id: Optional[UUID] = None,
) -> TaskSubmitResponse:
    """Run integration task pipeline. When reuse_task_id is set, update the existing task (approval resume)."""
    if body.ocgg_identity not in IDENTITY_DOMAIN_MAP:
        raise HTTPException(status_code=422, detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": "Unknown ocgg_identity"})
    domain = IDENTITY_DOMAIN_MAP[body.ocgg_identity]
    spec_pre = body.model_dump(mode="python")
    spec_pre.pop("trace_id", None)
    spec_pre.pop("uato", None)
    if minimal_plan_admissibility_issues(spec_pre):
        if reuse_task_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "FRAME_RESUME_FAILED",
                    "message": "Checkpoint spec failed integration shape preflight; cannot rebuild shared state.",
                    "reason_codes": list(minimal_plan_admissibility_issues(spec_pre)),
                },
            )
        uato_in_pf = build_uato_input_from_spec(
            spec_pre,
            ocgg_identity=body.ocgg_identity,
            trace_id=trace_id,
            uato_hints=body.uato,
        )
        uato_res_pf = evaluate_uato(uato_in_pf)
        uato_eval_pf = datetime.utcnow()
        uato_trace_pf = to_trace_record(uato_in_pf, uato_res_pf)
        plan_json_pf, plan_hash_pf, spec_hash_pf = integration_plan_preview(spec_pre, body.ocgg_identity)
        task_pf = Task(
            ocgg_identity=body.ocgg_identity,
            domain=domain,
            plan_hash=plan_hash_pf,
            spec_hash=spec_hash_pf,
            policy_version=UATO_DECISION_VERSION,
            gate_outcome="BLOCK",
            reason_codes=list(uato_res_pf.reason_codes),
            plan_json=plan_json_pf,
            audit_history=[
                {
                    "event_type": "uato_decision",
                    "payload": {**uato_trace_pf, "upstream_gate": "UATO", "admissibility_source": "UATO", "preflight": True},
                }
            ],
            status=TaskStatus.uato_blocked,
            trace_id=trace_id,
            uato_decision=uato_res_pf.decision,
            uato_reason_codes=list(uato_res_pf.reason_codes),
            uato_trust_level=uato_in_pf.trust_state.level,
            uato_authority_level=uato_in_pf.authority_state.level,
            uato_decision_version=uato_res_pf.decision_version,
            uato_input_hash=uato_trace_pf["uato_input_hash"],
            uato_evaluated_at=uato_eval_pf,
        )
        session.add(task_pf)
        await session.flush()
        gate_pf = GateDecisionRecord(
            task_id=task_pf.task_id,
            ocgg_identity=body.ocgg_identity,
            outcome="BLOCK",
            reason_codes=list(uato_res_pf.reason_codes),
            defect_list=[],
            policy_version=UATO_DECISION_VERSION,
            spec_hash=spec_hash_pf,
            plan_hash=plan_hash_pf,
            approver_id=None,
            trace_id=trace_id,
            uato_decision=uato_res_pf.decision,
            uato_reason_codes=list(uato_res_pf.reason_codes),
            uato_trust_level=uato_in_pf.trust_state.level,
            uato_authority_level=uato_in_pf.authority_state.level,
            uato_decision_version=uato_res_pf.decision_version,
            uato_input_hash=uato_trace_pf["uato_input_hash"],
            uato_evaluated_at=uato_eval_pf,
        )
        session.add(gate_pf)
        await session.commit()
        await session.refresh(task_pf)
        return _task_submit_response(
            task_id=task_pf.task_id,
            status=task_pf.status.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=list(uato_res_pf.reason_codes),
            uato_decision=uato_res_pf.decision,
            uato_reason_codes=list(uato_res_pf.reason_codes),
        )

    try:
        shared = build_shared_governable_state_for_task(body, trace_id, for_resume=bool(reuse_task_id))
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCodes.INVALID_PAYLOAD, "message": str(e)},
        )

    frame = run_evaluation_frame(shared)
    spec = dict(shared.spec_for_gate)
    uato_in = build_uato_input_from_spec(
        spec,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        uato_hints=body.uato,
    )
    uato_res = frame.uato_result
    uato_evaluated_at = datetime.utcnow()
    uato_trace = to_trace_record(uato_in, uato_res)
    ie_env_frame = build_execution_envelope(
        spec=spec,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        task_id=None,
        governance_outcome="PENDING",
        plan_hash=shared.plan_hash,
        spec_hash=shared.spec_hash,
    )
    ie_frame_evaluated_at = datetime.utcnow()
    ie_frame_trace = ie_to_trace(ie_env_frame, frame.invariant_e_result)
    plan_json, plan_hash, spec_hash = shared.plan_json, shared.plan_hash, shared.spec_hash
    ic_res = frame.invariant_c_result
    ie_res_frame = frame.invariant_e_result

    if reuse_task_id and frame.frame_status != FrameStatus.PASS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FRAME_RESUME_FAILED",
                "message": "Approval resume re-evaluated the admissibility frame; request remains non-admissible.",
                "frame_status": frame.frame_status.value,
                "uato_decision": uato_res.decision,
                "invariant_c_decision": ic_res.decision,
                "invariant_e_decision": ie_res_frame.decision,
                "reason_codes": list(frame.reason_codes),
            },
        )

    if frame.frame_status != FrameStatus.PASS:
        if frame.frame_status == FrameStatus.ESCALATED:
            short_status = TaskStatus.needs_review
        elif frame.frame_status == FrameStatus.APPROVAL_REQUIRED:
            short_status = TaskStatus.pending_approval
        elif uato_res.decision == "BLOCK":
            short_status = TaskStatus.uato_blocked
        elif ic_res.decision != "PASS":
            short_status = TaskStatus.invalid_plan
        elif ie_res_frame.decision != "EXECUTION_ALLOWED":
            short_status = TaskStatus.invariant_e_denied
        else:
            short_status = TaskStatus.uato_blocked
        frame_audit = {
            "event_type": "evaluation_frame_completed",
            "payload": {
                "frame_status": frame.frame_status.value,
                "shared_state_hash": frame.shared_state_hash,
                "invariant_c_decision": ic_res.decision,
                "invariant_c_reason_codes": list(ic_res.reason_codes),
                "uato_decision": uato_res.decision,
                "uato_reason_codes": list(uato_res.reason_codes),
                "invariant_e_decision": ie_res_frame.decision,
                "invariant_e_reason_codes": list(ie_res_frame.reason_codes),
            },
        }
        paused_evt = None
        if frame.frame_status == FrameStatus.APPROVAL_REQUIRED:
            paused_evt = {
                "event_type": "evaluation_frame_paused_for_approval",
                "payload": {"shared_state_hash": frame.shared_state_hash, "uato_decision": uato_res.decision},
            }
        elif frame.frame_status == FrameStatus.BLOCKED:
            paused_evt = {"event_type": "evaluation_frame_blocked", "payload": {"shared_state_hash": frame.shared_state_hash}}
        elif frame.frame_status == FrameStatus.ESCALATED:
            paused_evt = {"event_type": "evaluation_frame_blocked", "payload": {"frame_status": "ESCALATED", "shared_state_hash": frame.shared_state_hash}}
        task = Task(
            ocgg_identity=body.ocgg_identity,
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version=UATO_DECISION_VERSION,
            gate_outcome="BLOCK",
            reason_codes=list(frame.reason_codes),
            plan_json=plan_json,
            audit_history=[
                {
                    "event_type": "shared_state_built",
                    "payload": {"trace_id": trace_id, "shared_state_hash": frame.shared_state_hash},
                },
                {
                    "event_type": "invariant_c_decision",
                    "payload": {
                        "decision": ic_res.decision,
                        "reason_codes": list(ic_res.reason_codes),
                        "decision_version": ic_res.decision_version,
                        "admissibility_source": "INVARIANT_C",
                        "evaluation_phase": "frame",
                    },
                },
                {
                    "event_type": "uato_decision",
                    "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO", "evaluation_phase": "frame"},
                },
                {
                    "event_type": "invariant_e_decision",
                    "payload": {**ie_frame_trace, "upstream_gate": "INVARIANT_E", "admissibility_source": "INVARIANT_E", "evaluation_phase": "frame"},
                },
                frame_audit,
            ]
            + ([paused_evt] if paused_evt else []),
            status=short_status,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
            invariant_e_decision=ie_res_frame.decision,
            invariant_e_reason_codes=list(ie_res_frame.reason_codes),
            invariant_e_decision_version=ie_res_frame.decision_version,
            invariant_e_input_hash=ie_frame_trace["invariant_e_input_hash"],
            invariant_e_evaluated_at=ie_frame_evaluated_at,
            dispatch_blocked=ie_res_frame.dispatch_blocked,
        )
        session.add(task)
        await session.flush()
        gate_record = GateDecisionRecord(
            task_id=task.task_id,
            ocgg_identity=body.ocgg_identity,
            outcome="BLOCK",
            reason_codes=list(frame.reason_codes),
            defect_list=[],
            policy_version=UATO_DECISION_VERSION,
            spec_hash=spec_hash,
            plan_hash=plan_hash,
            approver_id=None,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
            invariant_e_decision=ie_res_frame.decision,
            invariant_e_reason_codes=list(ie_res_frame.reason_codes),
            invariant_e_decision_version=ie_res_frame.decision_version,
            invariant_e_input_hash=ie_frame_trace["invariant_e_input_hash"],
            invariant_e_evaluated_at=ie_frame_evaluated_at,
            dispatch_blocked=ie_res_frame.dispatch_blocked,
        )
        session.add(gate_record)
        await session.commit()
        await session.refresh(task)

        extra: dict[str, Any] = {}
        if frame.frame_status == FrameStatus.APPROVAL_REQUIRED and frame.approvable_via_uato:
            ar = await create_approval_request_for_stop(
                session,
                trace_id=trace_id,
                task_id=task.task_id,
                source_layer=ApprovalSourceLayer.UATO,
                reason_code=uato_res.reason_codes[0] if uato_res.reason_codes else "REQUIRE_APPROVAL",
                resume_from_stage="FRAME_REEVALUATION",
                task_submit_body=body,
                trace_id_for_body=trace_id,
                approval_scope="uato_require_approval",
            )
            task.approval_request_id = ar.id
            task.blocked_stage = "EVAL_FRAME"
            task.audit_history = task.audit_history or []
            task.audit_history.append(
                {
                    "event_type": "approval_requested",
                    "payload": {
                        "approval_request_id": str(ar.id),
                        "source_layer": "UATO",
                        "trace_id": trace_id,
                        "frame_snapshot_hash": frame.shared_state_hash,
                    },
                }
            )
            flag_modified(task, "audit_history")
            await session.commit()
            await session.refresh(task)
            extra = {
                "approval_required": True,
                "approval_request_id": ar.id,
                "approval_status": "PENDING",
                "source_layer": "UATO",
                "resume_available": True,
            }

        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            reason_codes=list(frame.reason_codes),
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res_frame.decision,
            invariant_e_reason_codes=list(ie_res_frame.reason_codes),
            dispatch_blocked=ie_res_frame.dispatch_blocked,
            **extra,
        )

    engine = GateEngine()
    evaluation = engine.evaluate(spec, body.ocgg_identity)
    decision = evaluation.decision
    plan_json = evaluation.plan_json
    spec_hash = evaluation.spec_hash
    plan_hash = evaluation.plan_hash

    if (
        not reuse_task_id
        and decision.outcome.value != "PASS"
        and "PROD_DEPLOY_NO_APPROVAL" in decision.reason_codes
    ):
        task, ar = await materialize_governance_prod_deploy_stop(
            session,
            body,
            trace_id,
            uato_in=uato_in,
            uato_res=uato_res,
            uato_evaluated_at=uato_evaluated_at,
            uato_trace=uato_trace,
            evaluation=evaluation,
            frame_shared_state_hash=frame.shared_state_hash,
            ic_res=ic_res,
            ie_frame_trace=ie_frame_trace,
        )
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome=decision.outcome.value,
            governance_outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            approval_required=True,
            approval_request_id=ar.id,
            approval_status="PENDING",
            source_layer="GOVERNANCE",
            resume_available=True,
        )

    if reuse_task_id:
        task = await session.get(Task, reuse_task_id)
        if not task or (task.trace_id or "") != (trace_id or ""):
            raise HTTPException(status_code=422, detail={"code": "TASK_REUSE_MISMATCH", "message": "task_id/trace_id mismatch for resume."})
        if task.status != TaskStatus.pending_approval:
            raise HTTPException(
                status_code=422,
                detail={"code": "TASK_NOT_RESUMABLE", "message": f"Task status {task.status} cannot resume from approval."},
            )
        gate_record = await _latest_gate_record(session, reuse_task_id)
        if not gate_record:
            raise HTTPException(status_code=422, detail={"code": "GATE_RECORD_MISSING", "message": "No gate_decisions row for task."})
        task.ocgg_identity = body.ocgg_identity
        task.domain = domain
        task.plan_hash = plan_hash
        task.spec_hash = spec_hash
        task.policy_version = decision.policy_version
        task.gate_outcome = decision.outcome.value
        task.governance_outcome = decision.outcome.value
        task.reason_codes = decision.reason_codes
        task.plan_json = plan_json
        task.uato_decision = uato_res.decision
        task.uato_reason_codes = list(uato_res.reason_codes)
        task.uato_trust_level = uato_in.trust_state.level
        task.uato_authority_level = uato_in.authority_state.level
        task.uato_decision_version = uato_res.decision_version
        task.uato_input_hash = uato_trace["uato_input_hash"]
        task.uato_evaluated_at = uato_evaluated_at
        task.status = TaskStatus.submitted
        task.blocked_stage = None
        gate_record.ocgg_identity = body.ocgg_identity
        gate_record.outcome = decision.outcome.value
        gate_record.reason_codes = decision.reason_codes
        gate_record.defect_list = [{"code": d.code, "field": d.field, "message": d.message} for d in decision.defect_list]
        gate_record.policy_version = decision.policy_version
        gate_record.spec_hash = spec_hash
        gate_record.plan_hash = plan_hash
        gate_record.approver_id = decision.approver_id
        gate_record.trace_id = trace_id
        gate_record.uato_decision = uato_res.decision
        gate_record.uato_reason_codes = list(uato_res.reason_codes)
        gate_record.uato_trust_level = uato_in.trust_state.level
        gate_record.uato_authority_level = uato_in.authority_state.level
        gate_record.uato_decision_version = uato_res.decision_version
        gate_record.uato_input_hash = uato_trace["uato_input_hash"]
        gate_record.uato_evaluated_at = uato_evaluated_at
        await session.flush()
        task.audit_history = task.audit_history or []
        task.audit_history.append(
            {
                "event_type": "evaluation_frame_resumed",
                "payload": {"shared_state_hash": frame.shared_state_hash, "frame_status": "PASS"},
            },
        )
        flag_modified(task, "audit_history")
    else:
        task = Task(
            ocgg_identity=body.ocgg_identity,
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version=decision.policy_version,
            gate_outcome=decision.outcome.value,
            governance_outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
            plan_json=plan_json,
            audit_history=_frame_pass_audit_entries(
                trace_id=trace_id,
                shared_state_hash=frame.shared_state_hash,
                ic_res=ic_res,
                uato_trace=uato_trace,
                ie_frame_trace=ie_frame_trace,
            ),
            status=TaskStatus.submitted,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
        )
        session.add(task)
        await session.flush()
        gate_record = GateDecisionRecord(
            task_id=task.task_id,
            ocgg_identity=body.ocgg_identity,
            outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
            defect_list=[{"code": d.code, "field": d.field, "message": d.message} for d in decision.defect_list],
            policy_version=decision.policy_version,
            spec_hash=spec_hash,
            plan_hash=plan_hash,
            approver_id=decision.approver_id,
            trace_id=trace_id,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            uato_trust_level=uato_in.trust_state.level,
            uato_authority_level=uato_in.authority_state.level,
            uato_decision_version=uato_res.decision_version,
            uato_input_hash=uato_trace["uato_input_hash"],
            uato_evaluated_at=uato_evaluated_at,
        )
        session.add(gate_record)
    await session.commit()
    await session.refresh(task)
    task.audit_history = task.audit_history or []
    task.audit_history.append({"event_type": "gate_decision", "payload": {"outcome": decision.outcome.value, "reason_codes": decision.reason_codes}})
    flag_modified(task, "audit_history")
    await session.commit()

    if decision.outcome.value != "PASS":
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome=decision.outcome.value,
            governance_outcome=decision.outcome.value,
            reason_codes=decision.reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
        )

    inv_env = build_execution_envelope(
        spec=spec,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        task_id=task.task_id,
        governance_outcome=decision.outcome.value,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
    )
    ie_res = evaluate_invariant_e(inv_env)
    ie_evaluated_at = datetime.utcnow()
    ie_trace = ie_to_trace(inv_env, ie_res)
    ie_hash = ie_trace["invariant_e_input_hash"]

    task.invariant_e_decision = ie_res.decision
    task.invariant_e_reason_codes = list(ie_res.reason_codes)
    task.invariant_e_decision_version = ie_res.decision_version
    task.invariant_e_input_hash = ie_hash
    task.invariant_e_evaluated_at = ie_evaluated_at
    task.execution_envelope_hash = ie_hash
    task.requested_capabilities_json = list(inv_env.requested_capabilities)
    task.allowed_capabilities_json = list(inv_env.allowed_capabilities)
    task.budget_limit_json = inv_env.budget_limit
    task.dispatch_blocked = ie_res.dispatch_blocked

    gate_record.invariant_e_decision = ie_res.decision
    gate_record.invariant_e_reason_codes = list(ie_res.reason_codes)
    gate_record.invariant_e_decision_version = ie_res.decision_version
    gate_record.invariant_e_input_hash = ie_hash
    gate_record.invariant_e_evaluated_at = ie_evaluated_at
    gate_record.execution_envelope_hash = ie_hash
    gate_record.requested_capabilities_json = list(inv_env.requested_capabilities)
    gate_record.allowed_capabilities_json = list(inv_env.allowed_capabilities)
    gate_record.budget_limit_json = inv_env.budget_limit
    gate_record.dispatch_blocked = ie_res.dispatch_blocked

    task.audit_history = task.audit_history or []
    task.audit_history.append(
        {
            "event_type": "invariant_e_decision",
            "payload": {**ie_trace, "upstream_gate": "INVARIANT_E", "admissibility_source": "INVARIANT_E"},
        }
    )
    flag_modified(task, "audit_history")

    if ie_res.decision != "EXECUTION_ALLOWED":
        task.reason_codes = [c for c in ie_res.reason_codes if c != "IE_ALLOWED"]
        task.status = TaskStatus.invariant_e_denied
        await session.commit()
        await session.refresh(task)
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            gate_outcome=_effective_gate_outcome_for_response(
                governance_outcome=decision.outcome.value,
                execution_denied=True,
            ),
            governance_outcome=decision.outcome.value,
            reason_codes=task.reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=True,
        )

    await session.commit()

    execution_token = generate_execution_token({
        "spec_hash": spec_hash,
        "plan_hash": plan_hash,
        "policy_version": decision.policy_version,
        "ocgg_identity": body.ocgg_identity,
        "outcome": "PASS",
        "trace_id": trace_id,
    })
    token_hash = hash_token(execution_token)
    verified, _ = verify_execution_token(execution_token)
    if not verified:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            governance_outcome="PASS",
            reason_codes=["EXECUTION_TOKEN_INVALID"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=False,
        )
    if get_policy_version_at_execution() != decision.policy_version:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            governance_outcome="PASS",
            reason_codes=["RE_EVALUATION_REQUIRED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=False,
        )
    existing = await session.get(UsedExecutionToken, token_hash)
    if existing:
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            governance_outcome="PASS",
            reason_codes=["TOKEN_ALREADY_USED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=False,
        )
    used = UsedExecutionToken(token_hash=token_hash, task_id=task.task_id)
    session.add(used)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return _task_submit_response(
            task_id=task.task_id,
            status=TaskStatus.submitted.value,
            trace_id=trace_id,
            gate_outcome="BLOCK",
            governance_outcome="PASS",
            reason_codes=["TOKEN_ALREADY_USED"],
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=False,
        )
    gate_record.execution_token_hash = token_hash
    task.execution_token_hash = token_hash
    await session.commit()

    try:
        client = OpenClawClient()
        result = await client.execute(plan_json, execution_token, task_id=str(task.task_id))
    except OpenClawError as e:
        try:
            task.status = TaskStatus(e.error_type)
        except ValueError:
            task.status = TaskStatus.error
        task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": e.response}]
        if e.response.get("execution_id"):
            task.execution_id = e.response["execution_id"]
        await session.commit()
        reason_codes = ["EXECUTION_ABORTED"] if e.error_type == "execution_aborted" else []
        return _task_submit_response(
            task_id=task.task_id,
            status=task.status.value,
            trace_id=trace_id,
            execution_response=e.response,
            gate_outcome="PASS",
            governance_outcome="PASS",
            reason_codes=reason_codes,
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            invariant_e_decision=ie_res.decision,
            invariant_e_reason_codes=list(ie_res.reason_codes),
            dispatch_blocked=False,
        )
    task.execution_id = result.get("execution_id")
    s = result.get("status")
    if s == "success":
        task.status = TaskStatus.completed
    elif s in ("failed", "partial", "needs_review"):
        task.status = TaskStatus(s)
    else:
        task.status = TaskStatus.failed
    task.audit_history = (task.audit_history or []) + [{"event_type": "execution_response", "payload": result}]
    await session.commit()
    return _task_submit_response(
        task_id=task.task_id,
        execution_id=task.execution_id,
        status=task.status.value,
        trace_id=trace_id,
        execution_response=result,
        gate_outcome="PASS",
        governance_outcome="PASS",
        reason_codes=[],
        uato_decision=uato_res.decision,
        uato_reason_codes=list(uato_res.reason_codes),
        invariant_e_decision=ie_res.decision,
        invariant_e_reason_codes=list(ie_res.reason_codes),
        dispatch_blocked=False,
    )
