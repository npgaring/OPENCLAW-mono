"""OpenClaw Gateway client: POST /v1/responses (OpenResponses API) with Bearer auth."""
import json
import logging
import re
from typing import Any, List, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict

from app.core.config import settings

logger = logging.getLogger(__name__)

ERROR_TYPE_MAP = {
    400: "invalid_plan",
    401: "auth_error",
    403: "domain_rejected",
}
DEFAULT_TIMEOUT = 60.0  # LLM execution can take longer than 10s


class OpenClawError(Exception):
    def __init__(self, error_type: str, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.response = response or {}
        super().__init__(message)


class ArtifactItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str = ""
    type: str = ""
    summary: str = ""


class AgentResponseSchema(BaseModel):
    """Expected agent JSON response (our contract via instructions)."""
    model_config = ConfigDict(extra="allow")
    status: Literal["success", "failed", "partial", "needs_review"]
    message: str = ""
    artifacts: Optional[List[ArtifactItem]] = None
    steps_completed: Optional[List[str]] = None
    session_summary: Optional[str] = None


def _extract_json_from_text(text: str) -> Optional[dict]:
    """Try to parse a JSON object from text (strip markdown code fences, find {...})."""
    if not text or not text.strip():
        return None
    s = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    s = s.strip()
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


BASE_RESPONSE_FORMAT_INSTRUCTION = (
    "You must respond with valid JSON only, in this exact shape: "
    '{"status": "success"|"failed"|"partial"|"needs_review", "message": "...", '
    '"artifacts": [{"path": "...", "type": "...", "summary": "..."}], '
    '"steps_completed": ["..."], "session_summary": "..."}. '
    "Only status and message are required; artifacts, steps_completed, and session_summary are optional. "
    "When you finish, if the user might send a follow-up, set session_summary to a short summary of what was done and current state."
)

DOMAIN_INSTRUCTIONS: dict[str, str] = {
    "web": (
        "You are implementing front-end deliverables for the web. "
        "Prefer semantic HTML, accessibility, and clear structure. "
        "Output artifacts (path, type, summary) when you create or modify files. "
        "The executor workspace may be empty or lack Node/npm: do not run npm, yarn, pnpm, or npx "
        "unless package.json (and any lockfile) already exists or you create them in this session first. "
        "If a plan step asks for a command that cannot run, set status to partial or needs_review and explain why."
    ),
    "recruiting": (
        "You are generating or editing job descriptions and screening criteria. "
        "Be consistent with company tone and compliance. "
        "Do not include discriminatory or non-compliant content."
    ),
}


def _plan_to_openresponses_body(plan: dict, task_id: Optional[str] = None) -> dict:
    """Build OpenResponses request body from plan { domain, plan_hash, operations }.

    Mapping from /task flow:
    - plan comes from gate engine (may include goal, context, acceptance_criteria).
    - user: project:{domain} or project:{domain}:{task_id} for session continuity.
    - instructions: response format + optional domain snippet (added by caller).
    - input: full plan as JSON string.
    """
    domain = plan.get("domain") or "default"
    user = f"project:{domain}:{task_id}" if task_id else f"project:{domain}"
    instructions = BASE_RESPONSE_FORMAT_INSTRUCTION + "\n\n" + (DOMAIN_INSTRUCTIONS.get(domain) or "")
    if plan.get("executor_contract") == "deterministic_web_v1" or isinstance(plan.get("execution_plan_v2"), dict):
        instructions += (
            "\n\nDeterministic executor contract is active. "
            "Execute only the structured execution_plan_v2 commands and file targets exactly as provided. "
            "Do not invent additional steps, tools, dependencies, or scope."
        )
    return {
        "model": "openclaw:main",
        "user": user,
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
    return " ".join(parts)


def _parse_gateway_response(resp_body: dict[str, Any]) -> dict[str, Any]:
    """Map OpenResponses response to integration shape. Validate structured JSON when possible."""
    execution_id = resp_body.get("id") or resp_body.get("response_id") or ""
    output = resp_body.get("output") or []
    text = _extract_text_from_output(output)
    result: dict[str, Any] = {
        "execution_id": execution_id,
        "status": "success",
        "output": output,
        "usage": resp_body.get("usage"),
        "id": resp_body.get("id"),
    }
    parsed = _extract_json_from_text(text) if text else None
    if parsed:
        try:
            validated = AgentResponseSchema.model_validate(parsed)
            result["status"] = validated.status
            result["message"] = validated.message
            if validated.artifacts is not None:
                result["artifacts"] = [a.model_dump() for a in validated.artifacts]
            if validated.steps_completed is not None:
                result["steps_completed"] = validated.steps_completed
            if validated.session_summary is not None:
                result["session_summary"] = validated.session_summary
            return result
        except Exception:
            pass
    result["response_parse_failed"] = True
    text_l = text.lower() if text else ""
    status = "success"
    if text_l and (
        "failed" in text_l
        or '"status": "failed"' in text_l
        or "'status': 'failed'" in text_l
        or '"status":"failed"' in text_l
    ):
        status = "failed"
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("status") == "incomplete":
                status = "failed"
                break
    result["status"] = status
    return result


def _parse_gateway_error(resp_body: dict[str, Any], status_code: int, fallback_text: str) -> tuple[str, str]:
    """Extract error type and message from Gateway/OpenResponses error shape.
    Handles: { error: { message, type } } and { detail: { message } } (e.g. from FastAPI).
    F4: resource_limit or execution_aborted from gateway -> execution_aborted.
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
    if err:
        gateway_type = (err.get("type") or "").strip().lower()
        if gateway_type in ("execution_aborted", "resource_limit", "resource_limit_exceeded"):
            error_type = "execution_aborted"
    return error_type, str(message)


class OpenClawClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or settings.openclaw_base_url).rstrip("/")
        self.api_key = api_key or settings.openclaw_api_key
        self.timeout = timeout

    async def execute(
        self,
        plan: dict[str, Any],
        execution_token: Optional[str],
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not execution_token:
            raise OpenClawError("auth_error", "Execution token required")
        url = f"{self.base_url}/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = _plan_to_openresponses_body(plan, task_id=str(task_id) if task_id else None)
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

    async def execute_follow_up(
        self,
        task_id: str,
        domain: str,
        message: str,
        prior_context: str = "",
    ) -> dict[str, Any]:
        """Send a follow-up message to the Gateway for the same task (same user/session). No execution token."""
        url = f"{self.base_url}/v1/responses"
        user = f"project:{domain}:{task_id}"
        instructions = BASE_RESPONSE_FORMAT_INSTRUCTION + "\n\n" + (DOMAIN_INSTRUCTIONS.get(domain) or "")
        instructions += "\n\nThe user has sent a follow-up. Use the prior context above and respond with the same JSON format (status, message, artifacts, steps_completed, session_summary)."
        input_text = f"Prior context for this task:\n{prior_context}\n\nUser's new message: {message}" if prior_context else message
        body = {
            "model": "openclaw:main",
            "user": user,
            "instructions": instructions,
            "input": input_text,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
