"""
Set-based aggregation: every law is classified independently; then one final decision is derived.

* If any law is in the **failure** set → ``STOP`` (``failed_laws`` lists all failing laws).
* Else if any law requires **approval** → ``REQUIRE_APPROVAL`` (``approval_sources`` lists all sources).
* Else → ``EXECUTE``.

No sequential priority among laws — all are scanned before composing the outcome.
"""
from __future__ import annotations

from typing import Literal, Optional

from app.core.config import settings
from app.evaluation.models import (
    AtomicEvaluationResult,
    AtomicFinalDecision,
    LawEvaluationRecord,
    LawId,
    standard_evaluator_input_hashes,
)
from app.evaluation.state import EvaluationState
from app.evaluation_frame.state import CompositeFrameResult, FrameStatus
from app.gate.models import GateEvaluation, GateOutcome
from app.invariant_c.evaluator import InvariantCResult
from app.invariant_e.types import InvariantEResult
from app.uato.types import UatoResult


def _law_records(
    ic: InvariantCResult,
    uato: UatoResult,
    ie: InvariantEResult,
    grl: GateEvaluation,
) -> tuple[LawEvaluationRecord, ...]:
    d = grl.decision
    grl_passed = d.outcome == GateOutcome.PASS
    return (
        LawEvaluationRecord(
            law_id=LawId.INVARIANT_C.value,
            passed=ic.decision == "PASS",
            reason_codes=tuple(ic.reason_codes),
            policy_or_version=ic.decision_version,
        ),
        LawEvaluationRecord(
            law_id=LawId.UATO.value,
            passed=uato.decision == "PASS",
            reason_codes=tuple(uato.reason_codes),
            policy_or_version=uato.decision_version,
        ),
        LawEvaluationRecord(
            law_id=LawId.GRL.value,
            passed=grl_passed,
            reason_codes=tuple(d.reason_codes),
            policy_or_version=d.policy_version,
            extra={
                "defect_list": [{"code": x.code, "field": x.field, "message": x.message} for x in d.defect_list],
                "spec_hash": d.spec_hash,
                "plan_hash": d.plan_hash,
            },
        ),
        LawEvaluationRecord(
            law_id=LawId.INVARIANT_E_DECISION.value,
            passed=ie.decision == "EXECUTION_ALLOWED",
            reason_codes=tuple(ie.reason_codes),
            policy_or_version=ie.decision_version,
        ),
    )


