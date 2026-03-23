"""OpenAI vessel unit tests: payload policy + strict schema rejection."""
import json

import httpx
import pytest

from app.models.openai_flow import OpenAIPlanRequest
from app.services.openai_vessel import (
    OpenAIVesselClient,
    OpenAIVesselSchemaError,
    OpenAIVesselUpstreamError,
    build_openai_payload,
    summarize_openai_upstream_error,
)


def _request() -> OpenAIPlanRequest:
    return OpenAIPlanRequest(
        ocgg_identity="W-OCGG",
        intent="web-build",
        deployment_target="preview",
        objective="Build a release candidate",
    )


def test_summarize_openai_upstream_error():
    raw = {
        "error": {
            "message": "The server had an error",
            "type": "server_error",
            "code": "internal_error",
        }
    }
    s = summarize_openai_upstream_error(raw)
    assert s["message"] == "The server had an error"
    assert s["type"] == "server_error"
    assert s["code"] == "internal_error"


def test_build_openai_payload_temperature_and_strict_json_schema():
    payload = build_openai_payload(_request())
    assert payload["temperature"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    step_variants = payload["response_format"]["json_schema"]["schema"]["properties"]["candidate_plan"]["properties"]["steps"]["items"]["anyOf"]
    write_config_variant = next(x for x in step_variants if x["properties"]["type"]["enum"] == ["write_config"])
    assert write_config_variant["properties"]["inputs"]["additionalProperties"] is False
    assert "path" in write_config_variant["properties"]["inputs"]["properties"]


@pytest.mark.asyncio
async def test_generate_candidate_plan_rejects_schema_violation(monkeypatch):
    class _Response:
        status_code = 200
        content = b"ok"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidate_plan": {
                                        "steps": [
                                            {
                                                "id": "s1",
                                                "type": "build",
                                                "action": "build",
                                                "target": "web/app",
                                                "inputs": {},
                                                "notes": "this field is forbidden",
                                            }
                                        ],
                                        "metadata": {"requiresApproval": False, "riskLevel": "low"},
                                    }
                                }
                            )
                        }
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr("app.services.openai_vessel.httpx.AsyncClient", _Client)

    with pytest.raises(OpenAIVesselSchemaError) as err:
        await OpenAIVesselClient().generate_candidate_plan(_request())
    assert "OPENAI_OUTPUT_SCHEMA_VIOLATION" in err.value.reason_codes


@pytest.mark.asyncio
async def test_generate_candidate_plan_retries_then_succeeds(monkeypatch):
    ok_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "candidate_plan": {
                                "steps": [
                                    {
                                        "id": "s1",
                                        "type": "write_config",
                                        "action": "write_config",
                                        "target": "web/app",
                                        "inputs": {"path": "x.txt", "content": "{}", "depends_on": []},
                                    }
                                ],
                                "metadata": {"requiresApproval": False, "riskLevel": "low"},
                            }
                        }
                    )
                }
            }
        ]
    }
    attempt = {"n": 0}

    class _BadThenOkResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        @property
        def content(self):
            return b"{}"

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
                raise httpx.HTTPStatusError("err", request=req, response=self)

    class _BadThenOkResponseOk:
        def __init__(self):
            self.status_code = 200

        @property
        def content(self):
            return b"ok"

        def json(self):
            return ok_body

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            attempt["n"] += 1
            if attempt["n"] == 1:
                return _BadThenOkResponse(502, {"error": {"message": "bad gateway"}})
            return _BadThenOkResponseOk()

    monkeypatch.setattr("app.services.openai_vessel.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_plan_max_retries", 3)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_plan_retry_backoff_seconds", 0.01)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_api_key", "sk-test")

    out, raw = await OpenAIVesselClient().generate_candidate_plan(_request())
    assert attempt["n"] == 2
    assert out.candidate_plan.steps[0].id == "s1"
    assert "choices" in raw


@pytest.mark.asyncio
async def test_generate_candidate_plan_non_retryable_401_no_extra_calls(monkeypatch):
    class _Resp401:
        status_code = 401

        @property
        def content(self):
            return b"{}"

        def json(self):
            return {"error": {"message": "invalid"}}

        def raise_for_status(self):
            req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            raise httpx.HTTPStatusError("err", request=req, response=self)

    posts = {"n": 0}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            posts["n"] += 1
            return _Resp401()

    monkeypatch.setattr("app.services.openai_vessel.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_plan_max_retries", 3)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_plan_retry_backoff_seconds", 0.01)
    monkeypatch.setattr("app.services.openai_vessel.settings.openai_api_key", "sk-test")

    with pytest.raises(OpenAIVesselUpstreamError):
        await OpenAIVesselClient().generate_candidate_plan(_request())
    assert posts["n"] == 1
