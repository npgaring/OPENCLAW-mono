"""OpenClaw executor client: POST /execute with Bearer + X-Execution-Token."""
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ERROR_TYPE_MAP = {
    400: "invalid_plan",
    401: "auth_error",
    403: "domain_rejected",
}
DEFAULT_TIMEOUT = 10.0


class OpenClawError(Exception):
    def __init__(self, error_type: str, message: str, status_code: int | None = None, response: dict | None = None):
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.response = response or {}
        super().__init__(message)


class OpenClawClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or settings.openclaw_base_url).rstrip("/")
        self.api_key = api_key or settings.openclaw_api_key
        self.timeout = timeout

    async def execute(self, plan: dict[str, Any], execution_token: str | None) -> dict[str, Any]:
        if not execution_token:
            raise OpenClawError("auth_error", "Execution token required")
        url = f"{self.base_url}/execute"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Execution-Token": execution_token,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=plan, headers=headers)
        except httpx.TimeoutException as e:
            raise OpenClawError("error", f"Timeout: {e}") from e
        except Exception as e:
            raise OpenClawError("error", str(e)) from e

        if resp.status_code >= 400:
            error_type = ERROR_TYPE_MAP.get(resp.status_code, "execution_failure")
            try:
                body = resp.json()
            except Exception:
                body = {}
            raise OpenClawError(
                error_type,
                body.get("message", body.get("detail", resp.text)) or f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                response=body,
            )
        return resp.json()
