"""Atomic evaluation result models (law outputs + aggregate semantics)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Optional

from app.gate.models import GateEvaluation
from app.invariant_c.evaluator import InvariantCResult
from app.invariant_e.types import InvariantEResult
from app.uato.types import UatoResult


class LawId(str, Enum):
    """Stable identifiers for laws evaluated in one atomic cycle."""

    INVARIANT_C = "INVARIANT_C"
    UATO = "UATO"
    GRL = "GRL"
    INVARIANT_E_DECISION = "INVARIANT_E_DECISION"


class AtomicFinalDecision(str, Enum):
    """Single authoritative outcome after all laws are evaluated (set-based aggregation)."""

    STOP = "STOP"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    EXECUTE = "EXECUTE"


# Backward-compatible aliases for internal migrations / readability
FinalAggregateDecision = AtomicFinalDecision


@dataclass(frozen=True)
class LawEvaluationRecord:
    """Serializable per-law snapshot for audit / evaluation_records.payload."""

    law_id: str
    passed: bool
    reason_codes: tuple[str, ...]
    policy_or_version: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


def standard_evaluator_input_hashes(state_hash: str) -> tuple[tuple[str, str], ...]:
    """Every law in the cycle must be keyed to the same ``state_hash`` (proves one shared snapshot)."""
    pairs = [
        (LawId.INVARIANT_C.value, state_hash),
        (LawId.UATO.value, state_hash),
        (LawId.GRL.value, state_hash),
        (LawId.INVARIANT_E_DECISION.value, state_hash),
    ]
    return tuple(sorted(pairs, key=lambda x: x[0]))


@dataclass(frozen=True)
class AtomicEvaluationResult:
    """
    One immutable result of evaluating all four laws against the same EvaluationState.

    ``final_decision`` is the only authoritative outcome; ``failed_laws`` / ``approval_sources`` are diagnostic.
    """

    state_hash: str
    trace_id: str
    shared_state_hash: str
    invariant_c: InvariantCResult
    uato: UatoResult
    invariant_e_decision: InvariantEResult
    grl: GateEvaluation
    final_decision: AtomicFinalDecision
    failed_laws: tuple[str, ...]
    approval_sources: tuple[str, ...]
    law_records: tuple[LawEvaluationRecord, ...]
    evaluator_input_hashes: tuple[tuple[str, str], ...]
    uato_approval_kind: Optional[Literal["STANDARD", "ESCALATION"]] = None

    @property
    def approval_required_governance(self) -> bool:
        return "GRL_PROD_DEPLOY" in self.approval_sources
