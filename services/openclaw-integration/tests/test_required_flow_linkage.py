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
