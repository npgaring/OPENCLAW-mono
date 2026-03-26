"""Contract checks for explicit frame -> governance -> task continuity."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.main import app


def _valid_spec():
    ops = [{"type": "build", "op_id": "1", "target": "repo", "inputs": {}, "outputs": {}}]
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    ph = hash_payload({"domain": domain, "operations": ops})
    return {"ocgg_identity": "W-OCGG", "plan_hash": ph, "operations": ops}


def test_gate_evaluate_emits_governance_evaluation_id(auth_headers):
    client = TestClient(app)
    r = client.post("/gate/evaluate", json=_valid_spec(), headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("uato_skipped_gate") is False
    assert data.get("governance_evaluation_id")
    ef = data.get("evaluation_frame") or {}
    assert ef.get("frame_status") == "PASS"
    assert ef.get("governance_reached") is True


def test_task_accepts_matching_governance_evaluation_id(auth_headers):
    client = TestClient(app)
    trace_id = "550e8400-e29b-41d4-a716-446655449901"
    spec = {**_valid_spec(), "trace_id": trace_id}
    g = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert g.status_code == 200, g.text
    gid = g.json().get("governance_evaluation_id")
    assert gid

    with patch("app.services.task_submission.OpenClawClient") as mock_client_class:
        mock_client_class.return_value.execute = AsyncMock(
            return_value={"execution_id": "ex-link", "status": "completed", "message": "ok"}
        )
        t = client.post("/task", json={**spec, "governance_evaluation_id": gid}, headers=auth_headers)
    assert t.status_code == 200, t.text
    td = t.json()
    assert td.get("gate_outcome") == "PASS"
    assert td.get("governance_outcome") == "PASS"
    assert td.get("governance_evaluation_id") == gid
    assert td.get("governance_continuity_verified") is True


def test_task_rejects_mismatched_governance_evaluation_id(auth_headers):
    client = TestClient(app)
    trace_id = "550e8400-e29b-41d4-a716-446655449902"
    spec = {**_valid_spec(), "trace_id": trace_id}

    t = client.post("/task", json={**spec, "governance_evaluation_id": "bad-ref"}, headers=auth_headers)
    assert t.status_code == 422, t.text
    detail = t.json().get("detail") or {}
    assert detail.get("code") == "GOVERNANCE_CONTINUITY_MISMATCH"


def test_validation_control_pass_c_fail_uato_is_deterministic(auth_headers):
    client = TestClient(app)
    spec = _valid_spec()
    body = {
        **spec,
        "validation": {"uato_scenario": "PASS_C_FAIL_UATO_BLOCK"},
    }
    frame = client.post("/evaluation-frame/evaluate", json=body, headers=auth_headers)
    assert frame.status_code == 200, frame.text
    fd = frame.json()
    assert (fd.get("invariant_c_result") or {}).get("decision") == "PASS"
    assert (fd.get("uato_result") or {}).get("decision") == "BLOCK"
    assert fd.get("frame_status") == "BLOCKED"
    assert fd.get("governance_reached") is False

    gate = client.post("/gate/evaluate", json=body, headers=auth_headers)
    assert gate.status_code == 200, gate.text
    gd = gate.json()
    assert gd.get("uato_decision") == "BLOCK"
    assert gd.get("uato_skipped_gate") is True
    gef = gd.get("evaluation_frame") or {}
    assert gef.get("governance_reached") is False


def test_validation_control_pass_governance_fail_dispatch_boundary(auth_headers):
    client = TestClient(app)
    trace_id = "550e8400-e29b-41d4-a716-446655449903"
    spec = {
        **_valid_spec(),
        "trace_id": trace_id,
        "validation": {"dispatch_boundary_scenario": "PASS_GOV_FAIL_INVARIANT_E_CAPABILITY"},
    }

    def _assert_invariant_e_denied_aligned(payload: dict):
        assert payload.get("frame_status") == "BLOCKED"
        ie = payload.get("invariant_e_result") or {}
        assert ie.get("decision") == "EXECUTION_DENIED"
        assert "IE_DENIED_CAPABILITY_NOT_ALLOWED" in (ie.get("reason_codes") or [])

    preview = client.post("/evaluation-frame/evaluate", json=spec, headers=auth_headers)
    assert preview.status_code == 200, preview.text
    _assert_invariant_e_denied_aligned(preview.json())

    gate = client.post("/gate/evaluate", json=spec, headers=auth_headers)
    assert gate.status_code == 200, gate.text
    gd = gate.json()
    # Frame blocks before GateEngine; governance is not evaluated for this request.
    assert gd.get("outcome") == "BLOCK"
    assert gd.get("uato_skipped_gate") is True
    assert gd.get("governance_evaluation_id") is None
    _assert_invariant_e_denied_aligned(gd.get("evaluation_frame") or {})

    with patch("app.services.task_submission.OpenClawClient") as mock_client_class:
        mock_client_class.return_value.execute = AsyncMock(
            return_value={"execution_id": "should-not-run", "status": "completed"}
        )
        task = client.post("/task", json=spec, headers=auth_headers)
    assert task.status_code == 200, task.text
    td = task.json()
    assert td.get("gate_outcome") == "BLOCK"
    assert td.get("invariant_e_decision") == "EXECUTION_DENIED"
    assert "IE_DENIED_CAPABILITY_NOT_ALLOWED" in (td.get("invariant_e_reason_codes") or [])
    assert td.get("dispatch_blocked") is True
    assert td.get("status") == "invariant_e_denied"
    _assert_invariant_e_denied_aligned(td.get("evaluation_frame") or {})
