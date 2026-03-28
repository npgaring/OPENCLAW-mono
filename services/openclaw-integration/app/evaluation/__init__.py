"""
Atomic evaluation layer: one immutable ``EvaluationState``, one ``EvaluationEngine``, set-based aggregation.

- **GRL** wraps legacy ``GateEngine`` policy in the same cycle as C, UATO, and Invariant-E *decision mode*.
- **Invariant-E** dispatch enforcement remains ``enforce_invariant_e_dispatch`` in ``app.invariant_e``.
"""

from app.evaluation.builder import (
    build_evaluation_state_from_gate_request,
    build_evaluation_state_from_shared_governable,
    build_evaluation_state_from_task_request,
    build_evaluation_state_with_resolved_approval,
)
from app.evaluation.engine import EvaluationEngine, default_engine
from app.evaluation.models import AtomicEvaluationResult, FinalAggregateDecision, LawId
from app.evaluation.state import EvaluationState

__all__ = [
    "AtomicEvaluationResult",
    "EvaluationEngine",
    "EvaluationState",
    "FinalAggregateDecision",
    "LawId",
    "build_evaluation_state_from_gate_request",
    "build_evaluation_state_from_shared_governable",
    "build_evaluation_state_from_task_request",
    "build_evaluation_state_with_resolved_approval",
    "default_engine",
]
