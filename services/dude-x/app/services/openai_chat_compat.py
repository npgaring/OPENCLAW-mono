"""Compatibility + observability helpers for OpenAI Chat Completions payloads."""
from __future__ import annotations

from typing import Any

import httpx

_MAX_ERROR_SNIPPET = 800


def is_gpt5_family_model(model: str | None) -> bool:
    """Return True when model belongs to the GPT-5 family."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


def sanitize_chat_completions_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop parameters that can be rejected by GPT-5 chat-completions variants."""
    out = dict(payload)
    model = str(out.get("model") or "")
    if is_gpt5_family_model(model):
        out.pop("temperature", None)
    return out


def summarize_chat_completions_response(response: httpx.Response | None) -> dict[str, Any]:
    """Safe, compact summary for upstream error logging."""
    if response is None:
        return {}

    out: dict[str, Any] = {"status_code": response.status_code}
    try:
        data = response.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                for key in ("type", "code", "param", "message"):
                    val = err.get(key)
                    if val is not None and val != "":
                        out[key] = str(val)[:_MAX_ERROR_SNIPPET]
            elif data:
                out["body"] = str(data)[:_MAX_ERROR_SNIPPET]
        elif data is not None:
            out["body"] = str(data)[:_MAX_ERROR_SNIPPET]
    except Exception:
        text = response.text
        if isinstance(text, str) and text:
            out["raw_text"] = text[:_MAX_ERROR_SNIPPET]
    return out


def summarize_chat_completions_exception(exc: Exception) -> dict[str, Any]:
    """Safe summary for logging unexpected chat-completions failures."""
    if isinstance(exc, httpx.HTTPStatusError):
        return summarize_chat_completions_response(exc.response)
    if isinstance(exc, httpx.HTTPError):
        return {"transport_error": str(exc)[:_MAX_ERROR_SNIPPET]}
    return {"error": str(exc)[:_MAX_ERROR_SNIPPET]}
