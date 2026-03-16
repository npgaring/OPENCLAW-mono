"""OpenClaw Gateway client: POST /v1/responses (OpenResponses API) with Bearer auth."""
import json
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
DEFAULT_TIMEOUT = 60.0  # LLM execution can take longer than 10s


class OpenClawError(Exception):
    def __init__(self, error_type: str, message: str, status_code: int | None = None, response: dict | None = None):
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.response = response or {}
        super().__init__(message)


def _plan_to_openresponses_body(plan: dict[str, Any]) -> dict[str, Any]:
    """Build OpenResponses request body from plan { domain, plan_hash, operations }.

    Mapping from /task flow:
    - plan comes from gate engine: { domain, plan_hash, operations } (canonical plan only).
    - model: OpenClaw agent id.
    - user: session routing (project:{domain}).
    - instructions: system directive + response format (JSON status/message).
    - input: full plan as JSON string (OpenResponses accepts string or array of items).
    """
    domain = plan.get("domain") or "default"
    instructions = (
        "Execute the plan in the user message. "
        "Return valid JSON only with keys: status (success or failed), message (optional)."
    )
    return {
        "model": "openclaw:main",
        "user": f"project:{domain}",
        "instructions": instructions,
        "input": json.dumps(plan, indent=2),
    }


def _extract_text_from_output(output: list[Any]) -> str:
    """Extract concatenated text from OpenResponses output items. Content can be string or array of parts."""
    parts: list[str] = []
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
    return " ".join(parts).lower()


def _parse_gateway_response(resp_body: dict[str, Any]) -> dict[str, Any]:
    """Map OpenResponses response to integration shape: execution_id, status, execution_response."""
    execution_id = resp_body.get("id") or resp_body.get("response_id") or ""
    output = resp_body.get("output") or []
    status = "success"
    text = _extract_text_from_output(output)
    if text and (
        "failed" in text
        or '"status": "failed"' in text
        or "'status': 'failed'" in text
        or '"status":"failed"' in text
    ):
        status = "failed"
    # OpenResponses items can have status: completed | incomplete | in_progress
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("status") == "incomplete":
                status = "failed"
                break
    return {
        "execution_id": execution_id,
        "status": status,
        "output": output,
        "usage": resp_body.get("usage"),
        "id": resp_body.get("id"),
    }


def _parse_gateway_error(resp_body: dict[str, Any], status_code: int, fallback_text: str) -> tuple[str, str]:
    """Extract error type and message from Gateway/OpenResponses error shape.
    Handles: { error: { message, type } } and { detail: { message } } (e.g. from FastAPI).
    """
    err = resp_body.get("error") if isinstance(resp_body.get("error"), dict) else None
    detail = resp_body.get("detail")
    message = (
        (err.get("message") if err else None)
        or resp_body.get("message")
        or (detail.get("message") if isinstance(detail, dict) else None)
        or (detail if isinstance(detail, str) else None)
        or fallback_text
    )
    if isinstance(message, dict):
        message = message.get("message", str(message))
    error_type = ERROR_TYPE_MAP.get(status_code, "execution_failure")
    return error_type, str(message)


class OpenClawClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or settings.openclaw_base_url).rstrip("/")
        self.api_key = api_key or settings.openclaw_api_key
        self.timeout = timeout

    async def execute(self, plan: dict[str, Any], execution_token: str | None) -> dict[str, Any]:
        if not execution_token:
            raise OpenClawError("auth_error", "Execution token required")
        url = f"{self.base_url}/v1/responses"
        # OpenClaw Gateway requires Bearer OPENCLAW_API_KEY (not INTEGRATION_API_KEY).
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = _plan_to_openresponses_body(plan)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise OpenClawError("error", f"Timeout: {e}") from e
        except Exception as e:
            raise OpenClawError("error", str(e)) from e

        try:
            resp_body = resp.json()
        except Exception:
            resp_body = {}

        if resp.status_code >= 400:
            error_type, message = _parse_gateway_error(
                resp_body, resp.status_code, f"HTTP {resp.status_code}"
            )
            response = dict(resp_body)
            response.setdefault("execution_id", resp_body.get("id") or resp_body.get("response_id"))
            raise OpenClawError(error_type, message, status_code=resp.status_code, response=response)
        return _parse_gateway_response(resp_body)
