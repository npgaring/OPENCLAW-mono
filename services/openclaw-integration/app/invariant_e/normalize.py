"""Deterministic normalization for Invariant-E (no plan mutation)."""
from __future__ import annotations

from typing import Any

from app.invariant_e.types import ExecutionEnvelope, INVARIANT_E_DECISION_VERSION


def normalize_capability_token(op_type: str) -> str:
    t = (op_type or "").strip().lower()
    return f"op:{t}"


def normalize_requested_capabilities(operations: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    caps: list[str] = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        raw = op.get("type")
        if raw is None:
            continue
        caps.append(normalize_capability_token(str(raw)))
    return tuple(sorted(set(caps)))


def normalize_envelope(envelope: ExecutionEnvelope) -> ExecutionEnvelope:
    """Return a copy with sorted capability tuples and stripped strings (frozen replace)."""
    tid = (envelope.trace_id or "").strip()
    ident = (envelope.identity or "").strip() if envelope.identity else None
    tenant = (envelope.tenant_id or "").strip() if envelope.tenant_id else None
    ph = (envelope.plan_hash or "").strip() if envelope.plan_hash else None
    sh = (envelope.spec_hash or "").strip() if envelope.spec_hash else None
    go = (envelope.governance_outcome or "").strip().upper()
    dt = (envelope.deployment_target or "").strip().lower() if envelope.deployment_target else None
    ar = envelope.approval_reference.strip() if isinstance(envelope.approval_reference, str) and envelope.approval_reference.strip() else None
    ap = envelope.approver_id.strip() if isinstance(envelope.approver_id, str) and envelope.approver_id.strip() else None
    req = tuple(sorted(set(envelope.requested_capabilities)))
    allow = tuple(sorted(set(envelope.allowed_capabilities)))
    ops = tuple(dict(o) if isinstance(o, dict) else {} for o in envelope.operations)
    return ExecutionEnvelope(
        trace_id=tid,
        task_id=envelope.task_id,
        tenant_id=tenant or None,
        identity=ident or None,
        plan_hash=ph or None,
        spec_hash=sh or None,
        governance_outcome=go,
        approval_reference=ar,
        approver_id=ap,
        deployment_target=dt,
        operations=ops,
        requested_capabilities=req,
        allowed_capabilities=allow,
        budget_limit=envelope.budget_limit,
        network_scope=dict(envelope.network_scope) if envelope.network_scope else None,
        filesystem_scope=dict(envelope.filesystem_scope) if envelope.filesystem_scope else None,
        runtime_context=dict(envelope.runtime_context) if envelope.runtime_context else None,
    )


def envelope_fingerprint_for_hash(envelope: ExecutionEnvelope) -> dict[str, Any]:
    """JSON-serializable stable material for hashing (replay)."""
    return {
        "version": INVARIANT_E_DECISION_VERSION,
        "trace_id": envelope.trace_id,
        "task_id": envelope.task_id,
        "tenant_id": envelope.tenant_id,
        "identity": envelope.identity,
        "plan_hash": envelope.plan_hash,
        "spec_hash": envelope.spec_hash,
        "governance_outcome": envelope.governance_outcome,
        "approval_reference": envelope.approval_reference,
        "approver_id": envelope.approver_id,
        "deployment_target": envelope.deployment_target,
        "requested_capabilities": list(envelope.requested_capabilities),
        "allowed_capabilities": list(envelope.allowed_capabilities),
        "budget_limit": envelope.budget_limit,
        "network_scope": envelope.network_scope,
        "filesystem_scope": envelope.filesystem_scope,
        "runtime_context": envelope.runtime_context,
    }