def merged_reason_codes_from_records(records: tuple[LawEvaluationRecord, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for lr in records:
        merged.extend(lr.reason_codes)
    return tuple(dict.fromkeys(merged))


def aggregate_atomic(
    state: EvaluationState,
    ic: InvariantCResult,
    uato: UatoResult,
    ie: InvariantEResult,
    grl: GateEvaluation,
) -> tuple[
    AtomicFinalDecision,
    tuple[str, ...],
    tuple[str, ...],
    Optional[Literal["STANDARD", "ESCALATION"]],
    tuple[LawEvaluationRecord, ...],
]:
    records = _law_records(ic, uato, ie, grl)
    failed: list[str] = []
    approvals: list[str] = []

    if ic.decision != "PASS":
        failed.append(LawId.INVARIANT_C.value)
    if uato.decision == "BLOCK":
        failed.append(LawId.UATO.value)
    elif uato.decision == "REQUIRE_APPROVAL":
        approvals.append("UATO_STANDARD")
    elif uato.decision == "ESCALATE":
        approvals.append("UATO_ESCALATION")

    d = grl.decision
    if d.outcome == GateOutcome.PASS:
        pass
    elif d.outcome in (GateOutcome.REFORM, GateOutcome.CLARIFY):
        approvals.append("GRL_CONDITIONAL")
    elif "PROD_DEPLOY_NO_APPROVAL" in d.reason_codes:
        approvals.append("GRL_PROD_DEPLOY")
    else:
        failed.append(LawId.GRL.value)

    if ie.decision != "EXECUTION_ALLOWED":
        failed.append(LawId.INVARIANT_E_DECISION.value)

    uato_kind: Optional[Literal["STANDARD", "ESCALATION"]] = None
    if "UATO_ESCALATION" in approvals:
        uato_kind = "ESCALATION"
    elif "UATO_STANDARD" in approvals:
        uato_kind = "STANDARD"

    failed_t = tuple(failed)
    appr_t = tuple(approvals)

    if failed_t:
        return AtomicFinalDecision.STOP, failed_t, appr_t, uato_kind, records
    if appr_t:
        return AtomicFinalDecision.REQUIRE_APPROVAL, failed_t, appr_t, uato_kind, records
    return AtomicFinalDecision.EXECUTE, failed_t, appr_t, uato_kind, records


def frame_status_from_final_decision(fd: AtomicFinalDecision) -> FrameStatus:
    """Single mapping: authoritative decision → frame_status (no law subset overrides)."""
    if fd == AtomicFinalDecision.EXECUTE:
        return FrameStatus.PASS
    if fd == AtomicFinalDecision.REQUIRE_APPROVAL:
        return FrameStatus.APPROVAL_REQUIRED
    return FrameStatus.BLOCKED


def composite_frame_from_atomic(atomic: AtomicEvaluationResult) -> CompositeFrameResult:
    """
    Truthful composite: ``frame_status`` is derived only from ``atomic.final_decision``.
    """
    ic, uato, ie = atomic.invariant_c, atomic.uato, atomic.invariant_e_decision
    status = frame_status_from_final_decision(atomic.final_decision)
    reason_tuple = merged_reason_codes_from_records(atomic.law_records)

    approvable_uato = bool(
        atomic.final_decision == AtomicFinalDecision.REQUIRE_APPROVAL and "UATO_STANDARD" in atomic.approval_sources
    )
    admissible = atomic.final_decision == AtomicFinalDecision.EXECUTE
    approval_required = atomic.final_decision == AtomicFinalDecision.REQUIRE_APPROVAL

    fr = CompositeFrameResult(
        frame_status=status,
        admissible=admissible,
        approval_required=approval_required,
        approvable_via_uato=approvable_uato,
        invariant_c_result=ic,
        uato_result=uato,
        invariant_e_result=ie,
        reason_codes=reason_tuple,
        trace_id=atomic.trace_id,
        shared_state_hash=atomic.shared_state_hash,
    )

    if (settings.app_env or "").lower() not in ("production", "prod"):
        assert fr.frame_status == frame_status_from_final_decision(atomic.final_decision), (
            "frame_status drift from final_decision"
        )
    return fr


def build_atomic_evaluation_result(
    state: EvaluationState,
    ic: InvariantCResult,
    uato: UatoResult,
    ie: InvariantEResult,
    grl: GateEvaluation,
) -> AtomicEvaluationResult:
    fd, failed, appr, uato_kind, law_records = aggregate_atomic(state, ic, uato, ie, grl)
    g = state.governable
    ev_hashes = standard_evaluator_input_hashes(state.state_hash)
    return AtomicEvaluationResult(
        state_hash=state.state_hash,
        trace_id=g.trace_id,
        shared_state_hash=g.shared_state_hash,
        invariant_c=ic,
        uato=uato,
        invariant_e_decision=ie,
        grl=grl,
        final_decision=fd,
        failed_laws=failed,
        approval_sources=appr,
        law_records=law_records,
        evaluator_input_hashes=ev_hashes,
        uato_approval_kind=uato_kind,
    )


def build_composite_frame_result(
    state: EvaluationState,
    ic: InvariantCResult,
    uato: UatoResult,
    ie: InvariantEResult,
) -> CompositeFrameResult:
    """Deprecated: synthesizes C/UATO/E only (tests); not used for production routes."""
    g = state.governable
    reason_tuple = merged_reason_codes_from_records(
        (
            LawEvaluationRecord(LawId.INVARIANT_C.value, ic.decision == "PASS", tuple(ic.reason_codes), ic.decision_version),
            LawEvaluationRecord(LawId.UATO.value, uato.decision == "PASS", tuple(uato.reason_codes), uato.decision_version),
            LawEvaluationRecord(LawId.INVARIANT_E_DECISION.value, ie.decision == "EXECUTION_ALLOWED", tuple(ie.reason_codes), ie.decision_version),
        )
    )
    c_ok = ic.decision == "PASS"
    e_ok = ie.decision == "EXECUTION_ALLOWED"
    u_dec = uato.decision

    if not c_ok:
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic,
            uato_result=uato,
            invariant_e_result=ie,
            reason_codes=reason_tuple,
            trace_id=g.trace_id,
            shared_state_hash=g.shared_state_hash,
        )
    if not e_ok:
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic,
            uato_result=uato,
            invariant_e_result=ie,
            reason_codes=reason_tuple,
            trace_id=g.trace_id,
            shared_state_hash=g.shared_state_hash,
        )
    if u_dec == "BLOCK":
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic,
            uato_result=uato,
            invariant_e_result=ie,
            reason_codes=reason_tuple,
            trace_id=g.trace_id,
            shared_state_hash=g.shared_state_hash,
        )
    if u_dec == "ESCALATE":
        return CompositeFrameResult(
            frame_status=FrameStatus.APPROVAL_REQUIRED,
            admissible=False,
            approval_required=True,
            approvable_via_uato=False,
            invariant_c_result=ic,
            uato_result=uato,
            invariant_e_result=ie,
            reason_codes=reason_tuple,
            trace_id=g.trace_id,
            shared_state_hash=g.shared_state_hash,
        )
    if u_dec == "REQUIRE_APPROVAL":
        return CompositeFrameResult(
            frame_status=FrameStatus.APPROVAL_REQUIRED,
            admissible=False,
            approval_required=True,
            approvable_via_uato=True,
            invariant_c_result=ic,
            uato_result=uato,
            invariant_e_result=ie,
            reason_codes=reason_tuple,
            trace_id=g.trace_id,
            shared_state_hash=g.shared_state_hash,
        )
    return CompositeFrameResult(
        frame_status=FrameStatus.PASS,
        admissible=True,
        approval_required=False,
        approvable_via_uato=False,
        invariant_c_result=ic,
        uato_result=uato,
        invariant_e_result=ie,
        reason_codes=reason_tuple,
        trace_id=g.trace_id,
        shared_state_hash=g.shared_state_hash,
    )


def defect_dicts_for_gate_stop(atomic: AtomicEvaluationResult) -> list[dict]:
    """When GRL is among failed laws, surface governance defects on BLOCK responses."""
    if LawId.GRL.value not in set(atomic.failed_laws):
        return []
    return [{"code": x.code, "field": x.field, "message": x.message} for x in atomic.grl.decision.defect_list]


def stop_reason_codes_for_api(atomic: AtomicEvaluationResult) -> list[str]:
    """Prefer defects from failed laws (e.g. GRL) for HTTP reason_codes."""
    codes: list[str] = []
    failed_set = set(atomic.failed_laws)
    for lr in atomic.law_records:
        if lr.law_id in failed_set:
            codes.extend(lr.reason_codes)
    if not codes:
        codes = list(merged_reason_codes_from_records(atomic.law_records))
    return list(dict.fromkeys(codes))
