"""Legacy/alternate client: submit_execute with Bearer only (no token)."""
from typing import Any

import httpx

from app.core.config import settings


async def submit_execute(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to OPENCLAW_BASE_URL/execute with Bearer only."""
    base = settings.openclaw_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{base}/execute",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.openclaw_api_key}",
                "Content-Type": "application/json",
            },
        )
    resp.raise_for_status()
    return resp.json()
