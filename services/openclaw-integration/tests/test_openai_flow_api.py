"""Integration tests for OpenAI Vessel + evaluation frame + substrate adapter routes."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_payload
from app.db.session import get_sessionmaker
from app.main import app
from app.models import (
    GateEvaluateRequest,
    InvariantCDecisionRecord,
    OpenAIPlanOutput,
    OpenAIVesselEvent,
    SubstrateAdapterEvent,
    TaskSubmitRequest,
)


@pytest.fixture
def client():
    return TestClient(app)


def _candidate_plan(requires_approval: bool = False, risk_level: str = "low"):
    return {
        "steps": [
            {
                "id": "s1",
                "type": "write_config",
                "action": "write_config",
                "target": "web/app",
                "inputs": {"path": "app/config.json", "content": "{}"},
            },
            {
                "id": "s2",
                "type": "build",
                "action": "build",
                "target": "web/app",
                "inputs": {"depends_on": ["s1"]},
            },
        ],
        "metadata": {"requiresApproval": requires_approval, "riskLevel": risk_level},
    }


def _fetch_rows(model):
    async def _go():
        factory = get_sessionmaker()
        async with factory() as session:
            result = await session.execute(select(model))
            return result.scalars().all()

    return asyncio.run(_go())


def test_openai_plan_success_and_event_persisted(client, auth_headers):
    mocked = OpenAIPlanOutput.model_validate({"candidate_plan": _candidate_plan()})
    with patch("app.api.openai_flow.OpenAIVesselClient.generate_candidate_plan", new=AsyncMock(return_value=(mocked, {"mock": True}))):
        resp = client.post(
            "/openai/plan",
            json={
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "deployment_target": "preview",
                "objective": "Generate a deployment plan",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body.keys()) == ["candidate_plan"]
    assert body["candidate_plan"]["steps"][0]["action"] == body["candidate_plan"]["steps"][0]["type"]
    assert resp.headers.get("X-Trace-Id")
    rows = _fetch_rows(OpenAIVesselEvent)
    assert any(r.outcome == "PASS" and r.schema_valid is True for r in rows)


def test_openai_plan_malformed_returns_valid_openai_plan_and_persists_failure_test_event(client, auth_headers):
    resp = client.post(
        "/openai/plan-malformed",
        json={
            "ocgg_identity": "W-OCGG",
            "intent": "web-build",
            "deployment_target": "preview",
            "objective": "Generate a deployment plan",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body.keys()) == ["candidate_plan"]
    assert resp.headers.get("X-Trace-Id")
    assert resp.headers.get("X-Candidate-Plan-Hash")

    parsed = OpenAIPlanOutput.model_validate(body)
    assert parsed.candidate_plan.steps[0].inputs.depends_on == ["s2"]

    rows = _fetch_rows(OpenAIVesselEvent)
    assert any(
        r.outcome == "PASS"
        and r.schema_valid is True
        and "OPENAI_ADAPTER_FAILURE_TEST_PLAN" in (r.reason_codes or [])
        for r in rows
    )


def test_openai_plan_malformed_output_fails_adapter_substrate_chain(client, auth_headers):
    plan_resp = client.post(
        "/openai/plan-malformed",
        json={
            "ocgg_identity": "W-OCGG",
            "intent": "web-build",
            "deployment_target": "preview",
            "objective": "Generate a deployment plan",
        },
        headers=auth_headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text
    candidate_plan = plan_resp.json()["candidate_plan"]

    adapter_resp = client.post(
        "/adapter/to-substrate",
        json={
            "ocgg_identity": "W-OCGG",
            "intent": "web-build",
            "deployment_target": "preview",
            "objective": "Generate a deployment plan",
            "candidate_plan": candidate_plan,
        },
        headers=auth_headers,
    )
    assert adapter_resp.status_code == 422, adapter_resp.text
    detail = adapter_resp.json()["detail"]
    if isinstance(detail, list):
        detail = detail[0] if detail else {}
    assert detail.get("code") == "EVALUATION_FRAME_BLOCK"
    assert detail.get("frame_status") == "BLOCKED"
    assert detail.get("ocgg_identity") == "W-OCGG"
    assert detail.get("deployment_target") == "preview"
    assert isinstance(detail.get("operations"), list) and len(detail["operations"]) >= 1
    expected_hash = hash_payload({"domain": detail["domain"], "operations": detail["operations"]})
    assert detail.get("governance_plan_hash") == expected_hash
    assert detail.get("integration_plan_hash") == expected_hash


def test_openai_plan_upstream_error_includes_upstream_summary(client, auth_headers):
    from app.services.openai_vessel import OpenAIVesselUpstreamError

    raw = {"error": {"message": "upstream failed", "type": "server_error"}}
    with patch(
        "app.api.openai_flow.OpenAIVesselClient.generate_candidate_plan",
        new=AsyncMock(
            side_effect=OpenAIVesselUpstreamError(reason_codes=["OPENAI_UPSTREAM_HTTP_ERROR"], raw_response=raw)
        ),
    ):
        resp = client.post(
            "/openai/plan",
            json={
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "deployment_target": "preview",
                "objective": "Generate a deployment plan",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "OPENAI_UPSTREAM_ERROR"
    assert detail["upstream"]["message"] == "upstream failed"
    assert detail["upstream"]["type"] == "server_error"


def test_openai_plan_schema_violation_is_blocked_and_persisted(client, auth_headers):
    from app.services.openai_vessel import OpenAIVesselSchemaError

    with patch(
        "app.api.openai_flow.OpenAIVesselClient.generate_candidate_plan",
        new=AsyncMock(side_effect=OpenAIVesselSchemaError(reason_codes=["OPENAI_OUTPUT_SCHEMA_VIOLATION"], raw_response={"raw": "bad"})),
    ):
        resp = client.post(
            "/openai/plan",
            json={
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "deployment_target": "preview",
                "objective": "Generate a deployment plan",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert data["detail"]["code"] == "OPENAI_SCHEMA_VIOLATION"
    rows = _fetch_rows(OpenAIVesselEvent)
    assert any(r.outcome == "BLOCK" and r.schema_valid is False for r in rows)


def test_openai_plan_to_substrate_runs_full_chain(client, auth_headers):
    mocked = OpenAIPlanOutput.model_validate({"candidate_plan": _candidate_plan()})
    with patch("app.api.openai_flow.OpenAIVesselClient.generate_candidate_plan", new=AsyncMock(return_value=(mocked, {"mock": True}))):
        resp = client.post(
            "/openai/plan-to-substrate",
            json={
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "deployment_target": "preview",
                "objective": "Build and verify a web release candidate",
                "context": "Use the current web pipeline",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["governance_plan_hash"]
    assert payload["integration_plan_hash"] == payload["governance_plan_hash"]
    assert payload["substrate_envelope_hash"]
    assert payload["plan_hash"] == payload["substrate_envelope_hash"]
    assert payload["goal"] == "Build and verify a web release candidate"
    assert payload["trace_id"]
    assert payload["operations"]
    ef = payload.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "PASS"
    assert ef.get("governance_reached") is False
    assert ef.get("dispatch_reached") is False
    assert resp.headers.get("X-Trace-Id")
    assert resp.headers.get("X-Candidate-Plan-Hash")
    inv_rows = _fetch_rows(InvariantCDecisionRecord)
    adapter_rows = _fetch_rows(SubstrateAdapterEvent)
    assert any(r.decision == "PASS" for r in inv_rows)
    assert any(r.outcome == "PASS" for r in adapter_rows)


def test_adapter_to_substrate_success_hash_matches_governance_canonical(client, auth_headers):
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "preview",
        "objective": "Build and verify a web release candidate",
        "candidate_plan": _candidate_plan(),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    expected = hash_payload({"domain": data["domain"], "operations": data["operations"]})
    assert data["governance_plan_hash"] == expected
    assert data["integration_plan_hash"] == expected
    assert data["substrate_envelope_hash"] != expected
    assert data["plan_hash"] == data["substrate_envelope_hash"]
    assert data["goal"] == "Build and verify a web release candidate"
    inv_rows = _fetch_rows(InvariantCDecisionRecord)
    adapter_rows = _fetch_rows(SubstrateAdapterEvent)
    assert any(r.decision == "PASS" for r in inv_rows)
    assert any(r.outcome == "PASS" and r.integration_plan_hash == expected for r in adapter_rows)


def test_adapter_response_includes_system_derived_uato_hints(client, auth_headers):
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "preview",
        "objective": "Build and verify a web release candidate",
        "candidate_plan": _candidate_plan(requires_approval=False, risk_level="medium"),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data.get("uato") or {}).get("trust_level") == "HIGH"
    assert (data.get("uato") or {}).get("authority_level") == "LOW"


def test_adapter_blocks_when_requires_approval_without_reference(client, auth_headers):
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "production",
        "objective": "Deploy the website to production",
        "candidate_plan": _candidate_plan(requires_approval=True),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert data["detail"]["code"] == "METADATA_APPROVAL_REQUIRED"
    adapter_rows = _fetch_rows(SubstrateAdapterEvent)
    assert any(r.outcome == "BLOCK" and "ADAPTER_METADATA_REQUIRES_APPROVAL" in (r.reason_codes or []) for r in adapter_rows)


def test_adapter_blocks_on_evaluation_frame_when_invariant_c_fails(client, auth_headers):
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "preview",
        "objective": "Prepare the website build",
        "candidate_plan": {
            "steps": [
                {
                    "id": "s1",
                    "type": "write_config",
                    "action": "write_config",
                    "target": "web/app",
                    "inputs": {"path": "app/x.json", "content": "{}", "depends_on": ["s2"]},
                },
                {
                    "id": "s2",
                    "type": "build",
                    "action": "build",
                    "target": "web/app",
                    "inputs": {},
                },
            ],
            "metadata": {"requiresApproval": False, "riskLevel": "low"},
        },
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    data = resp.json()
    detail = data["detail"]
    if isinstance(detail, list):
        detail = detail[0] if detail else {}
    assert detail.get("code") == "EVALUATION_FRAME_BLOCK"
    assert detail.get("frame_status") == "BLOCKED"
    assert detail.get("ocgg_identity") == "W-OCGG"
    assert isinstance(detail.get("operations"), list) and len(detail["operations"]) >= 1
    expected_hash = hash_payload({"domain": detail["domain"], "operations": detail["operations"]})
    assert detail.get("governance_plan_hash") == expected_hash
    assert detail.get("integration_plan_hash") == expected_hash
    inv_rows = _fetch_rows(InvariantCDecisionRecord)
    assert any(r.decision == "BLOCK" for r in inv_rows)


def test_adapter_prod_deploy_no_approval_block_includes_substrate_for_gate(client, auth_headers):
    """422 APPROVAL_REQUIRED still returns full substrate so clients can POST /gate/evaluate."""
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "production",
        "objective": "Deploy to production",
        "candidate_plan": _candidate_plan(requires_approval=False),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    if isinstance(detail, list):
        detail = detail[0] if detail else {}
    assert detail["code"] == "EVALUATION_FRAME_BLOCK"
    assert detail["frame_status"] == "APPROVAL_REQUIRED"
    assert "PROD_DEPLOY_NO_APPROVAL" in detail["reason_codes"]
    assert detail["ocgg_identity"] == "W-OCGG"
    assert detail["deployment_target"] == "production"
    assert isinstance(detail["operations"], list) and len(detail["operations"]) >= 1
    expected = hash_payload({"domain": detail["domain"], "operations": detail["operations"]})
    assert detail["governance_plan_hash"] == expected
    assert detail["integration_plan_hash"] == expected
    GateEvaluateRequest.model_validate(
        {
            "ocgg_identity": detail["ocgg_identity"],
            "plan_hash": detail["governance_plan_hash"],
            "operations": detail["operations"],
            "deployment_target": detail.get("deployment_target"),
            "goal": detail.get("goal"),
            "context": detail.get("context"),
            "uato": detail.get("uato"),
            "trace_id": detail.get("trace_id"),
        }
    )


def test_adapter_response_is_directly_compatible_with_task_and_gate_models(client, auth_headers):
    body = {
        "ocgg_identity": "W-OCGG",
        "intent": "web-build",
        "deployment_target": "preview",
        "objective": "Build and verify a web release candidate",
        "candidate_plan": _candidate_plan(),
    }
    resp = client.post("/adapter/to-substrate", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    task_req = TaskSubmitRequest.model_validate(
        {
            "ocgg_identity": payload["ocgg_identity"],
            "plan_hash": payload["governance_plan_hash"],
            "operations": payload["operations"],
            "deployment_target": payload.get("deployment_target"),
            "goal": payload.get("goal"),
            "context": payload.get("context"),
            "uato": payload.get("uato"),
            "trace_id": payload.get("trace_id"),
        }
    )
    gate_req = GateEvaluateRequest.model_validate(
        {
            "ocgg_identity": payload["ocgg_identity"],
            "plan_hash": payload["governance_plan_hash"],
            "operations": payload["operations"],
            "uato": payload.get("uato"),
            "trace_id": payload.get("trace_id"),
        }
    )
    assert task_req.plan_hash == payload["governance_plan_hash"]
    assert gate_req.plan_hash == payload["governance_plan_hash"]


def test_adapter_can_hydrate_objective_from_vessel_trace(client, auth_headers):
    mocked = OpenAIPlanOutput.model_validate({"candidate_plan": _candidate_plan()})
    with patch("app.api.openai_flow.OpenAIVesselClient.generate_candidate_plan", new=AsyncMock(return_value=(mocked, {"mock": True}))):
        openai_resp = client.post(
            "/openai/plan",
            json={
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "deployment_target": "preview",
                "objective": "Build and verify a web release candidate",
                "context": "Use the same release target as the current web pipeline",
            },
            headers=auth_headers,
        )
    trace_id = openai_resp.headers["X-Trace-Id"]
    adapter_resp = client.post(
        "/adapter/to-substrate",
        json={
            "ocgg_identity": "W-OCGG",
            "intent": "web-build",
            "trace_id": trace_id,
            "candidate_plan": _candidate_plan(),
        },
        headers=auth_headers,
    )
    assert adapter_resp.status_code == 200, adapter_resp.text
    payload = adapter_resp.json()
    assert payload["goal"] == "Build and verify a web release candidate"
    assert payload["context"] == "Use the same release target as the current web pipeline"
