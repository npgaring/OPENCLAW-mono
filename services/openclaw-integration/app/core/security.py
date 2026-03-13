"""Canonical JSON and SHA-256 hashing."""
import hashlib
import json
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(x) for x in value]
    return value


def hash_payload(value: Any) -> str:
    """SHA-256 hex of canonical JSON (sort_keys, no spaces)."""
    canonical = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
