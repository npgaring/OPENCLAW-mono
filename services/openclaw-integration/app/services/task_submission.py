"""Core POST /task pipeline: UATO → GateEngine → Invariant-E → token → OpenClaw."""
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
from app.gate.engine import GateEngine
from app.gate.policy import get_policy_version_at_execution
from app.gate.token import generate_execution_token, hash_token, verify_execution_token
from app.models import GateDecisionRecord, Task, TaskStatus, TaskSubmitRequest, TaskSubmitResponse, UsedExecutionToken
from app.models.approval_request import ApprovalSourceLayer
from app.services.approvals_service import create_approval_request_for_stop
from app.services.execution_client import OpenClawClient, OpenClawError
from app.uato import build_uato_input_from_spec, evaluate_uato, to_trace_record
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


async def _latest_gate_record(session: AsyncSession, task_id: UUID) -> Optional[GateDecisionRecord]:
    stmt = (
        select(GateDecisionRecord)
        .where(GateDecisionRecord.task_id == task_id)
        .order_by(GateDecisionRecord.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


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
    spec = body.model_dump()
    spec.pop("trace_id", None)
    spec.pop("uato", None)

    uato_in = build_uato_input_from_spec(
        spec,
        ocgg_identity=body.ocgg_identity,
        trace_id=trace_id,
        uato_hints=body.uato,
    )
    uato_res = evaluate_uato(uato_in)
    uato_evaluated_at = datetime.utcnow()
    uato_trace = to_trace_record(uato_in, uato_res)

    if uato_res.decision != "PASS":
        if reuse_task_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "UATO_RESUME_FAILED",
                    "message": "Resume requires UATO PASS; admissibility still blocked.",
                    "uato_decision": uato_res.decision,
                    "reason_codes": list(uato_res.reason_codes),
                },
            )
        plan_json, plan_hash, spec_hash = integration_plan_preview(spec, body.ocgg_identity)
        if uato_res.decision == "ESCALATE":
            short_status = TaskStatus.needs_review
        elif uato_res.decision == "REQUIRE_APPROVAL":
            short_status = TaskStatus.pending_approval
        elif uato_res.decision == "BLOCK":
            short_status = TaskStatus.uato_blocked
        else:
            short_status = TaskStatus.uato_blocked
        task = Task(
            ocgg_identity=body.ocgg_identity,
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version=UATO_DECISION_VERSION,
            gate_outcome="BLOCK",
            reason_codes=list(uato_res.reason_codes),
            plan_json=plan_json,
            audit_history=[
                {
                    "event_type": "uato_decision",
                    "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO"},
                }
            ],
            status=short_status,
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
            outcome="BLOCK",
            reason_codes=list(uato_res.reason_codes),
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
        )
        session.add(gate_record)
        await session.commit()
        await session.refresh(task)

        extra: dict[str, Any] = {}
        if uato_res.decision == "REQUIRE_APPROVAL":
            ar = await create_approval_request_for_stop(
                session,
                trace_id=trace_id,
                task_id=task.task_id,
                source_layer=ApprovalSourceLayer.UATO,
                reason_code=uato_res.reason_codes[0] if uato_res.reason_codes else "REQUIRE_APPROVAL",
                resume_from_stage="POST_UATO_RESUME",
                task_submit_body=body,
                trace_id_for_body=trace_id,
                approval_scope="uato_require_approval",
            )
            task.approval_request_id = ar.id
            task.blocked_stage = "UATO"
            task.audit_history = task.audit_history or []
            task.audit_history.append(
                {
                    "event_type": "approval_requested",
                    "payload": {
                        "approval_request_id": str(ar.id),
                        "source_layer": "UATO",
                        "trace_id": trace_id,
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
            reason_codes=list(uato_res.reason_codes),
            uato_decision=uato_res.decision,
            uato_reason_codes=list(uato_res.reason_codes),
            **extra,
        )

    engine = GateEngine()
    evaluation = engine.evaluate(spec, body.ocgg_identity)
    decision = evaluation.decision
    plan_json = evaluation.plan_json
    spec_hash = evaluation.spec_hash
    plan_hash = evaluation.plan_hash

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
            audit_history=[
                {
                    "event_type": "uato_decision",
                    "payload": {**uato_trace, "upstream_gate": "UATO", "admissibility_source": "UATO"},
                }
            ],
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
        if "PROD_DEPLOY_NO_APPROVAL" in decision.reason_codes and not reuse_task_id:
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
                }
            )
            flag_modified(task, "audit_history")
            await session.commit()
            await session.refresh(task)
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
