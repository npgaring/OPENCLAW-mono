"""Gate engine: evaluate spec + ocgg_identity -> GateEvaluation."""
from typing import Any

from app.core.identity import IDENTITY_ALLOWED_OPERATIONS, IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.gate.models import Defect, GateDecision, GateEvaluation, GateOutcome
from app.gate.policy import (
    APPROVAL_REFERENCE_FIELD,
    APPROVER_FIELD,
    ARTIFACT_OWNER_REGISTRY,
    CONTRADICTION_RULES,
    FORBIDDEN_OPERATION_TYPES,
    MAX_OPERATIONS_PER_PLAN,
    POLICY_VERSION,
    PROD_DEPLOYMENT_TARGETS,
    SCRIPT_CONTENT_BLOCKLIST,
    get_policy_version_at_execution,
)


class GateEngine:
    def evaluate(self, spec: Any, ocgg_identity: str) -> GateEvaluation:
        reason_codes: list[str] = []
        defects: list[Defect] = []
        outcome = GateOutcome.PASS

        if not isinstance(spec, dict):
            return self._result(GateOutcome.BLOCK, ["INVALID_SCHEMA"], [Defect("INVALID_SCHEMA", None, "Spec must be JSON object")], spec, ocgg_identity)

        for field in ["ocgg_identity", "plan_hash", "operations"]:
            if not spec.get(field):
                reason_codes.append("MISSING_FIELD")
                defects.append(Defect("MISSING_FIELD", field, f"Required field missing or empty: {field}"))
        if defects:
            return self._result(GateOutcome.BLOCK, list(set(reason_codes)), defects, spec, ocgg_identity)

        if spec.get("ocgg_identity") != ocgg_identity:
            reason_codes.append("IDENTITY_MISMATCH")
            defects.append(Defect("IDENTITY_MISMATCH", "ocgg_identity", "Spec identity does not match request context"))
        if ocgg_identity not in IDENTITY_DOMAIN_MAP:
            reason_codes.append("UNKNOWN_IDENTITY")
            defects.append(Defect("UNKNOWN_IDENTITY", "ocgg_identity", f"Unknown identity: {ocgg_identity}"))
        if reason_codes:
            return self._result(GateOutcome.BLOCK, list(set(reason_codes)), defects, spec, ocgg_identity)

        domain = IDENTITY_DOMAIN_MAP[ocgg_identity]
        operations = spec.get("operations") or []
        if not isinstance(operations, list):
            reason_codes.append("INVALID_SCHEMA")
            return self._result(GateOutcome.BLOCK, reason_codes, defects, spec, ocgg_identity)

        plan_canonical = {"domain": domain, "operations": operations}
        computed_plan_hash = hash_payload(plan_canonical)
        if spec.get("plan_hash") != computed_plan_hash:
            reason_codes.append("PLAN_HASH_MISMATCH")
            defects.append(Defect("PLAN_HASH_MISMATCH", "plan_hash", "Client plan_hash != canonical hash"))

        if len(operations) > MAX_OPERATIONS_PER_PLAN:
            reason_codes.append("COST_LIMIT_EXCEEDED")
            defects.append(Defect("COST_LIMIT_EXCEEDED", None, f"Max {MAX_OPERATIONS_PER_PLAN} operations"))

        allowed_ops = IDENTITY_ALLOWED_OPERATIONS.get(ocgg_identity, set())
        for i, op in enumerate(operations):
            if not isinstance(op, dict):
                continue
            op_type = op.get("type") or ""
            if op_type in FORBIDDEN_OPERATION_TYPES:
                reason_codes.append("FORBIDDEN_COMMAND")
                defects.append(Defect("FORBIDDEN_COMMAND", f"operations[{i}].type", op_type))
            if allowed_ops and op_type not in allowed_ops:
                reason_codes.append("CROSS_IDENTITY_OPERATION")
                defects.append(Defect("CROSS_IDENTITY_OPERATION", f"operations[{i}].type", op_type))

        for left, right in CONTRADICTION_RULES:
            if spec.get(left) and spec.get(right):
                reason_codes.append("CONTRADICTION")
                defects.append(Defect("CONTRADICTION", None, f"{left} and {right} both true"))

        deployment_target = (spec.get("deployment_target") or "").lower()
        if deployment_target in PROD_DEPLOYMENT_TARGETS:
            if not spec.get(APPROVER_FIELD) and not spec.get(APPROVAL_REFERENCE_FIELD):
                reason_codes.append("PROD_DEPLOY_NO_APPROVAL")
                defects.append(Defect("PROD_DEPLOY_NO_APPROVAL", None, "Production deploy requires approver_id or approval_reference"))
            if spec.get(APPROVER_FIELD) == ocgg_identity:
                reason_codes.append("SOD_VIOLATION")
                defects.append(Defect("SOD_VIOLATION", APPROVER_FIELD, "Approver must differ from ocgg_identity"))

        if reason_codes:
            outcome = GateOutcome.BLOCK
        spec_hash = hash_payload(spec)
        plan_hash = computed_plan_hash
        plan_json = {"domain": domain, "plan_hash": plan_hash, "operations": operations}
        decision = GateDecision(
            outcome=outcome,
            reason_codes=list(set(reason_codes)),
            defect_list=defects,
            policy_version=POLICY_VERSION,
            spec_hash=spec_hash,
            plan_hash=plan_hash,
            approver_id=spec.get(APPROVER_FIELD),
        )
        return GateEvaluation(decision=decision, plan_json=plan_json, spec_hash=spec_hash, plan_hash=plan_hash)

    def _result(
        self,
        outcome: GateOutcome,
        reason_codes: list[str],
        defects: list[Defect],
        spec: Any,
        ocgg_identity: str,
    ) -> GateEvaluation:
        domain = IDENTITY_DOMAIN_MAP.get(ocgg_identity, "web")
        operations = spec.get("operations", []) if isinstance(spec, dict) else []
        plan_json = {"domain": domain, "plan_hash": "", "operations": operations}
        spec_hash = hash_payload(spec) if isinstance(spec, dict) else ""
        plan_hash = hash_payload(plan_json) if plan_json.get("operations") else ""
        decision = GateDecision(
            outcome=outcome,
            reason_codes=reason_codes,
            defect_list=defects,
            policy_version=POLICY_VERSION,
            spec_hash=spec_hash,
            plan_hash=plan_hash,
            approver_id=spec.get(APPROVER_FIELD) if isinstance(spec, dict) else None,
        )
        return GateEvaluation(decision=decision, plan_json=plan_json, spec_hash=spec_hash, plan_hash=plan_hash)
