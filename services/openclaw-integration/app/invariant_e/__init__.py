"""Invariant-E: post-governance execution admission before OpenClaw dispatch."""
from app.invariant_e.build_envelope import build_execution_envelope
from app.invariant_e.evaluator import evaluate_invariant_e, evaluate_invariant_e_for_frame
from app.invariant_e.trace import to_trace_record
from app.invariant_e.types import (
    INVARIANT_E_DECISION_VERSION,
    ExecutionDecision,
    ExecutionEnvelope,
    InvariantEResult,
)

__all__ = [
    "INVARIANT_E_DECISION_VERSION",
    "ExecutionDecision",
    "ExecutionEnvelope",
    "InvariantEResult",
    "build_execution_envelope",
    "evaluate_invariant_e",
    "evaluate_invariant_e_for_frame",
    "to_trace_record",
]
