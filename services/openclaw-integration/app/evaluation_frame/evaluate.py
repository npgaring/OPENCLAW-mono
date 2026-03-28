"""
Adapter: shared governable snapshot → full atomic ``evaluate()`` → legacy ``CompositeFrameResult``.

All four laws run; the composite is derived from ``AtomicEvaluationResult`` (no partial engine path).
"""
from __future__ import annotations

from app.evaluation.aggregator import composite_frame_from_atomic
from app.evaluation.builder import build_evaluation_state_from_shared_governable
from app.evaluation.engine import default_engine
from app.evaluation_frame.state import CompositeFrameResult, SharedGovernableState


def run_evaluation_frame(state: SharedGovernableState) -> CompositeFrameResult:
    ev = build_evaluation_state_from_shared_governable(state)
    atomic = default_engine.evaluate(ev)
    return composite_frame_from_atomic(atomic)
