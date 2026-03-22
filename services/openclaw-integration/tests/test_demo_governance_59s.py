"""59-Second OpenClaw Governance Demo — sample testing."""
import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.session import get_sessionmaker
from app.models import GateDecisionRecord, Task, UsedExecutionToken

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Turn a SQLModel row into a JSON-serializable dict (e.g. UUID -> str)."""
    if row is None:
        return {}
    d = dict(row.__dict__)
    d.pop("_sa_instance_state", None)
    for k, v in list(d.items()):
        if hasattr(v, "hex"):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


async def _dump_db_async() -> Dict[str, List[Dict[str, Any]]]:
    """Query all task-related tables and return dict of table_name -> list of rows (dicts)."""
    out: Dict[str, List[Dict[str, Any]]] = {"tasks": [], "gate_decisions": [], "used_execution_tokens": []}
    try:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            for task in (await session.execute(select(Task))).scalars().all():
                out["tasks"].append(_row_to_dict(task))
            for rec in (await session.execute(select(GateDecisionRecord))).scalars().all():
                out["gate_decisions"].append(_row_to_dict(rec))
            for rec in (await session.execute(select(UsedExecutionToken))).scalars().all():
                out["used_execution_tokens"].append(_row_to_dict(rec))
    except Exception as e:
        out["_error"] = str(e)
    return out


def dump_db() -> Dict[str, List[Dict[str, Any]]]:
    """Sync wrapper: run _dump_db_async and return result for printing."""
    return asyncio.run(_dump_db_async())


def _print_request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> None:
    print("User sending this request:")
    print(f"  {method} {path}")
    if body is not None:
        print("  Body:")
        print(json.dumps(body, indent=4, default=str))
    print()


def _print_response(resp: Any) -> None:
    """Print response (object with .status_code and .json())."""
    print("The system returns:")
    print(f"  Status: {resp.status_code}")
    try:
        body = resp.json()
        print("  Body:")
        print(json.dumps(body, indent=4, default=str))
    except Exception:
        print("  Body: (raw)", resp.text[:500] if getattr(resp, "text", None) else resp)
    print()


def print_scene(
    scene_title: str,
    request_method: str,
    request_path: str,
    request_body: Optional[Dict[str, Any]],
    response: Any,
    include_receipts: bool = True,
) -> None:
    """
    Print a narrative: User request → System response → Verification receipts.
    response must have .status_code and .json() (e.g. TestClient response).
    """
    print("\n" + "=" * 60)
    print(scene_title)
    print("=" * 60)
    _print_request(request_method, request_path, request_body)
    _print_response(response)
    if include_receipts:
        receipts = dump_db()
        print("Verification receipts:")
        print(json.dumps(receipts, indent=2, default=str))
    print("=" * 60 + "\n")


def print_scene_multi(
    scene_title: str,
    steps: List[tuple],
    include_receipts: bool = True,
) -> None:
    """
    Print multiple request/response steps, then one verification receipt.
    steps: list of (method, path, body_or_none, response).
    """
    print("\n" + "=" * 60)
    print(scene_title)
    print("=" * 60)
    for i, (method, path, body, resp) in enumerate(steps, 1):
        if len(steps) > 1:
            print(f"--- Step {i} ---")
        _print_request(method, path, body)
        _print_response(resp)
    if include_receipts:
        receipts = dump_db()
        print("Verification receipts:")
        print(json.dumps(receipts, indent=2, default=str))
    print("=" * 60 + "\n")


def _production_deploy_operations():
    """Minimal production deploy plan (W-OCGG). Include outputs so plan_hash matches gate (TaskOperation adds outputs: {})."""
    return [
        {"op_id": "op-001", "type": "deploy", "target": "web/app", "inputs": {"provider": "vercel", "project": "marketing-site"}, "outputs": {}},
    ]


def _spec_for_gate(ocgg_identity: str = "W-OCGG", deployment_target: str = "production", approval_reference: Optional[str] = None, approver_id: Optional[str] = None):
    """Build spec with correct plan_hash for gate (domain + operations only)."""
    domain = IDENTITY_DOMAIN_MAP[ocgg_identity]
    operations = _production_deploy_operations()
    plan_canonical = {"domain": domain, "operations": operations}
    plan_hash = hash_payload(plan_canonical)
    spec = {
        "ocgg_identity": ocgg_identity,
        "plan_hash": plan_hash,
        "operations": operations,
        "deployment_target": deployment_target,
    }
    if approval_reference is not None:
        spec["approval_reference"] = approval_reference
    if approver_id is not None:
        spec["approver_id"] = approver_id
    return spec


class TestDemoGovernance59s:
    """
    Demo flow: BLOCK first (e.g. production without approval) → correct → PASS → execution → receipt.
    """

    def test_scene1_and_2_request_submitted_system_returns_block(self, client: TestClient, auth_headers: dict):
        """
        Scene 1–2: User submits production request without approval.
        System must return BLOCK (or REFORM/CLARIFY) with clear reason.
        """
        spec = _spec_for_gate(deployment_target="production")  # no approval_reference, no approver_id
        resp = client.post("/task", json=spec, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["gate_outcome"] == "BLOCK"
        assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])
        assert data.get("execution_id") is None
        assert "execution_response" not in data or data.get("execution_response") is None

        print_scene(
            "Scene 1–2: Request submitted (production, no approval) → system returns BLOCK",
            "POST",
            "/task",
            spec,
            resp,
        )

    def test_scene3_and_4_user_adds_approval_system_returns_pass_and_authority(self, client: TestClient, auth_headers: dict):
        """
        Scene 3–4: User adds approval_reference (or approver_id). System returns PASS and execution is authorised.
        """
        spec = _spec_for_gate(deployment_target="production", approval_reference="demo-approval-ref-001")
        mock_response = {
            "execution_id": "ex-demo-1",
            "status": "completed",
            "message": "Deployed.",
            "output": [{"type": "message", "content": [{"type": "text", "text": '{"status":"success","message":"Deployed."}'}]}],
            "usage": {},
        }
        with patch("app.services.task_submission.OpenClawClient") as mock_client_class:
            mock_client_class.return_value.execute = AsyncMock(return_value=mock_response)
            resp = client.post("/task", json=spec, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["gate_outcome"] == "PASS"
        assert data.get("execution_id") or data.get("execution_response")
        assert data.get("task_id") is not None
        mock_client_class.return_value.execute.assert_called_once()

        print_scene(
            "Scene 3–4: Request with approval_reference → system returns PASS and execution",
            "POST",
            "/task",
            spec,
            resp,
        )

    def test_full_demo_flow_block_then_pass_then_receipt(self, client: TestClient, auth_headers: dict):
        """
        Full 59s demo flow: (1) production no approval → BLOCK, (2) with approval → PASS + execution, (3) receipt.
        """
        spec_block = _spec_for_gate(deployment_target="production")
        resp1 = client.post("/task", json=spec_block, headers=auth_headers)
        assert resp1.status_code == 200
        d1 = resp1.json()
        assert d1["gate_outcome"] == "BLOCK"
        assert "PROD_DEPLOY_NO_APPROVAL" in (d1.get("reason_codes") or [])

        spec_pass = _spec_for_gate(deployment_target="production", approval_reference="demo-ref-59s")
        mock_response = {
            "execution_id": "ex-59s-1",
            "status": "completed",
            "message": "Done.",
            "output": [{"type": "message", "content": [{"type": "text", "text": '{"status":"success","message":"Done."}'}]}],
            "usage": {},
        }
        with patch("app.services.task_submission.OpenClawClient") as mock_client_class:
            mock_client_class.return_value.execute = AsyncMock(return_value=mock_response)
            resp2 = client.post("/task", json=spec_pass, headers=auth_headers)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2["gate_outcome"] == "PASS"
        assert d2.get("task_id")
        assert d2.get("execution_id") or d2.get("execution_response")

        task_id = d2["task_id"]
        resp3 = client.get(f"/status/{task_id}", headers=auth_headers)
        assert resp3.status_code == 200
        receipt = resp3.json()
        assert receipt.get("execution_id") or receipt.get("status")
        audit = receipt.get("audit_history") or []
        event_types = [e.get("event_type") for e in audit if isinstance(e, dict)]
        assert "gate_decision" in event_types
        assert "execution_response" in event_types or receipt.get("status") in ("completed", "failed", "partial", "needs_review")

        print_scene_multi(
            "Full demo: Block → Pass + execute → Receipt",
            [
                ("POST", "/task", spec_block, resp1),
                ("POST", "/task", spec_pass, resp2),
                ("GET", f"/status/{task_id}", None, resp3),
            ],
        )

    def test_gate_evaluate_returns_block_with_defect_message(self, client: TestClient, auth_headers: dict):
        """
        POST /gate/evaluate: production deploy without approval returns BLOCK and defect message for UI.
        """
        domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
        operations = _production_deploy_operations()
        plan_canonical = {"domain": domain, "operations": operations}
        plan_hash = hash_payload(plan_canonical)
        body = {
            "ocgg_identity": "W-OCGG",
            "plan_hash": plan_hash,
            "operations": operations,
            "deployment_target": "production",
        }
        resp = client.post("/gate/evaluate", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "BLOCK"
        assert "PROD_DEPLOY_NO_APPROVAL" in (data.get("reason_codes") or [])
        defect_messages = [d.get("message", "") for d in (data.get("defect_list") or []) if isinstance(d, dict)]
        assert any("approval" in m.lower() for m in defect_messages)

        print_scene(
            "Gate evaluate: production deploy without approval → BLOCK + defect message",
            "POST",
            "/gate/evaluate",
            body,
            resp,
        )


@pytest.fixture
def client():
    return TestClient(app)
