"""UATO audit/trace helpers (deterministic hashes, JSON-safe records)."""
from __future__ import annotations

from typing import Any

from app.uato.normalize import canonical_plan_fingerprint, stable_hash_uato_material
from app.uato.types import UatoInput, UatoResult, UatoTraceRecord


def uato_input_hash(inp: UatoInput) -> str:
    material = {
        "plan": canonical_plan_fingerprint(inp.plan),
        "trust": {
            "level": inp.trust_state.level,
            "source": inp.trust_state.source,
            "evidence": list(inp.trust_state.evidence),
        },
        "authority": {
            "level": inp.authority_state.level,
            "tenant_match": inp.authority_state.tenant_match,
            "identity_bound": inp.authority_state.identity_bound,
            "approval_capable": inp.authority_state.approval_capable,
            "requested_scope": list(inp.authority_state.requested_scope),
            "granted_scope": list(inp.authority_state.granted_scope),
        },
        "context": {
            "environment": inp.context.environment,
            "tenant_id": inp.context.tenant_id,
            "request_source": inp.context.request_source,
            "trace_id": inp.context.trace_id,
        },
    }
    return stable_hash_uato_material(material)


def to_trace_record(inp: UatoInput, result: UatoResult) -> UatoTraceRecord:
    return {
        "decision": result.decision,
        "reason_codes": list(result.reason_codes),
        "decision_version": result.decision_version,
        "trust_level": inp.trust_state.level,
        "authority_level": inp.authority_state.level,
        "trust_source": inp.trust_state.source,
        "uato_input_hash": uato_input_hash(inp),
        "trace_id": result.trace_id,
    }


def redacted_trace_json(inp: UatoInput) -> dict[str, Any]:
    """Optional expanded JSON for storage (keep plan as fingerprint only)."""
    return {
        "plan_fingerprint": canonical_plan_fingerprint(inp.plan),
        "trust": {
            "level": inp.trust_state.level,
            "source": inp.trust_state.source,
            "evidence": list(inp.trust_state.evidence),
        },
        "authority": {
            "level": inp.authority_state.level,
            "tenant_match": inp.authority_state.tenant_match,
            "identity_bound": inp.authority_state.identity_bound,
            "approval_capable": inp.authority_state.approval_capable,
            "requested_scope": list(inp.authority_state.requested_scope),
            "granted_scope": list(inp.authority_state.granted_scope),
        },
        "context": {
            "environment": inp.context.environment,
            "tenant_id": inp.context.tenant_id,
            "request_source": inp.context.request_source,
            "trace_id": inp.context.trace_id,
        },
    }
