"""Ownership-aware agent-team planning helpers for deterministic web builds."""
from __future__ import annotations

from typing import Any, Optional

INTERACTIVE_PAGE_TYPES = frozenset({
    "contact", "faq", "pricing", "gallery", "portfolio",
    "calculator", "booking", "search", "dashboard", "quiz",
})


def _classify_interactive_routes(
    routes: list[str],
    operations: list[dict[str, Any]],
) -> list[str]:
    """Return routes likely to require 'use client' based on page type heuristics."""
    interactive: list[str] = []
    op_types: dict[str, str] = {}
    for op in operations:
        if not isinstance(op, dict):
            continue
        slug = str(op.get("slug") or op.get("route") or "").strip().strip("/")
        ptype = str(op.get("page_type") or op.get("type") or "").strip().lower()
        if slug and ptype:
            op_types[slug] = ptype
    for route in routes:
        slug = route.strip("/") or "home"
        ptype = op_types.get(slug, slug)
        if ptype in INTERACTIVE_PAGE_TYPES or slug in INTERACTIVE_PAGE_TYPES:
            interactive.append(route)
    return interactive


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

    interactive_routes = _classify_interactive_routes(routes, operations)

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
        {
            "name": "directive_safety",
            "description": (
                "'use client' must be the very first line of any file using React hooks or event handlers. "
                "It is mutually exclusive with metadata exports. Violations break the build."
            ),
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
        "instructions": [
            "Place 'use client' as the VERY FIRST LINE of any file using hooks or event handlers.",
            f"These routes likely need 'use client': {interactive_routes}" if interactive_routes else
            "No routes were identified as requiring 'use client' — use server components by default.",
            "Shared components go in src/components/ with named exports.",
            "Route pages go in src/app/<slug>/page.tsx with a default export.",
            "Server pages (no hooks) should export const metadata for SEO.",
            "If a page needs both metadata AND interactivity, keep the page as a server component and extract interactive parts into a client component under src/components/.",
        ],
        "acceptance_checks": [
            "All planned marketing routes render under src/app.",
            "Shared components live under src/components and route modules may export metadata.",
            "'use client' is the first line in every file using hooks or event handlers.",
        ],
    }
    backend_packet = {
        "agent_role": "backend",
        "phase": "backend_done",
        "owned_paths": list(backend_owned_paths),
        "allowed_shared_paths": [],
        "depends_on": ["sanitizer_done"],
        "inputs": {
            "domain": domain,
            "integrations": list(integrations),
            "requires_server_files": any(
                str(op.get("type") or "").strip().lower() in {"api", "server_action", "integration"}
                for op in operations
            ),
        },
        "instructions": [
            "Server-only code must stay inside backend-owned paths.",
            "Do NOT overwrite or modify any frontend-owned files.",
            f"Integrations to wire up: {integrations}" if integrations else
            "No external integrations required.",
            "API routes go in src/app/api/<name>/route.ts with named HTTP-method exports.",
        ],
        "acceptance_checks": [
            "Server-only code stays in backend-owned paths.",
            "Backend work does not overwrite route or component files owned by frontend.",
        ],
    }
    sanitizer_packet = {
        "agent_role": "sanitizer",
        "phase": "sanitizer_done",
        "owned_paths": [],
        "allowed_shared_paths": [],
        "depends_on": ["frontend_done"],
        "inputs": {},
        "instructions": [
            "Run deterministic code transformations: directive normalization, import validation, export checks.",
            "No LLM calls — purely rule-based fixes.",
        ],
        "acceptance_checks": [
            "'use client' is the first line in every file that needs it.",
            "All hook/component imports resolve to existing files or packages.",
            "No file mixes 'use client' with metadata exports.",
        ],
    }
    reviewer_packet = {
        "agent_role": "reviewer",
        "phase": "review_done",
        "owned_paths": [],
        "allowed_shared_paths": [],
        "depends_on": ["backend_done"],
        "inputs": {},
        "instructions": [
            "Review ALL generated files for Next.js anti-patterns, broken cross-file references, and accessibility gaps.",
            "Only fix build-blocking and deploy-blocking issues. Do NOT change cosmetic styling.",
            "Return a structured JSON report with issues found and patched files.",
        ],
        "acceptance_checks": [
            "No build-blocking anti-patterns remain.",
            "All cross-file imports resolve correctly.",
            "Every image has alt text and pages have proper heading hierarchy.",
        ],
    }
    verifier_packet = {
        "agent_role": "verifier",
        "phase": "verify_done",
        "owned_paths": [],
        "allowed_shared_paths": [],
        "depends_on": ["review_done"],
        "inputs": {
            "deployment_target": (deployment_target or "preview"),
        },
        "instructions": [
            "Run ownership conflict detection, static quality gate, and local npm build preflight.",
            "Block deploy only on real failures — do not flag cosmetic issues.",
            f"Expected routes: {routes}",
        ],
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
                "instructions": [
                    "Emit ownership manifest, work packets with per-agent instructions, and reserved singletons.",
                    f"Site domain: {domain}",
                    f"Total routes: {len(routes)}, interactive routes: {len(interactive_routes)}",
                ],
                "acceptance_checks": [
                    "Planner emits ownership manifest, work packets, and reserved singletons.",
                ],
            },
            frontend_packet,
            sanitizer_packet,
            backend_packet,
            reviewer_packet,
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
                "agent_role": "sanitizer",
                "owned_paths": [],
                "allowed_shared_paths": [],
            },
            {
                "agent_role": "reviewer",
                "owned_paths": [],
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
