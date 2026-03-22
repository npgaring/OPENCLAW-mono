"""Pure deterministic Invariant-E execution admission (no I/O, no governance re-evaluation)."""
from __future__ import annotations

from app.core.config import settings
from app.gate.policy import FORBIDDEN_OPERATION_TYPES, PROD_DEPLOYMENT_TARGETS
from app.invariant_e import reason_codes as rc
from app.invariant_e.normalize import normalize_envelope
from app.invariant_e.types import ExecutionEnvelope, InvariantEResult, result_allowed, result_denied


def evaluate_invariant_e(envelope: ExecutionEnvelope) -> InvariantEResult:
    """
    Phase 1: returns EXECUTION_ALLOWED or EXECUTION_DENIED only.

    EXECUTION_TERMINATED is reserved for downstream signals (see types module TODO).
    """
    e = normalize_envelope(envelope)
    trace_id = e.trace_id

    if e.governance_outcome != "PASS":
        return result_denied(trace_id, (rc.IE_DENIED_GOVERNANCE_NOT_PASS,))

    if not trace_id:
        return result_denied(trace_id, (rc.IE_DENIED_MISSING_TRACE,))

    if not e.identity:
        return result_denied(trace_id, (rc.IE_DENIED_INVALID_ENVELOPE,))

    if e.tenant_id and e.identity and e.tenant_id != e.identity:
        return result_denied(trace_id, (rc.IE_DENIED_IDENTITY_TENANT_MISMATCH,))

    if not e.plan_hash:
        return result_denied(trace_id, (rc.IE_DENIED_MISSING_PLAN_HASH,))

    if not e.spec_hash:
        return result_denied(trace_id, (rc.IE_DENIED_MISSING_SPEC_HASH,))

    if not e.operations:
        return result_denied(trace_id, (rc.IE_DENIED_EMPTY_OPERATIONS,))

    deployment_target = (e.deployment_target or "").lower()
    if deployment_target in PROD_DEPLOYMENT_TARGETS:
        if not (e.approver_id or e.approval_reference):
            return result_denied(trace_id, (rc.IE_DENIED_PROD_APPROVAL_REQUIRED,))

    allowed_set = set(e.allowed_capabilities)
    for cap in e.requested_capabilities:
        if cap not in allowed_set:
            return result_denied(trace_id, (rc.IE_DENIED_CAPABILITY_NOT_ALLOWED,))

    if settings.invariant_e_require_budget_limit:
        bl = e.budget_limit
        if not bl or (isinstance(bl, dict) and len(bl) == 0):
            return result_denied(trace_id, (rc.IE_DENIED_BUDGET_REQUIRED,))

    for op in e.operations:
        if not isinstance(op, dict):
            continue
        ot = op.get("type") or ""
        if ot in FORBIDDEN_OPERATION_TYPES:
            return result_denied(trace_id, (rc.IE_DENIED_FORBIDDEN_OPERATION,))

    return result_allowed(trace_id)
