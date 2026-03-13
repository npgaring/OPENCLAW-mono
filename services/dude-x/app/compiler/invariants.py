"""Post-compile invariant checks."""
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload
from app.models import PlanPayload, SpecIn

INVARIANTS = [
    "SPEC_DETERMINISTIC",
    "PLAN_HASH_STABLE",
    "IDENTITY_BOUND",
    "NO_IMPLICIT_DEFAULTS",
    "NO_EXECUTION_CAPABILITY",
]


def validate_invariants(spec: SpecIn, plan: PlanPayload) -> None:
    """Raise INVARIANT_VIOLATION if any invariant fails."""
    # SPEC_DETERMINISTIC
    try:
        hash_payload(spec.model_dump(mode="python"))
    except (TypeError, ValueError) as e:
        raise DUDEXError(
            ErrorCode.INVARIANT_VIOLATION,
            str(e),
            details={"invariant": "SPEC_DETERMINISTIC"},
        ) from e

    # PLAN_HASH_STABLE
    plan_body = {
        "plan_version": plan.plan_version,
        "identity": plan.identity,
        "domain": plan.domain,
        "operations": [op.model_dump() for op in plan.operations],
        "rollback": plan.rollback,
    }
    recomputed = hash_payload(plan_body)
    if recomputed != plan.plan_hash:
        raise DUDEXError(
            ErrorCode.INVARIANT_VIOLATION,
            "Plan hash mismatch",
            details={"invariant": "PLAN_HASH_STABLE", "expected": plan.plan_hash, "got": recomputed},
        )

    # IDENTITY_BOUND
    if plan.identity != spec.identity:
        raise DUDEXError(
            ErrorCode.INVARIANT_VIOLATION,
            "Plan identity must match spec identity",
            details={"invariant": "IDENTITY_BOUND"},
        )

    # NO_IMPLICIT_DEFAULTS
    if len(plan.operations) != len(spec.decisions.operations):
        raise DUDEXError(
            ErrorCode.INVARIANT_VIOLATION,
            "Operation count mismatch",
            details={"invariant": "NO_IMPLICIT_DEFAULTS"},
        )
    for i, (sop, pop) in enumerate(zip(spec.decisions.operations, plan.operations)):
        if pop.op_id != sop.op_id or pop.type != sop.type or pop.target != sop.target:
            raise DUDEXError(
                ErrorCode.INVARIANT_VIOLATION,
                "Operation mismatch",
                details={"invariant": "NO_IMPLICIT_DEFAULTS", "index": i},
            )
    rollback_spec = spec.constraints.get("rollback", {})
    if plan.rollback != rollback_spec:
        raise DUDEXError(
            ErrorCode.INVARIANT_VIOLATION,
            "Rollback constraint mismatch",
            details={"invariant": "NO_IMPLICIT_DEFAULTS"},
        )

    # NO_EXECUTION_CAPABILITY (1:1 op check)
    for i, (sop, pop) in enumerate(zip(spec.decisions.operations, plan.operations)):
        if pop.op_id != sop.op_id or pop.type != sop.type:
            raise DUDEXError(
                ErrorCode.INVARIANT_VIOLATION,
                "Operation identity/type mismatch",
                details={"invariant": "NO_EXECUTION_CAPABILITY", "index": i},
            )
