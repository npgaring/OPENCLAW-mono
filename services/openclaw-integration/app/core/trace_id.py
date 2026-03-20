"""Correlation ID for compile → gate → task (governance demo / audit)."""
from __future__ import annotations

import uuid
from typing import Optional


def normalize_trace_id(client_value: Optional[str]) -> str:
    """Use client UUID if valid; otherwise generate a new UUID4 string."""
    if client_value is not None and isinstance(client_value, str):
        s = client_value.strip()
        if s:
            try:
                uuid.UUID(s)
                return s
            except ValueError:
                pass
    return str(uuid.uuid4())
