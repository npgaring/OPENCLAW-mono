"""Ensure spec/decisions/constraints contain only deterministic types."""
import json
import math
from typing import Any

from app.core.errors import DUDEXError, ErrorCode

ALLOWED_TYPES = (str, int, float, bool, type(None))


def _walk(value: Any, path: str) -> None:
    """Recurse and raise on non-deterministic structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise DUDEXError(
                    ErrorCode.NON_DETERMINISTIC_INPUT,
                    "Non-string dict key",
                    details={"path": path, "key_type": type(k).__name__},
                )
            _walk(v, f"{path}.{k}" if path else k)
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _walk(item, f"{path}[{i}]")
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return
            if isinstance(parsed, (dict, list)):
                raise DUDEXError(
                    ErrorCode.NON_DETERMINISTIC_STRUCTURE,
                    "Nested JSON string",
                    details={"path": path},
                )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DUDEXError(
                ErrorCode.NON_DETERMINISTIC_INPUT,
                "Non-finite float",
                details={"path": path},
            )
        return
    if type(value) not in ALLOWED_TYPES:
        raise DUDEXError(
            ErrorCode.NON_DETERMINISTIC_INPUT,
            "Unsupported type",
            details={"path": path, "type": type(value).__name__},
        )


def ensure_deterministic(payload: Any, root: str = "spec") -> None:
    """Raise DUDEXError if payload contains non-deterministic values."""
    _walk(payload, root)
