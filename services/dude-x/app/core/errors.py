"""Structured error codes and response model."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorCode(str, Enum):
    INVALID_SPEC = "INVALID_SPEC"
    SPEC_CONTRADICTION = "SPEC_CONTRADICTION"
    MISSING_DECISION = "MISSING_DECISION"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    NON_DETERMINISTIC_INPUT = "NON_DETERMINISTIC_INPUT"
    NON_DETERMINISTIC_STRUCTURE = "NON_DETERMINISTIC_STRUCTURE"
    ROLLBACK_REQUIRED_BUT_MISSING = "ROLLBACK_REQUIRED_BUT_MISSING"
    IDENTITY_INTENT_MISMATCH = "IDENTITY_INTENT_MISMATCH"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    ADDON_NOT_IN_REGISTRY = "ADDON_NOT_IN_REGISTRY"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class DUDEXError(Exception):
    """Raised for compile/gate/plans validation failures; mapped to 400 + ErrorResponse."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)
