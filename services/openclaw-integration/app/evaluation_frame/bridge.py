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
        "project_name",
        "linked_repo_name",
        "repo_name",
        "owner",
        "owner_type",
        "fallback_owner",
        "repo_name_template",
        "default_branch",
        "production_branch",
        "team_id",
        "domain_behavior",
        "branch",
        "visibility",
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
        normalized_type, normalized_inputs = _normalize_task_operation_for_candidate(
            op_type=str(st_raw),
            raw_inputs=raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
            target=raw.get("target"),
        )
        st = StepType(normalized_type)
        target = (raw.get("target") or "").strip() or "(integration-target)"
        inputs_raw = {k: v for k, v in normalized_inputs.items() if k in _TASK_INPUT_KEYS_ALLOWLIST}
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


def _normalize_task_operation_for_candidate(
    *,
    op_type: str,
    raw_inputs: dict[str, Any],
    target: Any,
) -> tuple[str, dict[str, Any]]:
    """
    Normalize integration operation types into bounded candidate step types.

    Compatibility rule:
    - provision_repo/provision_hosting are converted to deploy-shaped candidate steps.
      This keeps Invariant-C admissibility stable across older/newer StepType vocabularies.
    """
    t = (op_type or "").strip()
    if t == "provision_repo":
        provider = str(raw_inputs.get("provider") or "github").strip() or "github"
        project = str(
            raw_inputs.get("repo_name")
            or raw_inputs.get("project")
            or raw_inputs.get("project_name")
            or target
            or "repository"
        ).strip() or "repository"
        return "deploy", {"provider": provider, "project": project}
    if t == "provision_hosting":
        provider = str(raw_inputs.get("provider") or "vercel").strip() or "vercel"
        project = str(
            raw_inputs.get("project")
            or raw_inputs.get("project_name")
            or raw_inputs.get("linked_repo_name")
            or target
            or "hosting-project"
        ).strip() or "hosting-project"
        return "deploy", {"provider": provider, "project": project}
    return t, dict(raw_inputs or {})
