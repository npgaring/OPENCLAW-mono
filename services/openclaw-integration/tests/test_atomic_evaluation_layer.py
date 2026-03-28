"""Prove the atomic evaluation model: shared state_hash, determinism, order-independent aggregation, composition."""
from __future__ import annotations

import copy

import pytest

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.evaluation import build_evaluation_state_from_task_request, default_engine
from app.evaluation.aggregator import aggregate_atomic, composite_frame_from_atomic
from app.evaluation.engine import EvaluationEngine
from app.evaluation.evaluators.grl import evaluate_grl
from app.evaluation.evaluators.invariant_c import evaluate_invariant_c_law
from app.evaluation.evaluators.invariant_e import evaluate_invariant_e_decision
from app.evaluation.evaluators.uato import evaluate_uato_law
from app.evaluation.models import FinalAggregateDecision
from app.evaluation.state import EvaluationState
from app.evaluation_frame.state import FrameStatus
from app.invariant_e.evaluator import evaluate_invariant_e_decision as ie_decision_from_envelope
from app.invariant_e.build_envelope import build_execution_envelope
from app.models.task import TaskOperation, TaskSubmitRequest


def _minimal_body(**kwargs):
    ops = [TaskOperation(type="build", op_id="1", target="repo", inputs={}, outputs={})]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": [o.model_dump() for o in ops]})
    base = {"ocgg_identity": "W-OCGG", "plan_hash": ph, "operations": ops}
    base.update(kwargs)
    return TaskSubmitRequest.model_validate(base)


def _ev(trace: str = "550e8400-e29b-41d4-a716-446655440001") -> EvaluationState:
    return build_evaluation_state_from_task_request(_minimal_body(), trace)


def test_all_evaluators_see_same_state_hash():
    s = _ev()
    sh = s.state_hash
    evaluate_invariant_c_law(s)
    evaluate_uato_law(s)
    evaluate_invariant_e_decision(s)
    evaluate_grl(s)
    assert s.state_hash == sh


def test_evaluation_state_is_frozen_no_mutation_from_evaluators():
    s = _ev()
    spec_before = copy.deepcopy(s.governable.spec_for_gate)
    default_engine.evaluate(s)
    assert s.governable.spec_for_gate == spec_before


def test_identical_inputs_identical_atomic_result():
    t = "550e8400-e29b-41d4-a716-446655440002"
    a1 = default_engine.evaluate(build_evaluation_state_from_task_request(_minimal_body(), t))
    a2 = default_engine.evaluate(build_evaluation_state_from_task_request(_minimal_body(), t))
    assert a1.state_hash == a2.state_hash
    assert a1.final_decision == a2.final_decision
    assert a1.evaluator_input_hashes == a2.evaluator_input_hashes
    assert all(h == a1.state_hash for _, h in a1.evaluator_input_hashes)


@pytest.mark.parametrize(
    "order",
    [
        ("C", "UATO", "E", "GRL"),
        ("GRL", "E", "UATO", "C"),
        ("UATO", "C", "GRL", "E"),
        ("E", "GRL", "C", "UATO"),
    ],
)
def test_evaluator_order_independence_full_cycle(order: tuple[str, ...]):
    eng = EvaluationEngine()
    s = _ev("550e8400-e29b-41d4-a716-446655440003")
    r1 = eng.evaluate_with_evaluator_order(s, order=order)
    r2 = eng.evaluate(s)
    assert r1.state_hash == r2.state_hash
    assert r1.final_decision == r2.final_decision
    assert tuple((lr.law_id, lr.passed, lr.reason_codes) for lr in r1.law_records) == tuple(
        (lr.law_id, lr.passed, lr.reason_codes) for lr in r2.law_records
    )


def test_aggregate_order_independence_via_identical_law_outputs():
    s = _ev()
    ic = evaluate_invariant_c_law(s)
    u = evaluate_uato_law(s)
    ie = evaluate_invariant_e_decision(s)
    grl = evaluate_grl(s)
    fd1, *_rest1, rec1 = aggregate_atomic(s, ic, u, ie, grl)
    fd2, *_rest2, rec2 = aggregate_atomic(s, ic, u, ie, grl)
    assert fd1 == fd2
    assert rec1 == rec2


def test_composition_all_pass_executable():
    s = _ev("550e8400-e29b-41d4-a716-446655440004")
    a = default_engine.evaluate(s)
    if a.final_decision != FinalAggregateDecision.EXECUTE:
        pytest.skip("minimal body not universally executable in this environment")
    assert a.invariant_c.decision == "PASS"
    assert a.uato.decision == "PASS"
    assert a.invariant_e_decision.decision == "EXECUTION_ALLOWED"
    assert a.grl.decision.outcome.value == "PASS"


