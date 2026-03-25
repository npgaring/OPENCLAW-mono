"""Bridge integration specs / adapter artifacts into Invariant-C CandidatePlan + operations."""
from __future__ import annotations

from typing import Any

from app.models.openai_flow import CandidatePlan, CandidatePlanMetadata, CandidatePlanStep, RiskLevel, StepType

# Candidate plan steps use extra=forbid input models; integration /task ops may carry gate-only keys.
_TASK_INPUT_KEYS_ALLOWLIST = frozenset(
    {
        "depends_on",
        "path",
        "content",
        "command",
        "provider",
        "project",
        "artifact",
        "strategy",
    }
)


def default_intent_for_identity(ocgg_identity: str) -> str:
    if ocgg_identity == "W-OCGG":
        return "web-build"
    return "recruiting-update"


def operations_from_candidate_plan(candidate_plan: CandidatePlan) -> list[dict[str, Any]]:
    return [
        {
            "op_id": step.id,
            "type": step.type.value,
            "target": step.target,
            "inputs": step.inputs.model_dump(mode="python"),
            "outputs": {},
        }
        for step in candidate_plan.steps
    ]


def task_spec_to_candidate_plan(
    spec: dict[str, Any],
    *,
    ocgg_identity: str,
    intent: str,
) -> CandidatePlan:
    """
    Synthesize a CandidatePlan from POST /task-style spec for Invariant-C.

    Raises ValidationError if operations cannot be mapped to bounded candidate steps.
    """
    operations = spec.get("operations") or []
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    steps: list[CandidatePlanStep] = []
    for i, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise ValueError(f"operations[{i}] must be an object")
        op_id = raw.get("op_id") or raw.get("id") or f"op-{i + 1}"
        st_raw = raw.get("type")
        if not st_raw:
            raise ValueError(f"operations[{i}].type is required")
        st = StepType(str(st_raw))
        target = (raw.get("target") or "").strip() or "(integration-target)"
        inputs_raw = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
        inputs_raw = {k: v for k, v in inputs_raw.items() if k in _TASK_INPUT_KEYS_ALLOWLIST}
        step_payload = {
            "id": str(op_id).strip(),
            "type": st.value,
            "action": st.value,
            "target": target,
            "inputs": inputs_raw,
        }
        try:
            steps.append(CandidatePlanStep.model_validate(step_payload))
        except Exception as e:
            raise ValueError(f"operations[{i}] is not representable as a candidate step: {e}") from e
    return CandidatePlan(
        steps=steps,
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel=RiskLevel.low),
    )
