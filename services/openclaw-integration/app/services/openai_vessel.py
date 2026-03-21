"""Bounded OpenAI vessel for strict candidate plan generation."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models.openai_flow import OpenAIPlanOutput, OpenAIPlanRequest

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
logger = logging.getLogger(__name__)

STEP_ENUM = ["create_file", "write_config", "build", "deploy", "test", "rollback_prep"]
RISK_ENUM = ["low", "medium", "high"]

DEPENDS_ON_FIELD: dict[str, Any] = {
    "depends_on": {
        "type": "array",
        "items": {"type": "string"},
    }
}

CREATE_FILE_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "path": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
    },
    "required": ["depends_on", "path", "content"],
}

WRITE_CONFIG_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "path": {"type": "string", "minLength": 1},
        "content": {"type": ["string", "null"]},
    },
    "required": ["depends_on", "path", "content"],
}

BUILD_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "command": {"type": ["string", "null"]},
    },
    "required": ["depends_on", "command"],
}

DEPLOY_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "provider": {"type": "string", "minLength": 1},
        "project": {"type": "string", "minLength": 1},
    },
    "required": ["depends_on", "provider", "project"],
}

TEST_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "command": {"type": ["string", "null"]},
    },
    "required": ["depends_on", "command"],
}

ROLLBACK_PREP_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **DEPENDS_ON_FIELD,
        "artifact": {"type": ["string", "null"]},
        "strategy": {"type": ["string", "null"]},
    },
    "required": ["depends_on", "artifact", "strategy"],
}


def _step_schema(step_type: str, inputs_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "type": {"type": "string", "enum": [step_type]},
            "action": {"type": "string", "enum": [step_type]},
            "target": {"type": "string", "minLength": 1},
            "inputs": inputs_schema,
        },
        "required": ["id", "type", "action", "target", "inputs"],
    }


OPENAI_LOCKED_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_plan": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "anyOf": [
                            _step_schema("create_file", CREATE_FILE_INPUTS_SCHEMA),
                            _step_schema("write_config", WRITE_CONFIG_INPUTS_SCHEMA),
                            _step_schema("build", BUILD_INPUTS_SCHEMA),
                            _step_schema("deploy", DEPLOY_INPUTS_SCHEMA),
                            _step_schema("test", TEST_INPUTS_SCHEMA),
                            _step_schema("rollback_prep", ROLLBACK_PREP_INPUTS_SCHEMA),
                        ]
                    },
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requiresApproval": {"type": "boolean"},
                        "riskLevel": {"type": "string", "enum": RISK_ENUM},
                    },
                    "required": ["requiresApproval", "riskLevel"],
                },
            },
            "required": ["steps", "metadata"],
        }
    },
    "required": ["candidate_plan"],
}


class OpenAIVesselError(Exception):
    def __init__(self, *, reason_codes: list[str], raw_response: dict[str, Any] | None = None):
        super().__init__(",".join(reason_codes))
        self.reason_codes = reason_codes
        self.raw_response = raw_response or {}


class OpenAIVesselConfigError(OpenAIVesselError):
    pass


class OpenAIVesselUpstreamError(OpenAIVesselError):
    pass


class OpenAIVesselSchemaError(OpenAIVesselError):
    pass


def build_openai_payload(body: OpenAIPlanRequest) -> dict[str, Any]:
    objective = body.objective.strip()
    prompt_context = {
        "ocgg_identity": body.ocgg_identity,
        "intent": body.intent,
        "deployment_target": body.deployment_target,
        "objective": objective,
        "context": body.context,
        "constraints": body.constraints or {},
        "approval_reference": body.approval_reference,
        "approver_id": body.approver_id,
        "enum_types": STEP_ENUM,
        "enum_actions": STEP_ENUM,
        "bounded_inputs": {
            "create_file": ["path", "content", "depends_on"],
            "write_config": ["path", "content", "depends_on"],
            "build": ["command", "depends_on"],
            "deploy": ["provider", "project", "depends_on"],
            "test": ["command", "depends_on"],
            "rollback_prep": ["artifact", "strategy", "depends_on"],
        },
    }
    return {
        "model": settings.openai_plan_model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return strict JSON only with the required schema. "
                    "No prose, no explanations, no optional fields, no reasoning text. "
                    "action must exactly match type. "
                    "Only use bounded inputs allowed for each step type."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_context, separators=(",", ":"), ensure_ascii=True)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "candidate_plan_output",
                "strict": True,
                "schema": OPENAI_LOCKED_JSON_SCHEMA,
            },
        },
    }


class OpenAIVesselClient:
    async def generate_candidate_plan(self, body: OpenAIPlanRequest) -> tuple[OpenAIPlanOutput, dict[str, Any]]:
        if not settings.openai_api_key:
            raise OpenAIVesselConfigError(reason_codes=["OPENAI_CONFIG_MISSING_API_KEY"])
        payload = build_openai_payload(body)
        raw: dict[str, Any] = {}
        attempts = max(1, settings.openai_plan_max_retries)
        for attempt in range(attempts):
            try:
                timeout = httpx.Timeout(timeout=float(settings.openai_plan_timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        OPENAI_API_URL,
                        headers={
                            "Authorization": f"Bearer {settings.openai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                raw = resp.json() if resp.content else {}
                resp.raise_for_status()
                parsed = _parse_openai_response(raw)
                return parsed, raw
            except OpenAIVesselSchemaError:
                raise
            except httpx.HTTPStatusError as e:
                raw = _safe_json_response(e.response)
                logger.error(
                    "OpenAI vessel upstream HTTP error status=%s body=%s",
                    e.response.status_code if e.response is not None else "unknown",
                    raw,
                )
                if attempt + 1 >= attempts:
                    raise OpenAIVesselUpstreamError(
                        reason_codes=["OPENAI_UPSTREAM_HTTP_ERROR"],
                        raw_response=raw,
                    ) from e
            except httpx.HTTPError as e:
                logger.error("OpenAI vessel upstream transport error: %s", str(e))
                if attempt + 1 >= attempts:
                    raise OpenAIVesselUpstreamError(
                        reason_codes=["OPENAI_UPSTREAM_UNAVAILABLE"],
                        raw_response=raw,
                    ) from e
        raise OpenAIVesselUpstreamError(reason_codes=["OPENAI_UPSTREAM_UNAVAILABLE"], raw_response=raw)


def _parse_openai_response(raw: dict[str, Any]) -> OpenAIPlanOutput:
    content = _extract_content(raw)
    if content is None:
        raise OpenAIVesselSchemaError(
            reason_codes=["OPENAI_OUTPUT_MISSING_CONTENT"],
            raw_response=raw,
        )
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as e:
        raise OpenAIVesselSchemaError(
            reason_codes=["OPENAI_OUTPUT_NOT_JSON"],
            raw_response=raw,
        ) from e
    try:
        return OpenAIPlanOutput.model_validate(decoded)
    except Exception as e:
        raise OpenAIVesselSchemaError(
            reason_codes=["OPENAI_OUTPUT_SCHEMA_VIOLATION"],
            raw_response={"raw": raw, "decoded": decoded},
        ) from e


def _extract_content(raw: dict[str, Any]) -> str | None:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    texts.append(item["text"])
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    texts.append(item["content"])
        return "".join(texts) if texts else None
    return None


def _safe_json_response(response: httpx.Response | None) -> dict[str, Any]:
    if response is None:
        return {}
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
        return {"raw": data}
    except Exception:
        txt = response.text if response is not None else ""
        return {"raw_text": txt[:2000] if isinstance(txt, str) else ""}
