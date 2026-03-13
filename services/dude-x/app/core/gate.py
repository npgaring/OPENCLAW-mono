"""Governance gate: addon registry check only."""
from app.models.plan import PlanPayload

ADDON_REGISTRY: frozenset[str] = frozenset({"allowed_plugin", "official_web_helper"})


def evaluate_gate(plan: PlanPayload) -> dict[str, str | None]:
    """
    For each addon_execute op, require addon in ADDON_REGISTRY.
    Returns {"gate_decision": "PASS"|"BLOCK", "plan_hash": ..., "reason": ... (if BLOCK)}.
    """
    for op in plan.operations:
        if op.type == "addon_execute":
            addon = getattr(op, "addon", None) or (op.outputs or {}).get("addon")
            if not addon or addon not in ADDON_REGISTRY:
                return {
                    "gate_decision": "BLOCK",
                    "reason": "ADDON_NOT_IN_REGISTRY",
                    "plan_hash": plan.plan_hash,
                }
    return {
        "gate_decision": "PASS",
        "plan_hash": plan.plan_hash,
        "reason": None,
    }
