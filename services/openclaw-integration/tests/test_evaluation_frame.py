"""Unit tests for shared-state evaluation frame composition (Invariant-C + UATO + Invariant-E)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.evaluation_frame import build_shared_governable_state_for_task, run_evaluation_frame
from app.evaluation_frame.state import FrameStatus
from app.invariant_e.types import result_denied
from app.models.task import TaskSubmitRequest, TaskOperation


def _minimal_task_body(**kwargs):
    ops = [
        TaskOperation(type="build", op_id="1", target="repo", inputs={}, outputs={}),
    ]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": [o.model_dump() for o in ops]})
    base = {"ocgg_identity": "W-OCGG", "plan_hash": ph, "operations": ops}
    base.update(kwargs)
    return TaskSubmitRequest.model_validate(base)


def test_frame_runs_all_three_evaluators_when_c_blocks():
    """Invariant-C BLOCK must not skip UATO / Invariant-E; composite stays BLOCKED."""
    body = _minimal_task_body()
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-446655440099", for_resume=False)

    def fake_c(state):
        from app.invariant_c.evaluator import INVARIANT_C_DECISION_VERSION, InvariantCheckResult

        cr = {"Meaning": InvariantCheckResult(passed=False, reason_codes=("INVARIANT_C_SYNTHETIC",))}
        from app.invariant_c.evaluator import InvariantCResult

        return InvariantCResult(decision="BLOCK", reason_codes=("INVARIANT_C_SYNTHETIC",), check_results=cr, decision_version=INVARIANT_C_DECISION_VERSION)

    with patch("app.evaluation.evaluators.invariant_c.evaluate_invariant_c_law", side_effect=fake_c):
        fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.BLOCKED
    assert fr.uato_result.decision == "PASS"
    assert fr.invariant_e_result.decision == "EXECUTION_ALLOWED"


def test_frame_pass_allows_governance_progress_semantics():
    body = _minimal_task_body()
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-4466554400aa", for_resume=False)
    fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.PASS
    assert fr.admissible is True


def test_uato_require_approval_only_when_c_and_e_allow():
    body = _minimal_task_body(uato={"trust_level": "HIGH", "authority_level": "LOW"})
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-4466554400bb", for_resume=False)
    fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.APPROVAL_REQUIRED
    assert fr.approvable_via_uato is True


def test_invariant_e_deny_stops_even_when_uato_wants_approval(monkeypatch):
    """Set-based aggregate: Invariant-E failure is a STOP; UATO approval need does not mask it."""
    body = _minimal_task_body(uato={"trust_level": "HIGH", "authority_level": "LOW"})
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-4466554400cc", for_resume=False)

    monkeypatch.setattr(
        "app.evaluation.evaluators.invariant_e.evaluate_invariant_e_decision",
        lambda state: result_denied(state.governable.trace_id, ("IE_DENIED_SYNTHETIC",)),
    )
    fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.BLOCKED
    assert fr.approval_required is False
    assert fr.approvable_via_uato is False


def test_invariant_c_block_dominates_uato_require_approval(monkeypatch):
    """UATO REQUIRE_APPROVAL cannot yield APPROVAL_REQUIRED if Invariant-C fails (non-approvable)."""
    body = _minimal_task_body(uato={"trust_level": "HIGH", "authority_level": "LOW"})
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-4466554400ee", for_resume=False)

    def fake_c(state):
        from app.invariant_c.evaluator import INVARIANT_C_DECISION_VERSION, InvariantCheckResult, InvariantCResult

        cr = {"Meaning": InvariantCheckResult(passed=False, reason_codes=("INVARIANT_C_SYNTHETIC",))}
        return InvariantCResult(decision="BLOCK", reason_codes=("INVARIANT_C_SYNTHETIC",), check_results=cr, decision_version=INVARIANT_C_DECISION_VERSION)

    monkeypatch.setattr("app.evaluation.evaluators.invariant_c.evaluate_invariant_c_law", fake_c)
    fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.BLOCKED
    assert fr.uato_result.decision == "REQUIRE_APPROVAL"
    assert fr.approval_required is False


def test_escalate_domain_frame_is_approval_required_not_approvable_via_uato():
    body = _minimal_task_body(uato={"trust_level": "LOW", "authority_level": "HIGH"})
    shared = build_shared_governable_state_for_task(body, "550e8400-e29b-41d4-a716-4466554400dd", for_resume=False)
    fr = run_evaluation_frame(shared)
    assert fr.frame_status == FrameStatus.APPROVAL_REQUIRED
    assert fr.approval_required is True
    assert fr.approvable_via_uato is False
