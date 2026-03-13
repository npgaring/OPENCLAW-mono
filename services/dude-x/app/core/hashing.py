"""Canonical SHA-256 hashing for specs and plans."""
import hashlib
import json
import math
from typing import Any


def _normalize_numbers(data: Any) -> Any:
    """Recursively convert float to int when value is integer and finite."""
    if isinstance(data, dict):
        return {k: _normalize_numbers(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize_numbers(x) for x in data]
    if isinstance(data, float) and math.isfinite(data) and data == int(data):
        return int(data)
    return data


def canonical_json(data: Any) -> str:
    """Stable JSON: sort_keys, no spaces, ensure_ascii."""
    return json.dumps(
        _normalize_numbers(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def hash_payload(data: Any) -> str:
    """SHA-256 hex of canonical JSON (utf-8)."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
