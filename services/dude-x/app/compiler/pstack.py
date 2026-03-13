"""P-Stack validation layers."""
from app.compiler.determinism import ensure_deterministic
from app.core.errors import DUDEXError, ErrorCode
from app.models import PlanPayload, SpecIn
from pydantic import BaseModel, ConfigDict

IDENTITY_ALLOWED_INTENTS = {
    "W-OCGG": ["web-build", "web-maintenance"],
    "R-OCGG": ["recruiting-update"],
}
MAX_OPERATIONS = 50


class PStackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: list[str]
    success: bool


def _p1_schema(spec: SpecIn) -> None:
    if spec.signature.type not in ("human", "human_signed"):
        raise DUDEXError(ErrorCode.INVALID_SPEC, "signature.type must be human or human_signed", details={})
    if not spec.signature.hash:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "signature.hash required", details={})
    if not spec.decisions.operations:
        raise DUDEXError(ErrorCode.MISSING_DECISION, "decisions.operations must be non-empty", details={})
    ensure_deterministic(spec.model_dump(mode="python"), "spec")
    ensure_deterministic(spec.decisions.model_dump(mode="python"), "decisions")
    ensure_deterministic(spec.constraints, "constraints")


def _p2_identity(spec: SpecIn) -> None:
    allowed = IDENTITY_ALLOWED_INTENTS.get(spec.identity)
    if not allowed:
        raise DUDEXError(
            ErrorCode.IDENTITY_INTENT_MISMATCH,
            f"Identity {spec.identity!r} not in allowed set",
            details={"identity": spec.identity},
        )
    if spec.intent not in allowed:
        raise DUDEXError(
            ErrorCode.IDENTITY_INTENT_MISMATCH,
            f"Intent {spec.intent!r} not allowed for identity {spec.identity!r}",
            details={"identity": spec.identity, "intent": spec.intent},
        )


def _p3_operation_scope(spec: SpecIn) -> None:
    derived = "web" if spec.identity == "W-OCGG" else "recruiting"
    if spec.decisions.domain is not None and spec.decisions.domain != derived:
        raise DUDEXError(
            ErrorCode.DOMAIN_MISMATCH,
            "decisions.domain does not match derived domain",
            details={"decisions.domain": spec.decisions.domain, "derived": derived},
        )


def _p4_resource_envelope(spec: SpecIn) -> None:
    ops = spec.decisions.operations
    if len(ops) > MAX_OPERATIONS:
        raise DUDEXError(
            ErrorCode.INVALID_SPEC,
            f"Too many operations (max {MAX_OPERATIONS})",
            details={"count": len(ops)},
        )
    if "rollback" in spec.constraints and not spec.constraints.get("rollback"):
        raise DUDEXError(
            ErrorCode.ROLLBACK_REQUIRED_BUT_MISSING,
            "rollback key present but value empty",
            details={},
        )


def _p5_determinism_lock(spec: SpecIn) -> None:
    ensure_deterministic(spec.model_dump(mode="python"), "spec")
    ensure_deterministic(spec.decisions.model_dump(mode="python"), "decisions")
    ensure_deterministic(spec.constraints, "constraints")


def _p6_constraint_consistency(spec: SpecIn) -> None:
    if not spec.constraints.get("no_network"):
        return
    for op in spec.decisions.operations:
        if op.type == "deploy" and op.target and (
            str(op.target).startswith("http://") or str(op.target).startswith("https://")
        ):
            raise DUDEXError(
                ErrorCode.SPEC_CONTRADICTION,
                "no_network forbids deploy to http(s) URL",
                details={"op_id": op.op_id, "target": op.target},
            )


def run_pstack(spec: SpecIn) -> PStackResult:
    """Run all P-Stack layers in order. First failure raises DUDEXError."""
    layers = [
        "P1_SCHEMA",
        "P2_IDENTITY",
        "P3_OPERATION_SCOPE",
        "P4_RESOURCE_ENVELOPE",
        "P5_DETERMINISM_LOCK",
        "P6_CONSTRAINT_CONSISTENCY",
    ]
    for name in layers:
        if name == "P1_SCHEMA":
            _p1_schema(spec)
        elif name == "P2_IDENTITY":
            _p2_identity(spec)
        elif name == "P3_OPERATION_SCOPE":
            _p3_operation_scope(spec)
        elif name == "P4_RESOURCE_ENVELOPE":
            _p4_resource_envelope(spec)
        elif name == "P5_DETERMINISM_LOCK":
            _p5_determinism_lock(spec)
        elif name == "P6_CONSTRAINT_CONSISTENCY":
            _p6_constraint_consistency(spec)
    return PStackResult(layers=layers, success=True)
