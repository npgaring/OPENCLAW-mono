"""
Invariant-E: execution admission at the integration dispatch boundary (post-governance, pre-OpenClaw).

Phase 1: evaluate_invariant_e returns EXECUTION_ALLOWED or EXECUTION_DENIED only.
EXECUTION_TERMINATED is reserved for downstream/runtime-reported termination when a real signal path exists.
TODO: Wire EXECUTION_TERMINATED from OpenClaw execution responses if/when the gateway exposes a stable termination type.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.invariant_e.reason_codes import IE_ALLOWED

ExecutionDecision = Literal[
    "EXECUTION_ALLOWED",
    "EXECUTION_DENIED",
    "EXECUTION_TERMINATED",
]

INVARIANT_E_DECISION_VERSION = "invariant-e-v1"


@dataclass(frozen=True)
class ExecutionEnvelope:
    """Normalized execution-admission view; built from integration spec + governance PASS artifacts."""

    trace_id: str
    task_id: str | None
    tenant_id: str | None
    identity: str | None
    plan_hash: str | None
    spec_hash: str | None
    governance_outcome: str
    approval_reference: str | None
    approver_id: str | None
    deployment_target: str | None
    operations: tuple[dict[str, Any], ...]
    requested_capabilities: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    budget_limit: dict[str, Any] | None
    network_scope: dict[str, Any] | None
    filesystem_scope: dict[str, Any] | None
    runtime_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class InvariantEResult:
    decision: ExecutionDecision
    reason_codes: tuple[str, ...]
    decision_version: str
    trace_id: str
    dispatch_blocked: bool


def result_allowed(trace_id: str) -> InvariantEResult:
    return InvariantEResult(
        decision="EXECUTION_ALLOWED",
        reason_codes=(IE_ALLOWED,),
        decision_version=INVARIANT_E_DECISION_VERSION,
        trace_id=trace_id,
        dispatch_blocked=False,
    )


def result_denied(trace_id: str, codes: tuple[str, ...]) -> InvariantEResult:
    return InvariantEResult(
        decision="EXECUTION_DENIED",
        reason_codes=codes,
        decision_version=INVARIANT_E_DECISION_VERSION,
        trace_id=trace_id,
        dispatch_blocked=True,
    )
