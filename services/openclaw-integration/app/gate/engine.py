"""Gate engine: evaluate spec + ocgg_identity -> GateEvaluation."""
from typing import Any

from app.core.identity import IDENTITY_ALLOWED_OPERATIONS, IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.gate.models import Defect, GateDecision, GateEvaluation, GateOutcome
from app.gate.policy import (
    ALLOWED_TARGET_DOMAINS,
    ALLOWED_WRITE_ROOT,
    APPROVAL_REFERENCE_FIELD,
    APPROVER_FIELD,
    ARTIFACT_OWNER_REGISTRY,
    CONTRADICTION_RULES,
    FORBIDDEN_OPERATION_TYPES,
    MAX_CPU_SECONDS,
    MAX_MEMORY_MB,
    MAX_OPERATIONS_PER_PLAN,
    NETWORK_INPUT_KEYS,
    NETWORK_OP_TYPES,
    PATH_KEYS,
    PLUGIN_INPUT_KEYS,
    PLUGIN_OP_TYPES,
    POLICY_VERSION,
    PROD_DEPLOYMENT_TARGETS,
    REGISTERED_PLUGINS,
    RESOURCE_INPUT_KEYS,
    SCRIPT_CONTENT_BLOCKLIST,
    get_policy_version_at_execution,
    host_from_url_or_host,
    path_escapes_allowed_root,
)


class GateEngine:
    @staticmethod
    def _enrich_plan_json_from_spec(plan_json: dict[str, Any], spec: Any) -> None:
        if not isinstance(spec, dict):
            return
        # Optional payloads that are not part of plan_hash but required by deterministic executor paths.
        passthrough_keys = (
            "goal",
            "context",
            "acceptance_criteria",
            "build_sot_hash",
            "execution_plan_hash",
            "executor_contract",
            "execution_plan_v2",
        )
        for key in passthrough_keys:
            val = spec.get(key)
            if val is not None and val != "":
                plan_json[key] = val

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
            inputs = op.get("inputs") if isinstance(op.get("inputs"), dict) else {}

            if op_type in FORBIDDEN_OPERATION_TYPES:
                reason_codes.append("FORBIDDEN_COMMAND")
                defects.append(Defect("FORBIDDEN_COMMAND", f"operations[{i}].type", op_type))
            if allowed_ops and op_type not in allowed_ops:
                reason_codes.append("CROSS_IDENTITY_OPERATION")
                defects.append(Defect("CROSS_IDENTITY_OPERATION", f"operations[{i}].type", op_type))

            # F1 — Filesystem escalation: path must not escape ALLOWED_WRITE_ROOT
            for key in PATH_KEYS:
                val = inputs.get(key) if key in inputs else op.get(key)
                if isinstance(val, str) and path_escapes_allowed_root(val):
                    reason_codes.append("CAPABILITY_ENVELOPE_VIOLATION")
                    defects.append(Defect("CAPABILITY_ENVELOPE_VIOLATION", f"operations[{i}].{key}", "Write outside allowed directory"))
                    break

            # F2 — Network egress: outbound target must be in ALLOWED_TARGET_DOMAINS
            if op_type in NETWORK_OP_TYPES or any(k in inputs for k in NETWORK_INPUT_KEYS):
                found_unauthorized = False
                for key in NETWORK_INPUT_KEYS:
                    val = inputs.get(key)
                    if isinstance(val, str):
                        host = host_from_url_or_host(val)
                        if host and host not in ALLOWED_TARGET_DOMAINS:
                            reason_codes.append("UNAUTHORIZED_NETWORK_EGRESS")
                            defects.append(Defect("UNAUTHORIZED_NETWORK_EGRESS", f"operations[{i}].inputs.{key}", "Unauthorized outbound connection"))
                            found_unauthorized = True
                            break
                if not found_unauthorized and op_type in NETWORK_OP_TYPES and not any(inputs.get(k) for k in NETWORK_INPUT_KEYS if isinstance(inputs.get(k), str)):
                    reason_codes.append("UNAUTHORIZED_NETWORK_EGRESS")
                    defects.append(Defect("UNAUTHORIZED_NETWORK_EGRESS", f"operations[{i}].type", "Network op without allowed target"))

            # F3 — Command/shell injection: blocklisted script content
            injection_found = False
            for key in ("command", "script", "cmd", "content"):
                if injection_found:
                    break
                val = inputs.get(key) if key in inputs else op.get(key)
                if isinstance(val, str):
                    for pattern in SCRIPT_CONTENT_BLOCKLIST:
                        if pattern.search(val):
                            reason_codes.append("SANDBOX_REJECTION")
                            defects.append(Defect("SANDBOX_REJECTION", f"operations[{i}].{key}", "Shell injection attempt"))
                            injection_found = True
                            break

            # F4 — Resource limits: gate blocks plans requesting over limit
            for key in RESOURCE_INPUT_KEYS:
                val = inputs.get(key)
                if isinstance(val, (int, float)):
                    if key in ("memory_mb", "memory_mb_per_op") and val > MAX_MEMORY_MB:
                        reason_codes.append("RESOURCE_LIMIT_EXCEEDED")
                        defects.append(Defect("RESOURCE_LIMIT_EXCEEDED", f"operations[{i}].inputs.{key}", f"Exceeds max {MAX_MEMORY_MB} MB"))
                        break
                    if key in ("cpu_seconds", "timeout_seconds") and val > MAX_CPU_SECONDS:
                        reason_codes.append("RESOURCE_LIMIT_EXCEEDED")
                        defects.append(Defect("RESOURCE_LIMIT_EXCEEDED", f"operations[{i}].inputs.{key}", f"Exceeds max {MAX_CPU_SECONDS}s"))
                        break

            # F5 — Plugin injection: only REGISTERED_PLUGINS may be loaded
            if op_type in PLUGIN_OP_TYPES or any(k in inputs for k in PLUGIN_INPUT_KEYS):
                plugin_blocked = False
                for key in PLUGIN_INPUT_KEYS:
                    val = inputs.get(key)
                    if isinstance(val, str) and val.strip():
                        if val.strip() not in REGISTERED_PLUGINS:
                            reason_codes.append("UNREGISTERED_PLUGIN")
                            defects.append(Defect("UNREGISTERED_PLUGIN", f"operations[{i}].inputs.{key}", "Unregistered addon"))
                            plugin_blocked = True
                            break
                if not plugin_blocked and op_type in PLUGIN_OP_TYPES and not any(inputs.get(k) for k in PLUGIN_INPUT_KEYS if isinstance(inputs.get(k), str)):
                    reason_codes.append("UNREGISTERED_PLUGIN")
                    defects.append(Defect("UNREGISTERED_PLUGIN", f"operations[{i}].type", "Plugin op without registered plugin id"))

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
        self._enrich_plan_json_from_spec(plan_json, spec)
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
        self._enrich_plan_json_from_spec(plan_json, spec)
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
