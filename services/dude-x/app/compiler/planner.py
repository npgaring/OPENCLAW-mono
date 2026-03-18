"""Build PlanPayload from validated SpecIn."""
from app.compiler.validator import INTENT_DOMAIN
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload, integration_hash_payload
from app.models import PlanOperation, PlanPayload, SpecIn


def build_plan(spec: SpecIn) -> PlanPayload:
    """Produce deterministic plan from spec. Raises on domain mismatch or empty operations."""
    domain = INTENT_DOMAIN[spec.intent]
    if spec.decisions.domain is not None and spec.decisions.domain != domain:
        raise DUDEXError(
            ErrorCode.DOMAIN_MISMATCH,
            "decisions.domain does not match identity+intent derived domain",
            details={"decisions.domain": spec.decisions.domain, "derived": domain},
        )
    operations = [
        PlanOperation(
            op_id=op.op_id,
            type=op.type,
            target=op.target,
            inputs=op.inputs or {},
            outputs=op.outputs or {},
            addon=getattr(op, "addon", None),
        )
        for op in spec.decisions.operations
    ]
    if not operations:
        raise DUDEXError(ErrorCode.MISSING_DECISION, "No operations in decisions", details={})
    rollback = spec.constraints.get("rollback", {})
    if "rollback" in spec.constraints and not rollback:
        raise DUDEXError(
            ErrorCode.ROLLBACK_REQUIRED_BUT_MISSING,
            "rollback key present but value empty",
            details={},
        )
    plan_body = {
        "plan_version": "1.0",
        "identity": spec.identity,
        "ocgg_identity": spec.identity,
        "domain": domain,
        "operations": [op.model_dump() for op in operations],
        "rollback": rollback,
    }
    integration_plan_hash = integration_hash_payload(
        {"domain": domain, "operations": plan_body["operations"]}
    )
    plan_hash = hash_payload(plan_body)
    plan_body["plan_hash"] = plan_hash
    plan_body["integration_plan_hash"] = integration_plan_hash
    return PlanPayload(**plan_body)
