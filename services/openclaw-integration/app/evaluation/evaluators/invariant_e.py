"""
Invariant-E decision mode in the atomic cycle: envelope derived only from EvaluationState.
"""
from __future__ import annotations

from app.evaluation.invariant_e_view import derive_execution_envelope_from_state
from app.evaluation.state import EvaluationState
from app.invariant_e.evaluator import evaluate_invariant_e_decision as invariant_e_decision_on_envelope
from app.invariant_e.types import InvariantEResult


def evaluate_invariant_e_decision(state: EvaluationState) -> InvariantEResult:
    env = derive_execution_envelope_from_state(state)
    return invariant_e_decision_on_envelope(env)
