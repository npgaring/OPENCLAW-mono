"""Legacy/alternate client: POST to OpenClaw Gateway /v1/responses (OpenResponses API) with Bearer only."""
import json
from typing import Any

import httpx

from app.core.config import settings


def _to_openresponses_body(payload: dict[str, Any]) -> dict[str, Any]:
    """If payload already looks like OpenResponses (model, input), use it; else wrap as plan execution."""
    if payload.get("model") and ("input" in payload or "instructions" in payload):
        return payload
    return {
        "model": payload.get("model", "openclaw:main"),
        "user": payload.get("user", "project:default"),
        "instructions": payload.get("instructions", "Return valid JSON only."),
        "input": payload.get("input") if "input" in payload else json.dumps(payload, indent=2),
    }


async def submit_execute(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to OPENCLAW_BASE_URL/v1/responses (Gateway OpenResponses API) with Bearer only."""
    base = settings.openclaw_base_url.rstrip("/")
    body = _to_openresponses_body(payload)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base}/v1/responses",
            json=body,
            headers={
                "Authorization": f"Bearer {settings.openclaw_api_key}",
                "Content-Type": "application/json",
            },
        )
    resp.raise_for_status()
    return resp.json()
