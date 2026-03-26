"""Build UatoInput from integration spec + hints (deterministic; no external calls)."""
from __future__ import annotations

from typing import Any, Optional

from app.core.config import settings
from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.trace_id import normalize_trace_id
from app.uato.normalize import (
    derive_identity_bound,
    derive_requested_scope,
    normalize_authority_state,
    normalize_trust_state,
    normalize_uato_context,
)
from app.uato.types import AuthorityLevel, TrustLevel, TrustSource, UatoContext, UatoInput


def _map_app_env_to_uato_env() -> str:
    v = (settings.app_env or "development").lower()
    if v in ("production", "prod"):
        return "prod"
    if v in ("preview", "staging"):
        return "staging"
    return "dev"


def build_uato_input_from_spec(
    spec: dict[str, Any],
    *,
    ocgg_identity: str,
    trace_id: Optional[str],
    uato_hints: Optional[Any] = None,
    validation_controls: Optional[Any] = None,
) -> UatoInput:
    """
    Integration spec: same dict passed to GateEngine.evaluate (post trace_id pop optional).

    uato_hints: optional pydantic model or dict with:
      trust_level, authority_level, trust_source, request_source, tenant_id (optional overrides).
    Defaults: trust HIGH, authority HIGH (preserves pre-UATO behavior when hints omitted).
    """
    tid_raw = getattr(uato_hints, "tenant_id", None) if uato_hints is not None else None
    if tid_raw is None and isinstance(uato_hints, dict):
        tid_raw = uato_hints.get("tenant_id")
    tenant_id = (tid_raw or ocgg_identity or "").strip()

    scenario = _get_hint_str(validation_controls, "uato_scenario")
    if scenario == "PASS_C_FAIL_UATO_BLOCK":
        tl = "LOW"
        al = "LOW"
    else:
        tl = _get_hint_str(uato_hints, "trust_level") or settings.uato_default_trust_level
        al = _get_hint_str(uato_hints, "authority_level") or settings.uato_default_authority_level
    trust_level: TrustLevel = "HIGH" if str(tl).upper() == "HIGH" else "LOW"
    authority_level: AuthorityLevel = "HIGH" if str(al).upper() == "HIGH" else "LOW"

    ts = _get_hint_str(uato_hints, "trust_source") or "UNKNOWN"
    trust_source: TrustSource
    u = str(ts).upper()
    if u == "OPENAI_VESSEL":
        trust_source = "OPENAI_VESSEL"
    elif u == "INTERNAL":
        trust_source = "INTERNAL"
    elif u == "HUMAN_SUBMITTED":
        trust_source = "HUMAN_SUBMITTED"
    else:
        trust_source = "UNKNOWN"

    rs = _get_hint_str(uato_hints, "request_source") or "API"
    evidence_raw = getattr(uato_hints, "evidence", None) if uato_hints is not None else None
    if evidence_raw is None and isinstance(uato_hints, dict):
        evidence_raw = uato_hints.get("evidence")
    evidence_list: list[str] = []
    if isinstance(evidence_raw, (list, tuple)):
        evidence_list = [str(x) for x in evidence_raw if x is not None]

    norm_trace = normalize_trace_id(trace_id)
    ctx = normalize_uato_context(
        environment=_map_app_env_to_uato_env(),
        tenant_id=tenant_id,
        request_source=rs,
        trace_id=norm_trace,
    )
    if ctx is None:
        # Fail-closed: invalid env/tenant/trace — tenant_id "" yields tenant_match False in evaluator.
        ctx = UatoContext(
            environment="dev",
            tenant_id="",
            request_source="API",
            trace_id=norm_trace,
        )

    identity_bound = derive_identity_bound(ocgg_identity)
    tenant_match = tenant_id == ocgg_identity

    ops = spec.get("operations")
    req_scope = derive_requested_scope(ops)
    appr = bool(spec.get("approver_id") or spec.get("approval_reference"))
    # Without a separate grants registry, granted scope mirrors requested (admissibility only).
    granted = list(req_scope)

    trust_state = normalize_trust_state(level=trust_level, source=trust_source, evidence=evidence_list)
    authority_state = normalize_authority_state(
        level=authority_level,
        tenant_match=tenant_match,
        identity_bound=identity_bound,
        approval_capable=appr,
        requested_scope=req_scope,
        granted_scope=granted,
    )

    return UatoInput(plan=spec, trust_state=trust_state, authority_state=authority_state, context=ctx)


def _get_hint_str(hints: Any, key: str) -> Optional[str]:
    if hints is None:
        return None
    v = getattr(hints, key, None)
    if v is None and isinstance(hints, dict):
        v = hints.get(key)
    if v is None:
        return None
    return str(v)
