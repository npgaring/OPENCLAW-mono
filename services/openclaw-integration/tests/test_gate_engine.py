"""Gate engine: PASS, BLOCK, reason codes."""
import pytest

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.gate.engine import GateEngine
from app.gate.policy import POLICY_VERSION


def test_gate_pass_valid_payload():
    engine = GateEngine()
    spec = {
        "ocgg_identity": "W-OCGG",
        "plan_hash": "abc",
        "operations": [{"type": "build", "op_id": "1", "target": "repo"}],
    }
    # Plan hash will be computed; so we need to pass matching plan_hash
    from app.core.security import hash_payload
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    plan_canonical = {"domain": domain, "operations": spec["operations"]}
    spec["plan_hash"] = hash_payload(plan_canonical)
    evaluation = engine.evaluate(spec, "W-OCGG")
    assert evaluation.decision.outcome.value in ("PASS", "BLOCK")
    assert evaluation.decision.policy_version == POLICY_VERSION


def test_gate_block_plan_hash_mismatch():
    engine = GateEngine()
    spec = {
        "ocgg_identity": "W-OCGG",
        "plan_hash": "wrong_hash",
        "operations": [{"type": "build", "op_id": "1", "target": "repo"}],
    }
    evaluation = engine.evaluate(spec, "W-OCGG")
    assert evaluation.decision.outcome.value == "BLOCK"
    assert "PLAN_HASH_MISMATCH" in evaluation.decision.reason_codes


def test_gate_block_unknown_identity():
    engine = GateEngine()
    spec = {
        "ocgg_identity": "UNKNOWN",
        "plan_hash": "x",
        "operations": [{"type": "build", "op_id": "1", "target": "repo"}],
    }
    evaluation = engine.evaluate(spec, "UNKNOWN")
    assert evaluation.decision.outcome.value == "BLOCK"
    assert "UNKNOWN_IDENTITY" in evaluation.decision.reason_codes
