"""Integration plan preview for UATO halt paths (same canonical hash as GateEngine for valid ops)."""
from __future__ import annotations

from typing import Any, Tuple

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload


def integration_plan_preview(spec: dict[str, Any], ocgg_identity: str) -> Tuple[dict[str, Any], str, str]:
    """Returns (plan_json, plan_hash, spec_hash) consistent with gate engine for well-formed specs."""
    domain = IDENTITY_DOMAIN_MAP.get(ocgg_identity, "web")
    operations = spec.get("operations") if isinstance(spec.get("operations"), list) else []
    plan_canonical = {"domain": domain, "operations": operations}
    plan_hash = hash_payload(plan_canonical) if operations else ""
    plan_json: dict[str, Any] = {"domain": domain, "plan_hash": plan_hash, "operations": operations}
    if spec.get("goal"):
        plan_json["goal"] = spec["goal"]
    if spec.get("context"):
        plan_json["context"] = spec["context"]
    if spec.get("acceptance_criteria"):
        plan_json["acceptance_criteria"] = spec["acceptance_criteria"]
    # Align POST /gate/evaluate (optional plan_hash) with POST /task: canonical plan_hash on spec before
    # spec_hash so EvaluationState matches when the client omits plan_hash on gate but sends it on task.
    if not spec.get("plan_hash"):
        spec["plan_hash"] = plan_hash
    # Omit None-valued keys so TaskSubmitRequest.model_dump (many optional Nones) hashes like gate to_payload(exclude_none).
    spec_for_hash = {k: v for k, v in spec.items() if v is not None}
    spec_hash = hash_payload(spec_for_hash)
    return plan_json, plan_hash, spec_hash
