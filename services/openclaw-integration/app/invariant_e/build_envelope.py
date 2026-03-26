"""Build ExecutionEnvelope from integration spec + governance PASS artifacts (no I/O)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.identity import IDENTITY_ALLOWED_OPERATIONS
from app.gate.policy import (
    ALLOWED_TARGET_DOMAINS,
    ALLOWED_WRITE_ROOT,
    POLICY_VERSION,
)
from app.invariant_e.normalize import normalize_capability_token, normalize_requested_capabilities
from app.invariant_e.types import ExecutionEnvelope


def _allowed_capabilities_for_identity(ocgg_identity: str) -> tuple[str, ...]:
    base = IDENTITY_ALLOWED_OPERATIONS.get(ocgg_identity, set())
    caps = {normalize_capability_token(x) for x in base}
    extra = settings.invariant_e_allowed_capabilities_extra or ""
    for part in extra.split(","):
        p = part.strip()
        if not p:
            continue
        pl = p.lower()
        if pl.startswith("op:"):
            caps.add(pl)
        else:
            caps.add(normalize_capability_token(pl))
    return tuple(sorted(caps))


def build_execution_envelope(
    *,
    spec: dict[str, Any],
    ocgg_identity: str,
    trace_id: str,
    task_id: UUID | str | None,
    governance_outcome: str,
    plan_hash: str,
    spec_hash: str,
    validation_controls: Any = None,
) -> ExecutionEnvelope:
    """
    Canonical envelope for post-governance execution admission.

    ``spec`` is the same dict passed to ``GateEngine.evaluate`` (after model_dump / trace_id pop).
    """
    tid: str | None = None
    if task_id is not None:
        tid = str(task_id)
    ops_list = spec.get("operations") or []
    ops: tuple[dict[str, Any], ...] = tuple(o for o in ops_list if isinstance(o, dict))
    req_caps = normalize_requested_capabilities(ops)
    allow_caps = _allowed_capabilities_for_identity(ocgg_identity)
    dispatch_scenario = getattr(validation_controls, "dispatch_boundary_scenario", None)
    if isinstance(validation_controls, dict):
        dispatch_scenario = validation_controls.get("dispatch_boundary_scenario", dispatch_scenario)
    if governance_outcome == "PASS" and dispatch_scenario == "PASS_GOV_FAIL_INVARIANT_E_CAPABILITY":
        # Bounded deterministic scenario for dispatch-boundary validation:
        # keep requested capabilities from real operations, but no allowed capabilities at dispatch.
        allow_caps = tuple()

    dep = spec.get("deployment_target")
    dep_s = str(dep).strip().lower() if dep is not None else None

    ar = spec.get("approval_reference")
    ar_s = str(ar).strip() if ar is not None and str(ar).strip() else None
    ap = spec.get("approver_id")
    ap_s = str(ap).strip() if ap is not None and str(ap).strip() else None

    bl = spec.get("budget_limit")
    budget: dict[str, Any] | None
    if isinstance(bl, dict):
        budget = dict(bl)
    else:
        budget = None

    net_scope = {"allowed_target_domains": sorted(ALLOWED_TARGET_DOMAINS)}
    fs_scope = {"allowed_write_root": ALLOWED_WRITE_ROOT}

    rc: dict[str, Any] = {
        "integration_policy_version": POLICY_VERSION,
    }

    return ExecutionEnvelope(
        trace_id=trace_id,
        task_id=tid,
        tenant_id=ocgg_identity,
        identity=ocgg_identity,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        governance_outcome=governance_outcome,
        approval_reference=ar_s,
        approver_id=ap_s,
        deployment_target=dep_s,
        operations=ops,
        requested_capabilities=req_caps,
        allowed_capabilities=allow_caps,
        budget_limit=budget,
        network_scope=net_scope,
        filesystem_scope=fs_scope,
        runtime_context=rc,
    )
