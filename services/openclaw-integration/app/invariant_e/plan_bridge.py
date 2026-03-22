"""Helpers to align Invariant-E with integration plan/spec hashing (same inputs as gate)."""
from __future__ import annotations

from typing import Any

from app.core.security import hash_payload
from app.invariant_e.normalize import envelope_fingerprint_for_hash
from app.invariant_e.types import ExecutionEnvelope


def execution_envelope_hash(envelope: ExecutionEnvelope) -> str:
    """Deterministic hash of the admission envelope for audit/replay."""
    return hash_payload(envelope_fingerprint_for_hash(envelope))