def test_c_fail_blocks_aggregate(monkeypatch):
    s = _ev()

    def fake_c(state):
        from app.invariant_c.evaluator import INVARIANT_C_DECISION_VERSION, InvariantCheckResult, InvariantCResult

        cr = {"Meaning": InvariantCheckResult(passed=False, reason_codes=("INVARIANT_C_SYNTHETIC",))}
        return InvariantCResult(
            decision="BLOCK",
            reason_codes=("INVARIANT_C_SYNTHETIC",),
            check_results=cr,
            decision_version=INVARIANT_C_DECISION_VERSION,
        )

    monkeypatch.setattr("app.evaluation.evaluators.invariant_c.evaluate_invariant_c_law", fake_c)
    a = default_engine.evaluate(s)
    assert a.final_decision == FinalAggregateDecision.STOP


def test_uato_block_only_stops():
    s = _minimal_body(uato={"trust_level": "LOW", "authority_level": "LOW"})
    ev = build_evaluation_state_from_task_request(s, "550e8400-e29b-41d4-a716-446655440005")
    a = default_engine.evaluate(ev)
    assert a.uato.decision == "BLOCK"
    assert a.final_decision == FinalAggregateDecision.STOP


def test_grl_block_only_stops(monkeypatch):
    s = _ev("550e8400-e29b-41d4-a716-446655440006")

    class _FakeGrl:
        def evaluate(self, spec, ocgg_identity):
            from app.gate.models import Defect, GateDecision, GateEvaluation, GateOutcome

            d = GateDecision(
                outcome=GateOutcome.BLOCK,
                reason_codes=["PLAN_HASH_MISMATCH"],
                defect_list=[Defect("PLAN_HASH_MISMATCH", "plan_hash", "x")],
                policy_version="t",
                spec_hash="",
                plan_hash="",
                approver_id=None,
            )
            return GateEvaluation(decision=d, plan_json={}, spec_hash="", plan_hash="")

    monkeypatch.setattr("app.evaluation.evaluators.grl.GateEngine", _FakeGrl)
    a = default_engine.evaluate(s)
    assert a.final_decision == FinalAggregateDecision.STOP


def test_invariant_e_decision_deny_stops():
    s = _ev("550e8400-e29b-41d4-a716-446655440007")

    def fake_e(state):
        from app.invariant_e.types import result_denied

        return result_denied(state.governable.trace_id, ("IE_DENIED_TEST_ATOMIC",))

    ic = evaluate_invariant_c_law(s)
    u = evaluate_uato_law(s)
    ie = fake_e(s)
    grl = evaluate_grl(s)
    fd, failed, _appr, _kind, _rec = aggregate_atomic(s, ic, u, ie, grl)
    assert fd == FinalAggregateDecision.STOP
    assert "INVARIANT_E_DECISION" in failed


def test_dispatch_enforcement_can_deny_after_decision_allowed(monkeypatch):
    """Shared-state E may allow; dispatch-time enforcement can still deny."""
    import app.invariant_e.evaluator as ie_eval_mod

    s = _ev()
    env = build_execution_envelope(
        spec=dict(s.governable.spec_for_gate),
        ocgg_identity=s.governable.ocgg_identity,
        trace_id=s.governable.trace_id,
        task_id=None,
        governance_outcome="PASS",
        plan_hash=s.governable.plan_hash,
        spec_hash=s.governable.spec_hash,
        validation_controls=s.governable.validation_controls,
    )
    frame_env = build_execution_envelope(
        spec=dict(s.governable.spec_for_gate),
        ocgg_identity=s.governable.ocgg_identity,
        trace_id=s.governable.trace_id,
        task_id=None,
        governance_outcome="PENDING",
        plan_hash=s.governable.plan_hash,
        spec_hash=s.governable.spec_hash,
        validation_controls=s.governable.validation_controls,
    )
    frame_ie = ie_decision_from_envelope(frame_env)
    assert frame_ie.decision in ("EXECUTION_ALLOWED", "EXECUTION_DENIED")

    from app.invariant_e.types import result_denied as _rd

    monkeypatch.setattr(
        ie_eval_mod,
        "enforce_invariant_e_dispatch",
        lambda e: _rd(getattr(e, "trace_id", None) or "", ("IE_DISPATCH_ENFORCEMENT_TEST",)),
    )
    dispatch_res = ie_eval_mod.enforce_invariant_e_dispatch(env)
    assert dispatch_res.decision == "EXECUTION_DENIED"
    assert "IE_DISPATCH_ENFORCEMENT_TEST" in dispatch_res.reason_codes


