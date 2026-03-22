"""Invariant-C deterministic admissibility checks for candidate plans."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from app.core.identity import IDENTITY_ALLOWED_OPERATIONS, IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.models.openai_flow import CandidatePlan, StepType

InvariantDecision = Literal["PASS", "BLOCK"]
INVARIANT_C_DECISION_VERSION = "invariant-c-v1"
MAX_STEPS = 100
_SUPPORTED_CONSTRAINT_KEYS = frozenset({"max_steps", "allowed_types", "forbid_targets"})

INTENT_DOMAIN: dict[str, str] = {
    "web-build": "web",
    "web-maintenance": "web",
    "recruiting-update": "recruiting",
}

INTENT_ALLOWED_TYPES: dict[str, set[str]] = {
    "web-build": {x.value for x in StepType},
    "web-maintenance": {x.value for x in StepType},
    "recruiting-update": {"create_file", "write_config"},
}


@dataclass(frozen=True)
class InvariantCheckResult:
    passed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class InvariantCResult:
    decision: InvariantDecision
    reason_codes: tuple[str, ...]
    check_results: dict[str, InvariantCheckResult]
    decision_version: str = INVARIANT_C_DECISION_VERSION

    def to_persisted_checks(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, res in self.check_results.items():
            out[name] = {"passed": res.passed, "reason_codes": list(res.reason_codes)}
        return out


def evaluate_invariant_c(
    *,
    candidate_plan: CandidatePlan,
    ocgg_identity: str,
    intent: str,
    objective: str | None = None,
    context: str | None = None,
    constraints: dict[str, Any] | None = None,
) -> InvariantCResult:
    checks: dict[str, InvariantCheckResult] = {
        "Meaning": _check_meaning(candidate_plan),
        "ConstraintCompliance": _check_constraint_compliance(
            candidate_plan=candidate_plan,
            ocgg_identity=ocgg_identity,
            intent=intent,
            constraints=constraints,
        ),
        "TemporalConsistency": _check_temporal_consistency(candidate_plan),
        "GoalCoherence": _check_goal_coherence(
            candidate_plan,
            ocgg_identity=ocgg_identity,
            intent=intent,
            objective=objective,
            context=context,
        ),
        "Convergence": _check_convergence(candidate_plan),
    }
    reason_codes: list[str] = []
    for name in ("Meaning", "ConstraintCompliance", "TemporalConsistency", "GoalCoherence", "Convergence"):
        res = checks[name]
        if not res.passed:
            reason_codes.extend(res.reason_codes)
    deduped = tuple(dict.fromkeys(reason_codes))
    decision: InvariantDecision = "PASS" if not deduped else "BLOCK"
    return InvariantCResult(decision=decision, reason_codes=deduped, check_results=checks)


def _check_meaning(candidate_plan: CandidatePlan) -> InvariantCheckResult:
    reasons: list[str] = []
    steps = candidate_plan.steps
    if not steps:
        reasons.append("INVARIANT_C_MEANING_EMPTY_STEPS")
    ids = [s.id.strip() for s in steps]
    if any(not i for i in ids):
        reasons.append("INVARIANT_C_MEANING_MISSING_STEP_ID")
    if len(set(ids)) != len(ids):
        reasons.append("INVARIANT_C_MEANING_DUPLICATE_STEP_ID")
    for step in steps:
        if not step.target.strip():
            reasons.append("INVARIANT_C_MEANING_EMPTY_TARGET")
            break
        if not isinstance(_step_inputs_dict(step), dict):
            reasons.append("INVARIANT_C_MEANING_INVALID_INPUTS")
            break
    return InvariantCheckResult(passed=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _check_constraint_compliance(
    *,
    candidate_plan: CandidatePlan,
    ocgg_identity: str,
    intent: str,
    constraints: dict[str, Any] | None,
) -> InvariantCheckResult:
    reasons: list[str] = []
    allowed_ops_identity = IDENTITY_ALLOWED_OPERATIONS.get(ocgg_identity, set())
    allowed_ops_intent = INTENT_ALLOWED_TYPES.get(intent, set())
    for step in candidate_plan.steps:
        if step.type.value not in allowed_ops_identity:
            reasons.append("INVARIANT_C_CONSTRAINT_IDENTITY_OPERATION_NOT_ALLOWED")
        if step.type.value not in allowed_ops_intent:
            reasons.append("INVARIANT_C_CONSTRAINT_INTENT_OPERATION_NOT_ALLOWED")
    if constraints is not None and not isinstance(constraints, dict):
        reasons.append("INVARIANT_C_CONSTRAINT_INVALID_CONSTRAINTS")
    if isinstance(constraints, dict):
        unsupported = sorted(set(constraints.keys()) - _SUPPORTED_CONSTRAINT_KEYS)
        if unsupported:
            reasons.append("INVARIANT_C_CONSTRAINT_UNSUPPORTED_CONSTRAINT")
        if "max_steps" in constraints:
            max_steps = constraints.get("max_steps")
            if not isinstance(max_steps, int) or max_steps < 1:
                reasons.append("INVARIANT_C_CONSTRAINT_INVALID_MAX_STEPS")
            elif len(candidate_plan.steps) > max_steps:
                reasons.append("INVARIANT_C_CONSTRAINT_MAX_STEPS_EXCEEDED")
        if "allowed_types" in constraints:
            allowed_types = constraints.get("allowed_types")
            if not isinstance(allowed_types, list) or not all(isinstance(x, str) for x in allowed_types):
                reasons.append("INVARIANT_C_CONSTRAINT_INVALID_ALLOWED_TYPES")
            else:
                allowed_set = set(allowed_types)
                enum_values = {x.value for x in StepType}
                if not allowed_set.issubset(enum_values):
                    reasons.append("INVARIANT_C_CONSTRAINT_INVALID_ALLOWED_TYPES")
                for step in candidate_plan.steps:
                    if step.type.value not in allowed_set:
                        reasons.append("INVARIANT_C_CONSTRAINT_ALLOWED_TYPES_VIOLATION")
                        break
        if "forbid_targets" in constraints:
            forbid_targets = constraints.get("forbid_targets")
            if not isinstance(forbid_targets, list) or not all(isinstance(x, str) for x in forbid_targets):
                reasons.append("INVARIANT_C_CONSTRAINT_INVALID_FORBID_TARGETS")
            else:
                blocked = set(forbid_targets)
                for step in candidate_plan.steps:
                    if step.target in blocked:
                        reasons.append("INVARIANT_C_CONSTRAINT_FORBID_TARGET_VIOLATION")
                        break
    return InvariantCheckResult(passed=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _check_temporal_consistency(candidate_plan: CandidatePlan) -> InvariantCheckResult:
    reasons: list[str] = []
    steps = candidate_plan.steps
    id_to_index = {step.id: idx for idx, step in enumerate(steps)}
    graph: dict[str, list[str]] = {step.id: [] for step in steps}
    for idx, step in enumerate(steps):
        deps_raw = _step_inputs_dict(step).get("depends_on")
        deps: list[str] = []
        if isinstance(deps_raw, str):
            deps = [deps_raw]
        elif isinstance(deps_raw, list):
            deps = [x for x in deps_raw if isinstance(x, str)]
        for dep in deps:
            if dep not in id_to_index:
                reasons.append("INVARIANT_C_TEMPORAL_UNKNOWN_DEPENDENCY")
                continue
            if id_to_index[dep] >= idx:
                reasons.append("INVARIANT_C_TEMPORAL_BACKWARD_DEPENDENCY")
            graph[dep].append(step.id)
    if _has_cycle(graph):
        reasons.append("INVARIANT_C_TEMPORAL_CYCLE")
    return InvariantCheckResult(passed=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _check_goal_coherence(
    candidate_plan: CandidatePlan,
    *,
    ocgg_identity: str,
    intent: str,
    objective: str | None,
    context: str | None,
) -> InvariantCheckResult:
    reasons: list[str] = []
    domain_identity = IDENTITY_DOMAIN_MAP.get(ocgg_identity)
    domain_intent = INTENT_DOMAIN.get(intent)
    if not domain_identity or not domain_intent:
        reasons.append("INVARIANT_C_GOAL_UNKNOWN_IDENTITY_OR_INTENT")
    elif domain_identity != domain_intent:
        reasons.append("INVARIANT_C_GOAL_DOMAIN_MISMATCH")
    if ocgg_identity == "W-OCGG" and intent not in ("web-build", "web-maintenance"):
        reasons.append("INVARIANT_C_GOAL_IDENTITY_INTENT_MISMATCH")
    if ocgg_identity == "R-OCGG" and intent != "recruiting-update":
        reasons.append("INVARIANT_C_GOAL_IDENTITY_INTENT_MISMATCH")
    allowed_ops_intent = INTENT_ALLOWED_TYPES.get(intent, set())
    for step in candidate_plan.steps:
        if step.type.value not in allowed_ops_intent:
            reasons.append("INVARIANT_C_GOAL_OPERATION_INTENT_MISMATCH")
            break
    text = " ".join(x for x in ((objective or "").strip(), (context or "").strip()) if x).lower()
    if not text:
        reasons.append("INVARIANT_C_GOAL_MISSING_OBJECTIVE")
    else:
        # Avoid substring false positives (e.g. "release candidate" for a web build).
        if intent.startswith("web") and any(
            k in text for k in ("hiring", "recruit", "resume", "job posting", "job board", "applicant")
        ):
            reasons.append("INVARIANT_C_GOAL_OBJECTIVE_MISMATCH")
        if intent == "recruiting-update" and any(k in text for k in ("deploy", "build pipeline", "website release", "frontend")):
            reasons.append("INVARIANT_C_GOAL_OBJECTIVE_MISMATCH")
    return InvariantCheckResult(passed=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _check_convergence(candidate_plan: CandidatePlan) -> InvariantCheckResult:
    reasons: list[str] = []
    steps = candidate_plan.steps
    if len(steps) > MAX_STEPS:
        reasons.append("INVARIANT_C_CONVERGENCE_TOO_MANY_STEPS")
    fingerprints = [_step_fingerprint(step) for step in steps]
    for i in range(1, len(fingerprints)):
        if fingerprints[i] == fingerprints[i - 1]:
            reasons.append("INVARIANT_C_CONVERGENCE_REPEATED_ADJACENT_STEP")
            break
    counts = Counter(fingerprints)
    if any(v > 2 for v in counts.values()):
        reasons.append("INVARIANT_C_CONVERGENCE_REPEATED_LOOP_PATTERN")
    return InvariantCheckResult(passed=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _step_fingerprint(step: Any) -> str:
    inputs = dict(_step_inputs_dict(step))
    inputs.pop("depends_on", None)
    material = {"type": step.type.value, "target": step.target, "inputs": inputs}
    return hash_payload(material)


def _step_inputs_dict(step: Any) -> dict[str, Any]:
    inputs = getattr(step, "inputs", None)
    if inputs is None:
        return {}
    if isinstance(inputs, dict):
        return inputs
    if hasattr(inputs, "model_dump"):
        dumped = inputs.model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped
    return {}


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    color: dict[str, int] = {k: 0 for k in graph}

    def dfs(node: str) -> bool:
        color[node] = 1
        for nxt in graph.get(node, []):
            if color.get(nxt, 0) == 1:
                return True
            if color.get(nxt, 0) == 0 and dfs(nxt):
                return True
        color[node] = 2
        return False

    for node in graph:
        if color[node] == 0 and dfs(node):
            return True
    return False
