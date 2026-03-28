"""API/presentation-only shaping. Domain truth lives in ``AtomicEvaluationResult`` and ``CompositeFrameResult``."""
from __future__ import annotations

from app.evaluation.models import AtomicEvaluationResult, AtomicFinalDecision


def presentation_frame_status_value(atomic: AtomicEvaluationResult) -> str:
    """
    Legacy HTTP ``frame_status`` string: UATO escalation is still exposed as ESCALATED for clients,
    while internal ``CompositeFrameResult.frame_status`` stays APPROVAL_REQUIRED (single domain truth).
    """
    if atomic.final_decision == AtomicFinalDecision.REQUIRE_APPROVAL and atomic.uato_approval_kind == "ESCALATION":
        return "ESCALATED"
    _DOMAIN_TO_API = {
        AtomicFinalDecision.EXECUTE: "PASS",
        AtomicFinalDecision.REQUIRE_APPROVAL: "APPROVAL_REQUIRED",
        AtomicFinalDecision.STOP: "BLOCKED",
    }
    return _DOMAIN_TO_API[atomic.final_decision]
