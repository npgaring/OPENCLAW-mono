"""Adversarial determinism: key order, extra fields, float normalization, op_id sensitivity."""
import pytest

from app.api.compile import parse_compile_body
from app.compiler.planner import build_plan
from app.compiler.validator import validate_spec
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload, canonical_json
from app.models import Decisions, OperationSpec, Signature, SpecIn, Target


def _sig():
    return Signature(type="human_signed", signed_at="2024-01-01T00:00:00Z", hash="h1")


def _base_ops(op_id: str = "op-1"):
    return [
        OperationSpec(
            op_id=op_id,
            type="build",
            target="repo",
            inputs={},
            outputs={},
        ),
    ]


def test_spec_key_order_different_dicts_same_spec_hash():
    """Semantically same spec: root JSON key order differs → same hash after validate + model_dump."""
    d1 = {
        "spec_version": "1.0",
        "identity": "W-OCGG",
        "intent": "web-build",
        "target": {"resource_id": "r1", "environment": "preview"},
        "decisions": {"operations": [{"op_id": "op-1", "type": "build", "target": "repo", "inputs": {}, "outputs": {}}]},
        "constraints": {},
        "signature": {"type": "human_signed", "signed_at": "2024-01-01T00:00:00Z", "hash": "h1"},
    }
    d2 = {
        "signature": {"type": "human_signed", "signed_at": "2024-01-01T00:00:00Z", "hash": "h1"},
        "constraints": {},
        "decisions": {"operations": [{"op_id": "op-1", "type": "build", "target": "repo", "inputs": {}, "outputs": {}}]},
        "target": {"resource_id": "r1", "environment": "preview"},
        "intent": "web-build",
        "identity": "W-OCGG",
        "spec_version": "1.0",
    }
    s1 = SpecIn.model_validate(d1)
    s2 = SpecIn.model_validate(d2)
    assert hash_payload(s1.model_dump(mode="python")) == hash_payload(s2.model_dump(mode="python"))


def test_extra_top_level_field_rejected():
    with pytest.raises(DUDEXError) as exc:
        parse_compile_body(
            {
                "spec_version": "1.0",
                "identity": "W-OCGG",
                "intent": "web-build",
                "target": {"resource_id": "r1", "environment": "preview"},
                "decisions": {"operations": [{"op_id": "op-1", "type": "build", "target": "repo", "inputs": {}, "outputs": {}}]},
                "constraints": {},
                "signature": {"type": "human_signed", "signed_at": "2024-01-01T00:00:00Z", "hash": "h1"},
                "evil_injection": True,
            }
        )
    assert exc.value.code == ErrorCode.INVALID_SPEC


def test_canonical_json_float_integer_equivalence():
    """hash_payload normalizes 1.0 → 1 for integer-valued floats."""
    a = {"nested": {"x": 1.0}}
    b = {"nested": {"x": 1}}
    assert canonical_json(a) == canonical_json(b)
    assert hash_payload(a) == hash_payload(b)


def test_different_op_id_different_plan_hash():
    """Document: op_id is in plan body → different identity of operations changes plan_hash."""
    def make_spec(oid: str):
        return SpecIn(
            spec_version="1.0",
            identity="W-OCGG",
            intent="web-build",
            target=Target(resource_id="r1", environment="preview"),
            decisions=Decisions(operations=_base_ops(oid)),
            constraints={},
            signature=_sig(),
        )

    s1 = make_spec("op-a")
    s2 = make_spec("op-b")
    validate_spec(s1)
    validate_spec(s2)
    p1 = build_plan(s1)
    p2 = build_plan(s2)
    assert p1.plan_hash != p2.plan_hash


def test_build_plan_includes_agent_team_metadata():
    spec = SpecIn(
        spec_version="1.0",
        identity="W-OCGG",
        intent="web-build",
        target=Target(resource_id="r1", environment="preview"),
        decisions=Decisions(operations=_base_ops("op-agent")),
        constraints={},
        signature=_sig(),
    )

    plan = build_plan(spec)

    assert plan.agent_team is not None
    work_packets = plan.agent_team["work_packets"]
    assert [packet["agent_role"] for packet in work_packets] == [
        "planner", "frontend", "sanitizer", "backend", "reviewer", "verifier",
    ]
    assert any(entry["agent_role"] == "frontend" for entry in plan.agent_team["file_ownership"])
    assert any(entry["agent_role"] == "sanitizer" for entry in plan.agent_team["file_ownership"])
    assert any(entry["agent_role"] == "reviewer" for entry in plan.agent_team["file_ownership"])
    assert any(entry["route"] == "/" for entry in plan.agent_team["route_ownership"])
    for packet in work_packets:
        assert "instructions" in packet, f"Work packet for {packet['agent_role']} missing instructions"
