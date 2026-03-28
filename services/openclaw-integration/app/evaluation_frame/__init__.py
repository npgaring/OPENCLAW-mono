"""Shared-state admissibility evaluation frame (Invariant-C, UATO, Invariant-E)."""

from app.evaluation_frame.build import (
    build_shared_governable_state_for_gate_payload,
    build_shared_governable_state_for_task,
)
from app.evaluation_frame.state import (
    ApprovalFrameContext,
    CompositeFrameResult,
    FrameStatus,
    SharedGovernableState,
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


def __getattr__(name: str):
    if name == "run_evaluation_frame":
        from app.evaluation_frame.evaluate import run_evaluation_frame as _run_evaluation_frame

        return _run_evaluation_frame
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
