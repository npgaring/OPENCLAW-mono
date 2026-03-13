"""Governance and P-Stack tests."""
import pytest

from app.compiler.invariants import validate_invariants
from app.compiler.planner import build_plan
from app.compiler.pstack import run_pstack
from app.compiler.validator import validate_spec
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload
from app.models import Decisions, OperationSpec, Signature, SpecIn, Target


def _make_spec(
    identity: str = "W-OCGG",
    intent: str = "web-build",
    operations: list | None = None,
    domain_override: str | None = None,
    constraints: dict | None = None,
) -> SpecIn:
    ops = operations or [
        OperationSpec(op_id="op1", type="build", target="repo", inputs={}, outputs={}),
    ]
    return SpecIn(
        spec_version="1.0",
        identity=identity,
        intent=intent,
        target=Target(resource_id="r1", environment="preview"),
        decisions=Decisions(operations=ops, domain=domain_override),
        constraints=constraints or {},
        signature=Signature(type="human_signed", signed_at="2024-01-01T00:00:00Z", hash="abc123"),
    )


def test_identity_intent_mismatch():
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(identity="W-OCGG", intent="recruiting-update"))
    assert exc_info.value.code == ErrorCode.IDENTITY_INTENT_MISMATCH
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(identity="R-OCGG", intent="web-build"))
    assert exc_info.value.code == ErrorCode.IDENTITY_INTENT_MISMATCH


def test_identity_included_in_plan_hash():
    spec = _make_spec(identity="W-OCGG", intent="web-build")
    validate_spec(spec)
    plan = build_plan(spec)
    validate_invariants(spec, plan)
    assert plan.identity == "W-OCGG"
    plan_body = {
        "plan_version": plan.plan_version,
        "identity": plan.identity,
        "domain": plan.domain,
        "operations": [op.model_dump() for op in plan.operations],
        "rollback": plan.rollback,
    }
    assert hash_payload(plan_body) == plan.plan_hash


def test_pstack_layers_fail_fast():
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(operations=[]))
    assert exc_info.value.code == ErrorCode.MISSING_DECISION
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(identity="W-OCGG", intent="recruiting-update"))
    assert exc_info.value.code == ErrorCode.IDENTITY_INTENT_MISMATCH
    many_ops = [
        OperationSpec(op_id=f"op{i}", type="build", target="t", inputs={}, outputs={})
        for i in range(51)
    ]
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(operations=many_ops))
    assert exc_info.value.code == ErrorCode.INVALID_SPEC


def test_deterministic_hash_with_identity():
    spec = _make_spec(identity="R-OCGG", intent="recruiting-update")
    validate_spec(spec)
    plan1 = build_plan(spec)
    plan2 = build_plan(spec)
    assert plan1.plan_hash == plan2.plan_hash
    assert plan1.identity == "R-OCGG"


def test_domain_override_mismatch_raises_domain_mismatch():
    with pytest.raises(DUDEXError) as exc_info:
        validate_spec(_make_spec(identity="W-OCGG", intent="web-build", domain_override="recruiting"))
    assert exc_info.value.code == ErrorCode.DOMAIN_MISMATCH


def test_invariant_violation_raises_error():
    spec = _make_spec(identity="W-OCGG", intent="web-build")
    validate_spec(spec)
    plan = build_plan(spec)
    plan.plan_hash = "tampered"
    with pytest.raises(DUDEXError) as exc_info:
        validate_invariants(spec, plan)
    assert exc_info.value.code == ErrorCode.INVARIANT_VIOLATION
    assert "PLAN_HASH_STABLE" in str(exc_info.value.details)


def test_contradiction_no_network_forbids_deploy_to_url():
    spec = _make_spec(
        constraints={"no_network": True},
        operations=[
            OperationSpec(op_id="d1", type="deploy", target="https://api.example.com", inputs={}, outputs={}),
        ],
    )
    with pytest.raises(DUDEXError) as exc_info:
        run_pstack(spec)
    assert exc_info.value.code == ErrorCode.SPEC_CONTRADICTION
    assert (exc_info.value.details or {}).get("op_id") == "d1"
