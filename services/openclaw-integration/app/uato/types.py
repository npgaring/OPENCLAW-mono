"""
UATO types: trust/authority admissibility only.

Plan shape: integration gate spec (POST /task, POST /gate/evaluate) — see TaskSubmitRequest / GateEvaluateRequest.
The canonical runtime contract is the integration spec dict consumed by ``GateEngine.evaluate`` (``plan_hash``,
``operations``, optional ``goal`` / ``context`` / ``deployment_target`` / approvals, etc.).

OpenAI adapter: use ``governance_plan_hash`` (or deprecated ``integration_plan_hash``) as ``plan_hash`` for POST /task.
Do not use ``substrate_envelope_hash`` / deprecated ``plan_hash`` from ``AdapterToSubstrateResponse`` as the gate hash.
The gate verifies ``hash_payload({ domain, operations })`` only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

UatoDecision = Literal["PASS", "ESCALATE", "REQUIRE_APPROVAL", "BLOCK"]
TrustLevel = Literal["LOW", "HIGH"]
AuthorityLevel = Literal["LOW", "HIGH"]

TrustSource = Literal["OPENAI_VESSEL", "INTERNAL", "HUMAN_SUBMITTED", "UNKNOWN"]
RequestSource = Literal["OPENAI_VESSEL", "API", "SYSTEM"]

UATO_DECISION_VERSION = "uato-v1"


@dataclass(frozen=True)
class TrustState:
    level: TrustLevel
    source: TrustSource
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AuthorityState:
    level: AuthorityLevel
    tenant_match: bool
    identity_bound: bool
    approval_capable: bool
    requested_scope: tuple[str, ...]
    granted_scope: tuple[str, ...]


@dataclass(frozen=True)
class UatoContext:
    environment: Literal["dev", "staging", "prod"]
    tenant_id: str
    request_source: RequestSource
    trace_id: str


@dataclass(frozen=True)
class UatoInput:
    """plan: integration-side spec dict (ocgg_identity, plan_hash, operations, optional goal/context/...)."""

    plan: dict[str, Any]
    trust_state: TrustState
    authority_state: AuthorityState
    context: UatoContext


@dataclass(frozen=True)
class UatoResult:
    decision: UatoDecision
    reason_codes: tuple[str, ...]
    decision_version: Literal["uato-v1"]
    requires_human_approval: bool
    trace_id: str


class UatoTraceRecord(TypedDict, total=False):
    """Persisted audit/trace payload (JSON-serializable)."""

    decision: str
    reason_codes: list[str]
    decision_version: str
    trust_level: str
    authority_level: str
    trust_source: str
    uato_input_hash: str
    trace_id: str
