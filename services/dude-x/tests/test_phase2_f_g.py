"""Phase 2 tests: addon registry (F) and replay determinism (G)."""
import pytest

from app.compiler.invariants import validate_invariants
from app.compiler.planner import build_plan
from app.compiler.validator import validate_spec
from app.core.gate import evaluate_gate
from app.core.hashing import hash_payload
from app.models import Decisions, OperationSpec, PlanPayload, Signature, SpecIn, Target


def _make_spec(identity: str = "W-OCGG", intent: str = "web-build", operations: list | None = None) -> SpecIn:
    ops = operations or [
        OperationSpec(op_id="op1", type="build", target="repo", inputs={}, outputs={}),
    ]
    return SpecIn(
        spec_version="1.0",
        identity=identity,
        intent=intent,
        target=Target(resource_id="r1", environment="preview"),
        decisions=Decisions(operations=ops),
        constraints={},
        signature=Signature(type="human_signed", signed_at="2024-01-01T00:00:00Z", hash="abc123"),
    )


def test_f_addon_registry_violation():
    spec = _make_spec(
        operations=[
            OperationSpec(op_id="a1", type="addon_execute", target="t", inputs={}, outputs={}, addon="unregistered_plugin"),
        ],
    )
    validate_spec(spec)
    plan = build_plan(spec)
    validate_invariants(spec, plan)
    result = evaluate_gate(plan)
    assert result["gate_decision"] == "BLOCK"
    assert result["reason"] == "ADDON_NOT_IN_REGISTRY"


def test_f_registered_addon_passes_gate():
    spec = _make_spec(
        operations=[
            OperationSpec(op_id="a1", type="addon_execute", target="t", inputs={}, outputs={}, addon="allowed_plugin"),
        ],
    )
    validate_spec(spec)
    plan = build_plan(spec)
    validate_invariants(spec, plan)
    result = evaluate_gate(plan)
    assert result["gate_decision"] == "PASS"
    assert result["reason"] is None


def test_g_full_replay_determinism():
    spec = _make_spec(identity="R-OCGG", intent="recruiting-update")
    spec_payload = spec.model_dump(mode="python")
    spec_hash1 = hash_payload(spec_payload)
    validate_spec(spec)
    plan1 = build_plan(spec)
    validate_invariants(spec, plan1)
    plan_hash1 = plan1.plan_hash
    # Second run
    spec_hash2 = hash_payload(spec_payload)
    validate_spec(spec)
    plan2 = build_plan(spec)
    validate_invariants(spec, plan2)
    plan_hash2 = plan2.plan_hash
    assert spec_hash1 == spec_hash2
    assert plan_hash1 == plan_hash2
