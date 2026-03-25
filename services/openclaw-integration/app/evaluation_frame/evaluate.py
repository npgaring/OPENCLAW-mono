"""
Shared-state evaluation frame: Invariant-C, UATO, and Invariant-E are independent evaluators over the same
read-only SharedGovernableState.

Call order here is fixed (C, then UATO, then Invariant-E) for a straight-line implementation only; it is not a
sequential admissibility pipeline — every law runs to completion before composition, and no result is used to
skip another law inside the frame.
"""
from __future__ import annotations

from app.evaluation_frame.state import CompositeFrameResult, FrameStatus, SharedGovernableState
from app.invariant_c.evaluator import evaluate_invariant_c
from app.invariant_e.build_envelope import build_execution_envelope
from app.invariant_e.evaluator import evaluate_invariant_e_for_frame
from app.uato import build_uato_input_from_spec, evaluate_uato


def run_evaluation_frame(state: SharedGovernableState) -> CompositeFrameResult:
    """
    Evaluate Invariant-C, UATO, and Invariant-E against the same immutable ``state`` snapshot.

    Composite policy (explicit):
    - Invariant-C BLOCK always yields frame BLOCKED (non-approvable).
    - Invariant-E denial always yields frame BLOCKED (non-approvable); UATO approval cannot override.
    - UATO BLOCK yields frame BLOCKED (non-approvable).
    - UATO ESCALATE yields ESCALATED (distinct from approval).
    - UATO REQUIRE_APPROVAL only if C passed and E allowed; otherwise BLOCKED.
    - UATO PASS with C PASS and E allowed yields PASS.
    """
    ic_res = evaluate_invariant_c(
        candidate_plan=state.candidate_plan,
        ocgg_identity=state.ocgg_identity,
        intent=state.intent,
        objective=state.objective,
        context=state.context,
        constraints=state.constraints,
    )

    uato_in = build_uato_input_from_spec(
        state.spec_for_gate,
        ocgg_identity=state.ocgg_identity,
        trace_id=state.trace_id,
        uato_hints=state.uato_hints,
    )
    uato_res = evaluate_uato(uato_in)

    ie_env = build_execution_envelope(
        spec=state.spec_for_gate,
        ocgg_identity=state.ocgg_identity,
        trace_id=state.trace_id,
        task_id=None,
        governance_outcome="PENDING",
        plan_hash=state.plan_hash,
        spec_hash=state.spec_hash,
    )
    ie_res = evaluate_invariant_e_for_frame(ie_env)

    c_ok = ic_res.decision == "PASS"
    e_ok = ie_res.decision == "EXECUTION_ALLOWED"
    u_dec = uato_res.decision

    merged_rc: list[str] = []
    merged_rc.extend(ic_res.reason_codes)
    if not e_ok:
        merged_rc.extend(x for x in ie_res.reason_codes if x not in merged_rc)
    merged_rc.extend(x for x in uato_res.reason_codes if x not in merged_rc)
    reason_tuple = tuple(dict.fromkeys(merged_rc))

    if not c_ok:
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic_res,
            uato_result=uato_res,
            invariant_e_result=ie_res,
            reason_codes=reason_tuple,
            trace_id=state.trace_id,
            shared_state_hash=state.shared_state_hash,
        )

    if not e_ok:
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic_res,
            uato_result=uato_res,
            invariant_e_result=ie_res,
            reason_codes=reason_tuple,
            trace_id=state.trace_id,
            shared_state_hash=state.shared_state_hash,
        )

    if u_dec == "BLOCK":
        return CompositeFrameResult(
            frame_status=FrameStatus.BLOCKED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic_res,
            uato_result=uato_res,
            invariant_e_result=ie_res,
            reason_codes=reason_tuple,
            trace_id=state.trace_id,
            shared_state_hash=state.shared_state_hash,
        )

    if u_dec == "ESCALATE":
        return CompositeFrameResult(
            frame_status=FrameStatus.ESCALATED,
            admissible=False,
            approval_required=False,
            approvable_via_uato=False,
            invariant_c_result=ic_res,
            uato_result=uato_res,
            invariant_e_result=ie_res,
            reason_codes=reason_tuple,
            trace_id=state.trace_id,
            shared_state_hash=state.shared_state_hash,
        )

    if u_dec == "REQUIRE_APPROVAL":
        return CompositeFrameResult(
            frame_status=FrameStatus.APPROVAL_REQUIRED,
            admissible=False,
            approval_required=True,
            approvable_via_uato=True,
            invariant_c_result=ic_res,
            uato_result=uato_res,
            invariant_e_result=ie_res,
            reason_codes=reason_tuple,
            trace_id=state.trace_id,
            shared_state_hash=state.shared_state_hash,
        )

    return CompositeFrameResult(
        frame_status=FrameStatus.PASS,
        admissible=True,
        approval_required=False,
        approvable_via_uato=False,
        invariant_c_result=ic_res,
        uato_result=uato_res,
        invariant_e_result=ie_res,
        reason_codes=reason_tuple,
        trace_id=state.trace_id,
        shared_state_hash=state.shared_state_hash,
    )