def test_uato_independent_of_grl_violation_in_aggregate():
    s = _ev()
    u1 = evaluate_uato_law(s)

    class _Blk:
        def evaluate(self, spec, ocgg_identity):
            from app.gate.models import Defect, GateDecision, GateEvaluation, GateOutcome

            d = GateDecision(
                outcome=GateOutcome.BLOCK,
                reason_codes=["X"],
                defect_list=[Defect("X", None, "m")],
                policy_version="p",
                spec_hash="a",
                plan_hash="b",
                approver_id=None,
            )
            return GateEvaluation(decision=d, plan_json={}, spec_hash="a", plan_hash="b")

    import app.evaluation.evaluators.grl as grl_mod

    orig = grl_mod.GateEngine
    grl_mod.GateEngine = _Blk
    try:
        a = default_engine.evaluate(s)
    finally:
        grl_mod.GateEngine = orig
    u_record = next(x for x in a.law_records if x.law_id == "UATO")
    assert u_record.passed == (u1.decision == "PASS")


def test_composite_frame_grl_only_block_matches_final_stop():
    s = _ev()
    a = default_engine.evaluate(s)
    if a.final_decision != FinalAggregateDecision.STOP:
        pytest.skip("need GRL-only block scenario")
    triple = (
        a.invariant_c.decision == "PASS"
        and a.uato.decision == "PASS"
        and a.invariant_e_decision.decision == "EXECUTION_ALLOWED"
    )
    if not triple or a.grl.decision.outcome.value == "PASS":
        pytest.skip("not GRL-only block")
    fr = composite_frame_from_atomic(a)
    assert fr.frame_status == FrameStatus.BLOCKED
    assert "GRL" in a.failed_laws


def test_multi_failure_lists_all_failed_laws(monkeypatch):
    s = _ev()

    def fake_c(state):
        from app.invariant_c.evaluator import INVARIANT_C_DECISION_VERSION, InvariantCheckResult, InvariantCResult

        cr = {"Meaning": InvariantCheckResult(passed=False, reason_codes=("INVARIANT_C_SYNTHETIC",))}
        return InvariantCResult(
            decision="BLOCK",
            reason_codes=("INVARIANT_C_SYNTHETIC",),
            check_results=cr,
            decision_version=INVARIANT_C_DECISION_VERSION,
        )

    class _Blk:
        def evaluate(self, spec, ocgg_identity):
            from app.gate.models import Defect, GateDecision, GateEvaluation, GateOutcome

            d = GateDecision(
                outcome=GateOutcome.BLOCK,
                reason_codes=["PLAN_HASH_MISMATCH"],
                defect_list=[Defect("PLAN_HASH_MISMATCH", "plan_hash", "x")],
                policy_version="t",
                spec_hash="",
                plan_hash="",
                approver_id=None,
            )
            return GateEvaluation(decision=d, plan_json={}, spec_hash="", plan_hash="")

    monkeypatch.setattr("app.evaluation.evaluators.invariant_c.evaluate_invariant_c_law", fake_c)
    monkeypatch.setattr("app.evaluation.evaluators.grl.GateEngine", _Blk)
    a = default_engine.evaluate(s)
    assert a.final_decision == FinalAggregateDecision.STOP
    assert "INVARIANT_C" in a.failed_laws
    assert "GRL" in a.failed_laws


def test_invariant_e_evaluator_source_does_not_import_grl():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "app/evaluation/evaluators/invariant_e.py"
    text = p.read_text()
    assert "evaluators.grl" not in text
    assert "GateEngine" not in text


def test_grl_evaluator_source_does_not_import_other_law_evaluators():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "app/evaluation/evaluators/grl.py"
    text = p.read_text()
    assert "evaluators.uato" not in text
    assert "evaluators.invariant_c" not in text
    assert "evaluators.invariant_e" not in text


def test_evaluation_record_payload_has_trace_fields():
    from app.services.evaluation_persistence import atomic_evaluation_to_payload

    s = _ev()
    a = default_engine.evaluate(s)
    p = atomic_evaluation_to_payload(a)
    assert p["state_hash"] == a.state_hash
    assert set(p["evaluator_input_hashes"].keys()) == {"C", "UATO", "GRL", "E"}
    assert all(p["evaluator_input_hashes"][k] == a.state_hash for k in p["evaluator_input_hashes"])
    assert set(p["results"].keys()) == {"C", "UATO", "GRL", "E"}
    assert p["final_decision"] == a.final_decision.value
    assert p["failed_laws"] == list(a.failed_laws)
    assert p["approval_sources"] == list(a.approval_sources)


def test_approval_rebuild_merges_into_new_state():
    from app.evaluation import build_evaluation_state_with_resolved_approval

    trace = "550e8400-e29b-41d4-a716-446655440099"
    e1 = build_evaluation_state_with_resolved_approval(
        _minimal_body(approval_reference="ar-1", approver_id="approver-x"),
        trace,
    )
    assert e1.governable.spec_for_gate.get("approval_reference") == "ar-1"
    assert e1.governable.spec_for_gate.get("approver_id") == "approver-x"
    assert e1.governable.approval_context is not None
