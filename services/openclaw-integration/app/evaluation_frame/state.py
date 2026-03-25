"""Canonical shared governable state and composite frame result models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from app.invariant_c.evaluator import InvariantCResult
from app.invariant_e.types import InvariantEResult
from app.models.openai_flow import CandidatePlan
from app.uato.types import UatoResult


class FrameStatus(str, Enum):
    """Composite admissibility outcome for the C + UATO + E evaluation frame (pre-governance)."""

    PASS = "PASS"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ESCALATED = "ESCALATED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ApprovalFrameContext:
    """Human approval applied before this evaluation (e.g. POST /approvals/{id}/resume)."""

    approval_reference: Optional[str]
    approver_id: Optional[str]


@dataclass(frozen=True)
class SharedGovernableState:
    """
    Immutable snapshot shared by Invariant-C, UATO, and Invariant-E in one evaluation frame.

    Evaluators must treat this object as read-only input: no law mutates state for another law.
    """

    trace_id: str
    ocgg_identity: str
    domain: str
    intent: str
    objective: Optional[str]
    context: Optional[str]
    constraints: Optional[dict[str, Any]]
    spec_for_gate: dict[str, Any]
    plan_json: dict[str, Any]
    # Canonical governance plan fingerprint hash_payload({domain, operations}); not the client-asserted plan_hash key.
    plan_hash: str
    spec_hash: str
    candidate_plan: CandidatePlan
    uato_hints: Any
    approval_context: Optional[ApprovalFrameContext]
    shared_state_hash: str


@dataclass(frozen=True)
class CompositeFrameResult:
    """
    Single composed admissibility decision for the frame.

    Original per-law outputs are preserved; composite fields encode progression policy.
    """

    frame_status: FrameStatus
    # True only when frame_status is PASS; GateEngine may run only if admissible.
    admissible: bool
    approval_required: bool
    approvable_via_uato: bool
    invariant_c_result: InvariantCResult
    uato_result: UatoResult
    invariant_e_result: InvariantEResult
    reason_codes: tuple[str, ...]
    trace_id: str
    shared_state_hash: str
