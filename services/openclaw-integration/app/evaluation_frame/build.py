"""Construct SharedGovernableState for task, gate, and adapter entrypoints."""
from __future__ import annotations

from typing import Any, Optional

from app.core.security import hash_payload
from app.evaluation_frame.bridge import (
    default_intent_for_identity,
    operations_from_candidate_plan,
    task_spec_to_candidate_plan,
)
from app.evaluation_frame.state import ApprovalFrameContext, SharedGovernableState
from app.models.openai_flow import CandidatePlan
from app.models.task import TaskSubmitRequest
from app.uato.plan_bridge import integration_plan_preview


def _intent_from_spec(spec: dict[str, Any], ocgg_identity: str) -> str:
    raw = spec.get("intent")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default_intent_for_identity(ocgg_identity)


def _constraints_from_spec(spec: dict[str, Any]) -> Optional[dict[str, Any]]:
    c = spec.get("constraints")
    return c if isinstance(c, dict) else None


def _effective_objective_context_for_invariant_c(spec: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Invariant-C goal coherence requires non-empty objective/context text.
    Integration POST /task payloads often omit ``goal``/``context``; use a stable synthetic objective so the
    frame can run without forcing clients to duplicate narrative fields already implied by operations.
    """
    g = spec.get("goal")
    ctx = spec.get("context")
    gs = str(g).strip() if g is not None else ""
    cs = str(ctx).strip() if ctx is not None else ""
    if gs or cs:
        return (g if gs else None, ctx if cs else None)
    return ("integration-plan-execution", None)


def _shared_state_hash_material(
    *,
    trace_id: str,
    ocgg_identity: str,
    plan_hash: str,
    spec_hash: str,
    intent: str,
    candidate_plan: CandidatePlan,
) -> str:
    return hash_payload(
        {
            "trace_id": trace_id,
            "ocgg_identity": ocgg_identity,
            "plan_hash": plan_hash,
            "spec_hash": spec_hash,
            "intent": intent,
            "candidate_plan": candidate_plan.model_dump(mode="json"),
        }
    )


def build_shared_governable_state_for_task(
    body: TaskSubmitRequest,
    trace_id: str,
    *,
    for_resume: bool = False,
) -> SharedGovernableState:
    spec = body.model_dump(mode="python")
    spec.pop("trace_id", None)
    spec.pop("uato", None)
    spec.setdefault("ocgg_identity", body.ocgg_identity)

    domain_spec = dict(spec)
    plan_json, plan_hash, spec_hash = integration_plan_preview(domain_spec, body.ocgg_identity)

    intent = _intent_from_spec(spec, body.ocgg_identity)
    constraints = _constraints_from_spec(spec)
    eff_obj, eff_ctx = _effective_objective_context_for_invariant_c(spec)
    try:
        candidate_plan = task_spec_to_candidate_plan(domain_spec, ocgg_identity=body.ocgg_identity, intent=intent)
    except (ValueError, KeyError) as e:
        raise ValueError(f"TASK_SPEC_NOT_GOVERNABLE_AS_CANDIDATE: {e}") from e

    approval_ctx: Optional[ApprovalFrameContext] = None
    if for_resume and (body.approval_reference or body.approver_id):
        approval_ctx = ApprovalFrameContext(
            approval_reference=body.approval_reference,
            approver_id=body.approver_id,
        )

    domain = plan_json.get("domain") or ""
    sh = _shared_state_hash_material(
        trace_id=trace_id,
        ocgg_identity=body.ocgg_identity,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        intent=intent,
        candidate_plan=candidate_plan,
    )
    return SharedGovernableState(
        trace_id=trace_id,
        ocgg_identity=body.ocgg_identity,
        domain=str(domain),
        intent=intent,
        objective=eff_obj,
        context=eff_ctx,
        constraints=constraints,
        spec_for_gate=domain_spec,
        plan_json=plan_json,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        candidate_plan=candidate_plan,
        uato_hints=body.uato,
        approval_context=approval_ctx,
        shared_state_hash=sh,
    )


def build_shared_governable_state_for_gate_payload(
    spec: dict[str, Any],
    ocgg_identity: str,
    trace_id: str,
    uato_hints: Any,
) -> SharedGovernableState:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict")
    domain_spec = dict(spec)
    domain_spec.setdefault("ocgg_identity", ocgg_identity)
    plan_json, plan_hash, spec_hash = integration_plan_preview(domain_spec, ocgg_identity)

    intent = _intent_from_spec(domain_spec, ocgg_identity)
    constraints = _constraints_from_spec(domain_spec)
    eff_obj, eff_ctx = _effective_objective_context_for_invariant_c(domain_spec)
    try:
        candidate_plan = task_spec_to_candidate_plan(domain_spec, ocgg_identity=ocgg_identity, intent=intent)
    except (ValueError, KeyError) as e:
        raise ValueError(f"TASK_SPEC_NOT_GOVERNABLE_AS_CANDIDATE: {e}") from e

    sh = _shared_state_hash_material(
        trace_id=trace_id,
        ocgg_identity=ocgg_identity,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        intent=intent,
        candidate_plan=candidate_plan,
    )
    return SharedGovernableState(
        trace_id=trace_id,
        ocgg_identity=ocgg_identity,
        domain=str(plan_json.get("domain") or ""),
        intent=intent,
        objective=eff_obj,
        context=eff_ctx,
        constraints=constraints,
        spec_for_gate=domain_spec,
        plan_json=plan_json,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        candidate_plan=candidate_plan,
        uato_hints=uato_hints,
        approval_context=None,
        shared_state_hash=sh,
    )


def build_shared_governable_state_from_adapter_candidate(
    *,
    trace_id: str,
    ocgg_identity: str,
    intent: str,
    candidate_plan: CandidatePlan,
    deployment_target: Optional[str],
    objective: Optional[str],
    context: Optional[str],
    acceptance_criteria: Optional[list[str]],
    constraints: Optional[dict[str, Any]],
    approval_reference: Optional[str],
    approver_id: Optional[str],
) -> SharedGovernableState:
    operations = operations_from_candidate_plan(candidate_plan)
    domain = "web" if ocgg_identity == "W-OCGG" else "recruiting"
    spec: dict[str, Any] = {
        "ocgg_identity": ocgg_identity,
        "operations": operations,
        "goal": objective,
        "context": context,
        "acceptance_criteria": acceptance_criteria or [],
        "deployment_target": deployment_target,
        "constraints": constraints,
        "approval_reference": approval_reference,
        "approver_id": approver_id,
    }
    plan_json, plan_hash, spec_hash = integration_plan_preview(spec, ocgg_identity)
    spec["plan_hash"] = plan_hash
    plan_json["plan_hash"] = plan_hash

    approval_ctx: Optional[ApprovalFrameContext] = None
    if approval_reference or approver_id:
        approval_ctx = ApprovalFrameContext(approval_reference=approval_reference, approver_id=approver_id)

    sh = _shared_state_hash_material(
        trace_id=trace_id,
        ocgg_identity=ocgg_identity,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        intent=intent,
        candidate_plan=candidate_plan,
    )
    return SharedGovernableState(
        trace_id=trace_id,
        ocgg_identity=ocgg_identity,
        domain=domain,
        intent=intent,
        objective=objective,
        context=context,
        constraints=constraints,
        spec_for_gate=spec,
        plan_json=plan_json,
        plan_hash=plan_hash,
        spec_hash=spec_hash,
        candidate_plan=candidate_plan,
        uato_hints=None,
        approval_context=approval_ctx,
        shared_state_hash=sh,
    )
