"""Invariant-E audit/trace records (JSON-safe)."""
from __future__ import annotations

from typing import Any, TypedDict

from app.invariant_e.plan_bridge import execution_envelope_hash
from app.invariant_e.types import ExecutionEnvelope, InvariantEResult


class InvariantETraceRecord(TypedDict, total=False):
    decision: str
    reason_codes: list[str]
    decision_version: str
    trace_id: str
    invariant_e_input_hash: str
    execution_envelope_hash: str
    requested_capabilities: list[str]
    allowed_capabilities: list[str]
    dispatch_blocked: bool


def to_trace_record(envelope: ExecutionEnvelope, result: InvariantEResult) -> InvariantETraceRecord:
    eh = execution_envelope_hash(envelope)
    return {
        "decision": result.decision,
        "reason_codes": list(result.reason_codes),
        "decision_version": result.decision_version,
        "trace_id": result.trace_id,
        "invariant_e_input_hash": eh,
        "execution_envelope_hash": eh,
        "requested_capabilities": list(envelope.requested_capabilities),
        "allowed_capabilities": list(envelope.allowed_capabilities),
        "dispatch_blocked": result.dispatch_blocked,
    }


def redacted_trace_json(envelope: ExecutionEnvelope) -> dict[str, Any]:
    """Expanded JSON for storage (hashes + capability lists; no full operation payloads)."""
    from app.invariant_e.normalize import envelope_fingerprint_for_hash

    return envelope_fingerprint_for_hash(envelope)
