"""Pure derivation of Invariant-E envelope from EvaluationState (no GRL coupling on state)."""
from __future__ import annotations

from app.evaluation.state import EvaluationState
from app.invariant_e.build_envelope import build_execution_envelope
from app.invariant_e.types import ExecutionEnvelope

# Envelope field required by ``ExecutionEnvelope``; value means "not post-governance dispatch" for admission core.
# Not read from governance law output — fixed for the atomic *decision* cycle only.
_INVARIANT_E_DECISION_ENVELOPE_PHASE = "PENDING"


def derive_execution_envelope_from_state(state: EvaluationState) -> ExecutionEnvelope:
    """
    Deterministic execution view for Invariant-E *decision mode* in the atomic cycle.

    Derived only from ``state.governable`` (+ structural phase constant). No GRL-derived fields on ``EvaluationState``.
    """
    g = state.governable
    return build_execution_envelope(
        spec=g.spec_for_gate,
        ocgg_identity=g.ocgg_identity,
        trace_id=g.trace_id,
        task_id=None,
        governance_outcome=_INVARIANT_E_DECISION_ENVELOPE_PHASE,
        plan_hash=g.plan_hash,
        spec_hash=g.spec_hash,
        validation_controls=g.validation_controls,
    )
