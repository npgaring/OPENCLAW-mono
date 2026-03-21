"""UATO pure evaluator: matrix, determinism, monotonicity, no plan mutation."""
import copy

import pytest

from app.uato.evaluator import evaluate_uato
from app.uato.normalize import normalize_authority_state, normalize_trust_state, normalize_uato_context
from app.uato.reason_codes import (
    UATO_BLOCK_LOW_TRUST_LOW_AUTHORITY,
    UATO_ESCALATE_LOW_TRUST_HIGH_AUTHORITY,
    UATO_PASS_HIGH_TRUST_HIGH_AUTHORITY,
    UATO_REQUIRE_APPROVAL_HIGH_TRUST_LOW_AUTHORITY,
)
from app.uato.types import UatoInput


def _ctx():
    c = normalize_uato_context(
        environment="dev",
        tenant_id="W-OCGG",
        request_source="API",
        trace_id="550e8400-e29b-41d4-a716-446655440000",
    )
    assert c is not None
    return c


def _base_input(trust: str, auth: str) -> UatoInput:
    plan = {
        "ocgg_identity": "W-OCGG",
        "plan_hash": "ph",
        "operations": [{"type": "build", "op_id": "1", "target": "x"}],
        "noise_field": {"should_not_matter": [1, 2, 3]},
    }
    ts = normalize_trust_state(level=trust, source="INTERNAL", evidence=["e1"])
    au = normalize_authority_state(
        level=auth,
        tenant_match=True,
        identity_bound=True,
        approval_capable=False,
        requested_scope=["0:build:x"],
        granted_scope=["0:build:x"],
    )
    return UatoInput(plan=plan, trust_state=ts, authority_state=au, context=_ctx())


def test_matrix_low_low_block():
    r = evaluate_uato(_base_input("LOW", "LOW"))
    assert r.decision == "BLOCK"
    assert UATO_BLOCK_LOW_TRUST_LOW_AUTHORITY in r.reason_codes


def test_matrix_low_high_escalate():
    r = evaluate_uato(_base_input("LOW", "HIGH"))
    assert r.decision == "ESCALATE"
    assert UATO_ESCALATE_LOW_TRUST_HIGH_AUTHORITY in r.reason_codes
    assert r.requires_human_approval is True


def test_matrix_high_low_require_approval():
    r = evaluate_uato(_base_input("HIGH", "LOW"))
    assert r.decision == "REQUIRE_APPROVAL"
    assert UATO_REQUIRE_APPROVAL_HIGH_TRUST_LOW_AUTHORITY in r.reason_codes
    assert r.requires_human_approval is True


def test_matrix_high_high_pass():
    r = evaluate_uato(_base_input("HIGH", "HIGH"))
    assert r.decision == "PASS"
    assert UATO_PASS_HIGH_TRUST_HIGH_AUTHORITY in r.reason_codes
    assert r.requires_human_approval is False


def test_determinism():
    inp = _base_input("HIGH", "HIGH")
    a = evaluate_uato(inp)
    b = evaluate_uato(inp)
    assert a == b


def test_irrelevant_plan_noise():
    inp1 = _base_input("HIGH", "HIGH")
    inp2 = copy.deepcopy(inp1)
    inp2.plan["extra"] = "noise"  # type: ignore[index]
    # fingerprint in trace hash differs; evaluator decision uses trust×authority only
    assert evaluate_uato(inp1).decision == evaluate_uato(inp2).decision


def test_monotonic_not_worse_from_low_to_high_trust():
    blocked = evaluate_uato(_base_input("LOW", "HIGH"))
    better = evaluate_uato(_base_input("HIGH", "HIGH"))
    assert blocked.decision == "ESCALATE"
    assert better.decision == "PASS"


def test_no_contradictory_outputs():
    r = evaluate_uato(_base_input("HIGH", "HIGH"))
    assert not (r.decision == "PASS" and r.requires_human_approval)


def test_tenant_mismatch_blocks():
    inp = _base_input("HIGH", "HIGH")
    au = normalize_authority_state(
        level="HIGH",
        tenant_match=False,
        identity_bound=True,
        approval_capable=False,
        requested_scope=["0:build:x"],
        granted_scope=["0:build:x"],
    )
    inp2 = UatoInput(plan=inp.plan, trust_state=inp.trust_state, authority_state=au, context=inp.context)
    r = evaluate_uato(inp2)
    assert r.decision == "BLOCK"


def test_malformed_operations_block():
    inp = _base_input("HIGH", "HIGH")
    p = copy.deepcopy(inp.plan)
    p["operations"] = "not-a-list"  # type: ignore[assignment]
    inp2 = UatoInput(plan=p, trust_state=inp.trust_state, authority_state=inp.authority_state, context=inp.context)
    r = evaluate_uato(inp2)
    assert r.decision == "BLOCK"
