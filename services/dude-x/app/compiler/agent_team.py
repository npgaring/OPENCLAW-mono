"""Ownership-aware agent-team planning helpers for deterministic web builds."""
from __future__ import annotations

from typing import Any, Optional


def build_agent_team_plan(
    *,
    domain: str,
    deployment_target: Optional[str],
    routes: Optional[list[str]] = None,
    operations: Optional[list[dict[str, Any]]] = None,
    integrations: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Return the default multi-agent ownership contract for web plans."""
    routes = [str(route).strip() for route in (routes or []) if str(route).strip()]
    operations = [op for op in (operations or []) if isinstance(op, dict)]
    integrations = [str(item).strip() for item in (integrations or []) if str(item).strip()]

    frontend_owned_paths = [
        "src/app/**",
        "src/components/**",
        "src/styles/**",
        "public/**",
    ]
    backend_owned_paths = [
        "src/app/api/**",
        "src/lib/server/**",
        "src/lib/integrations/**",
        "src/lib/env/**",
        "src/lib/schema/**",
    ]
    reserved_singletons = [
        {"path": "src/app/layout.tsx", "agent_role": "frontend"},
        {"path": "src/app/globals.css", "agent_role": "frontend"},
        {"path": "package.json", "agent_role": "orchestrator"},
        {"path": "tsconfig.json", "agent_role": "orchestrator"},
        {"path": "next.config.*", "agent_role": "orchestrator"},
        {"path": "postcss.config.*", "agent_role": "orchestrator"},
    ]
    shared_contracts = [
        {
            "name": "next_app_router",
            "description": "Use Next.js App Router conventions and keep route-module exports module-local.",
        },
        {
            "name": "deploy_pipeline",
            "description": "Verifier must pass ownership, local build, and Vercel access checks before commit/deploy.",
        },
    ]

    frontend_packet = {
        "agent_role": "frontend",
        "phase": "frontend_done",
        "owned_paths": list(frontend_owned_paths),
        "allowed_shared_paths": ["public/**"],
        "depends_on": ["planner_done"],
        "inputs": {
            "domain": domain,
            "routes": list(routes),
            "operation_count": len(operations),
        },
        "acceptance_checks": [
            "All planned marketing routes render under src/app.",
            "Shared components live under src/components and route modules may export metadata.",
        ],
    }
    backend_packet = {
        "agent_role": "backend",
        "phase": "backend_done",
        "owned_paths": list(backend_owned_paths),
        "allowed_shared_paths": [],
        "depends_on": ["frontend_done"],
        "inputs": {
            "domain": domain,
            "integrations": list(integrations),
            "requires_server_files": any(
                str(op.get("type") or "").strip().lower() in {"api", "server_action", "integration"}
                for op in operations
            ),
        },
        "acceptance_checks": [
            "Server-only code stays in backend-owned paths.",
            "Backend work does not overwrite route or component files owned by frontend.",
        ],
    }
    verifier_packet = {
        "agent_role": "verifier",
        "phase": "verify_done",
        "owned_paths": [],
        "allowed_shared_paths": [],
        "depends_on": ["backend_done"],
        "inputs": {
            "deployment_target": (deployment_target or "preview"),
        },
        "acceptance_checks": [
            "Ownership conflicts are resolved before local preflight.",
            "Local build and Vercel preflight pass before commit/deploy.",
        ],
    }

    route_ownership = [
        {"route": route, "agent_role": "frontend"}
        for route in routes
    ]
    if "/" not in {entry["route"] for entry in route_ownership}:
        route_ownership.append({"route": "/", "agent_role": "frontend"})

    return {
        "work_packets": [
            {
                "agent_role": "planner",
                "phase": "planner_done",
                "owned_paths": [],
                "allowed_shared_paths": [],
                "depends_on": [],
                "inputs": {
                    "domain": domain,
                    "deployment_target": (deployment_target or "preview"),
                    "operation_count": len(operations),
                },
                "acceptance_checks": [
                    "Planner emits ownership manifest, work packets, and reserved singletons.",
                ],
            },
            frontend_packet,
            backend_packet,
            verifier_packet,
        ],
        "file_ownership": [
            {
                "agent_role": "frontend",
                "owned_paths": list(frontend_owned_paths),
                "allowed_shared_paths": ["public/**"],
            },
            {
                "agent_role": "backend",
                "owned_paths": list(backend_owned_paths),
                "allowed_shared_paths": [],
            },
            {
                "agent_role": "verifier",
                "owned_paths": [],
                "allowed_shared_paths": [],
            },
        ],
        "shared_contracts": shared_contracts,
        "reserved_singletons": reserved_singletons,
        "route_ownership": route_ownership,
    }
