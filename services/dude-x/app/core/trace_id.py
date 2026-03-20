"""Correlation ID for compile → gate → task (same contract as openclaw-integration)."""
from __future__ import annotations

import uuid
from typing import Optional


def normalize_trace_id(client_value: Optional[str]) -> str:
    if client_value is not None and isinstance(client_value, str):
        s = client_value.strip()
        if s:
            try:
                uuid.UUID(s)
                return s
            except ValueError:
                pass
    return str(uuid.uuid4())
