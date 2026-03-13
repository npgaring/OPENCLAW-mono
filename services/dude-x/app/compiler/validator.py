"""Spec validation: P-Stack + intent domain."""
from app.compiler.pstack import run_pstack
from app.core.errors import DUDEXError, ErrorCode
from app.models import SpecIn

INTENT_DOMAIN = {
    "web-build": "web",
    "web-maintenance": "web",
    "recruiting-update": "recruiting",
}


def validate_spec(spec: SpecIn) -> None:
    """Run P-Stack and ensure intent is in INTENT_DOMAIN. Raises on failure."""
    run_pstack(spec)
    if spec.intent not in INTENT_DOMAIN:
        raise DUDEXError(
            ErrorCode.UNSUPPORTED_OPERATION,
            f"Intent {spec.intent!r} not supported",
            details={"intent": spec.intent},
        )
