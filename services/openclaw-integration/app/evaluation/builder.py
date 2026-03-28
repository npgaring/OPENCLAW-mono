"""Build canonical EvaluationState from task/gate entrypoints (single construction site)."""
from __future__ import annotations

from typing import Any, Optional

from app.core.security import hash_payload
from app.evaluation.state import EvaluationState
from app.evaluation_frame.build import (
    build_shared_governable_state_for_gate_payload,
    build_shared_governable_state_for_task,
)
from app.evaluation_frame.state import ApprovalFrameContext, SharedGovernableState
from app.models.task import TaskSubmitRequest
from app.uato import build_uato_input_from_spec


EVALUATION_STATE_SCHEMA_VERSION = 1


def _serialize_optional_model(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _approval_material(ac: Optional[ApprovalFrameContext]) -> Any:
    if ac is None:
        return None
    return {"approval_reference": ac.approval_reference, "approver_id": ac.approver_id}


def _canonical_evaluation_material(shared: SharedGovernableState, ui: Any) -> dict[str, Any]:
    """Deterministic JSON-serializable material hashed into ``state_hash``."""
    ctx = ui.context
    return {
        "v": EVALUATION_STATE_SCHEMA_VERSION,
        "trace_id": shared.trace_id,
        "ocgg_identity": shared.ocgg_identity,
        "domain": shared.domain,
        "plan_hash": shared.plan_hash,
        "spec_hash": shared.spec_hash,
        "plan_json": shared.plan_json,
        "intent": shared.intent,
        "objective": shared.objective,
        "context": shared.context,
        "constraints": shared.constraints,
        "candidate_plan": shared.candidate_plan.model_dump(mode="json"),
        "uato_hints": _serialize_optional_model(shared.uato_hints),
        "validation_controls": _serialize_optional_model(shared.validation_controls),
        "approval_context": _approval_material(shared.approval_context),
        "uato_trust_level": ui.trust_state.level,
        "uato_authority_level": ui.authority_state.level,
        "uato_trust_source": ui.trust_state.source,
        "uato_evidence": list(ui.trust_state.evidence),
        "uato_context": {
            "environment": ctx.environment,
            "tenant_id": ctx.tenant_id,
            "request_source": ctx.request_source,
            "trace_id": ctx.trace_id,
        },
    }


def build_evaluation_state_from_shared_governable(shared: SharedGovernableState) -> EvaluationState:
    """
    Primary builder: shared governable snapshot + deterministic UATO trust/authority snapshot → EvaluationState.

    Uses the same spec dict as gate/task (``spec_for_gate``) for UATO input material.
    """
    ui = build_uato_input_from_spec(
        shared.spec_for_gate,
        ocgg_identity=shared.ocgg_identity,
        trace_id=shared.trace_id,
        uato_hints=shared.uato_hints,
        validation_controls=shared.validation_controls,
    )
    material = _canonical_evaluation_material(shared, ui)
    sh = hash_payload(material)
    return EvaluationState(
        governable=shared,
        uato_trust_level=ui.trust_state.level,
        uato_authority_level=ui.authority_state.level,
        uato_trust_source=ui.trust_state.source,
        state_hash=sh,
    )


def build_evaluation_state_with_resolved_approval(body: TaskSubmitRequest, trace_id: str) -> EvaluationState:
    """
    Re-build evaluation state after human approval: same as constructing from task body with approval context
    merged into spec (state transformation, not pipeline resume).
    """
    shared = build_shared_governable_state_for_task(body, trace_id, for_resume=True)
    return build_evaluation_state_from_shared_governable(shared)


def build_evaluation_state_from_task_request(body: TaskSubmitRequest, trace_id: str) -> EvaluationState:
    shared = build_shared_governable_state_for_task(body, trace_id, for_resume=False)
    return build_evaluation_state_from_shared_governable(shared)


def build_evaluation_state_from_gate_request(
    spec: dict[str, Any],
    ocgg_identity: str,
    trace_id: str,
    uato_hints: Any,
    validation_controls: Any = None,
) -> EvaluationState:
    shared = build_shared_governable_state_for_gate_payload(
        spec,
        ocgg_identity,
        trace_id,
        uato_hints,
        validation_controls,
    )
    return build_evaluation_state_from_shared_governable(shared)
