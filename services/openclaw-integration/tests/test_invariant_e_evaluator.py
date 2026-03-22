"""Invariant-E pure evaluator: admission matrix, determinism, independence from noisy fields."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.config import settings
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.invariant_e.build_envelope import build_execution_envelope
from app.invariant_e.evaluator import evaluate_invariant_e
from app.invariant_e.reason_codes import (
    IE_ALLOWED,
    IE_DENIED_BUDGET_REQUIRED,
    IE_DENIED_CAPABILITY_NOT_ALLOWED,
    IE_DENIED_FORBIDDEN_OPERATION,
    IE_DENIED_GOVERNANCE_NOT_PASS,
    IE_DENIED_IDENTITY_TENANT_MISMATCH,
    IE_DENIED_PROD_APPROVAL_REQUIRED,
)
from app.invariant_e.types import ExecutionEnvelope


def _ops(types: list[str]) -> tuple[dict, ...]:
    return tuple({"type": t, "op_id": str(i), "target": "x"} for i, t in enumerate(types))


def _envelope(**kwargs: object) -> ExecutionEnvelope:
    base = dict(
        trace_id="550e8400-e29b-41d4-a716-446655440000",
        task_id="task-1",
        tenant_id="W-OCGG",
        identity="W-OCGG",
        plan_hash="phash",
        spec_hash="shash",
        governance_outcome="PASS",
        approval_reference=None,
        approver_id=None,
        deployment_target=None,
        operations=_ops(["build"]),
        requested_capabilities=("op:build",),
        allowed_capabilities=("op:build", "op:deploy", "op:write_config", "op:create_file", "op:test", "op:rollback_prep"),
        budget_limit=None,
        network_scope={"allowed_target_domains": ["allowed-domain.com"]},
        filesystem_scope={"allowed_write_root": "/workspace"},
        runtime_context={"integration_policy_version": "1.0.0"},
    )
    base.update(kwargs)
    return ExecutionEnvelope(**base)  # type: ignore[arg-type]


def test_determinism():
    e = _envelope()
    assert evaluate_invariant_e(e) == evaluate_invariant_e(e)


def test_governance_not_pass_denies():
    r = evaluate_invariant_e(_envelope(governance_outcome="BLOCK"))
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_GOVERNANCE_NOT_PASS in r.reason_codes


def test_tenant_identity_mismatch_denies():
    r = evaluate_invariant_e(_envelope(tenant_id="R-OCGG", identity="W-OCGG"))
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_IDENTITY_TENANT_MISMATCH in r.reason_codes


def test_prod_requires_approval():
    r = evaluate_invariant_e(
        _envelope(
            deployment_target="production",
            approval_reference=None,
            approver_id=None,
        )
    )
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_PROD_APPROVAL_REQUIRED in r.reason_codes


def test_prod_passes_with_approval():
    r = evaluate_invariant_e(
        _envelope(
            deployment_target="production",
            approval_reference="ref-1",
        )
    )
    assert r.decision == "EXECUTION_ALLOWED"
    assert IE_ALLOWED in r.reason_codes


def test_capability_not_in_allowlist():
    r = evaluate_invariant_e(
        _envelope(
            operations=_ops(["unknown_op"]),
            requested_capabilities=("op:unknown_op",),
            allowed_capabilities=("op:build",),
        )
    )
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_CAPABILITY_NOT_ALLOWED in r.reason_codes


def test_forbidden_operation_type_defensive():
    r = evaluate_invariant_e(
        _envelope(
            operations=_ops(["rm_rf"]),
            requested_capabilities=("op:rm_rf",),
            allowed_capabilities=("op:rm_rf",),
        )
    )
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_FORBIDDEN_OPERATION in r.reason_codes


def test_budget_required_when_config_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "invariant_e_require_budget_limit", True)
    r = evaluate_invariant_e(_envelope(budget_limit=None))
    assert r.decision == "EXECUTION_DENIED"
    assert IE_DENIED_BUDGET_REQUIRED in r.reason_codes


def test_budget_satisfies_when_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "invariant_e_require_budget_limit", True)
    r = evaluate_invariant_e(_envelope(budget_limit={"max_cost_usd": 1}))
    assert r.decision == "EXECUTION_ALLOWED"


def test_noise_in_runtime_context_does_not_change_decision():
    e1 = _envelope()
    e2 = replace(e1, runtime_context={**(e1.runtime_context or {}), "noise": [1, 2, 3]})
    assert evaluate_invariant_e(e1).decision == evaluate_invariant_e(e2).decision


def test_build_envelope_aligns_with_gate_hashes():
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ops = [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]
    ph = hash_payload({"domain": domain, "operations": ops})
    spec = {
        "ocgg_identity": "W-OCGG",
        "plan_hash": ph,
        "operations": ops,
    }
    sh = hash_payload(spec)
    env = build_execution_envelope(
        spec=spec,
        ocgg_identity="W-OCGG",
        trace_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=None,
        governance_outcome="PASS",
        plan_hash=ph,
        spec_hash=sh,
    )
    r = evaluate_invariant_e(env)
    assert r.decision == "EXECUTION_ALLOWED"


def test_no_contradictory_allowed_and_blocked():
    r = evaluate_invariant_e(_envelope())
    assert not (r.decision == "EXECUTION_ALLOWED" and r.dispatch_blocked)
