"""API tests for governed DUDE-X v2 dual-engine flow."""
from fastapi.testclient import TestClient

from app.main import app


def _auth():
    return {"Authorization": "Bearer test-token"}


def test_v2_raw_intent_can_require_clarification():
    with TestClient(app) as client:
        resp = client.post(
            "/v2/raw-intents",
            json={
                "idea": "Need a website quickly",
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cognitive_outcome"] == "CLARIFY"
    assert "target_audience" in body["build_sot"]["unresolved_items"]


def test_v2_compile_requires_approval_and_is_deterministic():
    with TestClient(app) as client:
        create_resp = client.post(
            "/v2/raw-intents",
            json={
                "idea": "Create a business site with contact and pricing pages for local clinics.",
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "brief": {
                    "project_name": "Clinic Nova",
                    "site_purpose": "Acquire qualified leads for clinic consultations.",
                    "target_audience": ["local patients"],
                    "desired_tone": "professional",
                    "page_list": ["home", "pricing", "contact"],
                },
            },
            headers=_auth(),
        )
        assert create_resp.status_code == 200, create_resp.text
        env = create_resp.json()
        build_sot_hash = env["stage_linkage"]["build_sot_hash"]
        assert env["cognitive_outcome"] == "PASS"
        gov_resp = client.post(
            f"/v2/build-sot/{build_sot_hash}/governance/evaluate",
            json={"ocgg_identity": "W-OCGG", "intent": "web-build"},
            headers=_auth(),
        )
        compile_blocked = client.post(f"/v2/build-sot/{build_sot_hash}/compile", headers=_auth())
        approve_resp = client.post(
            f"/v2/build-sot/{build_sot_hash}/approval/decide",
            json={"decision": "APPROVE", "approver_id": "ops-01"},
            headers=_auth(),
        )
        compile_a = client.post(f"/v2/build-sot/{build_sot_hash}/compile", headers=_auth())
        compile_b = client.post(f"/v2/build-sot/{build_sot_hash}/compile", headers=_auth())
    assert gov_resp.status_code == 200, gov_resp.text
    assert gov_resp.json()["outcome"] == "PASS"
    assert compile_blocked.status_code == 400
    assert compile_blocked.json()["code"] == "INVALID_SPEC"
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["build_sot"]["status"] == "locked"
    assert compile_a.status_code == 200, compile_a.text
    assert compile_b.status_code == 200, compile_b.text
    pa = compile_a.json()
    pb = compile_b.json()
    assert pa["execution_mode"] == "deterministic_web_v1"
    assert pa["stage_linkage"]["execution_plan_hash"] == pb["stage_linkage"]["execution_plan_hash"]
    assert pa["governance_projection"]["plan_hash"] == pb["governance_projection"]["plan_hash"]


def test_v2_compile_includes_github_vercel_provisioning_defaults():
    with TestClient(app) as client:
        create_resp = client.post(
            "/v2/raw-intents",
            json={
                "idea": "Create a lead generation site for solar installers.",
                "ocgg_identity": "W-OCGG",
                "intent": "web-build",
                "brief": {
                    "project_name": "Solar Pulse",
                    "site_purpose": "Generate booked consultations.",
                    "target_audience": ["homeowners"],
                    "desired_tone": "professional",
                    "page_list": ["home", "contact"],
                },
            },
            headers=_auth(),
        )
        assert create_resp.status_code == 200, create_resp.text
        build_sot_hash = create_resp.json()["stage_linkage"]["build_sot_hash"]
        gov_resp = client.post(
            f"/v2/build-sot/{build_sot_hash}/governance/evaluate",
            json={"ocgg_identity": "W-OCGG", "intent": "web-build"},
            headers=_auth(),
        )
        assert gov_resp.status_code == 200, gov_resp.text
        approve_resp = client.post(
            f"/v2/build-sot/{build_sot_hash}/approval/decide",
            json={"decision": "APPROVE", "approver_id": "ops-02"},
            headers=_auth(),
        )
        assert approve_resp.status_code == 200, approve_resp.text
        compile_resp = client.post(f"/v2/build-sot/{build_sot_hash}/compile", headers=_auth())

    assert compile_resp.status_code == 200, compile_resp.text
    plan = compile_resp.json()
    repo_provision = next(x for x in plan["operations"] if x["type"] == "provision_repo")
    hosting_provision = next(x for x in plan["operations"] if x["type"] == "provision_hosting")
    deploy_op = next(x for x in plan["operations"] if x["type"] == "deploy")
    assert repo_provision["inputs"]["provider"] == "github"
    assert repo_provision["inputs"]["repo_name"].startswith("cdmbr-solar-pulse-")
    assert "{timestamp}" not in repo_provision["inputs"]["repo_name"]
    assert repo_provision["inputs"]["default_branch"] == "prod"
    assert hosting_provision["inputs"]["provider"] == "vercel"
    assert "{timestamp}" not in hosting_provision["inputs"]["project_name"]
    assert hosting_provision["inputs"]["production_branch"] == "prod"
    assert deploy_op["inputs"]["provider"] == "vercel"
    assert "{timestamp}" not in deploy_op["inputs"]["project"]
    assert deploy_op["inputs"]["branch"] == "prod"
