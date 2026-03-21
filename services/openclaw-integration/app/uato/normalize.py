"""Deterministic normalization for UATO evaluation (no policy, no plan mutation)."""
from __future__ import annotations

from typing import Any

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.uato.types import (
    AuthorityLevel,
    AuthorityState,
    TrustLevel,
    TrustSource,
    TrustState,
    UatoContext,
    UatoInput,
)


def canonical_plan_fingerprint(plan: dict[str, Any]) -> dict[str, Any]:
    """Stable subset of the integration spec for hashing (ignores noisy/extra keys)."""
    keys = (
        "ocgg_identity",
        "plan_hash",
        "operations",
        "deployment_target",
        "goal",
        "context",
        "acceptance_criteria",
        "approver_id",
        "approval_reference",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in plan:
            out[k] = plan[k]
    return out


def normalize_trust_state(
    *,
    level: TrustLevel,
    source: TrustSource,
    evidence: list[str] | tuple[str, ...] | None,
) -> TrustState:
    ev = tuple(sorted(set(evidence or ())))
    return TrustState(level=level, source=source, evidence=ev)


def normalize_authority_state(
    *,
    level: AuthorityLevel,
    tenant_match: bool,
    identity_bound: bool,
    approval_capable: bool,
    requested_scope: list[str] | tuple[str, ...],
    granted_scope: list[str] | tuple[str, ...],
) -> AuthorityState:
    return AuthorityState(
        level=level,
        tenant_match=tenant_match,
        identity_bound=identity_bound,
        approval_capable=approval_capable,
        requested_scope=tuple(requested_scope),
        granted_scope=tuple(granted_scope),
    )


def normalize_uato_context(
    *,
    environment: str,
    tenant_id: str,
    request_source: str,
    trace_id: str,
) -> UatoContext | None:
    env_map = {"dev": "dev", "development": "dev", "staging": "staging", "preview": "staging", "prod": "prod", "production": "prod"}
    e = env_map.get((environment or "").lower())
    if e not in ("dev", "staging", "prod"):
        return None
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    rs = (request_source or "API").upper()
    if rs == "OPENAI_VESSEL":
        src: Any = "OPENAI_VESSEL"
    elif rs == "SYSTEM":
        src = "SYSTEM"
    else:
        src = "API"
    tid_trace = (trace_id or "").strip()
    if not tid_trace:
        return None
    return UatoContext(
        environment=e,  # type: ignore[arg-type]
        tenant_id=tid,
        request_source=src,  # type: ignore[arg-type]
        trace_id=tid_trace,
    )


def derive_requested_scope(operations: Any) -> list[str]:
    if not isinstance(operations, list):
        return []
    scopes: list[str] = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            continue
        t = op.get("type") or ""
        tgt = op.get("target") or ""
        scopes.append(f"{i}:{t}:{tgt}")
    return sorted(scopes)


def derive_identity_bound(ocgg_identity: str) -> bool:
    return ocgg_identity in IDENTITY_DOMAIN_MAP


def build_normalized_uato_input(
    *,
    plan: dict[str, Any],
    trust_state: TrustState,
    authority_state: AuthorityState,
    context: UatoContext,
) -> UatoInput:
    return UatoInput(plan=plan, trust_state=trust_state, authority_state=authority_state, context=context)


def stable_hash_uato_material(material: dict[str, Any]) -> str:
    """Deterministic hash input for audit (hex digest length via hash_payload)."""
    from app.core.security import hash_payload

    return hash_payload(material)


def minimal_plan_admissibility_issues(plan: dict[str, Any]) -> list[str]:
    """
    Fail-closed checks on the integration spec shape (same dict as GateEngine.evaluate).
    Does not enforce governance policy hashes or operation semantics — only presence/shape.
    """
    issues: list[str] = []
    ph = plan.get("plan_hash")
    if ph is None or (isinstance(ph, str) and not ph.strip()):
        issues.append("missing_or_empty_plan_hash")
    ops = plan.get("operations")
    if ops is None:
        issues.append("missing_operations")
    elif not isinstance(ops, list):
        issues.append("operations_not_list")
    elif len(ops) == 0:
        issues.append("operations_empty")
    return issues
