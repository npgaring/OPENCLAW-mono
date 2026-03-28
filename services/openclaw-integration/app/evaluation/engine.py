"""
Central evaluation engine: all four laws run on the same immutable EvaluationState every cycle.

Evaluators are imported inside ``evaluate`` so tests can monkeypatch ``app.evaluation.evaluators.*`` reliably.
"""
from __future__ import annotations

from typing import Optional

from app.core.config import settings
from app.evaluation.aggregator import build_atomic_evaluation_result
from app.evaluation.models import AtomicEvaluationResult
from app.evaluation.state import EvaluationState
from app.gate.models import GateEvaluation
from app.invariant_c.evaluator import InvariantCResult
from app.invariant_e.types import InvariantEResult
from app.uato.types import UatoResult


def _assert_evaluator_input_hashes_consistent(state: EvaluationState, pairs: tuple[tuple[str, str], ...]) -> None:
    for law_id, h in pairs:
        if h != state.state_hash:
            raise AssertionError(
                f"evaluator_input_hashes mismatch for {law_id}: {h!r} != state_hash {state.state_hash!r}"
            )


class EvaluationEngine:
    """Single entrypoint: always C + UATO + GRL + Invariant-E (decision) on the same state."""

    def evaluate(self, state: EvaluationState) -> AtomicEvaluationResult:
        from app.evaluation.evaluators.grl import evaluate_grl
        from app.evaluation.evaluators.invariant_c import evaluate_invariant_c_law
        from app.evaluation.evaluators.invariant_e import evaluate_invariant_e_decision
        from app.evaluation.evaluators.uato import evaluate_uato_law

        original_hash = state.state_hash
        ic = evaluate_invariant_c_law(state)
        uato = evaluate_uato_law(state)
        grl: GateEvaluation = evaluate_grl(state)
        ie = evaluate_invariant_e_decision(state)

        if (settings.app_env or "").lower() not in ("production", "prod"):
            if state.state_hash != original_hash:
                raise AssertionError("STATE MUTATED DURING EVALUATION")

        result = build_atomic_evaluation_result(state, ic, uato, ie, grl)
        _assert_evaluator_input_hashes_consistent(state, result.evaluator_input_hashes)
        return result

    def evaluate_with_evaluator_order(
        self,
        state: EvaluationState,
        *,
        order: tuple[str, ...],
    ) -> AtomicEvaluationResult:
        """Test hook: permute invocation order; all four laws always run."""
        from app.evaluation.evaluators.grl import evaluate_grl
        from app.evaluation.evaluators.invariant_c import evaluate_invariant_c_law
        from app.evaluation.evaluators.invariant_e import evaluate_invariant_e_decision
        from app.evaluation.evaluators.uato import evaluate_uato_law

        original_hash = state.state_hash
        ic: Optional[InvariantCResult] = None
        uato: Optional[UatoResult] = None
        ie: Optional[InvariantEResult] = None
        grl: Optional[GateEvaluation] = None

        def run(name: str) -> None:
            nonlocal ic, uato, ie, grl
            if name == "C":
                ic = evaluate_invariant_c_law(state)
            elif name == "UATO":
                uato = evaluate_uato_law(state)
            elif name == "E":
                ie = evaluate_invariant_e_decision(state)
            elif name == "GRL":
                grl = evaluate_grl(state)

        for step in order:
            run(step)
        if ic is None:
            ic = evaluate_invariant_c_law(state)
        if uato is None:
            uato = evaluate_uato_law(state)
        if ie is None:
            ie = evaluate_invariant_e_decision(state)
        if grl is None:
            grl = evaluate_grl(state)

        if (settings.app_env or "").lower() not in ("production", "prod"):
            if state.state_hash != original_hash:
                raise AssertionError("STATE MUTATED DURING EVALUATION")

        result = build_atomic_evaluation_result(state, ic, uato, ie, grl)
        _assert_evaluator_input_hashes_consistent(state, result.evaluator_input_hashes)
        return result


default_engine = EvaluationEngine()
