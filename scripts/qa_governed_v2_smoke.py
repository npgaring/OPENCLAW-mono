#!/usr/bin/env python3
"""Governed v2 end-to-end QA smoke runner.

Flow:
1) DUDE-X cognitive mode: raw intent -> Build SoT
2) DUDE-X lock #1: Build SoT governance evaluate
3) DUDE-X approval: approve Build SoT
4) DUDE-X compiler mode: locked SoT -> execution plan
5) OpenClaw lock #2: execution plan lock
6) OpenClaw task dispatch
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass
class StepResult:
    name: str
    status_code: int
    payload: dict[str, Any]


def _base(url: str) -> str:
    return url.rstrip("/")


def _headers(api_key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url=url, data=payload, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return resp.status, parsed
    except error.HTTPError as e:
        raw = e.read().decode("utf-8")
        parsed = json.loads(raw) if raw else {}
        return e.code, parsed


def _fail(step: str, status: int, payload: dict[str, Any]) -> None:
    raise RuntimeError(f"[{step}] HTTP {status}: {json.dumps(payload, indent=2)}")


def _print_step(result: StepResult) -> None:
    print(f"[{result.name}] HTTP {result.status_code}")
    print(json.dumps(result.payload, indent=2))
    print("-" * 80)


def run(args: argparse.Namespace) -> int:
    token = args.api_key or os.getenv("INTEGRATION_API_KEY", "").strip()
    if not token:
        raise RuntimeError("INTEGRATION_API_KEY is required (flag --api-key or env var).")

    trace_id = str(uuid.uuid4())
    headers = _headers(token)

    dudex = _base(args.dudex_base)
    integration = _base(args.integration_base)

    print(f"trace_id={trace_id}")
    print(f"dudex_base={dudex}")
    print(f"integration_base={integration}")
    print("=" * 80)

    # 1) raw intent -> Build SoT
    raw_body = {
        "idea": args.idea,
        "voice": args.voice,
        "ocgg_identity": args.ocgg_identity,
        "intent": args.intent,
        "deployment_target": args.deployment_target,
        "trace_id": trace_id,
        "brief": {
            "project_name": args.project_name,
            "site_purpose": args.site_purpose,
            "target_audience": [x.strip() for x in args.target_audience.split(",") if x.strip()],
            "desired_tone": args.desired_tone,
            "page_list": [x.strip() for x in args.pages.split(",") if x.strip()],
            "integrations": [x.strip() for x in args.integrations.split(",") if x.strip()],
            "deployment_target": args.deployment_target,
        },
    }
    s, p = _http_json(method="POST", url=f"{dudex}/v2/raw-intents", headers=headers, body=raw_body)
    raw_step = StepResult("raw-intents", s, p)
    _print_step(raw_step)
    if s >= 500:
        _fail(raw_step.name, s, p)
    if s != 200:
        _fail(raw_step.name, s, p)
    build_sot_hash = (
        p.get("stage_linkage", {}).get("build_sot_hash")
        if isinstance(p.get("stage_linkage"), dict)
        else None
    )
    if not build_sot_hash:
        raise RuntimeError("[raw-intents] missing build_sot_hash")

    # 2) Build SoT governance evaluate
    gov_body = {"ocgg_identity": args.ocgg_identity, "intent": args.intent, "trace_id": trace_id}
    s, p = _http_json(
        method="POST",
        url=f"{dudex}/v2/build-sot/{build_sot_hash}/governance/evaluate",
        headers=headers,
        body=gov_body,
    )
    sot_lock_step = StepResult("build-sot-governance-evaluate", s, p)
    _print_step(sot_lock_step)
    if s >= 500:
        _fail(sot_lock_step.name, s, p)
    if s != 200:
        _fail(sot_lock_step.name, s, p)
    if p.get("outcome") != "PASS":
        raise RuntimeError(f"[{sot_lock_step.name}] expected PASS outcome, got {p.get('outcome')}")

    # 3) Approve SoT
    approve_body = {
        "decision": "APPROVE",
        "approver_id": args.approver_id,
        "comment": "QA smoke approval",
    }
    s, p = _http_json(
        method="POST",
        url=f"{dudex}/v2/build-sot/{build_sot_hash}/approval/decide",
        headers=headers,
        body=approve_body,
    )
    approve_step = StepResult("build-sot-approval", s, p)
    _print_step(approve_step)
    if s >= 500:
        _fail(approve_step.name, s, p)
    if s != 200:
        _fail(approve_step.name, s, p)

    # 4) compile
    s, p = _http_json(
        method="POST",
        url=f"{dudex}/v2/build-sot/{build_sot_hash}/compile",
        headers=headers,
        body=None,
    )
    compile_step = StepResult("compile", s, p)
    _print_step(compile_step)
    if s >= 500:
        _fail(compile_step.name, s, p)
    if s != 200:
        _fail(compile_step.name, s, p)
    execution_plan_hash = (
        p.get("stage_linkage", {}).get("execution_plan_hash")
        if isinstance(p.get("stage_linkage"), dict)
        else None
    )
    governance_projection = p.get("governance_projection") if isinstance(p, dict) else {}
    operations = p.get("operations") if isinstance(p, dict) else None
    if not execution_plan_hash:
        raise RuntimeError("[compile] missing execution_plan_hash")
    if not isinstance(operations, list) or not operations:
        raise RuntimeError("[compile] missing operations")

    # 5) execution plan lock
    lock_body = {
        "trace_id": trace_id,
        "ocgg_identity": args.ocgg_identity,
        "build_sot_hash": build_sot_hash,
        "execution_plan_hash": execution_plan_hash,
        "plan_hash": (governance_projection or {}).get("plan_hash"),
        "operations": operations,
        "deployment_target": args.deployment_target,
        "goal": (governance_projection or {}).get("goal"),
        "context": (governance_projection or {}).get("context"),
        "acceptance_criteria": (governance_projection or {}).get("acceptance_criteria"),
    }
    s, p = _http_json(
        method="POST",
        url=f"{integration}/v2/execution-plan/lock",
        headers=headers,
        body=lock_body,
    )
    exec_lock_step = StepResult("execution-plan-lock", s, p)
    _print_step(exec_lock_step)
    if s >= 500:
        _fail(exec_lock_step.name, s, p)
    if s != 200:
        _fail(exec_lock_step.name, s, p)
    if p.get("outcome") != "PASS":
        raise RuntimeError(f"[{exec_lock_step.name}] expected PASS outcome, got {p.get('outcome')}")
    continuity_id = p.get("continuity_id")
    governance_evaluation_id = p.get("governance_evaluation_id")
    if not continuity_id:
        raise RuntimeError("[execution-plan-lock] missing continuity_id")

    # 6) task dispatch
    task_body = {
        "ocgg_identity": args.ocgg_identity,
        "trace_id": trace_id,
        "plan_hash": (governance_projection or {}).get("plan_hash"),
        "operations": operations,
        "deployment_target": args.deployment_target,
        "goal": (governance_projection or {}).get("goal"),
        "context": (governance_projection or {}).get("context"),
        "acceptance_criteria": (governance_projection or {}).get("acceptance_criteria"),
        "build_sot_hash": build_sot_hash,
        "execution_plan_hash": execution_plan_hash,
        "v2_continuity_id": continuity_id,
        "governance_evaluation_id": governance_evaluation_id,
        "executor_contract": compile_step.payload.get("execution_mode", "deterministic_web_v1"),
        "execution_plan_v2": compile_step.payload,
    }
    s, p = _http_json(method="POST", url=f"{integration}/task", headers=headers, body=task_body)
    task_step = StepResult("task-submit", s, p)
    _print_step(task_step)
    if s >= 500:
        _fail(task_step.name, s, p)
    if s != 200:
        _fail(task_step.name, s, p)

    print("QA smoke completed without 5xx errors.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Governed v2 QA smoke runner.")
    parser.add_argument("--dudex-base", default="http://127.0.0.1:8011")
    parser.add_argument("--integration-base", default="http://127.0.0.1:8012")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--ocgg-identity", default="W-OCGG", choices=["W-OCGG", "R-OCGG"])
    parser.add_argument("--intent", default="web-build")
    parser.add_argument("--deployment-target", default="preview", choices=["preview", "production"])
    parser.add_argument("--approver-id", default="qa-operator")
    parser.add_argument("--idea", default="Build a governed conversion website for a local clinic.")
    parser.add_argument("--voice", default="Professional tone. Include contact funnel and analytics.")
    parser.add_argument("--project-name", default="Clinic Nova QA")
    parser.add_argument("--site-purpose", default="Generate qualified clinic consultation leads.")
    parser.add_argument("--target-audience", default="local patients")
    parser.add_argument("--desired-tone", default="professional")
    parser.add_argument("--pages", default="home,pricing,contact")
    parser.add_argument("--integrations", default="analytics")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args(sys.argv[1:])))
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
