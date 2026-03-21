"""OpenAI vessel unit tests: payload policy + strict schema rejection."""
import json

import pytest

from app.models.openai_flow import OpenAIPlanRequest
from app.services.openai_vessel import (
    OpenAIVesselClient,
    OpenAIVesselSchemaError,
    build_openai_payload,
)


def _request() -> OpenAIPlanRequest:
    return OpenAIPlanRequest(
        ocgg_identity="W-OCGG",
        intent="web-build",
        deployment_target="preview",
        objective="Build a release candidate",
    )


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
