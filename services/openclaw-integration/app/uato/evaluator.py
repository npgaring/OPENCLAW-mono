"""Pure deterministic UATO admissibility evaluation (no I/O, no governance policy)."""
from __future__ import annotations

from app.uato import reason_codes as rc
from app.uato.normalize import minimal_plan_admissibility_issues
from app.uato.types import UATO_DECISION_VERSION, UatoDecision, UatoInput, UatoResult


def evaluate_uato(inp: UatoInput) -> UatoResult:
    """
    Trust × authority matrix (fail-closed on invalid binding / malformed plan):
    - LOW + LOW  -> BLOCK
    - LOW + HIGH -> ESCALATE
    - HIGH + LOW -> REQUIRE_APPROVAL
    - HIGH + HIGH -> PASS
    """
    trace_id = inp.context.trace_id
    t = inp.trust_state.level
    a = inp.authority_state.level

    if not trace_id or not str(trace_id).strip():
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_INVALID_INPUT,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=str(trace_id or ""),
        )

    if not isinstance(inp.plan, dict):
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_INVALID_INPUT,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=trace_id,
        )

    shape_issues = minimal_plan_admissibility_issues(inp.plan)
    if shape_issues:
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_MALFORMED_PLAN,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=trace_id,
        )

    if not inp.authority_state.identity_bound:
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_IDENTITY_NOT_BOUND,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=trace_id,
        )

    if not inp.authority_state.tenant_match:
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_TENANT_MISMATCH,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=trace_id,
        )

    if t not in ("LOW", "HIGH") or a not in ("LOW", "HIGH"):
        return UatoResult(
            decision="BLOCK",
            reason_codes=(rc.UATO_BLOCK_INVALID_INPUT,),
            decision_version=UATO_DECISION_VERSION,
            requires_human_approval=False,
            trace_id=trace_id,
        )

    decision: UatoDecision
    reasons: tuple[str, ...]
    requires_human: bool

    if t == "LOW" and a == "LOW":
        decision = "BLOCK"
        reasons = (rc.UATO_BLOCK_LOW_TRUST_LOW_AUTHORITY,)
        requires_human = False
    elif t == "LOW" and a == "HIGH":
        decision = "ESCALATE"
        reasons = (rc.UATO_ESCALATE_LOW_TRUST_HIGH_AUTHORITY,)
        requires_human = True
    elif t == "HIGH" and a == "LOW":
        decision = "REQUIRE_APPROVAL"
        reasons = (rc.UATO_REQUIRE_APPROVAL_HIGH_TRUST_LOW_AUTHORITY,)
        requires_human = True
    else:
        decision = "PASS"
        reasons = (rc.UATO_PASS_HIGH_TRUST_HIGH_AUTHORITY,)
        requires_human = False

    return UatoResult(
        decision=decision,
        reason_codes=reasons,
        decision_version=UATO_DECISION_VERSION,
        requires_human_approval=requires_human,
        trace_id=trace_id,
    )
