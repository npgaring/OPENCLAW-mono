"""Canonical immutable evaluation state shared by all laws in one cycle."""
from __future__ import annotations

from dataclasses import dataclass

from app.evaluation_frame.state import SharedGovernableState


@dataclass(frozen=True)
class EvaluationState:
    """
    Single canonical snapshot for one evaluation cycle.

    Invariant-E decision mode uses a fixed envelope phase constant in ``invariant_e_view`` (not a field here),
    so E is not coupled to GRL via shared state.
    """

    governable: SharedGovernableState
    uato_trust_level: str
    uato_authority_level: str
    uato_trust_source: str
    state_hash: str
