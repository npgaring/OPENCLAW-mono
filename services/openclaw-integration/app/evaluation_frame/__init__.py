"""Shared-state admissibility evaluation frame (Invariant-C, UATO, Invariant-E)."""

from app.evaluation_frame.evaluate import run_evaluation_frame
from app.evaluation_frame.state import (
    ApprovalFrameContext,
    CompositeFrameResult,
    FrameStatus,
    SharedGovernableState,
)
from app.evaluation_frame.build import (
    build_shared_governable_state_for_gate_payload,
    build_shared_governable_state_for_task,
)

__all__ = [
    "ApprovalFrameContext",
    "CompositeFrameResult",
    "FrameStatus",
    "SharedGovernableState",
    "build_shared_governable_state_for_gate_payload",
    "build_shared_governable_state_for_task",
    "run_evaluation_frame",
]
