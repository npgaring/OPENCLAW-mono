"""Invariant-C law: semantic / constraint admissibility over EvaluationState."""
from __future__ import annotations

from app.evaluation.state import EvaluationState
from app.invariant_c.evaluator import InvariantCResult, evaluate_invariant_c


def evaluate_invariant_c_law(state: EvaluationState) -> InvariantCResult:
    g = state.governable
    return evaluate_invariant_c(
        candidate_plan=g.candidate_plan,
        ocgg_identity=g.ocgg_identity,
        intent=g.intent,
        objective=g.objective,
        context=g.context,
        constraints=g.constraints,
    )
