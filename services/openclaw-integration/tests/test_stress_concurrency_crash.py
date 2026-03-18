"""
Stress, Concurrency & Crash Safety (H1–H4).

H1 — Parallel Gate Evaluation: 1000 concurrent requests; deterministic outcomes, no corruption.
H2 — Parallel Execution: 100 concurrent tasks; no artifact collisions (isolated by task_id).
H3 — Mid-Execution Crash: kill runtime; rollback, no partial state.
H4 — Gate Restart During Evaluation: no orphaned execution (recovery marks orphans as error).
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

from app.core.identity import IDENTITY_DOMAIN_MAP
from app.core.security import hash_payload
from app.models import Task, TaskStatus, UsedExecutionToken
from app.services.execution_client import OpenClawClient, OpenClawError
from app.services.orphan_recovery import ORPHAN_AUDIT_EVENT, ORPHAN_STATUS, recover_orphaned_tasks

from app.db.session import get_sessionmaker
from app.gate.token import generate_execution_token, hash_token
from app.main import app


def _gate_evaluate_payload() -> dict[str, Any]:
    """Valid payload for POST /gate/evaluate (same outcome every time)."""
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    operations = [{"type": "build", "op_id": "1", "target": "repo"}]
    plan_canonical = {"domain": domain, "operations": operations}
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": hash_payload(plan_canonical),
        "operations": operations,
    }


def _task_submit_payload(unique_id: int) -> dict[str, Any]:
    """Valid payload for POST /task with unique plan (different plan_hash per id)."""
    domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
    operations = [{"type": "build", "op_id": f"op-{unique_id}", "target": "repo", "inputs": {"x": unique_id}}]
    plan_canonical = {"domain": domain, "operations": operations}
    return {
        "ocgg_identity": "W-OCGG",
        "plan_hash": hash_payload(plan_canonical),
        "operations": operations,
    }


# ----- H1 — Parallel Gate Evaluation -----


@pytest.mark.asyncio
async def test_H1_parallel_gate_evaluation_1000_concurrent_deterministic_no_corruption():
    """H1: 1000 concurrent gate evaluations; all outcomes identical, no corruption."""
    payload = _gate_evaluate_payload()
    auth_headers = {"Authorization": "Bearer test-integration-key"}
    transport = ASGITransport(app=app)

    async def one_request() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=transport) as client:
            r = await client.post(
                "http://testserver/gate/evaluate",
                json=payload,
                headers=auth_headers,
                timeout=30.0,
            )
            r.raise_for_status()
            return r.json()

    concurrency = 1000
    results = await asyncio.gather(*[one_request() for _ in range(concurrency)], return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"Expected no exceptions, got {len(errors)}: {errors[:3]}"

    jsons = [r for r in results if isinstance(r, dict)]
    assert len(jsons) == concurrency

    first = jsons[0]
    for i, resp in enumerate(jsons):
        assert resp.get("outcome") == first.get("outcome"), f"Request {i}: outcome mismatch"
        assert resp.get("reason_codes") == first.get("reason_codes"), f"Request {i}: reason_codes mismatch"
        assert resp.get("spec_hash") == first.get("spec_hash"), f"Request {i}: spec_hash mismatch"
        assert resp.get("plan_hash") == first.get("plan_hash"), f"Request {i}: plan_hash mismatch"
        assert resp.get("policy_version") == first.get("policy_version"), f"Request {i}: policy_version mismatch"


# ----- H2 — Parallel Execution (no artifact collisions) -----


@pytest.mark.asyncio
async def test_H2_parallel_execution_100_concurrent_no_artifact_collisions():
    """H2: 100 concurrent task submissions; each execution has isolated user/session (task_id). No artifact collisions."""
    auth_headers = {"Authorization": "Bearer test-integration-key"}
    transport = ASGITransport(app=app)
    executed_task_ids: list[str] = []
    executed_users: list[str] = []

    async def mock_execute(plan: dict, execution_token: str | None, task_id: str | None = None):
        executed_task_ids.append(task_id or "")
        domain = plan.get("domain") or "default"
        user = f"project:{domain}:{task_id}" if task_id else f"project:{domain}"
        executed_users.append(user)
        return {
            "execution_id": f"ex-{task_id}",
            "status": "success",
            "message": "ok",
            "artifacts": [{"path": f"out/{task_id}", "type": "file", "summary": "done"}],
        }

    with patch.object(OpenClawClient, "execute", new_callable=AsyncMock, side_effect=mock_execute):
        async with httpx.AsyncClient(transport=transport) as client:
            tasks_to_run = [_task_submit_payload(i) for i in range(100)]
            responses = await asyncio.gather(
                *[
                    client.post("http://testserver/task", json=payload, headers=auth_headers, timeout=60.0)
                    for payload in tasks_to_run
                ],
                return_exceptions=True,
            )

    errors = [r for r in responses if isinstance(r, Exception)]
    assert not errors, f"Expected no request exceptions: {errors[:3]}"

    ok = [r for r in responses if isinstance(r, httpx.Response) and r.status_code == 200]
    assert len(ok) == 100, f"Expected 100 OK responses, got {len(ok)}"

    # Each execute() call had a distinct task_id (and thus distinct user)
    assert len(executed_task_ids) == 100
    assert len(set(executed_task_ids)) == 100, "All execution calls must have distinct task_id (no artifact collision)"
    assert len(set(executed_users)) == 100, "All execution calls must have distinct user (session isolation)"


# ----- H3 — Mid-Execution Crash (rollback, no partial state) -----


@pytest.mark.asyncio
async def test_H3_mid_execution_crash_rollback_no_partial_state():
    """H3: When runtime fails during execute(), task is marked failed; no partial state (execution_id only if in response)."""
    auth_headers = {"Authorization": "Bearer test-integration-key"}
    transport = ASGITransport(app=app)
    payload = _task_submit_payload(0)

    with patch.object(
        OpenClawClient,
        "execute",
        new_callable=AsyncMock,
        side_effect=OpenClawError("error", "Timeout: runtime killed", response={"execution_id": None}),
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            r = await client.post("http://testserver/task", json=payload, headers=auth_headers, timeout=30.0)

    assert r.status_code == 200
    data = r.json()
    assert data.get("gate_outcome") == "PASS"
    assert data.get("status") in ("error", "failed", "invalid_plan", "auth_error", "domain_rejected")
    # No partial state: task is not left as "submitted" with token consumed and no result
    assert data.get("status") != "submitted" or data.get("execution_id") is not None


@pytest.mark.asyncio
async def test_H3_crash_after_commit_before_execute_task_eventually_recoverable():
    """H3: Task committed with token consumed but execute() never completes (crash). Orphan recovery marks it error."""
    from app.db.init_db import ensure_db_ready
    await ensure_db_ready()
    async with get_sessionmaker()() as session:
        from app.models import GateDecisionRecord

        domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
        operations = [{"type": "build", "op_id": "orphan", "target": "repo"}]
        plan_canonical = {"domain": domain, "operations": operations}
        plan_hash = hash_payload(plan_canonical)
        spec = {"ocgg_identity": "W-OCGG", "plan_hash": plan_hash, "operations": operations}
        spec_hash = hash_payload(spec)
        token = generate_execution_token({
            "spec_hash": spec_hash,
            "plan_hash": plan_hash,
            "policy_version": "1.0",
            "ocgg_identity": "W-OCGG",
            "outcome": "PASS",
        })
        token_hash = hash_token(token)

        task = Task(
            ocgg_identity="W-OCGG",
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version="1.0",
            gate_outcome="PASS",
            reason_codes=[],
            plan_json={"domain": domain, "plan_hash": plan_hash, "operations": operations},
            audit_history=[],
            status=TaskStatus.submitted,
            execution_token_hash=token_hash,
            execution_id=None,
        )
        session.add(task)
        await session.flush()
        session.add(GateDecisionRecord(
            task_id=task.task_id,
            ocgg_identity="W-OCGG",
            outcome="PASS",
            reason_codes=[],
            defect_list=[],
            policy_version="1.0",
            spec_hash=spec_hash,
            plan_hash=plan_hash,
        ))
        session.add(UsedExecutionToken(token_hash=token_hash, task_id=task.task_id))
        await session.commit()
        orphan_id = task.task_id

    async with get_sessionmaker()() as session_recovery:
        count = await recover_orphaned_tasks(session_recovery)
    async with get_sessionmaker()() as session2:
        task_after = await session2.get(Task, orphan_id)
        assert task_after is not None
        assert task_after.status == ORPHAN_STATUS
        audit_types = [e.get("event_type") for e in (task_after.audit_history or []) if isinstance(e, dict)]
        assert ORPHAN_AUDIT_EVENT in audit_types


# ----- H4 — Gate Restart During Evaluation (no orphaned execution) -----


@pytest.mark.asyncio
async def test_H4_gate_restart_during_evaluation_no_orphaned_execution():
    """H4: Orphan recovery marks tasks (token consumed, no execution_id) as error so no orphaned execution."""
    from app.db.init_db import ensure_db_ready
    await ensure_db_ready()
    async with get_sessionmaker()() as session:
        from app.models import GateDecisionRecord

        domain = IDENTITY_DOMAIN_MAP["W-OCGG"]
        operations = [{"type": "build", "op_id": "h4", "target": "repo"}]
        plan_canonical = {"domain": domain, "operations": operations}
        plan_hash = hash_payload(plan_canonical)
        spec = {"ocgg_identity": "W-OCGG", "plan_hash": plan_hash, "operations": operations}
        spec_hash = hash_payload(spec)
        token = generate_execution_token({
            "spec_hash": spec_hash,
            "plan_hash": plan_hash,
            "policy_version": "1.0",
            "ocgg_identity": "W-OCGG",
            "outcome": "PASS",
        })
        token_hash = hash_token(token)

        task = Task(
            ocgg_identity="W-OCGG",
            domain=domain,
            plan_hash=plan_hash,
            spec_hash=spec_hash,
            policy_version="1.0",
            gate_outcome="PASS",
            reason_codes=[],
            plan_json={"domain": domain, "plan_hash": plan_hash, "operations": operations},
            audit_history=[],
            status=TaskStatus.submitted,
            execution_token_hash=token_hash,
            execution_id=None,
        )
        session.add(task)
        await session.flush()
        session.add(GateDecisionRecord(
            task_id=task.task_id,
            ocgg_identity="W-OCGG",
            outcome="PASS",
            reason_codes=[],
            defect_list=[],
            policy_version="1.0",
            spec_hash=spec_hash,
            plan_hash=plan_hash,
        ))
        session.add(UsedExecutionToken(token_hash=token_hash, task_id=task.task_id))
        await session.commit()
        orphan_id = task.task_id

    async with get_sessionmaker()() as session2:
        n = await recover_orphaned_tasks(session2)
    assert n >= 1
    async with get_sessionmaker()() as session3:
        task_after = await session3.get(Task, orphan_id)
        assert task_after is not None
        assert task_after.status == ORPHAN_STATUS
        assert task_after.execution_id is None
        # Orphan is resolved: no lingering "submitted + token used" state
        assert not (
            task_after.status == "submitted"
            and task_after.execution_token_hash is not None
            and task_after.execution_id is None
        )
