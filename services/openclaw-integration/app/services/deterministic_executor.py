"""Deterministic in-service executor for deterministic_web_v1 plans.

Multi-phase pipeline:
  1. Provision GitHub repository (template or empty)
  2. Generate production-quality code via OpenAI
  3. Batch-commit all generated files via GitHub Trees API
  4. Create Vercel project and trigger deployment
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
VERCEL_API_BASE = "https://api.vercel.com"
OPENAI_API_BASE = "https://api.openai.com/v1"

REASON_GITHUB_AUTH_FAILED = "EXECUTION_GITHUB_AUTH_FAILED"
REASON_GITHUB_REPO_CREATE_FAILED = "EXECUTION_GITHUB_REPO_CREATE_FAILED"
REASON_VERCEL_PROJECT_CREATE_FAILED = "EXECUTION_VERCEL_PROJECT_CREATE_FAILED"
REASON_VERCEL_DEPLOY_FAILED = "EXECUTION_VERCEL_DEPLOY_FAILED"
REASON_DEPLOY_QUALITY_GATE_FAILED = "EXECUTION_DEPLOY_QUALITY_GATE_FAILED"
REASON_CODE_GENERATION_FAILED = "EXECUTION_CODE_GENERATION_FAILED"
REASON_CODEGEN_CONFLICT_DETECTED = "EXECUTION_CODEGEN_CONFLICT_DETECTED"
REASON_CODEGEN_AUTOFIX_STALLED = "EXECUTION_CODEGEN_AUTOFIX_STALLED"

CODEGEN_TIMEOUT_SECONDS = 180
GITHUB_TIMEOUT_SECONDS = 60
VERCEL_TIMEOUT_SECONDS = 60
BRANCH_RETRY_DELAYS = (2, 3, 5, 8)

LEGACY_BUILD_PHASE_BY_AGENT_PHASE = {
    "planner_done": "architect_done",
    "frontend_done": "foundation_done",
    "sanitizer_done": "foundation_done",
    "backend_done": "pages_done",
    "review_done": "pages_done",
    "verify_done": "pages_done",
    "complete": "complete",
    "error": "error",
}

AGENT_ROLE_BY_PHASE = {
    "planner_done": "planner",
    "frontend_done": "frontend",
    "sanitizer_done": "sanitizer",
    "backend_done": "backend",
    "review_done": "reviewer",
    "verify_done": "verifier",
    "complete": "orchestrator",
    "error": "verifier",
}

ALLOWED_ROUTE_MODULE_EXPORTS = {
    "default",
    "metadata",
    "generateMetadata",
    "viewport",
    "generateViewport",
    "generateStaticParams",
    "revalidate",
    "dynamic",
    "dynamicParams",
    "fetchCache",
    "runtime",
    "preferredRegion",
    "maxDuration",
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _sanitize_error_snippet(data: Any, text: str, *, limit: int = 280) -> str:
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return " ".join(message.split())[:limit]
        error = data.get("error")
        if isinstance(error, dict):
            msg = error.get("message")
            if isinstance(msg, str) and msg.strip():
                return " ".join(msg.split())[:limit]
    if isinstance(text, str) and text.strip():
        return " ".join(text.split())[:limit]
    return "unknown upstream error"


def _normalize_private_key(value: str) -> str:
    normalized = (value or "").strip()
    if "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized


def _is_deterministic_plan(plan: dict[str, Any]) -> bool:
    return plan.get("executor_contract") == "deterministic_web_v1" or isinstance(plan.get("execution_plan_v2"), dict)


def _legacy_build_phase(agent_phase: str) -> str:
    return LEGACY_BUILD_PHASE_BY_AGENT_PHASE.get(agent_phase, agent_phase)


def _agent_role_for_phase(agent_phase: str) -> Optional[str]:
    return AGENT_ROLE_BY_PHASE.get(agent_phase)


class DeterministicExecutionError(Exception):
    def __init__(
        self,
        *,
        reason_code: str,
        message: str,
        status_code: Optional[int] = None,
        provider: Optional[str] = None,
        snippet: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ):
        self.reason_code = reason_code
        self.message = message
        self.status_code = status_code
        self.provider = provider
        self.snippet = snippet
        self.extra = extra or {}
        super().__init__(message)

    def as_execution_response(self, *, execution_id: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "needs_review",
            "message": self.message,
            "reason_codes": [self.reason_code],
        }
        if execution_id:
            payload["execution_id"] = execution_id
        if self.provider or self.status_code is not None or self.snippet:
            payload["provider_error"] = {
                "provider": self.provider,
                "status_code": self.status_code,
                "snippet": self.snippet,
            }
        payload.update(self.extra)
        return payload


@dataclass
class RepoSpec:
    owner: str
    name: str
    branch: str
    private: bool


@dataclass
class RepoProvisionResult:
    owner: str
    name: str
    branch: str
    html_url: str
    default_branch: str


@dataclass
class VercelProjectResult:
    id: Optional[str]
    name: str


@dataclass
class VercelDeploymentResult:
    id: Optional[str]
    url: Optional[str]
    target: str


APPROVED_PACKAGES: dict[str, str] = {
    "next": "^15.5.14",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "tailwindcss": "^4.2.2",
    "@tailwindcss/postcss": "^4.2.2",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.0.2",
    "class-variance-authority": "^0.7.1",
    "lucide-react": "^0.511.0",
    "react-icons": "^5.5.0",
    "framer-motion": "^12.9.4",
    "react-hook-form": "^7.56.3",
    "zod": "^3.24.4",
    "@hookform/resolvers": "^5.0.1",
    "date-fns": "^4.1.0",
    "slugify": "^1.6.6",
    "sharp": "^0.34.2",
    "typescript": "^5.8.3",
    "@types/node": "^22",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "eslint": "^9.39.1",
    "eslint-config-next": "^15",
}

APPROVED_PACKAGE_SUBPATHS: dict[str, set[str]] = {
    "next": {"", "link", "image", "navigation", "font/google", "script", "headers"},
    "react": {""},
    "react-dom": {"", "client"},
    "react-icons": {"*"},
    "date-fns": {"*"},
    "@hookform/resolvers": {"zod"},
}


def _strip_markdown_fences(content: str) -> str:
    """Remove wrapping markdown code fences that AI models sometimes emit."""
    stripped = content.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl > 0:
            stripped = stripped[first_nl + 1:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
        stripped = stripped.strip()
    return stripped


@dataclass
class GeneratedFile:
    path: str
    content: str


@dataclass
class TemplateReference:
    source_repo: str = ""
    source_branch: str = ""
    package_json: dict[str, Any] = field(default_factory=dict)
    key_files: dict[str, str] = field(default_factory=dict)


@dataclass
class LocalPreflightResult:
    success: bool
    logs: str


@dataclass
class BuildManifest:
    """Runtime continuity ledger for deterministic compiler calls.

    This state is strictly execution-runtime continuity and must never be
    treated as Build SoT or any canonical product artifact.
    """

    packages: dict[str, str] = field(default_factory=dict)
    files_created: list[str] = field(default_factory=list)
    exports_registered: dict[str, str] = field(default_factory=dict)
    css_variables: list[str] = field(default_factory=list)
    routes_created: list[str] = field(default_factory=list)
    utility_modules: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_runtime_json(cls, data: Optional[dict[str, Any]]) -> "BuildManifest":
        if not isinstance(data, dict):
            return cls()
        return cls(
            packages=dict(data.get("packages") or {}),
            files_created=[str(x) for x in (data.get("files_created") or []) if str(x).strip()],
            exports_registered={str(k): str(v) for k, v in dict(data.get("exports_registered") or {}).items()},
            css_variables=[str(x) for x in (data.get("css_variables") or []) if str(x).strip()],
            routes_created=[str(x) for x in (data.get("routes_created") or []) if str(x).strip()],
            utility_modules={str(k): str(v) for k, v in dict(data.get("utility_modules") or {}).items()},
        )

    def to_runtime_json(self) -> dict[str, Any]:
        return {
            "packages": dict(self.packages),
            "files_created": list(dict.fromkeys(self.files_created)),
            "exports_registered": dict(self.exports_registered),
            "css_variables": list(dict.fromkeys(self.css_variables)),
            "routes_created": list(dict.fromkeys(self.routes_created)),
            "utility_modules": dict(self.utility_modules),
        }

    def update_from_files(self, files: list[GeneratedFile]) -> None:
        for f in files:
            if f.path not in self.files_created:
                self.files_created.append(f.path)
            if f.path.endswith("package.json"):
                try:
                    pkg = json.loads(f.content)
                except Exception:
                    pkg = {}
                if isinstance(pkg, dict):
                    for bucket_name in ("dependencies", "devDependencies"):
                        bucket = pkg.get(bucket_name)
                        if isinstance(bucket, dict):
                            for name, version in bucket.items():
                                if isinstance(name, str) and isinstance(version, str):
                                    self.packages[name] = version
            if f.path.endswith((".ts", ".tsx", ".js", ".jsx")):
                for match in re.finditer(r"export\s+(?:async\s+)?(?:function|const|class)\s+(\w+)", f.content):
                    self.exports_registered[match.group(1)] = f.path
                if f.path.endswith((".css",)):
                    continue
                if "/lib/" in f.path or "/utils/" in f.path:
                    module_name = f.path.rsplit("/", 1)[-1].split(".")[0]
                    self.utility_modules[module_name] = f.path
            if f.path.endswith(".css"):
                for match in re.finditer(r"--([a-zA-Z0-9_-]+)\s*:", f.content):
                    var_name = f"--{match.group(1)}"
                    if var_name not in self.css_variables:
                        self.css_variables.append(var_name)

    def add_routes(self, routes: list[str]) -> None:
        for route in routes:
            route_s = str(route or "").strip()
            if route_s and route_s not in self.routes_created:
                self.routes_created.append(route_s)

    def prompt_context(self) -> str:
        parts: list[str] = [
            "=== BUILD MANIFEST (RUNTIME CONTINUITY ONLY) ===",
            "This is execution continuity state, not product-level source of truth.",
        ]
        if self.routes_created:
            parts.append("Routes already planned: " + json.dumps(self.routes_created))
        if self.packages:
            parts.append("Packages already present: " + json.dumps(self.packages, sort_keys=True))
        if self.files_created:
            parts.append("Files already created: " + json.dumps(self.files_created[:200]))
        if self.exports_registered:
            parts.append("Named exports available: " + json.dumps(self.exports_registered, sort_keys=True))
        if self.css_variables:
            parts.append("CSS variables already defined: " + json.dumps(sorted(self.css_variables)))
        if self.utility_modules:
            parts.append("Utility modules already present: " + json.dumps(self.utility_modules, sort_keys=True))
        parts.append("DO NOT recreate, rename, or contradict these artifacts. Reuse/import them.")
        parts.append("=== END BUILD MANIFEST ===")
        return "\n".join(parts) + "\n\n"


class DeterministicWebExecutor:
    """Multi-phase executor: repo → codegen → commit → deploy."""

    def __init__(self, *, timeout_seconds: float = 300.0):
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # Build-state serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def deserialize_template_reference(data: Optional[dict[str, Any]]) -> TemplateReference:
        if not data:
            return TemplateReference()
        return TemplateReference(
            source_repo=data.get("source_repo", ""),
            source_branch=data.get("source_branch", ""),
            package_json=data.get("package_json", {}),
            key_files=data.get("key_files", {}),
        )

    @staticmethod
    def deserialize_files(data: Optional[list[dict[str, str]]]) -> list[GeneratedFile]:
        if not data:
            return []
        return [GeneratedFile(path=d["path"], content=d["content"]) for d in data]

    @staticmethod
    def serialize_files(files: list[GeneratedFile]) -> list[dict[str, str]]:
        return [{"path": f.path, "content": f.content} for f in files]

    @staticmethod
    def _utc_timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _classify_interactive_routes(
        routes: list[str],
        pages: list[dict[str, Any]],
    ) -> list[str]:
        """Return routes likely to require 'use client' based on page type."""
        INTERACTIVE = {
            "contact", "faq", "pricing", "gallery", "portfolio",
            "calculator", "booking", "search", "dashboard", "quiz",
        }
        page_types: dict[str, str] = {}
        for page in pages:
            if not isinstance(page, dict):
                continue
            slug = str(page.get("slug") or "").strip().strip("/")
            ptype = str(page.get("page_type") or page.get("type") or slug).strip().lower()
            if slug:
                page_types[slug] = ptype
        interactive: list[str] = []
        for route in routes:
            slug = route.strip("/") or "home"
            ptype = page_types.get(slug, slug)
            if ptype in INTERACTIVE or slug in INTERACTIVE:
                interactive.append(route)
        return interactive

    def _default_agent_team_plan(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
        blueprint: dict[str, Any],
    ) -> dict[str, Any]:
        routes = [str(route).strip() for route in (context.get("routes") or []) if str(route).strip()]
        if not routes:
            routes = ["/"]
        pages = blueprint.get("pages") or []
        interactive_routes = self._classify_interactive_routes(routes, pages)
        integrations = list(plan.get("integrations") or [])
        shared_components = list(blueprint.get("shared_components") or [])

        file_ownership = [
            {
                "agent_role": "frontend",
                "owned_paths": ["src/app/**", "src/components/**", "src/styles/**", "public/**"],
                "allowed_shared_paths": ["public/**"],
            },
            {
                "agent_role": "backend",
                "owned_paths": [
                    "src/app/api/**",
                    "src/lib/server/**",
                    "src/lib/integrations/**",
                    "src/lib/env/**",
                    "src/lib/schema/**",
                ],
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
        ]
        reserved_singletons = [
            {"path": "src/app/layout.tsx", "agent_role": "frontend"},
            {"path": "src/app/globals.css", "agent_role": "frontend"},
            {"path": "package.json", "agent_role": "orchestrator"},
            {"path": "tsconfig.json", "agent_role": "orchestrator"},
            {"path": "next.config.*", "agent_role": "orchestrator"},
            {"path": "postcss.config.*", "agent_role": "orchestrator"},
        ]
        work_packets = [
            {
                "agent_role": "planner",
                "phase": "planner_done",
                "owned_paths": [],
                "allowed_shared_paths": [],
                "depends_on": [],
                "inputs": {
                    "goal": context.get("goal"),
                    "route_count": len(routes),
                },
                "instructions": [
                    "Emit ownership manifest, work packets with per-agent instructions, and reserved singletons.",
                    f"Total routes: {len(routes)}, interactive routes: {len(interactive_routes)}",
                ],
                "acceptance_checks": [
                    "Planner emits work packets, file ownership, route ownership, and reserved singletons.",
                ],
            },
            {
                "agent_role": "frontend",
                "phase": "frontend_done",
                "owned_paths": [entry["owned_paths"] for entry in file_ownership if entry["agent_role"] == "frontend"][0],
                "allowed_shared_paths": ["public/**"],
                "depends_on": ["planner_done"],
                "inputs": {
                    "routes": list(routes),
                    "shared_components": shared_components,
                },
                "instructions": [
                    "Place 'use client' as the VERY FIRST LINE of any file using hooks or event handlers.",
                    f"These routes likely need 'use client': {interactive_routes}" if interactive_routes else
                    "No routes identified as needing 'use client' — prefer server components.",
                    f"Shared components to generate: {shared_components}" if shared_components else
                    "Generate NavBar and Footer as shared components at minimum.",
                    "Server pages should export const metadata for SEO.",
                    "If a page needs both metadata AND interactivity, keep the page as a server component "
                    "and extract interactive parts into a client component under src/components/.",
                ],
                "acceptance_checks": [
                    "Frontend owns route modules, page content, and shared UI components.",
                    "Route modules may use legal Next.js exports like metadata and generateMetadata.",
                    "'use client' is line 1 in every file using hooks or event handlers.",
                ],
            },
            {
                "agent_role": "sanitizer",
                "phase": "sanitizer_done",
                "owned_paths": [],
                "allowed_shared_paths": [],
                "depends_on": ["frontend_done"],
                "inputs": {},
                "instructions": [
                    "Run deterministic transforms: directive normalization, import validation, export checks.",
                    "No LLM calls — purely rule-based.",
                ],
                "acceptance_checks": [
                    "'use client' is line 1 wherever needed.",
                    "All imports resolve.",
                    "No server/client mixing in a single file.",
                ],
            },
            {
                "agent_role": "backend",
                "phase": "backend_done",
                "owned_paths": [entry["owned_paths"] for entry in file_ownership if entry["agent_role"] == "backend"][0],
                "allowed_shared_paths": [],
                "depends_on": ["sanitizer_done"],
                "inputs": {
                    "integrations": integrations,
                },
                "instructions": [
                    "Server-only code must stay inside backend-owned paths.",
                    "Do NOT overwrite or modify any frontend-owned files.",
                    f"Integrations to wire: {integrations}" if integrations else
                    "No external integrations required.",
                    "API routes go in src/app/api/<name>/route.ts with named HTTP-method exports.",
                ],
                "acceptance_checks": [
                    "Backend work stays inside server-owned paths and does not overwrite frontend-owned files.",
                ],
            },
            {
                "agent_role": "reviewer",
                "phase": "review_done",
                "owned_paths": [],
                "allowed_shared_paths": [],
                "depends_on": ["backend_done"],
                "inputs": {},
                "instructions": [
                    "Review ALL files for Next.js anti-patterns, broken cross-file references, and accessibility gaps.",
                    "Only fix build-blocking and deploy-blocking issues.",
                ],
                "acceptance_checks": [
                    "No build-blocking anti-patterns remain.",
                    "All cross-file imports resolve.",
                ],
            },
            {
                "agent_role": "verifier",
                "phase": "verify_done",
                "owned_paths": [],
                "allowed_shared_paths": [],
                "depends_on": ["review_done"],
                "inputs": {
                    "deployment_target": plan.get("deploy_target") or context.get("deployment_target"),
                },
                "instructions": [
                    "Run ownership conflict detection, static quality gate, and local npm build preflight.",
                    "Block deploy only on real failures.",
                    f"Expected routes: {routes}",
                ],
                "acceptance_checks": [
                    "Verifier blocks only on real ownership, build, or deploy-preflight failures.",
                ],
            },
        ]
        return {
            "work_packets": work_packets,
            "file_ownership": file_ownership,
            "shared_contracts": [
                {
                    "name": "next_route_module_exports",
                    "description": "Treat route-module exports as module-local, not global singleton exports.",
                },
                {
                    "name": "directive_safety",
                    "description": (
                        "'use client' must be the very first line of any file using React hooks or event handlers. "
                        "It is mutually exclusive with metadata exports."
                    ),
                },
            ],
            "reserved_singletons": reserved_singletons,
            "route_ownership": [{"route": route, "agent_role": "frontend"} for route in routes],
        }

    def _build_ownership_manifest(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
        blueprint: dict[str, Any],
    ) -> dict[str, Any]:
        raw_agent_team = plan.get("agent_team") if isinstance(plan.get("agent_team"), dict) else {}
        manifest = json.loads(json.dumps(raw_agent_team or self._default_agent_team_plan(plan=plan, context=context, blueprint=blueprint)))
        manifest.setdefault("work_packets", [])
        manifest.setdefault("file_ownership", [])
        manifest.setdefault("shared_contracts", [])
        manifest.setdefault("reserved_singletons", [])
        manifest.setdefault("route_ownership", [])

        existing_routes = {str(entry.get("route") or "").strip() for entry in manifest["route_ownership"] if isinstance(entry, dict)}
        for page in blueprint.get("pages") or []:
            if not isinstance(page, dict):
                continue
            slug = str(page.get("slug") or "").strip()
            route = "/" if slug in ("", "home") else f"/{slug.strip('/')}"
            if route not in existing_routes:
                manifest["route_ownership"].append(
                    {
                        "route": route,
                        "agent_role": "frontend",
                        "path": "src/app/page.tsx" if route == "/" else f"src/app/{route.strip('/')}/page.tsx",
                    }
                )
                existing_routes.add(route)
        if "/" not in existing_routes:
            manifest["route_ownership"].append({"route": "/", "agent_role": "frontend", "path": "src/app/page.tsx"})
        return manifest

    @staticmethod
    def _append_agent_result(
        agent_results: Optional[dict[str, Any]],
        *,
        agent_role: str,
        summary: str,
        files: list[GeneratedFile],
        warnings: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        next_results = dict(agent_results or {})
        next_results[agent_role] = {
            "status": "completed",
            "started_at": next_results.get(agent_role, {}).get("started_at") or DeterministicWebExecutor._utc_timestamp(),
            "ended_at": DeterministicWebExecutor._utc_timestamp(),
            "summary": summary,
            "files_produced": [f.path for f in files],
            "warnings": list(warnings or []),
        }
        return next_results

    @staticmethod
    def _match_owned_path(path: str, patterns: list[str]) -> bool:
        return any(fnmatch(path, pattern) for pattern in patterns)

    def _owner_for_path(self, path: str, ownership_manifest: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(ownership_manifest, dict):
            return None
        for entry in ownership_manifest.get("reserved_singletons") or []:
            if isinstance(entry, dict) and fnmatch(path, str(entry.get("path") or "")):
                return str(entry.get("agent_role") or "").strip() or None
        for entry in ownership_manifest.get("file_ownership") or []:
            if not isinstance(entry, dict):
                continue
            patterns = [str(p) for p in (entry.get("owned_paths") or []) if str(p).strip()]
            if self._match_owned_path(path, patterns):
                return str(entry.get("agent_role") or "").strip() or None
        return None

    @staticmethod
    def _normalize_route_path(path: str) -> Optional[str]:
        normalized = str(path or "").strip()
        for prefix in ("src/app/", "app/"):
            if not normalized.startswith(prefix):
                continue
            rel = normalized[len(prefix):]
            if rel == "page.tsx":
                return "/"
            if rel.endswith("/page.tsx"):
                rel = rel[: -len("/page.tsx")]
            elif rel == "route.ts":
                return "/"
            elif rel.endswith("/route.ts"):
                rel = rel[: -len("/route.ts")]
            else:
                return None
            segments = [
                segment for segment in rel.split("/")
                if segment and not segment.startswith("(") and not segment.startswith("@")
            ]
            return "/" + "/".join(segments) if segments else "/"
        return None

    @staticmethod
    def _format_conflict(conflict: dict[str, Any]) -> str:
        conflict_type = str(conflict.get("type") or "").strip()
        if conflict_type == "duplicate_file":
            return f"DUPLICATE_FILE:{conflict.get('path')} ({conflict.get('count')} times)"
        if conflict_type == "reserved_singleton_collision":
            owners = conflict.get("owners") or conflict.get("owner")
            return f"RESERVED_SINGLETON:{conflict.get('path')} owner={json.dumps(owners)}"
        if conflict_type == "duplicate_route":
            return f"DUPLICATE_ROUTE:{conflict.get('route')} paths={json.dumps(conflict.get('paths') or [])}"
        if conflict_type == "route_ownership_conflict":
            return f"ROUTE_OWNERSHIP:{conflict.get('route')} owners={json.dumps(conflict.get('owners') or [])}"
        if conflict_type == "package_fragmentation":
            return f"PACKAGE_FRAGMENTATION:{json.dumps(conflict.get('paths') or [])}"
        return json.dumps(conflict, sort_keys=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    async def execute(
        self,
        plan: dict[str, Any],
        *,
        task_id: str,
        trace_id: Optional[str] = None,
        deployment_target: Optional[str] = None,
    ) -> dict[str, Any]:
        execution_id = f"detexec_{task_id}"
        operations = plan.get("operations")
        if not isinstance(operations, list) or not operations:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Deterministic execution requires non-empty operations.",
                provider="deterministic_executor",
            )

        repo_spec = self._resolve_repo_spec(operations)
        hosting_team_id = self._resolve_vercel_team_id(operations)
        project_name = self._resolve_project_name(operations, repo_spec)
        deploy_branch = self._resolve_deploy_branch(operations, repo_spec.branch)
        deploy_target = "production" if (deployment_target or "").lower() == "production" else "preview"

        steps_completed: list[str] = []
        template_reference = TemplateReference()

        # ── Phase 1: Provision GitHub Repository ──────────────────────
        logger.info(
            "deterministic.executor.phase1_start task_id=%s repo=%s/%s",
            task_id, repo_spec.owner, repo_spec.name,
        )
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS) as gh_client:
            github_installation_token = await self._github_installation_token(gh_client)
            repo = await self._github_provision_repo(gh_client, github_installation_token, repo_spec)
            await self._github_ensure_branch(
                gh_client,
                github_installation_token,
                owner=repo.owner,
                repo=repo.name,
                target_branch=repo_spec.branch,
                default_branch=repo.default_branch,
            )
            template_reference = await self._github_collect_template_reference(
                gh_client,
                github_installation_token,
                owner=repo.owner,
                repo=repo.name,
                ref=repo.default_branch or "main",
            )
        steps_completed.append("provision_repo")
        logger.info(
            "deterministic.executor.phase1_done task_id=%s repo_url=%s",
            task_id, repo.html_url,
        )

        # ── Phase 2a: Architect blueprint ─────────────────────────────
        api_key = (settings.openai_api_key or "").strip()
        context = self._build_project_context(plan, operations)
        model = self._resolve_codegen_model()
        runtime_manifest = BuildManifest()
        runtime_manifest.add_routes([str(r) for r in (context.get("routes") or []) if str(r).strip()])

        logger.info("deterministic.executor.codegen.phase1_architect_start model=%s", model)
        if api_key:
            blueprint = await self._phase1_architect(
                api_key, model, context, plan, operations,
                template_reference=template_reference,
                manifest=runtime_manifest,
            )
        else:
            blueprint = self._default_blueprint(context, operations)
        logger.info(
            "deterministic.executor.codegen.phase1_architect_done pages=%d components=%d",
            len(blueprint.get("pages", [])), len(blueprint.get("shared_components", [])),
        )
        steps_completed.append("architect")
        runtime_manifest = BuildManifest()
        runtime_manifest.add_routes([p.get("slug", "") for p in (blueprint.get("pages") or []) if isinstance(p, dict)])
        ownership_manifest = self._build_ownership_manifest(plan=plan, context=context, blueprint=blueprint)
        work_packets = list(ownership_manifest.get("work_packets") or [])
        agent_results = self._append_agent_result(
            {},
            agent_role="planner",
            summary="Planner completed repository provisioning, blueprint generation, and ownership manifest creation.",
            files=[],
        )

        build_state = {
            "blueprint": blueprint,
            "context": context,
            "repo_info": {
                "owner": repo.owner,
                "name": repo.name,
                "html_url": repo.html_url,
                "default_branch": repo.default_branch,
                "branch": repo_spec.branch,
            },
            "template_reference": {
                "source_repo": template_reference.source_repo,
                "source_branch": template_reference.source_branch,
                "package_json": template_reference.package_json,
                "key_files": template_reference.key_files,
            },
            "config": {
                "task_id": task_id,
                "trace_id": trace_id,
                "deployment_target": deploy_target,
                "hosting_team_id": hosting_team_id,
                "project_name": project_name,
                "deploy_branch": deploy_branch,
                "execution_id": execution_id,
                "plan_json": plan,
                "runtime_manifest": runtime_manifest.to_runtime_json(),
            },
            "work_packets": work_packets,
            "ownership_manifest": ownership_manifest,
            "agent_results": agent_results,
            "verification": None,
            "repair_history": [],
        }

        return {
            "execution_id": execution_id,
            "status": "partial",
            "build_phase": "architect_done",
            "agent_phase": "planner_done",
            "agent_role": "planner",
            "message": "Planner complete: repository provisioned, blueprint generated, and ownership manifest recorded.",
            "artifacts": [{"path": repo.html_url, "type": "repository", "summary": "GitHub repository created."}],
            "steps_completed": steps_completed,
            "repository_url": repo.html_url,
            "files_generated": 0,
            "_build_state": build_state,
        }

    # ------------------------------------------------------------------
    # Phased execution: Foundation
    # ------------------------------------------------------------------
    async def execute_foundation(
        self,
        *,
        blueprint: dict[str, Any],
        context: dict[str, Any],
        template_reference: TemplateReference,
        task_id: str,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> tuple[list[GeneratedFile], dict[str, Any]]:
        """Phase 2: Generate foundation files (configs, layout, shared components)."""
        api_key = (settings.openai_api_key or "").strip()
        model = self._resolve_codegen_model()
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.add_routes([p.get("slug", "") for p in (blueprint.get("pages") or []) if isinstance(p, dict)])

        if not api_key:
            return [], runtime_manifest.to_runtime_json()

        pages = blueprint.get("pages") or []
        shared_components = blueprint.get("shared_components") or []
        design_notes = blueprint.get("design_notes", "")
        color_palette = blueprint.get("color_palette", {})
        content_strategy = blueprint.get("content_strategy", "")
        goal = context.get("goal", "Professional website")
        project_context_str = context.get("context", "")

        max_tokens = getattr(settings, "codegen_phase2_max_tokens", 16000)
        all_files: list[GeneratedFile] = []

        # Split foundation into focused sub-calls for better quality
        # Call 1: Config + Layout + NavBar + Footer
        config_layout_prompt = self._build_config_layout_prompt(
            goal, project_context_str, pages, design_notes, color_palette, content_strategy,
            template_reference=template_reference,
        )
        logger.info("deterministic.executor.codegen.foundation_config_start task_id=%s", task_id)
        config_content = await self._openai_chat(
            api_key, model, self._BUILDER_SYSTEM_PROMPT, config_layout_prompt,
            temperature=0.3, max_tokens=max_tokens,
            manifest=runtime_manifest,
        )
        if config_content:
            config_files = self._parse_codegen_response(config_content, [])
            all_files.extend(config_files)
            runtime_manifest.update_from_files(config_files)
            logger.info("deterministic.executor.codegen.foundation_config_done files=%d", len(config_files))

        # Call 2+: Shared components in batches of 5
        component_batch_size = 5
        component_names = [c for c in shared_components if c not in ("NavBar", "Footer")]
        for batch_start in range(0, len(component_names), component_batch_size):
            batch = component_names[batch_start:batch_start + component_batch_size]
            comp_prompt = self._build_components_prompt(
                goal, project_context_str, batch, design_notes, color_palette, content_strategy,
            )
            logger.info(
                "deterministic.executor.codegen.foundation_components_start task_id=%s batch=%d-%d",
                task_id, batch_start, batch_start + len(batch),
            )
            comp_content = await self._openai_chat(
                api_key, model, self._BUILDER_SYSTEM_PROMPT, comp_prompt,
                temperature=0.3, max_tokens=max_tokens,
                manifest=runtime_manifest,
            )
            if comp_content:
                comp_files = self._parse_codegen_response(comp_content, [])
                all_files.extend(comp_files)
                runtime_manifest.update_from_files(comp_files)
                logger.info(
                    "deterministic.executor.codegen.foundation_components_done batch=%d-%d files=%d",
                    batch_start, batch_start + len(batch), len(comp_files),
                )

        logger.info("deterministic.executor.codegen.foundation_done task_id=%s total_files=%d", task_id, len(all_files))
        return all_files, runtime_manifest.to_runtime_json()

    # ------------------------------------------------------------------
    # Phased execution: Pages
    # ------------------------------------------------------------------
    async def execute_pages(
        self,
        *,
        blueprint: dict[str, Any],
        context: dict[str, Any],
        foundation_files: list[GeneratedFile],
        task_id: str,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> tuple[list[GeneratedFile], dict[str, Any]]:
        """Phase 3: Generate page files in deterministic sequential batches."""
        api_key = (settings.openai_api_key or "").strip()
        model = self._resolve_codegen_model()
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.add_routes([p.get("slug", "") for p in (blueprint.get("pages") or []) if isinstance(p, dict)])
        runtime_manifest.update_from_files(foundation_files)

        if not api_key:
            return foundation_files, runtime_manifest.to_runtime_json()

        pages = blueprint.get("pages") or []
        design_notes = blueprint.get("design_notes", "")
        color_palette = blueprint.get("color_palette", {})
        content_strategy = blueprint.get("content_strategy", "")
        goal = context.get("goal", "Professional website")
        project_context_str = context.get("context", "")

        max_tokens = getattr(settings, "codegen_phase2_max_tokens", 16000)
        batch_size = getattr(settings, "codegen_phase2_batch_size", 3)

        component_signatures = self._extract_component_signatures(foundation_files)
        page_files: list[GeneratedFile] = []

        async def _build_page_batch(batch_start: int, batch: list) -> list[GeneratedFile]:
            page_prompt = self._build_pages_prompt(
                goal, project_context_str, batch, component_signatures,
                design_notes, color_palette, content_strategy,
            )
            page_content = await self._openai_chat(
                api_key, model, self._BUILDER_SYSTEM_PROMPT, page_prompt,
                temperature=0.3, max_tokens=max_tokens,
                manifest=runtime_manifest,
            )
            if page_content:
                pf = self._parse_codegen_response(page_content, [])
                logger.info(
                    "deterministic.executor.codegen.phase_pages batch=%d-%d files=%d",
                    batch_start, batch_start + len(batch), len(pf),
                )
                return pf
            return []

        for i in range(0, len(pages), batch_size):
            batch = pages[i:i + batch_size]
            pf = await _build_page_batch(i, batch)
            runtime_manifest.update_from_files(pf)
            page_files.extend(pf)

        all_files = foundation_files + page_files
        logger.info("deterministic.executor.codegen.pages_done task_id=%s total_files=%d", task_id, len(all_files))
        return all_files, runtime_manifest.to_runtime_json()

    # ------------------------------------------------------------------
    # Phased execution: Frontend agent
    # ------------------------------------------------------------------
    async def execute_frontend(
        self,
        *,
        blueprint: dict[str, Any],
        context: dict[str, Any],
        template_reference: TemplateReference,
        task_id: str,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        foundation_files, runtime_manifest_json = await self.execute_foundation(
            blueprint=blueprint,
            context=context,
            template_reference=template_reference,
            task_id=task_id,
            runtime_manifest_json=runtime_manifest_json,
        )
        all_files, runtime_manifest_json = await self.execute_pages(
            blueprint=blueprint,
            context=context,
            foundation_files=foundation_files,
            task_id=task_id,
            runtime_manifest_json=runtime_manifest_json,
        )
        return {
            "status": "partial",
            "build_phase": _legacy_build_phase("frontend_done"),
            "agent_phase": "frontend_done",
            "agent_role": "frontend",
            "message": f"Frontend agent generated {len(all_files)} site files.",
            "files_generated": len(all_files),
            "files": all_files,
            "runtime_manifest": runtime_manifest_json,
        }

    # ------------------------------------------------------------------
    # Phased execution: Sanitizer (deterministic, no LLM)
    # ------------------------------------------------------------------
    def execute_sanitize(
        self,
        *,
        all_files: list[GeneratedFile],
        blueprint: dict[str, Any],
        template_reference: Optional[TemplateReference] = None,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Deterministic code transforms: directive safety, import/export validation, server/client mixing."""
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.update_from_files(all_files)
        file_map = {f.path: f for f in all_files}
        warnings: list[str] = []

        self._normalize_directive_placement(file_map)
        self._ensure_use_client_directive(file_map)
        self._normalize_directive_placement(file_map)
        self._fix_duplicate_imports(file_map)
        self._validate_component_exports(file_map, warnings)
        self._fix_export_import_mismatches(file_map)
        self._validate_hook_imports(file_map, warnings)
        self._validate_next_imports(file_map, warnings)
        mixing_issues = self._detect_server_client_mixing(file_map)
        warnings.extend(mixing_issues)
        self._fix_missing_standard_imports(file_map)
        self._normalize_directive_placement(file_map)

        sanitized_files = list(file_map.values())
        runtime_manifest.update_from_files(sanitized_files)

        if warnings:
            logger.info(
                "deterministic.executor.sanitizer.warnings count=%d sample=%s",
                len(warnings), warnings[:10],
            )

        return {
            "status": "partial",
            "build_phase": _legacy_build_phase("sanitizer_done"),
            "agent_phase": "sanitizer_done",
            "agent_role": "sanitizer",
            "message": f"Sanitizer applied deterministic fixes to {len(sanitized_files)} files ({len(warnings)} warnings).",
            "files_generated": len(sanitized_files),
            "files": sanitized_files,
            "sanitizer_warnings": warnings,
            "runtime_manifest": runtime_manifest.to_runtime_json(),
        }

    @staticmethod
    def _validate_hook_imports(file_map: dict[str, GeneratedFile], issues: list[str]) -> None:
        """Ensure files using React hooks have the corresponding import from 'react'."""
        import re
        HOOKS = ["useState", "useEffect", "useRef", "useCallback", "useMemo", "useReducer", "useContext"]
        hook_re = re.compile(r"\b(" + "|".join(HOOKS) + r")\b")
        react_import_re = re.compile(r"""from\s+['"]react['"]""")

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            used_hooks = set(hook_re.findall(f.content))
            if not used_hooks:
                continue
            if react_import_re.search(f.content):
                continue
            issues.append(f"missing_react_import:{path}:hooks={','.join(sorted(used_hooks))}")
            import_line = "import { " + ", ".join(sorted(used_hooks)) + ' } from "react";\n'
            content = f.content
            directive_match = re.match(r'^(["\']use client["\'];?\s*\n)', content)
            if directive_match:
                insert_pos = directive_match.end()
                content = content[:insert_pos] + import_line + content[insert_pos:]
            else:
                content = import_line + content
            file_map[path] = GeneratedFile(path=path, content=content)

    @staticmethod
    def _validate_next_imports(file_map: dict[str, GeneratedFile], issues: list[str]) -> None:
        """Ensure files using Next.js components/hooks have proper imports."""
        import re
        NEXT_IMPORTS: list[tuple[str, str, str]] = [
            (r"<Link[\s/>]", "next/link", 'import Link from "next/link";'),
            (r"<Image[\s/>]", "next/image", 'import Image from "next/image";'),
            (r"\buseRouter\b", "next/navigation", 'import { useRouter } from "next/navigation";'),
            (r"\busePathname\b", "next/navigation", 'import { usePathname } from "next/navigation";'),
            (r"\buseSearchParams\b", "next/navigation", 'import { useSearchParams } from "next/navigation";'),
        ]
        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            for pattern, check_pkg, statement in NEXT_IMPORTS:
                if re.search(pattern, f.content) and check_pkg not in f.content:
                    issues.append(f"missing_next_import:{path}:{check_pkg}")

    @staticmethod
    def _detect_server_client_mixing(file_map: dict[str, GeneratedFile]) -> list[str]:
        """Flag files with both 'use client' and metadata exports (mutually exclusive in App Router).

        When mixing is detected, the metadata export is removed since 'use client' takes priority
        for files that already use hooks/handlers.
        """
        import re
        issues: list[str] = []
        METADATA_BLOCK_RE = re.compile(
            r"(?:^|\n)(export\s+const\s+metadata[\s\S]*?^};?\s*$)", re.MULTILINE
        )
        GENERATE_METADATA_RE = re.compile(
            r"(?:^|\n)(export\s+(?:async\s+)?function\s+generateMetadata[\s\S]*?^}\s*$)", re.MULTILINE
        )
        METADATA_IMPORT_RE = re.compile(
            r"^import\s+type\s+\{\s*Metadata\s*\}\s+from\s+['\"]next['\"];?\s*\n?", re.MULTILINE
        )

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            has_directive = '"use client"' in f.content or "'use client'" in f.content
            has_metadata = (
                "export const metadata" in f.content
                or "export function generateMetadata" in f.content
                or "export async function generateMetadata" in f.content
            )
            if has_directive and has_metadata:
                issues.append(f"server_client_mixing:{path}")
                content = f.content
                content = METADATA_BLOCK_RE.sub("", content)
                content = GENERATE_METADATA_RE.sub("", content)
                content = METADATA_IMPORT_RE.sub("", content)
                file_map[path] = GeneratedFile(path=path, content=content.strip() + "\n")
                logger.info(
                    "deterministic.executor.sanitizer.removed_metadata_from_client_component file=%s",
                    path,
                )
        return issues

    # ------------------------------------------------------------------
    # Phased execution: Backend agent
    # ------------------------------------------------------------------
    async def execute_backend(
        self,
        *,
        all_files: list[GeneratedFile],
        plan: dict[str, Any],
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.update_from_files(all_files)
        backend_operations = [
            op for op in (plan.get("operations") or [])
            if isinstance(op, dict) and str(op.get("target") or "").startswith("hosting/")
        ]
        summary = "Backend agent found no server-side file generation requirements."
        if backend_operations:
            summary = "Backend agent recorded deployment and server-side ownership requirements without mutating frontend files."
        return {
            "status": "partial",
            "build_phase": _legacy_build_phase("backend_done"),
            "agent_phase": "backend_done",
            "agent_role": "backend",
            "message": summary,
            "files_generated": len(all_files),
            "files": all_files,
            "runtime_manifest": runtime_manifest.to_runtime_json(),
        }

    # ------------------------------------------------------------------
    # Phased execution: Reviewer (LLM-based code review)
    # ------------------------------------------------------------------
    _REVIEWER_SYSTEM_PROMPT = (
        "You are a senior code reviewer specializing in Next.js App Router, React 19, TypeScript, and Tailwind CSS v4.\n"
        "You receive all generated source files for a website and must identify build-blocking issues.\n\n"
        "CHECK FOR THESE CRITICAL ISSUES:\n"
        "1. DIRECTIVE ERRORS: 'use client' must be the very first line (before all imports) in files using "
        "hooks (useState, useEffect, etc.) or event handlers (onClick, onChange, etc.). "
        "A file CANNOT have both 'use client' and metadata exports.\n"
        "2. IMPORT ERRORS: Every import must resolve — @/ imports map to src/. "
        "Check that imported components actually exist in the file set.\n"
        "3. EXPORT ERRORS: Components must use named exports. "
        "Pages must have a default export function. "
        "No duplicate default exports in a single file.\n"
        "4. TYPE ERRORS: No 'any' casts in component props. Event handler types must be correct.\n"
        "5. ACCESSIBILITY: Every <img>/<Image> must have alt text. "
        "Pages should have a logical heading hierarchy (h1 -> h2 -> h3).\n"
        "6. SEO: Server-rendered pages (no 'use client') should export metadata or generateMetadata.\n\n"
        "OUTPUT FORMAT:\n"
        "First, output a JSON block with your review:\n"
        "```json\n"
        '{"issues": [{"severity": "critical"|"warning", "file": "path", "line_hint": "...", "message": "..."}], '
        '"files_to_fix": ["path1", "path2"]}\n'
        "```\n"
        "Then, output ONLY the fixed files using:\n"
        "===FILE: path/to/file.ext===\n<full corrected content>\n===END_FILE===\n\n"
        "RULES:\n"
        "- Only fix build-blocking (critical) issues. Do NOT change styling or content.\n"
        "- Output the COMPLETE file content for each fix — not just a diff.\n"
        "- If there are no critical issues, output an empty issues array and no files.\n"
    )

    async def execute_review(
        self,
        *,
        all_files: list[GeneratedFile],
        blueprint: dict[str, Any],
        ownership_manifest: Optional[dict[str, Any]] = None,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """LLM-based code review that catches anti-patterns the sanitizer cannot detect."""
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.update_from_files(all_files)
        api_key = (settings.openai_api_key or "").strip()
        model = self._resolve_codegen_model()

        review_report: dict[str, Any] = {
            "status": "passed",
            "issues_found": 0,
            "files_patched": 0,
            "iterations": 0,
        }

        if not api_key:
            review_report["status"] = "skipped"
            return {
                "status": "partial",
                "build_phase": _legacy_build_phase("review_done"),
                "agent_phase": "review_done",
                "agent_role": "reviewer",
                "message": "Reviewer skipped (no API key).",
                "files_generated": len(all_files),
                "files": all_files,
                "review_report": review_report,
                "runtime_manifest": runtime_manifest.to_runtime_json(),
            }

        max_review_iterations = 2
        current_files = list(all_files)

        for iteration in range(max_review_iterations):
            review_report["iterations"] = iteration + 1
            file_summaries = self._build_review_file_summaries(current_files)
            routes = [p.get("slug", "") for p in (blueprint.get("pages") or []) if isinstance(p, dict)]

            user_prompt = (
                f"Review these {len(current_files)} generated files for a website.\n"
                f"Expected routes: {routes}\n\n"
                f"{file_summaries}\n\n"
                "Identify critical (build-blocking) issues and fix them."
            )

            logger.info(
                "deterministic.executor.reviewer.iteration_%d_start file_count=%d",
                iteration + 1, len(current_files),
            )
            content = await self._openai_chat(
                api_key, model, self._REVIEWER_SYSTEM_PROMPT, user_prompt,
                temperature=0.2,
                max_tokens=getattr(settings, "codegen_review_max_tokens", 12000),
                manifest=runtime_manifest,
            )
            if not content:
                break

            issues = self._parse_review_issues(content)
            review_report["issues_found"] = len(issues)
            critical_issues = [i for i in issues if i.get("severity") == "critical"]

            if not critical_issues:
                review_report["status"] = "passed"
                logger.info(
                    "deterministic.executor.reviewer.iteration_%d_clean issues=%d critical=0",
                    iteration + 1, len(issues),
                )
                break

            fixed_files = self._parse_codegen_response(content, [])
            if not fixed_files:
                logger.info(
                    "deterministic.executor.reviewer.iteration_%d_no_fixes critical=%d",
                    iteration + 1, len(critical_issues),
                )
                break

            file_map = {f.path: f for f in current_files}
            patched_count = 0
            for ff in fixed_files:
                if ff.path in file_map:
                    file_map[ff.path] = ff
                    patched_count += 1
            current_files = list(file_map.values())
            runtime_manifest.update_from_files(current_files)
            review_report["files_patched"] = patched_count
            logger.info(
                "deterministic.executor.reviewer.iteration_%d_done critical=%d patched=%d",
                iteration + 1, len(critical_issues), patched_count,
            )

        review_report.setdefault("status", "passed")
        return {
            "status": "partial",
            "build_phase": _legacy_build_phase("review_done"),
            "agent_phase": "review_done",
            "agent_role": "reviewer",
            "message": f"Reviewer completed {review_report['iterations']} iteration(s): "
                       f"{review_report['issues_found']} issues found, "
                       f"{review_report.get('files_patched', 0)} files patched.",
            "files_generated": len(current_files),
            "files": current_files,
            "review_report": review_report,
            "runtime_manifest": runtime_manifest.to_runtime_json(),
        }

    @staticmethod
    def _build_review_file_summaries(files: list[GeneratedFile]) -> str:
        """Build a compact summary of all files for the reviewer prompt."""
        parts: list[str] = []
        for f in sorted(files, key=lambda x: x.path):
            truncated = f.content[:3000]
            if len(f.content) > 3000:
                truncated += f"\n// ... truncated ({len(f.content)} chars total)"
            parts.append(f"===FILE: {f.path}===\n{truncated}\n===END_FILE===")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_review_issues(content: str) -> list[dict[str, Any]]:
        """Extract the JSON issues block from reviewer output."""
        import re
        json_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", content)
        if not json_match:
            json_match = re.search(r"(\{[^{}]*\"issues\"\s*:\s*\[[\s\S]*?\]\s*[^{}]*\})", content)
        if not json_match:
            return []
        try:
            parsed = json.loads(json_match.group(1))
            issues = parsed.get("issues") if isinstance(parsed, dict) else []
            return [i for i in (issues or []) if isinstance(i, dict)]
        except (json.JSONDecodeError, TypeError):
            return []

    # ------------------------------------------------------------------
    # Phased execution: Verifier
    # ------------------------------------------------------------------
    async def execute_verify(
        self,
        *,
        all_files: list[GeneratedFile],
        blueprint: dict[str, Any],
        template_reference: TemplateReference,
        operations: list[dict[str, Any]],
        repo_info: dict[str, Any],
        task_id: str,
        deployment_target: str,
        hosting_team_id: str,
        project_name: str,
        deploy_branch: str,
        ownership_manifest: Optional[dict[str, Any]] = None,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
        repair_history_json: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        execution_id = f"detexec_{task_id}"
        runtime_manifest = BuildManifest.from_runtime_json(runtime_manifest_json)
        runtime_manifest.update_from_files(all_files)
        html_url = repo_info["html_url"]

        logger.info("deterministic.executor.codegen.phase3_inspector_start task_id=%s", task_id)
        if not all_files:
            all_files = self._extract_files_from_operations(operations)
        validated_files, conflicts = self._phase3_inspect(
            all_files,
            blueprint,
            template_reference=template_reference,
            ownership_manifest=ownership_manifest,
        )
        runtime_manifest.update_from_files(validated_files)
        logger.info("deterministic.executor.codegen.phase3_inspector_done task_id=%s files=%d", task_id, len(validated_files))

        verifier_report: dict[str, Any] = {
            "status": "passed",
            "ownership_check": {
                "status": "passed",
                "conflicts_detected": len(conflicts),
            },
            "local_preflight": {"status": "skipped"},
            "deploy_preflight": {"status": "pending"},
            "repair_attempts": 0,
        }
        if conflicts:
            verifier_report["ownership_check"]["conflicts"] = conflicts

        if settings.enable_codegen_deploy_static_gate():
            qmap = {f.path: f for f in validated_files}
            qviol = self._collect_deploy_quality_violations(qmap)
            if qviol:
                logger.warning(
                    "deterministic.executor.deploy_quality_gate.failed task_id=%s violations=%s",
                    task_id, qviol[:12],
                )
                raise DeterministicExecutionError(
                    reason_code=REASON_DEPLOY_QUALITY_GATE_FAILED,
                    message=(
                        "Deploy quality gate blocked commit: fix generated output before shipping. "
                        + "; ".join(qviol[:8])
                    ),
                    provider="openclaw_codegen",
                    extra={
                        "quality_violations": qviol,
                        "verifier_report": {**verifier_report, "status": "blocked"},
                        "ownership_conflicts": conflicts,
                    },
                )

        logger.info("deterministic.executor.vercel_preflight_start task_id=%s", task_id)
        async with httpx.AsyncClient(timeout=VERCEL_TIMEOUT_SECONDS) as vc_client:
            vercel_project = await self._vercel_create_or_resolve_project(
                vc_client,
                team_id=hosting_team_id,
                project_name=project_name,
                github_owner=repo_info["owner"],
                github_repo=repo_info["name"],
                production_branch=deploy_branch,
            )
        verifier_report["deploy_preflight"] = {
            "status": "passed",
            "provider": "vercel",
            "project_name": vercel_project.name,
            "project_id": vercel_project.id,
        }
        logger.info(
            "deterministic.executor.vercel_preflight_done task_id=%s project_id=%s project_name=%s",
            task_id,
            vercel_project.id,
            vercel_project.name,
        )

        api_key = (settings.openai_api_key or "").strip()
        model = self._resolve_codegen_model()
        max_fix_retries = getattr(settings, "codegen_max_fix_retries", 2)
        local_preflight_fix_attempts = 0
        preflight_logs = ""
        repair_history = list(repair_history_json or [])
        seen_failure_signatures: set[str] = set()

        if settings.enable_codegen_local_preflight():
            while True:
                preflight = await self._run_local_preflight(validated_files)
                preflight_logs = preflight.logs
                if preflight.success:
                    verifier_report["local_preflight"] = {"status": "passed"}
                    break
                verifier_report["local_preflight"] = {
                    "status": "failed",
                    "last_error": preflight.logs[:500],
                }
                failure_signature = self._preflight_failure_signature(preflight.logs, validated_files)
                if failure_signature in seen_failure_signatures or local_preflight_fix_attempts >= max_fix_retries or not api_key:
                    verifier_report["status"] = "blocked"
                    verifier_report["repair_attempts"] = local_preflight_fix_attempts
                    return {
                        "execution_id": execution_id,
                        "status": "needs_review",
                        "build_phase": "error",
                        "agent_phase": "verify_done",
                        "agent_role": "verifier",
                        "message": "Verifier blocked finalize after local preflight failed to converge.",
                        "reason_codes": [REASON_CODEGEN_AUTOFIX_STALLED],
                        "repository_url": html_url,
                        "files_generated": len(validated_files),
                        "vercel_ready_state": "SKIPPED_LOCAL_PREFLIGHT_FAILED",
                        "local_preflight_fix_attempts": local_preflight_fix_attempts,
                        "build_logs": preflight_logs,
                        "ownership_conflicts": conflicts,
                        "verifier_report": verifier_report,
                        "repair_history": repair_history,
                        "verification_json": {
                            "verifier_report": verifier_report,
                            "ownership_conflicts": conflicts,
                            "build_logs": preflight_logs,
                            "local_preflight_fix_attempts": local_preflight_fix_attempts,
                            "vercel_project": {"id": vercel_project.id, "name": vercel_project.name},
                        },
                    }
                seen_failure_signatures.add(failure_signature)
                local_preflight_fix_attempts += 1
                repaired_files = await self._auto_fix_build_errors(
                    api_key,
                    model,
                    preflight_logs,
                    validated_files,
                    template_reference=template_reference,
                    manifest=runtime_manifest,
                )
                repaired_paths = sorted(
                    {
                        new_file.path
                        for new_file in repaired_files
                        for old_file in validated_files
                        if new_file.path == old_file.path and new_file.content != old_file.content
                    }
                    | {
                        new_file.path for new_file in repaired_files
                        if new_file.path not in {old_file.path for old_file in validated_files}
                    }
                )
                repair_history.append(
                    {
                        "issue_id": f"local-preflight-{local_preflight_fix_attempts}",
                        "reason": "local_preflight_failure",
                        "files_touched": repaired_paths,
                        "outcome": "applied",
                    }
                )
                validated_files = repaired_files
                runtime_manifest.update_from_files(validated_files)
                quality_after_fix = self._collect_deploy_quality_violations({f.path: f for f in validated_files})
                if quality_after_fix:
                    verifier_report["status"] = "blocked"
                    verifier_report["repair_attempts"] = local_preflight_fix_attempts
                    return {
                        "execution_id": execution_id,
                        "status": "needs_review",
                        "build_phase": "error",
                        "agent_phase": "verify_done",
                        "agent_role": "verifier",
                        "message": "Verifier blocked finalize after scoped repair introduced unresolved static issues.",
                        "reason_codes": [REASON_DEPLOY_QUALITY_GATE_FAILED],
                        "repository_url": html_url,
                        "files_generated": len(validated_files),
                        "vercel_ready_state": "SKIPPED_LOCAL_PREFLIGHT_FAILED",
                        "local_preflight_fix_attempts": local_preflight_fix_attempts,
                        "build_logs": preflight_logs,
                        "ownership_conflicts": conflicts,
                        "verifier_report": {**verifier_report, "quality_violations": quality_after_fix},
                        "repair_history": repair_history,
                        "verification_json": {
                            "verifier_report": {**verifier_report, "quality_violations": quality_after_fix},
                            "ownership_conflicts": conflicts,
                            "build_logs": preflight_logs,
                            "local_preflight_fix_attempts": local_preflight_fix_attempts,
                            "vercel_project": {"id": vercel_project.id, "name": vercel_project.name},
                        },
                    }

        verifier_report["repair_attempts"] = local_preflight_fix_attempts
        return {
            "status": "partial",
            "build_phase": _legacy_build_phase("verify_done"),
            "agent_phase": "verify_done",
            "agent_role": "verifier",
            "message": "Verifier passed ownership, local build, and deploy preflight checks.",
            "files_generated": len(validated_files),
            "files": validated_files,
            "ownership_conflicts": conflicts,
            "verifier_report": verifier_report,
            "repair_history": repair_history,
            "verification_json": {
                "verifier_report": verifier_report,
                "ownership_conflicts": conflicts,
                "build_logs": preflight_logs,
                "local_preflight_fix_attempts": local_preflight_fix_attempts,
                "vercel_project": {"id": vercel_project.id, "name": vercel_project.name},
            },
            "runtime_manifest": runtime_manifest.to_runtime_json(),
        }

    # ------------------------------------------------------------------
    # Phased execution: Commit and deploy
    # ------------------------------------------------------------------
    async def execute_commit_and_deploy(
        self,
        *,
        validated_files: list[GeneratedFile],
        repo_info: dict[str, Any],
        task_id: str,
        trace_id: Optional[str],
        deployment_target: str,
        hosting_team_id: str,
        project_name: str,
        deploy_branch: str,
        verification_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        execution_id = f"detexec_{task_id}"
        owner = repo_info["owner"]
        repo_name = repo_info["name"]
        html_url = repo_info["html_url"]
        branch = repo_info.get("branch", "main")
        deploy_target = "production" if (deployment_target or "").lower() == "production" else "preview"
        verifier_report = dict((verification_json or {}).get("verifier_report") or {})
        ownership_conflicts = list((verification_json or {}).get("ownership_conflicts") or [])
        local_preflight_fix_attempts = int((verification_json or {}).get("local_preflight_fix_attempts") or 0)
        preflight_logs = str((verification_json or {}).get("build_logs") or "")
        verified_project = (verification_json or {}).get("vercel_project") or {}
        project_name = str(verified_project.get("name") or project_name)
        steps_completed: list[str] = ["provision_repo", "architect", "frontend", "backend", "verify"]

        logger.info("deterministic.executor.phase3_start task_id=%s", task_id)
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS) as gh_client:
            github_installation_token = await self._github_installation_token(gh_client)
            commit_sha = await self._github_batch_commit(
                gh_client,
                github_installation_token,
                owner=owner,
                repo=repo_name,
                branch=branch,
                files=validated_files,
                message=f"feat: initial site generation via deterministic_web_v1\n\nTask: {task_id}\nTrace: {trace_id or 'N/A'}",
            )
        steps_completed.append("write_files")
        logger.info("deterministic.executor.phase3_done task_id=%s commit_sha=%s", task_id, commit_sha)

        logger.info("deterministic.executor.phase4_start task_id=%s", task_id)
        async with httpx.AsyncClient(timeout=VERCEL_TIMEOUT_SECONDS) as vc_client:
            steps_completed.append("provision_hosting")
            deployment = await self._vercel_deploy_files(
                vc_client,
                team_id=hosting_team_id,
                project_name=project_name,
                files=validated_files,
                target=deploy_target,
            )
            steps_completed.append("deploy")
            logger.info("deterministic.executor.phase4_deployed task_id=%s deployment_id=%s", task_id, deployment.id)

        deployment_url = self._normalize_deployment_url(deployment.url)
        logger.info("deterministic.executor.phase4_done task_id=%s deployment_url=%s", task_id, deployment_url)

        artifacts = [
            {"path": html_url, "type": "repository", "summary": "GitHub repository created and code committed."},
        ]
        if deployment_url:
            artifacts.append({"path": deployment_url, "type": "deployment", "summary": "Vercel deployment triggered; build in progress."})

        result: dict[str, Any] = {
            "execution_id": execution_id,
            "status": "success",
            "build_phase": "complete",
            "agent_phase": "complete",
            "agent_role": "orchestrator",
            "message": f"Pipeline completed: {len(validated_files)} files verified, committed, and deployment triggered.",
            "artifacts": artifacts,
            "steps_completed": steps_completed,
            "repository_url": html_url,
            "repo_commit_sha": commit_sha,
            "deployment_id": deployment.id,
            "deployment_url": deployment_url,
            "files_generated": len(validated_files),
            "provider_ids": {"vercel_project_id": verified_project.get("id")},
            "vercel_ready_state": "DEPLOYING",
            "fix_attempts": 0,
            "local_preflight_fix_attempts": local_preflight_fix_attempts,
            "build_logs": preflight_logs,
            "verifier_report": verifier_report or None,
            "ownership_conflicts": ownership_conflicts or None,
        }
        if deploy_target == "preview":
            result["preview_url"] = deployment_url
        return result

    # ------------------------------------------------------------------
    # Phased execution: Finalize (compat wrapper)
    # ------------------------------------------------------------------
    async def execute_finalize(
        self,
        *,
        all_files: list[GeneratedFile],
        blueprint: dict[str, Any],
        template_reference: TemplateReference,
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
        repo_info: dict[str, Any],
        task_id: str,
        trace_id: Optional[str],
        deployment_target: str,
        hosting_team_id: str,
        project_name: str,
        deploy_branch: str,
        ownership_manifest: Optional[dict[str, Any]] = None,
        runtime_manifest_json: Optional[dict[str, Any]] = None,
        repair_history_json: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        verify_result = await self.execute_verify(
            all_files=all_files,
            blueprint=blueprint,
            template_reference=template_reference,
            operations=operations,
            repo_info=repo_info,
            task_id=task_id,
            deployment_target=deployment_target,
            hosting_team_id=hosting_team_id,
            project_name=project_name,
            deploy_branch=deploy_branch,
            ownership_manifest=ownership_manifest,
            runtime_manifest_json=runtime_manifest_json,
            repair_history_json=repair_history_json,
        )
        if verify_result.get("status") != "partial":
            return verify_result
        final_result = await self.execute_commit_and_deploy(
            validated_files=list(verify_result.get("files") or []),
            repo_info=repo_info,
            task_id=task_id,
            trace_id=trace_id,
            deployment_target=deployment_target,
            hosting_team_id=hosting_team_id,
            project_name=project_name,
            deploy_branch=deploy_branch,
            verification_json=verify_result.get("verification_json"),
        )
        ownership_conflicts = list(verify_result.get("ownership_conflicts") or [])
        if ownership_conflicts:
            final_result["conflicts_detected"] = len(ownership_conflicts)
            final_result["conflict_samples"] = [self._format_conflict(conflict) for conflict in ownership_conflicts[:20]]
            final_result["ownership_conflicts"] = ownership_conflicts
        if verify_result.get("verifier_report") and not final_result.get("verifier_report"):
            final_result["verifier_report"] = verify_result.get("verifier_report")
        return final_result

    # ------------------------------------------------------------------
    # Operation resolvers
    # ------------------------------------------------------------------
    def _resolve_repo_spec(self, operations: list[dict[str, Any]]) -> RepoSpec:
        app_id = (settings.github_app_id or "").strip()
        private_key = _normalize_private_key(settings.github_private_key or "")
        installation_id = (settings.github_installation_id or "").strip()
        template_owner = (settings.github_template_owner or "").strip()
        template_repo = (settings.github_template_repo or "").strip()
        if not all([app_id, private_key, installation_id]):
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="Missing GitHub App credentials for deterministic execution.",
                provider="github",
            )
        if not all([template_owner, template_repo]):
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Missing GitHub template configuration for deterministic execution.",
                provider="github",
            )

        provision_op = None
        for op in operations:
            if isinstance(op, dict) and str(op.get("type") or "").strip().lower() == "provision_repo":
                provision_op = op
                break
        if provision_op is None:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Deterministic plan is missing provision_repo operation.",
                provider="github",
            )

        inputs = provision_op.get("inputs") if isinstance(provision_op.get("inputs"), dict) else {}
        owner = str(inputs.get("owner") or inputs.get("fallback_owner") or template_owner).strip()
        repo_name = str(
            inputs.get("repo_name")
            or inputs.get("name")
            or inputs.get("project_name")
            or inputs.get("project")
            or ""
        ).strip()
        if not owner or not repo_name:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Deterministic plan is missing repository owner or repository name.",
                provider="github",
            )
        branch = "main"
        visibility = str(inputs.get("visibility") or "public").strip().lower()
        private = visibility == "private"
        return RepoSpec(owner=owner, name=repo_name, branch=branch, private=private)

    def _resolve_vercel_team_id(self, operations: list[dict[str, Any]]) -> str:
        for op in operations:
            if not isinstance(op, dict):
                continue
            op_type = str(op.get("type") or "").strip().lower()
            if op_type not in ("provision_hosting", "deploy"):
                continue
            inputs = op.get("inputs") if isinstance(op.get("inputs"), dict) else {}
            team_id = str(inputs.get("team_id") or "").strip()
            if team_id:
                return team_id
        raise DeterministicExecutionError(
            reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
            message="Deterministic plan is missing Vercel team_id in provision_hosting/deploy inputs.",
            provider="vercel",
        )

    def _resolve_project_name(self, operations: list[dict[str, Any]], repo_spec: RepoSpec) -> str:
        for op in operations:
            if not isinstance(op, dict):
                continue
            if str(op.get("type") or "").strip().lower() != "provision_hosting":
                continue
            inputs = op.get("inputs") if isinstance(op.get("inputs"), dict) else {}
            project_name = str(
                inputs.get("project_name") or inputs.get("project") or inputs.get("linked_repo_name") or ""
            ).strip()
            if project_name:
                return project_name
        return repo_spec.name

    def _resolve_deploy_branch(self, operations: list[dict[str, Any]], default_branch: str) -> str:
        return "main"

    # ------------------------------------------------------------------
    # Phase 2: Three-Phase AI Code Generation
    # ------------------------------------------------------------------
    _PAGE_TYPE_SECTIONS: dict[str, list[str]] = {
        "home": ["hero_gradient", "features_grid", "social_proof", "stats_counter", "testimonials", "cta_banner"],
        "about": ["hero_banner", "company_story", "mission_values", "team_grid", "timeline", "cta_banner"],
        "services": ["hero_banner", "services_grid", "process_steps", "feature_comparison", "cta_banner"],
        "pricing": ["hero_banner", "pricing_tiers", "feature_matrix", "faq_section", "cta_banner"],
        "contact": ["hero_banner", "contact_form", "office_info", "map_placeholder", "social_links"],
        "blog": ["hero_banner", "featured_post", "article_grid", "categories_sidebar", "newsletter_signup"],
        "portfolio": ["hero_banner", "project_grid", "case_study_highlight", "client_logos", "cta_banner"],
        "gallery": ["hero_banner", "image_grid", "lightbox_modal", "category_filter"],
        "faq": ["hero_banner", "faq_accordion", "contact_cta"],
        "testimonials": ["hero_banner", "testimonial_cards", "rating_summary", "cta_banner"],
        "careers": ["hero_banner", "culture_section", "benefits_grid", "open_positions", "application_cta"],
        "features": ["hero_banner", "feature_showcase", "comparison_table", "integration_logos", "cta_banner"],
    }

    def _classify_page_type(self, slug: str) -> str:
        slug_lower = slug.lower().replace("-", "").replace("_", "")
        for key in self._PAGE_TYPE_SECTIONS:
            if key in slug_lower:
                return key
        return "generic"

    def _resolve_codegen_model(self) -> str:
        return (
            getattr(settings, "openai_content_model", None)
            or getattr(settings, "skills_engine_model", None)
            or settings.openai_plan_model
            or "gpt-4o-mini"
        )

    async def _openai_chat(
        self,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 16000,
        manifest: Optional[BuildManifest] = None,
    ) -> Optional[str]:
        effective_user_prompt = user_prompt
        if manifest is not None:
            effective_user_prompt = manifest.prompt_context() + user_prompt
        try:
            async with httpx.AsyncClient(timeout=CODEGEN_TIMEOUT_SECONDS) as client:
                resp, data = await self._request(
                    client, "POST", f"{OPENAI_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    payload={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": effective_user_prompt},
                        ],
                        "temperature": temperature,
                        "max_completion_tokens": max_tokens,
                    },
                )
            if resp.status_code != 200:
                logger.error("deterministic.executor.openai_chat.error status=%s body=%s", resp.status_code, str(data)[:300])
                return None
            if isinstance(data, dict):
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    return choices[0].get("message", {}).get("content", "")
            return None
        except Exception:
            logger.exception("deterministic.executor.openai_chat.exception")
            return None

    async def _generate_code_via_openai(
        self,
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        trace_id: Optional[str] = None,
        template_reference: Optional[TemplateReference] = None,
    ) -> list[GeneratedFile]:
        """Three-phase AI code generation: Architect → Builder → Inspector."""
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            logger.warning("deterministic.executor.codegen.no_api_key falling back to plan content")
            return self._ensure_scaffold_integrity(
                self._extract_files_from_operations(operations),
                template_reference=template_reference,
            )

        context = self._build_project_context(plan, operations)
        model = self._resolve_codegen_model()
        runtime_manifest = BuildManifest()
        runtime_manifest.add_routes([str(r) for r in (context.get("routes") or []) if str(r).strip()])

        # ── Phase 1: Architect ───────────────────────────────────────────
        logger.info("deterministic.executor.codegen.phase1_architect_start model=%s", model)
        blueprint = await self._phase1_architect(
            api_key,
            model,
            context,
            plan,
            operations,
            template_reference=template_reference,
            manifest=runtime_manifest,
        )
        logger.info(
            "deterministic.executor.codegen.phase1_architect_done pages=%d components=%d",
            len(blueprint.get("pages", [])), len(blueprint.get("shared_components", [])),
        )

        # ── Phase 2: Builder ─────────────────────────────────────────────
        logger.info("deterministic.executor.codegen.phase2_builder_start")
        generated_files = await self._phase2_build(
            api_key,
            model,
            blueprint,
            context,
            template_reference=template_reference,
            manifest=runtime_manifest,
        )
        logger.info("deterministic.executor.codegen.phase2_builder_done files=%d", len(generated_files))

        if not generated_files:
            logger.warning("deterministic.executor.codegen.phase2_empty falling back to plan content")
            generated_files = self._extract_files_from_operations(operations)

        # ── Phase 3: Inspector ───────────────────────────────────────────
        logger.info("deterministic.executor.codegen.phase3_inspector_start")
        validated_files, conflicts = self._phase3_inspect(generated_files, blueprint, template_reference=template_reference)
        logger.info("deterministic.executor.codegen.phase3_inspector_done files=%d", len(validated_files))
        if conflicts:
            logger.warning(
                "deterministic.executor.codegen.phase3_conflicts_detected count=%d sample=%s",
                len(conflicts),
                conflicts[:10],
            )

        return validated_files

    # ------------------------------------------------------------------
    # Phase 1: Architect — site blueprint + foundation planning
    # ------------------------------------------------------------------
    async def _phase1_architect(
        self,
        api_key: str,
        model: str,
        context: dict[str, Any],
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        template_reference: Optional[TemplateReference] = None,
        manifest: Optional[BuildManifest] = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are an expert web architect specializing in planning production-quality websites.\n"
            "Given a project brief, you create a detailed site blueprint as JSON.\n\n"
            "Your blueprint must include:\n"
            "1. An expanded page list — add pages the project needs beyond what was requested\n"
            "2. For each page: slug, title, page_type, and a list of sections with descriptions\n"
            "3. A shared_components list — reusable UI components needed across pages\n"
            "4. Design notes — visual direction, color usage, spacing patterns\n"
            "5. Content strategy — tone guidance and key messaging per page\n\n"
            "Page types: home, about, services, pricing, contact, blog, portfolio, gallery, faq, testimonials, careers, features, generic\n\n"
            "Respond with ONLY valid JSON. No markdown, no explanation."
        )

        user_parts: list[str] = ["Create a site blueprint for:\n"]
        if context.get("goal"):
            user_parts.append(f"Project Goal: {context['goal']}")
        if context.get("context"):
            user_parts.append(f"Context: {context['context']}")
        if context.get("routes"):
            user_parts.append(f"Requested Pages: {json.dumps(context['routes'])}")
        if context.get("content_blocks") and isinstance(context["content_blocks"], dict):
            user_parts.append(f"Content Blocks: {json.dumps(dict(list(context['content_blocks'].items())[:15]))}")
        if context.get("acceptance_criteria"):
            user_parts.append(f"Acceptance Criteria: {json.dumps(context['acceptance_criteria'])}")
        if context.get("components"):
            user_parts.append(f"Planned Components: {json.dumps(context['components'][:15])}")

        user_parts.append(
            "\nRespond with JSON matching this schema:\n"
            "{\n"
            '  "pages": [{"slug": "home", "title": "Home", "page_type": "home", '
            '"sections": [{"name": "hero", "description": "Gradient hero with headline and CTA"}], '
            '"content_brief": "Main landing with value proposition"}],\n'
            '  "shared_components": ["NavBar", "Footer", "Hero", "CTABanner", "FeatureCard"],\n'
            '  "design_notes": "Modern SaaS style...",\n'
            '  "color_palette": {"primary": "#2563eb", "secondary": "#7c3aed", "accent": "#f59e0b"},\n'
            '  "content_strategy": "Professional yet approachable tone..."\n'
            "}"
        )

        content = await self._openai_chat(
            api_key, model, system_prompt, "\n".join(user_parts),
            temperature=0.4,
            max_tokens=getattr(settings, "codegen_phase1_max_tokens", 4000),
            manifest=manifest,
        )
        if not content:
            return self._default_blueprint(context, operations)

        blueprint = self._parse_json_response(content)
        if isinstance(blueprint, dict) and "pages" in blueprint:
            return blueprint
        return self._default_blueprint(context, operations)

    def _default_blueprint(self, context: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Fallback blueprint built from plan data without AI."""
        routes = context.get("routes") or []
        pages: list[dict[str, Any]] = []
        for route in routes:
            slug = str(route).strip("/").replace("/", "-") or "home"
            page_type = self._classify_page_type(slug)
            sections = self._PAGE_TYPE_SECTIONS.get(page_type, ["hero_banner", "content_section", "cta_banner"])
            pages.append({
                "slug": slug,
                "title": slug.replace("-", " ").title(),
                "page_type": page_type,
                "sections": [{"name": s, "description": ""} for s in sections],
                "content_brief": "",
            })
        if not pages:
            pages = [{"slug": "home", "title": "Home", "page_type": "home",
                       "sections": [{"name": s, "description": ""} for s in self._PAGE_TYPE_SECTIONS["home"]],
                       "content_brief": ""}]
        return {
            "pages": pages,
            "shared_components": ["NavBar", "Footer", "Hero", "CTABanner", "FeatureCard"],
            "design_notes": "Modern, clean design with gradient accents.",
            "color_palette": {"primary": "#2563eb", "secondary": "#7c3aed", "accent": "#f59e0b"},
            "content_strategy": context.get("goal", "Professional website"),
        }

    @staticmethod
    def _parse_json_response(content: str) -> Any:
        content = content.strip()
        if content.startswith("```"):
            first_nl = content.find("\n")
            if first_nl > 0:
                content = content[first_nl + 1:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end])
                except json.JSONDecodeError:
                    pass
        return None

    # ------------------------------------------------------------------
    # Phase 2: Builder — component + page generation via multiple calls
    # ------------------------------------------------------------------
    _BUILDER_SYSTEM_PROMPT = (
        "You are an expert full-stack web developer specializing in Next.js App Router, React 19, TypeScript, and Tailwind CSS v4.\n"
        "You generate production-quality code: beautiful, responsive, accessible, with REAL content (no Lorem Ipsum).\n\n"
        "DIRECTIVE RULES (BUILD-CRITICAL — violations break the Vercel build):\n"
        "- \"use client\" MUST be the VERY FIRST LINE of any file that uses React hooks "
        "(useState, useEffect, useRef, useCallback, useMemo, useReducer, useContext, "
        "useRouter, usePathname, useSearchParams) or browser event handlers (onClick, onChange, onSubmit, etc.).\n"
        "- NEVER place \"use client\" after import statements — this causes an immediate build failure.\n"
        "- \"use client\" and metadata exports (export const metadata / generateMetadata) are MUTUALLY EXCLUSIVE. "
        "A file CANNOT have both. If a page needs interactivity AND metadata, extract the interactive parts "
        "into a separate client component under src/components/ and import it into the server page.\n"
        "- Server Components (no \"use client\") can import Client Components, but Client Components must NOT "
        "use server-only APIs like cookies() or headers().\n\n"
        "CRITICAL TECHNICAL RULES:\n"
        "- Use Next.js App Router with src/app/ directory structure.\n"
        "- Place shared UI under src/components/ only — NEVER under src/app/components/ (breaks imports and deploy gates).\n"
        "- Tailwind CSS v4: use @import \"tailwindcss\" in globals.css. NO tailwind.config files.\n"
        "- PostCSS: export default { plugins: { \"@tailwindcss/postcss\": {} } };\n"
        "- EVERY component imported MUST be generated. All components use named exports.\n"
        "- ALWAYS import identifiers: Link from next/link, Image from next/image, etc.\n"
        "- INTERNAL navigation (href starting with \"/\", same-site): NEVER use raw <a>. "
        "Use: import Link from \"next/link\"; and <Link href=\"/path\">...</Link>. "
        "External URLs (https://, mailto:, tel:) may use <a> with rel=\"noopener noreferrer\".\n"
        "- Remove unused imports and unused variables so ESLint passes (no-unused-vars).\n"
        "- Avoid default-exporting anonymous objects from lib files; use named exports or: const x = { ... }; export default x;\n"
        "- For MetadataRoute.Robots use lowercase keys: userAgent, allow, disallow, crawlDelay.\n"
        "- Use proper TypeScript types throughout.\n\n"
        "DEPENDENCY RULES (STRICTLY ENFORCED):\n"
        "- You may ONLY use these npm packages: next, react, react-dom, tailwindcss, @tailwindcss/postcss, "
        "clsx, tailwind-merge, class-variance-authority, lucide-react, react-icons, framer-motion, "
        "react-hook-form, zod, @hookform/resolvers, date-fns, slugify, sharp.\n"
        "- Do NOT import or use ANY other npm packages. No axios, no lodash, no styled-components, no moment, no uuid, etc.\n"
        "- If you need functionality not provided by these packages, implement it inline with plain TypeScript.\n"
        "- For HTTP requests use the native fetch API. For unique IDs use crypto.randomUUID().\n\n"
        "QUALITY RULES:\n"
        "- Write marketing-quality copy — compelling headlines, clear value propositions, real testimonials.\n"
        "- Design with visual hierarchy: large hero sections, consistent spacing, readable typography.\n"
        "- Make every page feel complete with 3-6 distinct content sections.\n"
        "- Use Tailwind utility classes for all styling. Use gradients, shadows, rounded corners, hover effects.\n"
        "- Ensure full mobile responsiveness with sm:/md:/lg: breakpoints.\n"
        "- Add smooth transitions and hover states for interactive elements.\n\n"
        "PLANNER INSTRUCTIONS: If the prompt includes a PLANNER INSTRUCTIONS section, follow those "
        "project-specific directions precisely. They contain tailored guidance for this particular site.\n\n"
        "OUTPUT FORMAT: For each file, use EXACTLY:\n"
        "===FILE: path/to/file.ext===\n<content>\n===END_FILE===\n"
    )

    async def _phase2_build(
        self,
        api_key: str,
        model: str,
        blueprint: dict[str, Any],
        context: dict[str, Any],
        *,
        template_reference: Optional[TemplateReference] = None,
        manifest: Optional[BuildManifest] = None,
    ) -> list[GeneratedFile]:
        runtime_manifest = manifest or BuildManifest()
        runtime_manifest.add_routes([p.get("slug", "") for p in (blueprint.get("pages") or []) if isinstance(p, dict)])
        all_files: list[GeneratedFile] = []
        pages = blueprint.get("pages") or []
        shared_components = blueprint.get("shared_components") or []
        design_notes = blueprint.get("design_notes", "")
        color_palette = blueprint.get("color_palette", {})
        content_strategy = blueprint.get("content_strategy", "")
        goal = context.get("goal", "Professional website")
        project_context_str = context.get("context", "")

        max_tokens = getattr(settings, "codegen_phase2_max_tokens", 16000)
        batch_size = getattr(settings, "codegen_phase2_batch_size", 3)

        # ── Call 1: Foundation files + shared components ──────────────────
        foundation_prompt = self._build_foundation_prompt(
            goal, project_context_str, shared_components, pages, design_notes, color_palette, content_strategy,
            template_reference=template_reference,
        )
        foundation_content = await self._openai_chat(
            api_key, model, self._BUILDER_SYSTEM_PROMPT, foundation_prompt,
            temperature=0.3, max_tokens=max_tokens,
            manifest=runtime_manifest,
        )
        if foundation_content:
            foundation_files = self._parse_codegen_response(foundation_content, [])
            all_files.extend(foundation_files)
            runtime_manifest.update_from_files(foundation_files)
            logger.info("deterministic.executor.codegen.phase2_foundation files=%d", len(foundation_files))

        component_signatures = self._extract_component_signatures(all_files)

        # ── Calls 2-N: Pages in sequential batches for cross-turn continuity ──
        async def _build_page_batch(batch_start: int, batch: list) -> list[GeneratedFile]:
            page_prompt = self._build_pages_prompt(
                goal, project_context_str, batch, component_signatures, design_notes, color_palette, content_strategy,
            )
            page_content = await self._openai_chat(
                api_key, model, self._BUILDER_SYSTEM_PROMPT, page_prompt,
                temperature=0.3, max_tokens=max_tokens,
                manifest=runtime_manifest,
            )
            if page_content:
                page_files = self._parse_codegen_response(page_content, [])
                logger.info(
                    "deterministic.executor.codegen.phase2_pages batch=%d-%d files=%d",
                    batch_start, batch_start + len(batch), len(page_files),
                )
                return page_files
            return []

        for i in range(0, len(pages), batch_size):
            page_files = await _build_page_batch(i, pages[i:i + batch_size])
            runtime_manifest.update_from_files(page_files)
            all_files.extend(page_files)

        return all_files

    def _build_foundation_prompt(
        self,
        goal: str,
        project_context: str,
        shared_components: list[str],
        pages: list[dict[str, Any]],
        design_notes: str,
        color_palette: dict[str, str],
        content_strategy: str,
        *,
        template_reference: Optional[TemplateReference] = None,
    ) -> str:
        nav_links = [p.get("title", p.get("slug", "")) for p in pages]
        primary = color_palette.get("primary", "#2563eb")
        secondary = color_palette.get("secondary", "#7c3aed")
        accent = color_palette.get("accent", "#f59e0b")

        parts: list[str] = [
            f"Generate the FOUNDATION files for a website: {goal}\n",
            f"Context: {project_context}" if project_context else "",
            f"Design Direction: {design_notes}" if design_notes else "",
            f"Content Strategy: {content_strategy}" if content_strategy else "",
            f"Colors: primary={primary}, secondary={secondary}, accent={accent}\n",
            f"Navigation Links: {json.dumps(nav_links)}\n",
            "\nGenerate these files:\n",
            "1. package.json — full deps including next, react, react-dom, tailwindcss, @tailwindcss/postcss, typescript, @types/react, @types/node",
            "2. tsconfig.json — with @/* path alias to ./src/*",
            "3. postcss.config.mjs — using @tailwindcss/postcss",
            "4. next.config.ts — minimal Next.js config",
            f"5. src/app/globals.css — @import \"tailwindcss\" + CSS variables for colors: primary={primary}, secondary={secondary}, accent={accent}",
            f"6. src/app/layout.tsx — RootLayout importing NavBar + Footer, metadata with title and description",
        ]

        for comp in shared_components:
            if comp in ("NavBar", "Footer"):
                continue
            slug_lower = comp.lower()
            if "hero" in slug_lower:
                parts.append(f"7. src/components/{comp}.tsx — Reusable hero section with title, subtitle, CTA button props. Gradient background using primary/secondary colors.")
            elif "cta" in slug_lower:
                parts.append(f"8. src/components/{comp}.tsx — Call-to-action banner with headline, description, and button. Use accent color.")
            elif "feature" in slug_lower or "card" in slug_lower:
                parts.append(f"9. src/components/{comp}.tsx — Card component with icon/number, title, description. Hover shadow effect.")
            elif "testimonial" in slug_lower:
                parts.append(f"10. src/components/{comp}.tsx — Testimonial card with quote, author name, role, avatar placeholder.")
            elif "pricing" in slug_lower:
                parts.append(f"11. src/components/{comp}.tsx — Pricing tier card with plan name, price, features list, CTA button. Highlighted tier option.")
            elif "team" in slug_lower:
                parts.append(f"12. src/components/{comp}.tsx — Team member card with photo placeholder, name, role, bio snippet.")
            else:
                parts.append(f"- src/components/{comp}.tsx — Reusable {comp} component with appropriate props.")

        parts.append(
            f"\n13. src/components/NavBar.tsx — Sticky navigation: logo/brand '{goal.split('|')[0].strip()}', "
            f"links for {json.dumps(nav_links)}, mobile hamburger menu, backdrop blur. "
            "Use import Link from \"next/link\" and <Link href=\"/path\"> for internal routes (never <a href=\"/\">).",
        )
        parts.append(
            "14. src/components/Footer.tsx — Multi-column: brand + tagline; use Link for internal page links, <a> only for external URLs.",
        )

        if template_reference and template_reference.source_repo:
            parts.append(f"\nTemplate Reference: {template_reference.source_repo}")

        parts.append("\nRemember: EVERY component must be a named export. Use real, compelling content.")

        return "\n".join(p for p in parts if p)

    def _build_pages_prompt(
        self,
        goal: str,
        project_context: str,
        page_batch: list[dict[str, Any]],
        component_signatures: dict[str, str],
        design_notes: str,
        color_palette: dict[str, str],
        content_strategy: str,
    ) -> str:
        parts: list[str] = [
            f"Generate page files for: {goal}\n",
        ]
        if project_context:
            parts.append(f"Context: {project_context}")
        if content_strategy:
            parts.append(f"Content Strategy: {content_strategy}")
        if design_notes:
            parts.append(f"Design: {design_notes}")

        if component_signatures:
            parts.append("\nAvailable shared components (import from @/components/):")
            for name, sig in component_signatures.items():
                parts.append(f"  - {name}: {sig}")

        parts.append("\nPages to generate:\n")
        for page in page_batch:
            slug = page.get("slug", "")
            title = page.get("title", slug.replace("-", " ").title())
            page_type = page.get("page_type", self._classify_page_type(slug))
            sections = page.get("sections", [])
            brief = page.get("content_brief", "")

            file_path = "src/app/page.tsx" if slug == "home" else f"src/app/{slug}/page.tsx"
            parts.append(f"### {file_path} — {title} ({page_type} page)")

            if brief:
                parts.append(f"   Content Brief: {brief}")

            section_descriptions = self._PAGE_TYPE_SECTIONS.get(page_type, ["hero_banner", "content_section", "cta_banner"])
            if sections:
                section_names = []
                for s in sections:
                    if isinstance(s, dict):
                        desc = s.get("description", "")
                        section_names.append(f"{s.get('name', 'section')}" + (f" — {desc}" if desc else ""))
                    else:
                        section_names.append(str(s))
                parts.append(f"   Sections: {', '.join(section_names)}")
            else:
                parts.append(f"   Sections: {', '.join(section_descriptions)}")

            if page_type == "home":
                parts.append("   REQUIREMENTS: Large gradient hero with compelling headline + subtitle + 2 CTA buttons. Features grid (3-6 cards). Social proof / stats. Testimonials. Final CTA banner.")
            elif page_type == "about":
                parts.append("   REQUIREMENTS: Hero with company name. Founding story section. Mission & values (3+ values with icons). Team grid (4+ members with photo placeholders). Timeline optional.")
            elif page_type == "services":
                parts.append("   REQUIREMENTS: Services grid (3-6 services with icons). Process steps (3-5 numbered steps). Feature comparison or detail expand. CTA to contact.")
            elif page_type == "pricing":
                parts.append("   REQUIREMENTS: 2-3 pricing tiers with highlight on recommended. Feature checklist per tier. Toggle for monthly/annual optional. FAQ section below. 'use client' for interactivity.")
            elif page_type == "contact":
                parts.append("   REQUIREMENTS: Contact form (name, email, phone, message, submit). Office address + hours. Phone/email links. Map placeholder div. 'use client' for form state.")
            elif page_type == "blog":
                parts.append("   REQUIREMENTS: Featured article hero. Article grid (6+ articles with image placeholder, title, excerpt, date, category tag). Categories sidebar or filter.")
            elif page_type == "portfolio":
                parts.append("   REQUIREMENTS: Project grid (6+ projects with image placeholder, title, description, tags). Hover overlay effect. Optional category filter.")
            elif page_type == "faq":
                parts.append("   REQUIREMENTS: Accordion-style Q&A (8+ questions). 'use client' for toggle state. Contact CTA at bottom.")
            elif page_type == "testimonials":
                parts.append("   REQUIREMENTS: Testimonial cards grid (6+ reviews). Star ratings. Author info. Rating summary section. CTA.")
            else:
                parts.append(f"   REQUIREMENTS: Hero banner. 3+ content sections with real content relevant to '{title}'. CTA at bottom.")

            parts.append("")

        parts.append("IMPORTANT: Write compelling, real content (not placeholder text). Each page should have 3-6 sections minimum.")
        parts.append("Use Tailwind CSS for styling. Make pages responsive. Export pages as default exports.")
        parts.append("If a page needs interactivity (forms, toggles, accordions), add 'use client' at the top and use useState.")
        parts.append("For links to other pages on this site use import Link from \"next/link\" and <Link href=\"/slug\"> — never <a href=\"/\"> for internal routes.")

        return "\n".join(parts)

    def _build_config_layout_prompt(
        self,
        goal: str,
        project_context: str,
        pages: list[dict[str, Any]],
        design_notes: str,
        color_palette: dict[str, str],
        content_strategy: str,
        *,
        template_reference: Optional[TemplateReference] = None,
    ) -> str:
        """Prompt for config files + layout + NavBar + Footer (focused call)."""
        nav_links = [p.get("title", p.get("slug", "")) for p in pages]
        primary = color_palette.get("primary", "#2563eb")
        secondary = color_palette.get("secondary", "#7c3aed")
        accent = color_palette.get("accent", "#f59e0b")

        parts: list[str] = [
            f"Generate the CORE STRUCTURE files for a website: {goal}\n",
            f"Context: {project_context}" if project_context else "",
            f"Design Direction: {design_notes}" if design_notes else "",
            f"Content Strategy: {content_strategy}" if content_strategy else "",
            f"Colors: primary={primary}, secondary={secondary}, accent={accent}\n",
            f"Navigation Links: {json.dumps(nav_links)}\n",
            "\nGenerate EXACTLY these files:\n",
            "1. package.json — full deps: next, react, react-dom, tailwindcss, @tailwindcss/postcss, clsx, tailwind-merge, class-variance-authority, lucide-react, framer-motion, typescript, @types/react, @types/node, eslint, eslint-config-next",
            "2. tsconfig.json — with @/* path alias to ./src/*, next plugin, strict mode",
            '3. postcss.config.mjs — export default { plugins: { "@tailwindcss/postcss": {} } }',
            "4. next.config.ts — minimal NextConfig = {}",
            f'5. src/app/globals.css — @import "tailwindcss" + CSS variables for primary={primary}, secondary={secondary}, accent={accent}',
            f"6. src/app/layout.tsx — RootLayout importing NavBar + Footer from @/components, metadata with title related to '{goal}'",
            f"7. src/components/NavBar.tsx — Sticky navigation: logo/brand text, links for {json.dumps(nav_links)}, mobile hamburger menu with useState, backdrop blur. Use 'use client'. "
            "MUST use import Link from \"next/link\" and <Link href=\"/path\"> for every internal route (NOT <a href=\"/\">). Rich implementation with transitions.",
            f"8. src/components/Footer.tsx — Multi-column: brand + tagline, page links (Link for internal, <a> only for external), social placeholders, newsletter signup form, copyright year.",
        ]
        if template_reference and template_reference.source_repo:
            parts.append(f"\nTemplate Reference: {template_reference.source_repo}")
        parts.append("\nCRITICAL: Every component must use NAMED exports. Write thorough, production-quality code with real content.")
        parts.append("Each component should be FULLY implemented — no skeleton/placeholder implementations.")
        return "\n".join(p for p in parts if p)

    def _build_components_prompt(
        self,
        goal: str,
        project_context: str,
        component_names: list[str],
        design_notes: str,
        color_palette: dict[str, str],
        content_strategy: str,
    ) -> str:
        """Prompt for a batch of shared components (focused call)."""
        primary = color_palette.get("primary", "#2563eb")
        secondary = color_palette.get("secondary", "#7c3aed")
        accent = color_palette.get("accent", "#f59e0b")

        parts: list[str] = [
            f"Generate SHARED COMPONENTS for a website: {goal}\n",
            f"Context: {project_context}" if project_context else "",
            f"Design Direction: {design_notes}" if design_notes else "",
            f"Colors: primary={primary}, secondary={secondary}, accent={accent}\n",
            f"\nGenerate these {len(component_names)} component files:\n",
        ]

        for i, comp in enumerate(component_names, 1):
            slug_lower = comp.lower()
            if "hero" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Reusable hero section: title, subtitle, CTA button props. Gradient background primary→secondary. Full-width, min-h-[500px].")
            elif "cta" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Call-to-action banner: headline, description, button. Accent color bg. Centered layout with padding.")
            elif "feature" in slug_lower or "card" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Card component: icon/number prop, title, description. Hover shadow, rounded corners, border.")
            elif "testimonial" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Testimonial card: quote text, author name, role, avatar placeholder. Star rating optional.")
            elif "pricing" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Pricing tier card: plan name, price, features list, CTA button. Highlighted/popular tier option.")
            elif "team" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Team member card: photo placeholder, name, role, bio. Hover effect with social links.")
            elif "form" in slug_lower or "contact" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Form component with labeled inputs, validation states, submit button. 'use client' for useState.")
            elif "faq" in slug_lower or "accordion" in slug_lower:
                parts.append(f"{i}. src/components/{comp}.tsx — Expandable FAQ/accordion: question, answer toggle. 'use client' for state. Smooth transition.")
            else:
                parts.append(f"{i}. src/components/{comp}.tsx — Reusable {comp} component with well-typed props and Tailwind styling.")

        parts.append("\nCRITICAL: Every component must use NAMED exports. Write thorough implementations with real content, not placeholders.")
        parts.append("Use Tailwind CSS for all styling. Make responsive. Add hover/transition effects.")
        parts.append(f"Content Strategy: {content_strategy}" if content_strategy else "")
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _extract_component_signatures(files: list[GeneratedFile]) -> dict[str, str]:
        """Extract component names and their prop signatures from generated files."""
        import re
        signatures: dict[str, str] = {}
        for f in files:
            if not f.path.startswith("src/components/") or not f.path.endswith(".tsx"):
                continue
            name = f.path.rsplit("/", 1)[-1].replace(".tsx", "")
            prop_match = re.search(r"export\s+function\s+\w+\s*\(([^)]*)\)", f.content)
            if prop_match:
                props_str = prop_match.group(1).strip()
                signatures[name] = f"<{name} {props_str} />" if props_str else f"<{name} />"
            else:
                signatures[name] = f"<{name} />"
        return signatures

    # ------------------------------------------------------------------
    # Phase 3: Inspector — validation, auto-fix, polish
    # ------------------------------------------------------------------
    def _phase3_inspect(
        self,
        files: list[GeneratedFile],
        blueprint: dict[str, Any],
        *,
        template_reference: Optional[TemplateReference] = None,
        ownership_manifest: Optional[dict[str, Any]] = None,
    ) -> tuple[list[GeneratedFile], list[dict[str, Any]]]:
        """Validate all generated files and fix issues to guarantee build success."""
        conflicts = self._detect_cross_batch_conflicts(files, ownership_manifest=ownership_manifest)
        if conflicts:
            conflict_samples = [self._format_conflict(conflict) for conflict in conflicts[:12]]
            logger.warning(
                "deterministic.executor.phase3.cross_batch_conflicts count=%d mode=%s sample=%s",
                len(conflicts),
                settings.normalized_codegen_conflict_mode(),
                conflict_samples,
            )
            if settings.normalized_codegen_conflict_mode() == "block":
                verifier_report = {
                    "status": "blocked",
                    "ownership_check": {
                        "status": "failed",
                        "conflicts_detected": len(conflicts),
                        "conflicts": conflicts[:20],
                    },
                }
                raise DeterministicExecutionError(
                    reason_code=REASON_CODEGEN_CONFLICT_DETECTED,
                    message="Cross-batch conflicts detected during deterministic inspection.",
                    provider="openclaw_codegen",
                    extra={
                        "conflicts_detected": len(conflicts),
                        "conflict_samples": [self._format_conflict(conflict) for conflict in conflicts[:20]],
                        "ownership_conflicts": conflicts[:20],
                        "verifier_report": verifier_report,
                    },
                )
        file_map = {f.path: f for f in files}

        issues: list[str] = []

        # Check 1: Ensure every page from blueprint has a file
        for page in blueprint.get("pages", []):
            slug = page.get("slug", "")
            expected = "src/app/page.tsx" if slug == "home" else f"src/app/{slug}/page.tsx"
            if expected not in file_map:
                issues.append(f"missing_page:{expected}")
                page_type = page.get("page_type", self._classify_page_type(slug))
                file_map[expected] = GeneratedFile(
                    path=expected,
                    content=self._generate_fallback_page(slug, page.get("title", slug.title()), page_type),
                )

        # Check 2: Ensure layout.tsx exists
        if "src/app/layout.tsx" not in file_map and "app/layout.tsx" not in file_map:
            issues.append("missing_layout")
            file_map["src/app/layout.tsx"] = GeneratedFile(
                path="src/app/layout.tsx",
                content=self._generate_fallback_layout(blueprint),
            )

        # Check 2b: Root page required for App Router (governed deploy gate + Next build)
        if "src/app/layout.tsx" in file_map and "src/app/page.tsx" not in file_map:
            issues.append("missing_root_page")
            file_map["src/app/page.tsx"] = GeneratedFile(
                path="src/app/page.tsx",
                content=self._generate_fallback_page("home", "Home", "home"),
            )
        elif "app/layout.tsx" in file_map and "app/page.tsx" not in file_map:
            issues.append("missing_root_page")
            file_map["app/page.tsx"] = GeneratedFile(
                path="app/page.tsx",
                content=self._generate_fallback_page("home", "Home", "home"),
            )

        # Check 3: Validate component exports match imports
        self._validate_component_exports(file_map, issues)

        # Check 4: Fix duplicate imports
        self._fix_duplicate_imports(file_map)

        # Check 5: Ensure page metadata exports
        self._ensure_page_metadata(file_map)

        # Check 6: Add SEO files if missing
        self._ensure_seo_files(file_map, blueprint)

        if issues:
            logger.info("deterministic.executor.phase3.issues_found count=%d issues=%s", len(issues), issues[:10])

        # Run existing scaffold integrity (tsconfig, postcss, package.json, globals.css, missing imports, etc.)
        validated = self._ensure_scaffold_integrity(list(file_map.values()), template_reference=template_reference)
        return validated, conflicts

    def _detect_cross_batch_conflicts(
        self,
        files: list[GeneratedFile],
        *,
        ownership_manifest: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Detect real ownership collisions before path dedup hides generation issues."""
        conflicts: list[dict[str, Any]] = []
        if not files:
            return conflicts

        path_counts: dict[str, int] = {}
        for f in files:
            path_counts[f.path] = path_counts.get(f.path, 0) + 1
        for path, count in sorted(path_counts.items()):
            if count > 1:
                owner = self._owner_for_path(path, ownership_manifest)
                reserved_owner = any(
                    fnmatch(path, str(entry.get("path") or ""))
                    for entry in ((ownership_manifest or {}).get("reserved_singletons") or [])
                    if isinstance(entry, dict)
                )
                conflicts.append(
                    {
                        "type": "duplicate_file",
                        "path": path,
                        "count": count,
                        "owner": owner,
                        "message": f"Multiple generated files resolved to the same path '{path}'.",
                    }
                )
                if owner and reserved_owner:
                    conflicts.append(
                        {
                            "type": "reserved_singleton_collision",
                            "path": path,
                            "count": count,
                            "owner": owner,
                            "message": f"Owned path '{path}' was emitted {count} times.",
                        }
                    )

        route_to_paths: dict[str, list[str]] = {}
        for f in files:
            route = self._normalize_route_path(f.path)
            if not route:
                continue
            route_to_paths.setdefault(route, [])
            if f.path not in route_to_paths[route]:
                route_to_paths[route].append(f.path)
        for route, paths in sorted(route_to_paths.items()):
            if len(paths) > 1:
                owner = self._owner_for_path(paths[0], ownership_manifest)
                conflicts.append(
                    {
                        "type": "duplicate_route",
                        "route": route,
                        "paths": paths,
                        "owner": owner,
                        "message": f"Multiple files resolved to route '{route}'.",
                    }
                )

        route_ownership_map: dict[str, set[str]] = {}
        for entry in (ownership_manifest or {}).get("route_ownership") or []:
            if not isinstance(entry, dict):
                continue
            route = str(entry.get("route") or "").strip()
            owner = str(entry.get("agent_role") or "").strip()
            if not route or not owner:
                continue
            route_ownership_map.setdefault(route, set()).add(owner)
        for route, owners in sorted(route_ownership_map.items()):
            if len(owners) > 1:
                conflicts.append(
                    {
                        "type": "route_ownership_conflict",
                        "route": route,
                        "owners": sorted(owners),
                        "message": f"Route '{route}' is assigned to multiple agents.",
                    }
                )

        singleton_owners: dict[str, set[str]] = {}
        for entry in (ownership_manifest or {}).get("reserved_singletons") or []:
            if not isinstance(entry, dict):
                continue
            singleton_path = str(entry.get("path") or "").strip()
            owner = str(entry.get("agent_role") or "").strip()
            if not singleton_path or not owner:
                continue
            singleton_owners.setdefault(singleton_path, set()).add(owner)
        for singleton_path, owners in sorted(singleton_owners.items()):
            if len(owners) > 1:
                conflicts.append(
                    {
                        "type": "reserved_singleton_collision",
                        "path": singleton_path,
                        "owners": sorted(owners),
                        "message": f"Reserved singleton '{singleton_path}' is assigned to multiple agents.",
                    }
                )

        package_paths = sorted({f.path for f in files if f.path.endswith("package.json")})
        if len(package_paths) > 1:
            conflicts.append(
                {
                    "type": "package_fragmentation",
                    "paths": package_paths,
                    "owner": "orchestrator",
                    "message": "Multiple package.json files were generated for one deployment target.",
                }
            )

        return conflicts

    @staticmethod
    def _generate_fallback_page(slug: str, title: str, page_type: str) -> str:
        """Generate a minimal but complete page when the AI didn't produce one."""
        needs_client = page_type in ("contact", "faq", "pricing")
        lines: list[str] = []
        if needs_client:
            lines.append('"use client";\n')
            lines.append('import { useState } from "react";\n')
        lines.append(f"export default function {title.replace(' ', '').replace('-', '')}Page() {{")
        lines.append("  return (")
        lines.append('    <div className="min-h-screen">')
        lines.append(f'      <section className="bg-gradient-to-br from-blue-600 to-purple-700 text-white py-20">')
        lines.append(f'        <div className="max-w-7xl mx-auto px-4 text-center">')
        lines.append(f'          <h1 className="text-4xl md:text-5xl font-bold mb-4">{title}</h1>')
        lines.append(f'          <p className="text-xl opacity-90">Welcome to our {title.lower()} page</p>')
        lines.append("        </div>")
        lines.append("      </section>")
        lines.append('      <section className="py-16">')
        lines.append('        <div className="max-w-7xl mx-auto px-4">')
        lines.append(f'          <h2 className="text-3xl font-bold text-center mb-8">About {title}</h2>')
        lines.append(f'          <p className="text-lg text-gray-600 text-center max-w-3xl mx-auto">')
        lines.append(f"            We are committed to delivering exceptional results. Explore our {title.lower()} to learn more.")
        lines.append("          </p>")
        lines.append("        </div>")
        lines.append("      </section>")
        lines.append("    </div>")
        lines.append("  );")
        lines.append("}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _generate_fallback_layout(blueprint: dict[str, Any]) -> str:
        return (
            'import type { Metadata } from "next";\n'
            'import "./globals.css";\n'
            'import { NavBar } from "@/components/NavBar";\n'
            'import { Footer } from "@/components/Footer";\n\n'
            "export const metadata: Metadata = {\n"
            '  title: "Website",\n'
            '  description: "Generated by OpenClaw",\n'
            "};\n\n"
            "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
            "  return (\n"
            '    <html lang="en">\n'
            '      <body className="min-h-screen flex flex-col">\n'
            "        <NavBar />\n"
            '        <main className="flex-1">{children}</main>\n'
            "        <Footer />\n"
            "      </body>\n"
            "    </html>\n"
            "  );\n"
            "}\n"
        )

    @staticmethod
    def _validate_component_exports(file_map: dict[str, GeneratedFile], issues: list[str]) -> None:
        """Ensure every component file has a matching named export."""
        import re
        for path, f in list(file_map.items()):
            if not path.startswith("src/components/") or not (path.endswith(".tsx") or path.endswith(".ts")):
                continue
            name = path.rsplit("/", 1)[-1].split(".")[0]
            has_named = bool(re.search(rf"export\s+(function|const|class)\s+{re.escape(name)}\b", f.content))
            has_default = "export default" in f.content
            if not has_named and not has_default:
                issues.append(f"no_export:{path}")
                file_map[path] = GeneratedFile(
                    path=path,
                    content=f.content.rstrip() + f"\n\nexport function {name}() {{\n  return <div>{name}</div>;\n}}\n",
                )

    @staticmethod
    def _fix_duplicate_imports(file_map: dict[str, GeneratedFile]) -> None:
        """Remove duplicate import lines from all source files."""
        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".ts") or path.endswith(".jsx") or path.endswith(".js")):
                continue
            lines = f.content.split("\n")
            seen: set[str] = set()
            deduped: list[str] = []
            changed = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import ") and stripped in seen:
                    changed = True
                    continue
                if stripped.startswith("import "):
                    seen.add(stripped)
                deduped.append(line)
            if changed:
                file_map[path] = GeneratedFile(path=path, content="\n".join(deduped))

    @staticmethod
    def _ensure_page_metadata(file_map: dict[str, GeneratedFile]) -> None:
        """Add Metadata export to server-rendered pages that lack it."""
        import re
        for path, f in list(file_map.items()):
            if not path.endswith("/page.tsx"):
                continue
            if '"use client"' in f.content or "'use client'" in f.content:
                continue
            if "export const metadata" in f.content or "export function generateMetadata" in f.content:
                continue
            title_match = re.search(r"<h1[^>]*>([^<]+)</h1>", f.content)
            title = title_match.group(1).strip() if title_match else path.split("/")[-2].replace("-", " ").title()
            metadata_block = (
                'import type { Metadata } from "next";\n\n'
                f"export const metadata: Metadata = {{\n"
                f'  title: "{title}",\n'
                f'  description: "Learn more about {title.lower()}",\n'
                f"}};\n\n"
            )
            if 'from "next"' not in f.content and "from 'next'" not in f.content:
                file_map[path] = GeneratedFile(path=path, content=metadata_block + f.content)
            else:
                meta_line = (
                    f"\nexport const metadata: Metadata = {{\n"
                    f'  title: "{title}",\n'
                    f'  description: "Learn more about {title.lower()}",\n'
                    f"}};\n"
                )
                export_match = re.search(r"^export\s+default\s+function", f.content, re.MULTILINE)
                if export_match:
                    insert_pos = export_match.start()
                    file_map[path] = GeneratedFile(
                        path=path,
                        content=f.content[:insert_pos] + meta_line + "\n" + f.content[insert_pos:],
                    )

    @staticmethod
    def _ensure_seo_files(file_map: dict[str, GeneratedFile], blueprint: dict[str, Any]) -> None:
        """Add sitemap.ts and robots.ts if not present."""
        app_root = "src/app" if any(p.startswith("src/app/") for p in file_map) else "app"

        sitemap_path = f"{app_root}/sitemap.ts"
        if sitemap_path not in file_map:
            pages = blueprint.get("pages", [])
            entries: list[str] = []
            for page in pages:
                slug = page.get("slug", "")
                route = "/" if slug == "home" else f"/{slug}"
                priority = "1.0" if slug == "home" else "0.8"
                entries.append(
                    f"    {{ url: `${{baseUrl}}{route}`, lastModified: new Date(), changeFrequency: 'weekly' as const, priority: {priority} }},"
                )
            file_map[sitemap_path] = GeneratedFile(
                path=sitemap_path,
                content=(
                    'import type { MetadataRoute } from "next";\n\n'
                    "export default function sitemap(): MetadataRoute.Sitemap {\n"
                    '  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://example.com";\n'
                    "  return [\n" + "\n".join(entries) + "\n  ];\n}\n"
                ),
            )

        robots_path = f"{app_root}/robots.ts"
        if robots_path not in file_map:
            file_map[robots_path] = GeneratedFile(
                path=robots_path,
                content=(
                    'import type { MetadataRoute } from "next";\n\n'
                    "export default function robots(): MetadataRoute.Robots {\n"
                    '  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://example.com";\n'
                    "  return {\n"
                    '    rules: { userAgent: "*", allow: "/" },\n'
                    "    sitemap: `${baseUrl}/sitemap.xml`,\n"
                    "  };\n}\n"
                ),
            )

    # ------------------------------------------------------------------
    # Shared helpers for code generation
    # ------------------------------------------------------------------
    def _build_project_context(self, plan: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for key in ("template_family", "scaffold_type", "framework", "routes", "components",
                     "content_blocks", "schema_blocks", "integrations", "deploy_target"):
            if key in plan:
                context[key] = plan[key]
        gp = plan.get("governance_projection")
        if isinstance(gp, dict):
            for key in ("goal", "context", "acceptance_criteria", "deployment_target"):
                if key in gp:
                    context[key] = gp[key]
        return context

    def _parse_codegen_response(self, content: str, file_specs: list[dict[str, str]]) -> list[GeneratedFile]:
        files: list[GeneratedFile] = []
        marker_start = "===FILE:"
        marker_end = "===END_FILE==="

        idx = 0
        while idx < len(content):
            start = content.find(marker_start, idx)
            if start == -1:
                break
            path_end = content.find("===", start + len(marker_start))
            if path_end == -1:
                break
            path = content[start + len(marker_start):path_end].strip()
            file_content_start = path_end + 3
            if content[file_content_start:file_content_start + 1] == "\n":
                file_content_start += 1
            end = content.find(marker_end, file_content_start)
            if end == -1:
                file_content = _strip_markdown_fences(content[file_content_start:])
                files.append(GeneratedFile(path=path, content=file_content))
                break
            file_content = _strip_markdown_fences(content[file_content_start:end])
            files.append(GeneratedFile(path=path, content=file_content))
            idx = end + len(marker_end)

        if not files and file_specs:
            logger.warning(
                "deterministic.executor.codegen.parse_failed specs=%d raw_len=%d",
                len(file_specs), len(content),
            )
        return files

    def _ensure_scaffold_integrity(
        self,
        files: list[GeneratedFile],
        *,
        template_reference: Optional[TemplateReference] = None,
    ) -> list[GeneratedFile]:
        """Validate and fix critical scaffold files to guarantee a buildable project.

        Forces known-good content for tsconfig, postcss, and globals.css.
        Ensures package.json preserves template baseline deps and adds missing ones.
        Strips legacy tailwind config files.
        Fills any missing component files referenced by imports.
        """
        file_map = {f.path: f for f in files}
        self._relocate_misplaced_app_components(file_map)
        uses_src_layout = any(path.startswith("src/") for path in file_map)
        app_root = "src/app" if any(path.startswith("src/app/") for path in file_map) else "app"
        alias_target = "./src/*" if uses_src_layout else "./*"

        # ── tsconfig.json: must have @/* path alias ──────────────────────
        tsconfig_path = "tsconfig.json"
        existing_ts = file_map.get(tsconfig_path)
        if existing_ts:
            try:
                ts = json.loads(existing_ts.content)
                co = ts.setdefault("compilerOptions", {})
                co.setdefault("target", "ES2017")
                co.setdefault("lib", ["dom", "dom.iterable", "esnext"])
                co.setdefault("allowJs", True)
                co.setdefault("skipLibCheck", True)
                co.setdefault("strict", True)
                co.setdefault("noEmit", True)
                co.setdefault("esModuleInterop", True)
                co.setdefault("module", "esnext")
                co.setdefault("moduleResolution", "bundler")
                co.setdefault("resolveJsonModule", True)
                co.setdefault("isolatedModules", True)
                co.setdefault("jsx", "preserve")
                co.setdefault("incremental", True)
                co.setdefault("baseUrl", ".")
                co["paths"] = {"@/*": [alias_target]}
                plugins = co.get("plugins", [])
                if not any(p.get("name") == "next" for p in plugins if isinstance(p, dict)):
                    plugins.append({"name": "next"})
                co["plugins"] = plugins
                ts.setdefault("include", ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"])
                ts.setdefault("exclude", ["node_modules"])
                file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=json.dumps(ts, indent=2) + "\n")
            except (json.JSONDecodeError, TypeError):
                file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=self._tsconfig_fallback(alias_target))
        else:
            file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=self._tsconfig_fallback(alias_target))

        # ── postcss.config.mjs: must use @tailwindcss/postcss ────────────
        file_map["postcss.config.mjs"] = GeneratedFile(
            path="postcss.config.mjs",
            content='export default {\n  plugins: {\n    "@tailwindcss/postcss": {},\n  },\n};\n',
        )

        # ── next.config.ts: always force known-good to prevent build failure ─
        for stale_config in ("next.config.js", "next.config.mjs"):
            file_map.pop(stale_config, None)
        eslint_lines = ""
        if settings.codegen_next_eslint_ignore_during_build:
            eslint_lines = "  eslint: { ignoreDuringBuilds: true },\n"
        file_map["next.config.ts"] = GeneratedFile(
            path="next.config.ts",
            content=(
                'import type { NextConfig } from "next";\n\n'
                "const nextConfig: NextConfig = {\n"
                f"{eslint_lines}"
                "  reactStrictMode: true,\n"
                "};\n\nexport default nextConfig;\n"
            ),
        )

        # ── globals.css: must use @import "tailwindcss" ──────────────────
        globals_path = f"{app_root}/globals.css"
        existing_globals = file_map.get(globals_path)
        if existing_globals:
            content = existing_globals.content
            for d in ("@tailwind base;", "@tailwind components;", "@tailwind utilities;"):
                content = content.replace(d, "")
            if '@import "tailwindcss"' not in content and "@import 'tailwindcss'" not in content:
                content = '@import "tailwindcss";\n\n' + content.strip() + "\n"
            file_map[globals_path] = GeneratedFile(path=globals_path, content=content)
        else:
            file_map[globals_path] = GeneratedFile(
                path=globals_path,
                content='@import "tailwindcss";\n\n:root {\n  --background: #ffffff;\n  --foreground: #171717;\n}\n\nbody {\n  color: var(--foreground);\n  background: var(--background);\n  font-family: Arial, Helvetica, sans-serif;\n}\n',
            )

        # ── package.json: ensure template-aware dependencies ──────────────
        template_pkg = (
            template_reference.package_json
            if template_reference and isinstance(template_reference.package_json, dict)
            else {}
        )
        template_deps = template_pkg.get("dependencies") if isinstance(template_pkg.get("dependencies"), dict) else {}
        template_dev_deps = (
            template_pkg.get("devDependencies") if isinstance(template_pkg.get("devDependencies"), dict) else {}
        )
        template_scripts = template_pkg.get("scripts") if isinstance(template_pkg.get("scripts"), dict) else {}

        REQUIRED_DEPS = {
            "next": "^15.5.14",
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
            "tailwindcss": "^4.2.2",
            "@tailwindcss/postcss": "^4.2.2",
        }
        REQUIRED_DEV_DEPS = {
            "typescript": "^5.8.3",
            "@types/node": "^22",
            "@types/react": "^19",
            "@types/react-dom": "^19",
            "eslint": "^9.39.1",
            "eslint-config-next": str(template_deps.get("next") or template_dev_deps.get("eslint-config-next") or "^15"),
        }

        pkg_path = "package.json"
        existing_pkg = file_map.get(pkg_path)
        pkg: dict[str, Any] = {}
        if existing_pkg:
            try:
                loaded = json.loads(existing_pkg.content)
                if isinstance(loaded, dict):
                    pkg = loaded
            except (json.JSONDecodeError, TypeError):
                pkg = {}
        if not pkg and template_pkg:
            pkg = dict(template_pkg)

        deps = pkg.setdefault("dependencies", {})
        if not isinstance(deps, dict):
            deps = {}
            pkg["dependencies"] = deps
        for k, v in template_deps.items():
            if isinstance(v, str):
                deps.setdefault(k, v)
        for k, v in REQUIRED_DEPS.items():
            deps[k] = v

        dev = pkg.setdefault("devDependencies", {})
        if not isinstance(dev, dict):
            dev = {}
            pkg["devDependencies"] = dev
        for k, v in template_dev_deps.items():
            if isinstance(v, str):
                dev.setdefault(k, v)
        for k, v in REQUIRED_DEV_DEPS.items():
            dev[k] = v

        scripts = pkg.setdefault("scripts", {})
        if not isinstance(scripts, dict):
            scripts = {}
            pkg["scripts"] = scripts
        for k, v in template_scripts.items():
            if isinstance(v, str):
                scripts.setdefault(k, v)
        scripts.setdefault("dev", "next dev")
        scripts.setdefault("build", "next build")
        scripts.setdefault("start", "next start")
        scripts.setdefault("lint", "next lint")

        # ── Strip imports of unapproved packages before augmentation ─────
        self._rewrite_unapproved_imports(file_map, template_reference=template_reference)

        self._augment_package_dependencies_from_imports(
            file_map,
            deps=deps,
            dev_deps=dev,
            template_reference=template_reference,
        )

        # ── Final enforcement: remove any unapproved deps from package.json
        self._enforce_package_allowlist(deps, dev, template_reference=template_reference)
        if settings.codegen_strict_package_pinning_enabled:
            self._pin_approved_package_versions(deps, dev)

        # ── Deduplicate: dev-only packages must not appear in dependencies ─
        for k in REQUIRED_DEV_DEPS:
            deps.pop(k, None)
        for k in list(deps.keys()):
            if k.startswith("@types/") and k in dev:
                del deps[k]

        file_map[pkg_path] = GeneratedFile(path=pkg_path, content=json.dumps(pkg, indent=2) + "\n")

        # ── Remove legacy tailwind config files ──────────────────────────
        for path in ("tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs"):
            file_map.pop(path, None)

        # ── Ensure 'use client' on files using hooks/event handlers ──────
        self._ensure_use_client_directive(file_map)

        # ── Fill missing component imports ────────────────────────────────
        self._fill_missing_component_imports(file_map)

        # ── Fix export/import style mismatches (named vs default) ────────
        self._fix_export_import_mismatches(file_map)

        # ── Ensure barrel index files for directory imports ──────────────
        self._ensure_barrel_exports(file_map)

        # ── Rewrite internal <a href="/..."> to Next.js <Link> (ESLint no-html-link-for-pages)
        self._rewrite_internal_anchors_to_next_link(file_map)

        # ── Auto-fix missing standard imports in all tsx/ts files ────────
        self._fix_missing_standard_imports(file_map)

        # ── Normalize MetadataRoute.Robots key casing ────────────────────
        self._normalize_robots_metadata_keys(file_map)

        # ── Final import graph verification + safety-net stubs ───────────
        self._verify_import_graph(
            file_map,
            strict_bindings=settings.enable_codegen_strict_import_graph(),
        )

        # Second pass: stubs / import fixes may introduce new anchors or pages
        self._rewrite_internal_anchors_to_next_link(file_map)
        self._fix_missing_standard_imports(file_map)

        # Final safety net: ensure "use client" is always line 1 after all transforms
        self._normalize_directive_placement(file_map)

        return list(file_map.values())

    @staticmethod
    def _tsconfig_fallback(alias_target: str) -> str:
        payload = {
            "compilerOptions": {
                "target": "ES2017",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": True,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "baseUrl": ".",
                "paths": {"@/*": [alias_target]},
                "plugins": [{"name": "next"}],
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"],
        }
        return json.dumps(payload, indent=2) + "\n"

    @staticmethod
    def _augment_package_dependencies_from_imports(
        file_map: dict[str, GeneratedFile],
        *,
        deps: dict[str, str],
        dev_deps: dict[str, str],
        template_reference: Optional[TemplateReference] = None,
    ) -> None:
        import re

        import_patterns = [
            re.compile(r"""(?:from|import)\s+["']([^"']+)["']"""),
            re.compile(r"""require\(\s*["']([^"']+)["']\s*\)"""),
            re.compile(r"""import\(\s*["']([^"']+)["']\s*\)"""),
        ]
        builtin_modules = {
            "assert", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram", "dns",
            "domain", "events", "fs", "http", "https", "module", "net", "os", "path", "perf_hooks", "process",
            "querystring", "readline", "stream", "string_decoder", "timers", "tls", "tty", "url", "util", "v8",
            "vm", "worker_threads", "zlib",
        }

        template_versions: dict[str, str] = {}
        if template_reference and isinstance(template_reference.package_json, dict):
            for section in ("dependencies", "devDependencies"):
                bucket = template_reference.package_json.get(section)
                if isinstance(bucket, dict):
                    for k, v in bucket.items():
                        if isinstance(v, str) and v.strip():
                            template_versions[k] = v

        inferred: set[str] = set()
        for f in file_map.values():
            if not (f.path.endswith(".ts") or f.path.endswith(".tsx") or f.path.endswith(".js") or f.path.endswith(".jsx")):
                continue
            for pattern in import_patterns:
                for m in pattern.finditer(f.content):
                    raw_mod = str(m.group(1) or "").strip()
                    if not raw_mod:
                        continue
                    if raw_mod.startswith((".", "/", "@/")) or raw_mod.startswith("node:"):
                        continue
                    if raw_mod.startswith("@"):
                        parts = raw_mod.split("/")
                        if len(parts) < 2:
                            continue
                        pkg_name = "/".join(parts[:2])
                    else:
                        pkg_name = raw_mod.split("/")[0]
                    if (
                        not pkg_name
                        or pkg_name in builtin_modules
                        or pkg_name in {"next", "react", "react-dom"}
                    ):
                        continue
                    inferred.add(pkg_name)

        for pkg_name in sorted(inferred):
            if pkg_name in deps or pkg_name in dev_deps:
                continue
            resolved_version = template_versions.get(pkg_name) or "latest"
            if pkg_name.startswith("@types/"):
                dev_deps[pkg_name] = resolved_version
            else:
                deps[pkg_name] = resolved_version

    @staticmethod
    def _normalize_robots_metadata_keys(file_map: dict[str, GeneratedFile]) -> None:
        import re

        key_map = {
            "UserAgent": "userAgent",
            "Allow": "allow",
            "Disallow": "disallow",
            "CrawlDelay": "crawlDelay",
        }
        robots_paths = [p for p in file_map if p.endswith("/robots.ts") or p == "robots.ts"]
        for path in robots_paths:
            content = file_map[path].content
            updated = content
            for bad, good in key_map.items():
                updated = re.sub(rf'(?m)^(\s*){bad}(\s*:)', rf"\1{good}\2", updated)
                updated = re.sub(rf'(?m)^(\s*)[\'"]{bad}[\'"](\s*:)', rf"\1{good}\2", updated)
            if updated != content:
                file_map[path] = GeneratedFile(path=path, content=updated)
                logger.info("deterministic.executor.scaffold.robots_keys_normalized file=%s", path)

    @staticmethod
    def _parse_package_import(raw_mod: str) -> tuple[str, str]:
        if raw_mod.startswith("@"):
            parts = raw_mod.split("/")
            pkg_name = "/".join(parts[:2]) if len(parts) >= 2 else raw_mod
            subpath = "/".join(parts[2:]) if len(parts) > 2 else ""
            return pkg_name, subpath
        parts = raw_mod.split("/")
        pkg_name = parts[0]
        subpath = "/".join(parts[1:]) if len(parts) > 1 else ""
        return pkg_name, subpath

    @staticmethod
    def _is_allowed_package_import(
        raw_mod: str,
        template_reference: Optional["TemplateReference"] = None,
    ) -> bool:
        template_pkgs: set[str] = set()
        if template_reference and isinstance(template_reference.package_json, dict):
            for section in ("dependencies", "devDependencies"):
                bucket = template_reference.package_json.get(section)
                if isinstance(bucket, dict):
                    template_pkgs.update(bucket.keys())

        pkg_name, subpath = DeterministicWebExecutor._parse_package_import(raw_mod)
        if pkg_name in template_pkgs and pkg_name not in APPROVED_PACKAGES:
            return True
        if pkg_name not in APPROVED_PACKAGES:
            return False

        allowed_subpaths = APPROVED_PACKAGE_SUBPATHS.get(pkg_name)
        if not allowed_subpaths:
            return subpath == ""
        if "*" in allowed_subpaths:
            return True
        return subpath in allowed_subpaths

    @staticmethod
    def _resolve_relative_module(file_map: dict[str, GeneratedFile], current_path: str, source: str) -> str | None:
        if source.startswith("@/"):
            target = source[2:]
            base_candidates = [f"src/{target}", target]
        elif source.startswith("."):
            current_dir = os.path.dirname(current_path)
            normalized = os.path.normpath(os.path.join(current_dir, source)).replace("\\", "/")
            base_candidates = [normalized]
        else:
            return None

        ext_candidates = (".tsx", ".ts", ".jsx", ".js")
        for base in base_candidates:
            for ext in ext_candidates:
                candidate = f"{base}{ext}"
                if candidate in file_map:
                    return candidate
            for index_name in ("index.tsx", "index.ts", "index.jsx", "index.js"):
                candidate = f"{base}/{index_name}"
                if candidate in file_map:
                    return candidate
        return None

    @staticmethod
    def _analyze_exports(
        file_map: dict[str, GeneratedFile],
        path: str,
        visited: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        import re

        if visited is None:
            visited = set()
        if path in visited or path not in file_map:
            return {"named": set(), "has_default": False, "default_identifier": None}
        visited.add(path)

        content = file_map[path].content
        named: set[str] = set()
        has_default = False
        default_identifier: Optional[str] = None

        for regex in (
            re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE),
            re.compile(r"^export\s+const\s+(\w+)", re.MULTILINE),
            re.compile(r"^export\s+class\s+(\w+)", re.MULTILINE),
        ):
            named.update(regex.findall(content))

        m_default_func = re.search(r"^export\s+default\s+function\s+(\w+)", content, re.MULTILINE)
        if m_default_func:
            has_default = True
            default_identifier = m_default_func.group(1)
            named.add(default_identifier)

        m_default_ident = re.search(r"^export\s+default\s+(\w+)\s*;", content, re.MULTILINE)
        if m_default_ident:
            has_default = True
            default_identifier = m_default_ident.group(1)

        export_list_re = re.compile(
            r"^export\s*\{([^}]+)\}\s*(?:from\s+['\"]([^'\"]+)['\"])?",
            re.MULTILINE,
        )
        for match in export_list_re.finditer(content):
            spec_blob = match.group(1)
            reexport_source = match.group(2)
            child_analysis = None
            child_path = None
            if reexport_source:
                child_path = DeterministicWebExecutor._resolve_relative_module(file_map, path, reexport_source)
                if child_path:
                    child_analysis = DeterministicWebExecutor._analyze_exports(file_map, child_path, visited)
            for raw_spec in spec_blob.split(","):
                spec = raw_spec.strip()
                if not spec:
                    continue
                if " as " in spec:
                    local_name, exported_name = [part.strip() for part in spec.split(" as ", 1)]
                else:
                    local_name = exported_name = spec
                if exported_name == "default":
                    has_default = True
                    if local_name == "default" and child_analysis:
                        default_identifier = child_analysis.get("default_identifier")
                    else:
                        default_identifier = local_name
                    continue
                named.add(exported_name)
                if local_name == "default" and child_analysis and child_analysis.get("default_identifier"):
                    named.add(exported_name)

            if child_analysis:
                named.update(child_analysis.get("named", set()))

        export_star_re = re.compile(r"^export\s+\*\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
        for match in export_star_re.finditer(content):
            child_path = DeterministicWebExecutor._resolve_relative_module(file_map, path, match.group(1))
            if not child_path:
                continue
            child_analysis = DeterministicWebExecutor._analyze_exports(file_map, child_path, visited)
            named.update(child_analysis.get("named", set()))

        return {"named": named, "has_default": has_default, "default_identifier": default_identifier}

    @staticmethod
    def _append_named_export_stub(path: str, export_name: str) -> str:
        is_component = path.endswith((".tsx", ".jsx")) or export_name[:1].isupper()
        if is_component:
            return (
                f"\nexport function {export_name}() {{\n"
                f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{export_name}</div>;\n"
                f"}}\n"
            )
        return f"\nexport const {export_name} = null;\n"

    @staticmethod
    def _rewrite_unapproved_imports(
        file_map: dict[str, GeneratedFile],
        template_reference: Optional["TemplateReference"] = None,
    ) -> None:
        """Strip import lines for npm packages not on the approved allowlist.

        Runs before _augment_package_dependencies_from_imports so that the
        augmentation step never sees (and therefore never re-adds) a banned
        package to package.json.
        """
        import re

        builtin_modules = {
            "assert", "buffer", "child_process", "cluster", "console", "constants",
            "crypto", "dgram", "dns", "domain", "events", "fs", "http", "https",
            "module", "net", "os", "path", "perf_hooks", "process", "querystring",
            "readline", "stream", "string_decoder", "timers", "tls", "tty", "url",
            "util", "v8", "vm", "worker_threads", "zlib",
        }

        import_re = re.compile(
            r"""^(?:import\s+.*?\s+from\s+["']([^"']+)["']|import\s+["']([^"']+)["']|.*?require\(\s*["']([^"']+)["']\s*\))"""
        )

        for f in list(file_map.values()):
            if not (f.path.endswith((".ts", ".tsx", ".js", ".jsx"))):
                continue

            new_lines: list[str] = []
            changed = False
            for line in f.content.splitlines(keepends=True):
                m = import_re.match(line.strip())
                if m:
                    raw_mod = (m.group(1) or m.group(2) or m.group(3) or "").strip()
                    if raw_mod and not raw_mod.startswith((".", "/", "@/", "node:")):
                        pkg_name, _ = DeterministicWebExecutor._parse_package_import(raw_mod)

                        if (
                            pkg_name
                            and pkg_name not in builtin_modules
                            and not DeterministicWebExecutor._is_allowed_package_import(raw_mod, template_reference)
                        ):
                            logger.info(
                                "deterministic.executor.allowlist.stripped_import pkg=%s import=%s file=%s",
                                pkg_name, raw_mod, f.path,
                            )
                            new_lines.append(f"// [ALLOWLIST] removed: {line.rstrip()}\n")
                            changed = True
                            continue

                new_lines.append(line)

            if changed:
                file_map[f.path] = GeneratedFile(path=f.path, content="".join(new_lines))

    @staticmethod
    def _enforce_package_allowlist(
        deps: dict[str, str],
        dev_deps: dict[str, str],
        template_reference: Optional["TemplateReference"] = None,
    ) -> None:
        """Remove packages from deps/devDeps that are not on the approved allowlist.

        Runs after _augment_package_dependencies_from_imports to catch anything
        that may have slipped through (e.g. packages the AI added directly to
        its generated package.json).
        """
        template_pkgs: set[str] = set()
        if template_reference and isinstance(template_reference.package_json, dict):
            for section in ("dependencies", "devDependencies"):
                bucket = template_reference.package_json.get(section)
                if isinstance(bucket, dict):
                    template_pkgs.update(bucket.keys())

        allowed = set(APPROVED_PACKAGES.keys()) | template_pkgs

        for label, bucket in (("dependencies", deps), ("devDependencies", dev_deps)):
            to_remove = [k for k in bucket if k not in allowed]
            for k in to_remove:
                logger.info(
                    "deterministic.executor.allowlist.removed_dep section=%s pkg=%s",
                    label, k,
                )
                del bucket[k]

    @staticmethod
    def _pin_approved_package_versions(
        deps: dict[str, str],
        dev_deps: dict[str, str],
    ) -> None:
        """Pin all approved packages currently present to canonical versions."""
        for bucket_name, bucket in (("dependencies", deps), ("devDependencies", dev_deps)):
            for pkg_name in list(bucket.keys()):
                canonical = APPROVED_PACKAGES.get(pkg_name)
                if not canonical:
                    continue
                if bucket.get(pkg_name) != canonical:
                    logger.info(
                        "deterministic.executor.package_pin.updated section=%s pkg=%s from=%s to=%s",
                        bucket_name,
                        pkg_name,
                        bucket.get(pkg_name),
                        canonical,
                    )
                    bucket[pkg_name] = canonical

    @staticmethod
    def _ensure_use_client_directive(file_map: dict[str, GeneratedFile]) -> None:
        """Add 'use client' directive to files that use React hooks or browser event handlers.

        In Next.js App Router, any component using hooks like useState or event
        handlers like onClick must be marked as a Client Component. If the file
        also has a metadata export (server-only), the metadata is removed since
        it's incompatible with 'use client'.
        """
        import re

        CLIENT_HOOK_RE = re.compile(
            r"\b(?:useState|useEffect|useRef|useCallback|useMemo|useReducer|useContext"
            r"|useRouter|usePathname|useSearchParams)\b"
        )
        EVENT_HANDLER_RE = re.compile(
            r"\b(?:onClick|onChange|onSubmit|onFocus|onBlur|onKeyDown|onKeyUp|onMouseEnter|onMouseLeave)\s*="
        )
        METADATA_BLOCK_RE = re.compile(
            r"(?:^|\n)(export\s+const\s+metadata[\s\S]*?^};?\s*$)", re.MULTILINE
        )
        GENERATE_METADATA_RE = re.compile(
            r"(?:^|\n)(export\s+(?:async\s+)?function\s+generateMetadata[\s\S]*?^}\s*$)", re.MULTILINE
        )
        METADATA_IMPORT_RE = re.compile(
            r"^import\s+type\s+\{\s*Metadata\s*\}\s+from\s+['\"]next['\"];?\s*\n?", re.MULTILINE
        )

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            if '"use client"' in f.content or "'use client'" in f.content:
                continue

            needs_client = bool(
                CLIENT_HOOK_RE.search(f.content) or EVENT_HANDLER_RE.search(f.content)
            )
            if not needs_client:
                continue

            content = f.content
            has_metadata = (
                "export const metadata" in content
                or "export function generateMetadata" in content
                or "export async function generateMetadata" in content
            )
            if has_metadata:
                content = METADATA_BLOCK_RE.sub("", content)
                content = GENERATE_METADATA_RE.sub("", content)
                content = METADATA_IMPORT_RE.sub("", content)
                content = content.strip()

            content = '"use client";\n\n' + content
            file_map[path] = GeneratedFile(path=path, content=content)
            logger.info(
                "deterministic.executor.scaffold.use_client_added file=%s had_metadata=%s",
                path, has_metadata,
            )

    @staticmethod
    def _normalize_directive_placement(file_map: dict[str, GeneratedFile]) -> None:
        """Ensure 'use client' directive is always the very first line of the file.

        If the directive appears after import statements (a build-fatal error in
        Next.js App Router), strip it from its current position and re-insert it
        as the first line.
        """
        import re
        DIRECTIVE_RE = re.compile(r"""^[ \t]*(['"]use client['"])\s*;?\s*$""", re.MULTILINE)

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            content = f.content
            first_line = content.split("\n", 1)[0].strip()
            if first_line in ('"use client";', "'use client';", '"use client"', "'use client'"):
                continue
            m = DIRECTIVE_RE.search(content)
            if not m:
                continue
            content_without = content[:m.start()] + content[m.end():]
            content_without = content_without.lstrip("\n")
            content = '"use client";\n\n' + content_without
            file_map[path] = GeneratedFile(path=path, content=content)
            logger.info(
                "deterministic.executor.scaffold.directive_normalized file=%s",
                path,
            )

    @staticmethod
    def _fill_missing_component_imports(file_map: dict[str, GeneratedFile]) -> None:
        """Scan all .tsx/.ts files for @/ imports and create stubs for missing modules.

        Handles both direct file imports (e.g. @/components/Hero) and directory/barrel
        imports (e.g. @/components) by detecting when a directory of files already exists.
        """
        import re
        at_import_re = re.compile(r"""(?:from|import)\s+.*?['"]@/([\w/]+)['"]""")

        needed_paths: set[str] = set()
        for f in file_map.values():
            if not (f.path.endswith(".tsx") or f.path.endswith(".ts") or f.path.endswith(".jsx") or f.path.endswith(".js")):
                continue
            for m in at_import_re.finditer(f.content):
                import_path = m.group(1)
                needed_paths.add(import_path)

        for import_path in needed_paths:
            src_base = f"src/{import_path}"
            candidates = [
                f"{src_base}.tsx", f"{src_base}.ts", f"{src_base}.js",
                f"{src_base}/index.tsx", f"{src_base}/index.ts",
                import_path + ".tsx", import_path + ".ts",
            ]
            if any(c in file_map for c in candidates):
                continue

            dir_prefix = f"src/{import_path}/"
            children = [
                p for p in file_map
                if p.startswith(dir_prefix)
                and "/" not in p[len(dir_prefix):]
                and (p.endswith(".tsx") or p.endswith(".ts") or p.endswith(".js"))
            ]
            if children:
                stub_path = f"src/{import_path}/index.tsx"
                exports: list[str] = []
                for child in sorted(children):
                    name = child.rsplit("/", 1)[-1].split(".")[0]
                    exports.append(f"export * from './{name}';")
                file_map[stub_path] = GeneratedFile(path=stub_path, content="\n".join(exports) + "\n")
                logger.info("deterministic.executor.scaffold.barrel_created path=%s children=%d", stub_path, len(children))
                continue

            parts = import_path.split("/")
            module_name = parts[-1]
            is_component = "component" in import_path.lower() or module_name[0:1].isupper()
            stub_path = f"src/{import_path}.tsx" if is_component else f"src/{import_path}.ts"
            if is_component:
                stub_content = (
                    f"export function {module_name}() {{\n"
                    f"  return (\n"
                    f"    <div className=\"w-full\">\n"
                    f"      <div className=\"max-w-7xl mx-auto px-4 py-6\">\n"
                    f"        <p className=\"text-gray-600\">{module_name}</p>\n"
                    f"      </div>\n"
                    f"    </div>\n"
                    f"  );\n"
                    f"}}\n"
                )
            else:
                stub_content = f"// Auto-generated stub for {import_path}\nexport default {{}};\n"
            file_map[stub_path] = GeneratedFile(path=stub_path, content=stub_content)
            logger.info("deterministic.executor.scaffold.stub_created module=%s path=%s", import_path, stub_path)

    @staticmethod
    def _fix_export_import_mismatches(file_map: dict[str, GeneratedFile]) -> None:
        """Ensure every component file has both named and default exports.

        The AI sometimes generates `export default function Hero()` while
        pages import `{ Hero }` (named), or vice versa.  By guaranteeing
        both export styles exist, imports work regardless of which style
        the consuming page chose.  This also makes `export *` in barrel
        files re-export the component correctly.
        """
        import re

        default_func_re = re.compile(
            r"^export\s+default\s+function\s+(\w+)", re.MULTILINE
        )
        default_const_re = re.compile(
            r"^export\s+default\s+(?:const\s+)?(\w+)\s*;", re.MULTILINE
        )
        named_func_re = re.compile(
            r"^export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE
        )
        named_const_re = re.compile(
            r"^export\s+const\s+(\w+)", re.MULTILINE
        )
        has_default_re = re.compile(
            r"^export\s+default\b", re.MULTILINE
        )

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            if "/components/" not in path and "/Components/" not in path:
                continue
            if path.endswith("index.tsx") or path.endswith("index.ts"):
                continue

            component_name = path.rsplit("/", 1)[-1].split(".")[0]
            content = f.content
            changed = False

            stale_re = re.compile(rf"^export\s*\{{\s*{re.escape(component_name)}\s*\}}\s*;\s*$\n?", re.MULTILINE)
            if stale_re.search(content):
                content = stale_re.sub("", content)
                changed = True

            m_default_func = default_func_re.search(content)
            if m_default_func:
                ai_name = m_default_func.group(1)
                named_pattern = re.compile(
                    rf"^export\s+(?:async\s+)?function\s+{re.escape(ai_name)}\b(?!\s*\()",
                    re.MULTILINE,
                )
                if not named_pattern.search(content.replace(m_default_func.group(0), "")):
                    content = content.replace(
                        m_default_func.group(0),
                        f"export function {ai_name}",
                        1,
                    )
                    content = content.rstrip() + f"\n\nexport default {ai_name};\n"
                    changed = True
            elif has_default_re.search(content):
                named_funcs = named_func_re.findall(content)
                named_consts = named_const_re.findall(content)
                all_named = set(named_funcs) | set(named_consts)
                if component_name in all_named:
                    pass
                elif all_named:
                    pass
                else:
                    m_dc = default_const_re.search(content)
                    if m_dc and m_dc.group(1) != component_name:
                        ai_name = m_dc.group(1)
                        content = content.rstrip() + f"\nexport const {component_name} = {ai_name};\n"
                        changed = True
                    elif m_dc and m_dc.group(1) == component_name:
                        bare_const = re.compile(rf"^(const\s+{re.escape(component_name)}\b)", re.MULTILINE)
                        bare_func = re.compile(rf"^(function\s+{re.escape(component_name)}\b)", re.MULTILINE)
                        if bare_const.search(content):
                            content = bare_const.sub(f"export const {component_name}", content, count=1)
                            changed = True
                        elif bare_func.search(content):
                            content = bare_func.sub(f"export function {component_name}", content, count=1)
                            changed = True
            else:
                named_funcs = named_func_re.findall(content)
                named_consts = named_const_re.findall(content)
                main_export = component_name if component_name in (set(named_funcs) | set(named_consts)) else None
                if not main_export and named_funcs:
                    main_export = named_funcs[0]
                if not main_export and named_consts:
                    main_export = named_consts[0]
                if main_export and not has_default_re.search(content):
                    content = content.rstrip() + f"\n\nexport default {main_export};\n"
                    changed = True

            if changed:
                file_map[path] = GeneratedFile(path=path, content=content)
                logger.info(
                    "deterministic.executor.scaffold.export_fix file=%s component=%s",
                    path, component_name,
                )

    @staticmethod
    def _ensure_barrel_exports(file_map: dict[str, GeneratedFile]) -> None:
        """Ensure directory-style imports have barrel index files that re-export all children.

        Handles the case where an index.tsx already exists but is missing re-exports
        that consumers actually import, and creates new barrels for directories that
        lack them entirely (complementing _fill_missing_component_imports).
        """
        import re
        named_import_re = re.compile(
            r"""import\s+\{([^}]+)\}\s+from\s+['"]@/([\w/]+)['"]"""
        )

        dir_named_imports: dict[str, set[str]] = {}
        for f in file_map.values():
            if not (f.path.endswith(".tsx") or f.path.endswith(".ts")
                    or f.path.endswith(".jsx") or f.path.endswith(".js")):
                continue
            for m in named_import_re.finditer(f.content):
                names = {n.strip() for n in m.group(1).split(",") if n.strip()}
                import_path = m.group(2)
                dir_prefix = f"src/{import_path}/"
                has_children = any(p.startswith(dir_prefix) for p in file_map)
                if has_children:
                    dir_named_imports.setdefault(import_path, set()).update(names)

        for import_path, needed_names in dir_named_imports.items():
            dir_prefix = f"src/{import_path}/"
            index_path = f"{dir_prefix}index.tsx"
            index_path_ts = f"{dir_prefix}index.ts"

            children = sorted(
                p for p in file_map
                if p.startswith(dir_prefix)
                and "/" not in p[len(dir_prefix):]
                and p not in (index_path, index_path_ts)
                and (p.endswith(".tsx") or p.endswith(".ts") or p.endswith(".js"))
            )

            existing_index = file_map.get(index_path) or file_map.get(index_path_ts)

            if existing_index:
                missing = []
                for name in sorted(needed_names):
                    export_patterns = [
                        rf"export\s+.*\b{re.escape(name)}\b",
                        rf"as\s+{re.escape(name)}\b",
                    ]
                    if not any(re.search(p, existing_index.content) for p in export_patterns):
                        missing.append(name)
                if missing:
                    child_names = {
                        p.rsplit("/", 1)[-1].split(".")[0] for p in children
                    }
                    extra_lines: list[str] = []
                    for name in missing:
                        if name in child_names:
                            extra_lines.append(f"export * from './{name}';")
                        else:
                            child_stub_path = f"{dir_prefix}{name}.tsx"
                            if child_stub_path not in file_map:
                                file_map[child_stub_path] = GeneratedFile(
                                    path=child_stub_path,
                                    content=(
                                        f'"use client";\n\n'
                                        f"export function {name}() {{\n"
                                        f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{name}</div>;\n"
                                        f"}}\n"
                                    ),
                                )
                            extra_lines.append(f"export * from './{name}';")
                    if extra_lines:
                        actual_path = index_path if index_path in file_map else index_path_ts
                        updated = existing_index.content.rstrip() + "\n" + "\n".join(extra_lines) + "\n"
                        file_map[actual_path] = GeneratedFile(path=actual_path, content=updated)
                        logger.info(
                            "deterministic.executor.scaffold.barrel_augmented path=%s added=%s",
                            actual_path, missing,
                        )
            elif children:
                exports_lines: list[str] = []
                for child in children:
                    name = child.rsplit("/", 1)[-1].split(".")[0]
                    exports_lines.append(f"export * from './{name}';")
                file_map[index_path] = GeneratedFile(
                    path=index_path, content="\n".join(exports_lines) + "\n"
                )
                logger.info(
                    "deterministic.executor.scaffold.barrel_created path=%s children=%d",
                    index_path, len(children),
                )

    @staticmethod
    def _verify_import_graph(
        file_map: dict[str, GeneratedFile],
        *,
        strict_bindings: bool = False,
    ) -> None:
        """Final validation pass: verify all @/ imports resolve and create safety-net stubs.

        Runs after all other fix-up passes. For any import that still cannot be
        resolved to a file in file_map, creates a minimal stub so the build doesn't
        fail with 'Module not found'.
        """
        import re
        named_import_re = re.compile(r"""import\s+\{([^}]*)\}\s+from\s+['"]@/([\w/]+)['"]""")
        default_and_named_import_re = re.compile(
            r"""import\s+(\w+)\s*,\s*\{([^}]*)\}\s+from\s+['"]@/([\w/]+)['"]"""
        )
        default_import_re = re.compile(r"""import\s+(\w+)\s+from\s+['"]@/([\w/]+)['"]""")

        _EXT_CANDIDATES = (".tsx", ".ts", ".js", ".jsx")

        def _resolve(import_path: str) -> str | None:
            src_base = f"src/{import_path}"
            for ext in _EXT_CANDIDATES:
                if f"{src_base}{ext}" in file_map:
                    return f"{src_base}{ext}"
            for idx in ("index.tsx", "index.ts"):
                if f"{src_base}/{idx}" in file_map:
                    return f"{src_base}/{idx}"
            for ext in _EXT_CANDIDATES:
                if f"{import_path}{ext}" in file_map:
                    return f"{import_path}{ext}"
            return None

        requests: dict[str, dict[str, Any]] = {}

        def _record(import_path: str, *, named: set[str], wants_default: bool) -> None:
            bucket = requests.setdefault(import_path, {"named": set(), "default": False})
            bucket["named"].update(named)
            bucket["default"] = bucket["default"] or wants_default

        for f in file_map.values():
            if not any(f.path.endswith(ext) for ext in _EXT_CANDIDATES):
                continue
            for m in default_and_named_import_re.finditer(f.content):
                names = {
                    n.strip().split(" as ")[-1].strip()
                    for n in m.group(2).split(",")
                    if n.strip()
                }
                _record(m.group(3), named=names, wants_default=True)
            for m in named_import_re.finditer(f.content):
                names = {
                    n.strip().split(" as ")[-1].strip()
                    for n in m.group(1).split(",")
                    if n.strip()
                }
                _record(m.group(2), named=names, wants_default=False)
            for m in default_import_re.finditer(f.content):
                if default_and_named_import_re.search(m.group(0)):
                    continue
                _record(m.group(2), named=set(), wants_default=True)

        for import_path, request in requests.items():
            names = set(request["named"])
            wants_default = bool(request["default"])
            resolved = _resolve(import_path)
            if resolved is not None and strict_bindings:
                export_info = DeterministicWebExecutor._analyze_exports(file_map, resolved)
                updates: list[str] = []
                basename = resolved.rsplit("/", 1)[-1].split(".")[0]
                is_component = resolved.endswith((".tsx", ".jsx")) or basename[:1].isupper()
                is_barrel = basename == "index"

                if wants_default and not export_info["has_default"]:
                    candidate = export_info["default_identifier"]
                    if not candidate:
                        if basename != "index" and basename in export_info["named"]:
                            candidate = basename
                        elif export_info["named"]:
                            candidate = sorted(export_info["named"])[0]
                    if candidate:
                        updates.append(f"\nexport default {candidate};\n")
                    elif is_component:
                        component_name = basename if basename != "index" else "ModuleDefault"
                        updates.append(
                            f"\nexport function {component_name}() {{\n"
                            f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{component_name}</div>;\n"
                            f"}}\n"
                            f"\nexport default {component_name};\n"
                        )
                    else:
                        updates.append("\nconst moduleDefault = {};\nexport default moduleDefault;\n")

                missing_named = sorted(name for name in names if name not in export_info["named"])
                for missing in missing_named:
                    if is_barrel:
                        dir_prefix = resolved.rsplit("/", 1)[0]
                        child_base = f"{dir_prefix}/{missing}"
                        child_path = None
                        for ext in _EXT_CANDIDATES:
                            if f"{child_base}{ext}" in file_map:
                                child_path = f"{child_base}{ext}"
                                break
                        if child_path is None:
                            child_path = f"{child_base}.tsx"
                            file_map[child_path] = GeneratedFile(
                                path=child_path,
                                content=DeterministicWebExecutor._append_named_export_stub(child_path, missing),
                            )
                        export_line = f"export * from './{missing}';"
                        if export_line not in file_map[resolved].content and export_line not in "".join(updates):
                            updates.append("\n" + export_line + "\n")
                        continue

                    default_identifier = export_info.get("default_identifier")
                    if default_identifier:
                        updates.append(f"\nexport const {missing} = {default_identifier};\n")
                    else:
                        updates.append(DeterministicWebExecutor._append_named_export_stub(resolved, missing))

                if updates:
                    file_map[resolved] = GeneratedFile(
                        path=resolved,
                        content=file_map[resolved].content.rstrip() + "".join(updates),
                    )
                    logger.info(
                        "verify_import_graph.repaired_bindings module=%s path=%s default=%s named=%s",
                        import_path, resolved, wants_default, missing_named,
                    )
                continue
            if resolved is not None:
                continue

            parts = import_path.split("/")
            module_name = parts[-1]
            is_component = "component" in import_path.lower() or module_name[0:1].isupper()
            stub_path = f"src/{import_path}.tsx" if is_component else f"src/{import_path}.ts"

            if stub_path in file_map:
                logger.info(
                    "verify_import_graph.skip_existing module=%s path=%s",
                    import_path, stub_path,
                )
                continue

            if names and is_component:
                lines: list[str] = []
                for name in sorted(names):
                    lines.append(
                        f"export function {name}() {{\n"
                        f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{name}</div>;\n"
                        f"}}"
                    )
                stub_content = "\n\n".join(lines) + "\n"
            elif is_component:
                stub_content = (
                    f"export function {module_name}() {{\n"
                    f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{module_name}</div>;\n"
                    f"}}\n"
                )
            else:
                exports = " ".join(f"{n}: null," for n in sorted(names)) if names else ""
                stub_content = f"// Auto-generated safety-net stub\nexport default {{{exports}}};\n"
                if names:
                    for n in sorted(names):
                        stub_content += f"export const {n} = null;\n"

            file_map[stub_path] = GeneratedFile(path=stub_path, content=stub_content)
            logger.warning(
                "verify_import_graph.unresolved_stub_created module=%s names=%s path=%s",
                import_path, sorted(names) if names else "default", stub_path,
            )

    @staticmethod
    def _relocate_misplaced_app_components(file_map: dict[str, GeneratedFile]) -> None:
        """Move src/app/components/* to src/components/* and fix @/app/components imports."""
        wrong_prefix = "src/app/components/"
        right_prefix = "src/components/"
        for path in list(file_map.keys()):
            if not path.startswith(wrong_prefix):
                continue
            if not path.endswith((".tsx", ".ts", ".jsx")):
                continue
            rest = path[len(wrong_prefix) :]
            canonical = right_prefix + rest
            gf = file_map.pop(path)
            if canonical in file_map:
                logger.warning(
                    "deterministic.executor.scaffold.drop_duplicate_wrong_path kept=%s dropped=%s",
                    canonical, path,
                )
                continue
            file_map[canonical] = gf
            logger.info("deterministic.executor.scaffold.relocate_component %s -> %s", path, canonical)
        for p, f in list(file_map.items()):
            if not p.endswith((".tsx", ".ts", ".jsx", ".css", ".mjs")):
                continue
            c = f.content
            c2 = (
                c.replace("@/app/components/", "@/components/")
                .replace("'@/app/components/", "'@/components/")
                .replace('"@/app/components/', '"@/components/')
            )
            if c2 != c:
                file_map[p] = GeneratedFile(path=p, content=c2)

    @staticmethod
    def _collect_deploy_quality_violations(file_map: dict[str, GeneratedFile]) -> list[str]:
        """Static checks that correlate with Vercel next build / ESLint (no npm required)."""
        import re

        violations: list[str] = []
        paths = set(file_map.keys())
        if "src/app/layout.tsx" not in paths and "app/layout.tsx" not in paths:
            violations.append("missing_root_layout")
        if "src/app/page.tsx" not in paths and "app/page.tsx" not in paths:
            violations.append("missing_root_page")
        internal_a = re.compile(
            r"<a(?:\s[^>]*?)\bhref\s*=\s*(?:"
            r'(["\'])((?:/[^/"\'?#][^"\'?#]*|/))\1'
            r"|"
            r'\{\s*(["\'])((?:/[^/"\'?#][^"\'?#]*|/))\3\s*\}'
            r")",
            re.IGNORECASE,
        )
        directive_after_import_re = re.compile(
            r"^import\s+", re.MULTILINE
        )
        misplaced_directive_re = re.compile(
            r"""^[ \t]*['"]use client['"];?\s*$""", re.MULTILINE
        )
        server_client_mix_re = re.compile(
            r"\bexport\s+(?:const\s+metadata|(?:async\s+)?function\s+generateMetadata)\b"
        )
        for path, f in file_map.items():
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            norm = path.replace("\\", "/").lstrip("./")
            if not (norm.startswith("src/") or norm.startswith("app/")):
                continue
            if internal_a.search(f.content):
                violations.append(f"internal_html_link:{path}")
            first_import = directive_after_import_re.search(f.content)
            directive_match = misplaced_directive_re.search(f.content)
            if first_import and directive_match and first_import.start() < directive_match.start():
                violations.append(f"directive_after_import:{path}")
            if directive_match and server_client_mix_re.search(f.content):
                violations.append(f"server_client_mixing:{path}")
        pkg = file_map.get("package.json")
        if not pkg:
            violations.append("missing_package_json")
        else:
            try:
                data = json.loads(pkg.content)
                if not isinstance(data, dict) or not str(data.get("name", "")).strip():
                    violations.append("invalid_package_json_name")
            except (json.JSONDecodeError, TypeError):
                violations.append("invalid_package_json_parse")
        return violations

    @staticmethod
    def _rewrite_internal_anchors_to_next_link(file_map: dict[str, GeneratedFile]) -> None:
        """Replace <a href=\"/...\">...</a> with <Link> for same-site routes (Next.js ESLint rule)."""
        import re

        pattern = re.compile(
            r"<a(?P<before>\s[^>]*?)\bhref\s*=\s*(?:"
            r'(?P<quote>["\'])(?P<href_q>(?:/[^/"\'?#][^"\'?#]*|/))(?P=quote)'
            r"|"
            r'\{\s*(?P<expr_quote>["\'])(?P<href_expr>(?:/[^/"\'?#][^"\'?#]*|/))(?P=expr_quote)\s*\}'
            r")(?P<after>[^>]*?)>(?P<body>.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            normalized = path.replace("\\", "/").lstrip("./")
            if not (normalized.startswith("src/") or normalized.startswith("app/")):
                continue
            new_content = f.content
            safety = 0
            while safety < 500:
                safety += 1
                m = pattern.search(new_content)
                if not m:
                    break
                href = m.group("href_q") or m.group("href_expr") or "/"
                repl = (
                    f"<Link{m.group('before')}href=\"{href}\""
                    f"{m.group('after')}>{m.group('body')}</Link>"
                )
                new_content = new_content[: m.start()] + repl + new_content[m.end() :]
            if new_content != f.content:
                file_map[path] = GeneratedFile(path=path, content=new_content)
                logger.info("deterministic.executor.scaffold.rewrite_internal_links file=%s", path)

    @staticmethod
    def _fix_missing_standard_imports(file_map: dict[str, GeneratedFile]) -> None:
        """Detect common Next.js/React identifiers used without imports and prepend them."""
        import re

        IMPORT_RULES: list[tuple[str, str, str]] = [
            # (identifier_pattern, import_check_string, import_statement)
            (r"<Link[\s/>]", "from \"next/link\"", "import Link from \"next/link\";"),
            (r"<Link[\s/>]", "from 'next/link'", "import Link from \"next/link\";"),
            (r"<Image[\s/>]", "from \"next/image\"", "import Image from \"next/image\";"),
            (r"<Image[\s/>]", "from 'next/image'", "import Image from \"next/image\";"),
            (r"\buseRouter\b", "from \"next/navigation\"", "import { useRouter } from \"next/navigation\";"),
            (r"\buseRouter\b", "from 'next/navigation'", "import { useRouter } from \"next/navigation\";"),
            (r"\busePathname\b", "from \"next/navigation\"", "import { usePathname } from \"next/navigation\";"),
            (r"\busePathname\b", "from 'next/navigation'", "import { usePathname } from \"next/navigation\";"),
            (r"\buseSearchParams\b", "from \"next/navigation\"", "import { useSearchParams } from \"next/navigation\";"),
            (r"\buseSearchParams\b", "from 'next/navigation'", "import { useSearchParams } from \"next/navigation\";"),
        ]

        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            imports_to_add: list[str] = []
            seen_imports: set[str] = set()
            for pattern, check, statement in IMPORT_RULES:
                if statement in seen_imports:
                    continue
                if re.search(pattern, f.content) and check not in f.content:
                    partner_check = check.replace('"', "'") if '"' in check else check.replace("'", '"')
                    if partner_check in f.content:
                        continue
                    imports_to_add.append(statement)
                    seen_imports.add(statement)
            if imports_to_add:
                prefix = "\n".join(imports_to_add) + "\n"
                content = f.content
                directive_match = re.match(r'^(["\']use client["\'];?\s*\n)', content)
                if directive_match:
                    insert_pos = directive_match.end()
                    content = content[:insert_pos] + prefix + content[insert_pos:]
                else:
                    content = prefix + content
                file_map[path] = GeneratedFile(path=path, content=content)
                logger.info(
                    "deterministic.executor.scaffold.auto_import file=%s added=%s",
                    path, ", ".join(imports_to_add),
                )

    def _extract_files_from_operations(self, operations: list[dict[str, Any]]) -> list[GeneratedFile]:
        """Fallback: extract file content directly from the plan operations."""
        files: list[GeneratedFile] = []
        for op in operations:
            if not isinstance(op, dict):
                continue
            op_type = str(op.get("type") or "").strip().lower()
            if op_type not in ("create_file", "write_config"):
                continue
            inputs = op.get("inputs") if isinstance(op.get("inputs"), dict) else {}
            path = str(inputs.get("path") or "").strip()
            if not path:
                continue
            content_value = inputs.get("content")
            if isinstance(content_value, str):
                content = _strip_markdown_fences(content_value)
            elif content_value is None:
                content = ""
            else:
                content = json.dumps(content_value, ensure_ascii=False)
            files.append(GeneratedFile(path=path, content=content))
        return files

    async def _run_local_preflight(self, files: list[GeneratedFile]) -> LocalPreflightResult:
        """Materialize generated files locally and run install/build before commit or deploy."""
        import shutil
        if not shutil.which("npm"):
            logger.warning("deterministic.executor.local_preflight.skipped npm not found in PATH")
            return LocalPreflightResult(success=True, logs="[skipped] npm not available in this environment")
        timeout_seconds = max(30, int(getattr(settings, "codegen_local_preflight_timeout_seconds", 300)))
        with tempfile.TemporaryDirectory(prefix="openclaw-preflight-") as temp_dir:
            skipped_paths: list[str] = []
            for generated in files:
                normalized = os.path.normpath(generated.path).replace("\\", "/").lstrip("./")
                if not normalized or normalized.startswith("../") or os.path.isabs(normalized):
                    skipped_paths.append(generated.path)
                    continue
                abs_path = os.path.join(temp_dir, normalized)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding="utf-8") as handle:
                    handle.write(generated.content)

            log_parts: list[str] = []
            if skipped_paths:
                log_parts.append("Skipped unsafe paths:\n" + "\n".join(sorted(skipped_paths)))

            install_code, install_logs = await self._run_local_command(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=temp_dir,
                timeout_seconds=timeout_seconds,
            )
            log_parts.append("$ npm install --legacy-peer-deps\n" + install_logs)
            if install_code != 0:
                return LocalPreflightResult(success=False, logs="\n\n".join(log_parts))

            build_code, build_logs = await self._run_local_command(
                ["npm", "run", "build"],
                cwd=temp_dir,
                timeout_seconds=timeout_seconds,
            )
            log_parts.append("$ npm run build\n" + build_logs)
            return LocalPreflightResult(success=build_code == 0, logs="\n\n".join(log_parts))

    async def _run_local_command(
        self,
        argv: list[str],
        *,
        cwd: str,
        timeout_seconds: int,
    ) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            output = (stdout or b"").decode("utf-8", errors="ignore")
            return proc.returncode or 0, output
        except asyncio.TimeoutError:
            proc.kill()
            stdout, _ = await proc.communicate()
            output = (stdout or b"").decode("utf-8", errors="ignore")
            timeout_msg = f"\n[local-preflight-timeout after {timeout_seconds}s]\n"
            return 124, output + timeout_msg

    @staticmethod
    def _preflight_failure_signature(logs: str, files: list[GeneratedFile]) -> str:
        """Stable signature used to detect no-progress auto-fix loops."""
        normalized_logs = "\n".join(line.strip() for line in (logs or "").splitlines()[-120:] if line.strip())
        file_fingerprints = [
            f"{f.path}:{hashlib.sha256(f.content.encode('utf-8', errors='ignore')).hexdigest()}"
            for f in sorted(files, key=lambda item: item.path)
        ]
        payload = normalized_logs + "\n" + "\n".join(file_fingerprints)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # GitHub: Authentication
    # ------------------------------------------------------------------
    async def _github_installation_token(self, client: httpx.AsyncClient) -> str:
        app_id = (settings.github_app_id or "").strip()
        installation_id = (settings.github_installation_id or "").strip()
        private_key = _normalize_private_key(settings.github_private_key or "")
        jwt_token = self._build_github_app_jwt(app_id=app_id, private_key_pem=private_key)
        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        resp, data = await self._request(client, "POST", url, headers=headers, payload={})
        if resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="GitHub installation token exchange failed.",
                provider="github",
                resp=resp,
                data=data,
            )
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="GitHub installation token exchange returned no token.",
                provider="github",
            )
        return token

    # ------------------------------------------------------------------
    # GitHub: Repository Provisioning
    # ------------------------------------------------------------------
    async def _github_provision_repo(
        self,
        client: httpx.AsyncClient,
        installation_token: str,
        spec: RepoSpec,
    ) -> RepoProvisionResult:
        template_owner = (settings.github_template_owner or "").strip()
        template_repo = (settings.github_template_repo or "").strip()
        url = f"{GITHUB_API_BASE}/repos/{template_owner}/{template_repo}/generate"
        generate_payload = {
            "owner": spec.owner,
            "name": spec.name,
            "private": spec.private,
            "include_all_branches": False,
        }

        tokens_to_try: list[tuple[str, str]] = [
            ("installation", f"Bearer {installation_token}"),
        ]
        pat = (settings.github_token or "").strip()
        if pat:
            tokens_to_try.append(("pat", f"token {pat}"))

        resp = data = None
        for token_type, auth_value in tokens_to_try:
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": auth_value,
                "X-GitHub-Api-Version": "2022-11-28",
            }
            resp, data = await self._request(client, "POST", url, headers=headers, payload=generate_payload)
            logger.info(
                "deterministic.executor.repo_create_attempt token_type=%s owner=%s repo=%s status=%s",
                token_type, spec.owner, spec.name, resp.status_code,
            )
            if resp.status_code in (200, 201):
                break
            if resp.status_code in (409, 422):
                break
            if resp.status_code == 403 and token_type != tokens_to_try[-1][0]:
                logger.warning("deterministic.executor.template_generate_403 token_type=%s retrying_with_next", token_type)
                continue
            break
        if resp.status_code in (200, 201):
            return RepoProvisionResult(
                owner=spec.owner,
                name=spec.name,
                branch=spec.branch,
                html_url=str(data.get("html_url") or f"https://github.com/{spec.owner}/{spec.name}"),
                default_branch=str(data.get("default_branch") or "main"),
            )
        if resp.status_code in (409, 422):
            get_url = f"{GITHUB_API_BASE}/repos/{spec.owner}/{spec.name}"
            get_resp, get_data = await self._request(client, "GET", get_url, headers=headers)
            if get_resp.status_code == 200:
                return RepoProvisionResult(
                    owner=spec.owner,
                    name=spec.name,
                    branch=spec.branch,
                    html_url=str(get_data.get("html_url") or f"https://github.com/{spec.owner}/{spec.name}"),
                    default_branch=str(get_data.get("default_branch") or "main"),
                )
        if resp.status_code in (403, 404):
            logger.warning(
                "deterministic.executor.template_unavailable template=%s/%s status=%s falling_back_to_empty_repo",
                template_owner, template_repo, resp.status_code,
            )
            fallback_result = await self._github_create_empty_repo(client, installation_token, spec)
            if fallback_result is not None:
                return fallback_result
        self._raise_http_error(
            reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
            message="GitHub repository creation from template failed.",
            provider="github",
            resp=resp,
            data=data,
        )
        raise AssertionError("unreachable")

    async def _github_create_empty_repo(
        self,
        client: httpx.AsyncClient,
        installation_token: str,
        spec: RepoSpec,
    ) -> Optional[RepoProvisionResult]:
        """Fallback: create a regular empty repo when template is unavailable.

        Tries multiple strategies in order:
        1. For each token, attempt POST /orgs/{owner}/repos to preserve explicit org owner.
        2. Then attempt POST /user/repos for personal-owner cases.
        3. If repo already exists (409/422), reuse it.
        """
        create_payload = {
            "name": spec.name,
            "private": spec.private,
            "auto_init": True,
            "description": "Auto-generated by OpenClaw deterministic executor",
        }

        strategies: list[tuple[str, str, dict[str, str]]] = []
        pat = (settings.github_token or "").strip()
        if pat:
            strategies.append((
                "pat",
                f"token {pat}",
                {"Accept": "application/vnd.github+json", "Authorization": f"token {pat}", "X-GitHub-Api-Version": "2022-11-28"},
            ))
        strategies.append((
            "installation",
            f"Bearer {installation_token}",
            {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {installation_token}", "X-GitHub-Api-Version": "2022-11-28"},
        ))

        last_status = 0
        last_data: Any = {}
        for token_type, _, headers in strategies:
            attempts = [
                ("org", f"{GITHUB_API_BASE}/orgs/{spec.owner}/repos"),
                ("user", f"{GITHUB_API_BASE}/user/repos"),
            ]
            for endpoint_kind, create_url in attempts:
                resp, data = await self._request(client, "POST", create_url, headers=headers, payload=create_payload)
                last_status, last_data = resp.status_code, data
                logger.info(
                    "deterministic.executor.empty_repo_attempt token_type=%s endpoint=%s owner=%s status=%s",
                    token_type, endpoint_kind, spec.owner, resp.status_code,
                )
                if resp.status_code in (200, 201):
                    resolved_owner = str(data.get("owner", {}).get("login") or spec.owner) if isinstance(data, dict) else spec.owner
                    if resolved_owner.lower() != spec.owner.lower():
                        logger.warning(
                            "deterministic.executor.empty_repo_owner_mismatch requested_owner=%s created_owner=%s token_type=%s endpoint=%s",
                            spec.owner, resolved_owner, token_type, endpoint_kind,
                        )
                        continue
                    return RepoProvisionResult(
                        owner=resolved_owner,
                        name=spec.name,
                        branch=spec.branch,
                        html_url=str(data.get("html_url") or f"https://github.com/{resolved_owner}/{spec.name}"),
                        default_branch=str(data.get("default_branch") or "main"),
                    )
                if resp.status_code in (409, 422):
                    get_url = f"{GITHUB_API_BASE}/repos/{spec.owner}/{spec.name}"
                    get_resp, get_data = await self._request(client, "GET", get_url, headers=headers)
                    if get_resp.status_code == 200:
                        return RepoProvisionResult(
                            owner=spec.owner,
                            name=spec.name,
                            branch=spec.branch,
                            html_url=str(get_data.get("html_url") or f"https://github.com/{spec.owner}/{spec.name}"),
                            default_branch=str(get_data.get("default_branch") or "main"),
                        )

        logger.error(
            "deterministic.executor.empty_repo_create_failed status=%s body=%s",
            last_status, str(last_data)[:300],
        )
        return None

    # ------------------------------------------------------------------
    # GitHub: Branch Management
    # ------------------------------------------------------------------
    async def _github_ensure_branch(
        self,
        client: httpx.AsyncClient,
        installation_token: str,
        *,
        owner: str,
        repo: str,
        target_branch: str,
        default_branch: str,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {installation_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        branch_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{target_branch}"
        branch_resp, branch_data = await self._request(client, "GET", branch_url, headers=headers)
        if branch_resp.status_code == 200:
            return
        if branch_resp.status_code not in (404, 409):
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message=f"Failed to resolve target branch '{target_branch}'.",
                provider="github",
                resp=branch_resp,
                data={},
            )

        # If 409 (repo initializing), wait before checking default branch
        if branch_resp.status_code == 409:
            await asyncio.sleep(3)

        default_ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{default_branch}"
        default_resp, default_data = await self._request(client, "GET", default_ref_url, headers=headers)
        if default_resp.status_code in (404, 409):
            for _wait in BRANCH_RETRY_DELAYS:
                logger.info(
                    "deterministic.executor.branch_not_ready repo=%s/%s branch=%s status=%s retrying_in=%ds",
                    owner, repo, default_branch, default_resp.status_code, _wait,
                )
                await asyncio.sleep(_wait)
                default_resp, default_data = await self._request(client, "GET", default_ref_url, headers=headers)
                if default_resp.status_code == 200:
                    break
        if default_resp.status_code != 200:
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message=f"Failed to resolve default branch '{default_branch}'.",
                provider="github",
                resp=default_resp,
                data=default_data,
            )
        default_sha = (
            default_data.get("object", {}).get("sha")
            if isinstance(default_data, dict)
            else None
        )
        if not isinstance(default_sha, str) or not default_sha:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Default branch SHA missing while creating target branch.",
                provider="github",
            )
        if target_branch == default_branch:
            return
        create_ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs"
        create_payload = {"ref": f"refs/heads/{target_branch}", "sha": default_sha}
        create_resp, create_data = await self._request(client, "POST", create_ref_url, headers=headers, payload=create_payload)
        if create_resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message=f"Failed to create branch '{target_branch}'.",
                provider="github",
                resp=create_resp,
                data=create_data,
            )

    async def _github_collect_template_reference(
        self,
        client: httpx.AsyncClient,
        installation_token: str,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> TemplateReference:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {installation_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        key_paths = (
            "package.json",
            "tsconfig.json",
            "next.config.ts",
            "next.config.js",
            "postcss.config.mjs",
            "app/layout.tsx",
            "app/globals.css",
            "src/app/layout.tsx",
            "src/app/globals.css",
        )
        key_files: dict[str, str] = {}
        for path in key_paths:
            text = await self._github_fetch_text_file(
                client,
                headers=headers,
                owner=owner,
                repo=repo,
                path=path,
                ref=ref,
            )
            if text is not None:
                key_files[path] = text

        package_json: dict[str, Any] = {}
        raw_package = key_files.get("package.json")
        if raw_package:
            try:
                parsed = json.loads(raw_package)
                if isinstance(parsed, dict):
                    package_json = parsed
            except json.JSONDecodeError:
                logger.warning("deterministic.executor.template_ref.invalid_package_json repo=%s/%s", owner, repo)
        logger.info(
            "deterministic.executor.template_ref.loaded repo=%s/%s ref=%s files=%d deps=%d dev_deps=%d",
            owner,
            repo,
            ref,
            len(key_files),
            len(package_json.get("dependencies", {}) if isinstance(package_json.get("dependencies"), dict) else {}),
            len(package_json.get("devDependencies", {}) if isinstance(package_json.get("devDependencies"), dict) else {}),
        )
        return TemplateReference(
            source_repo=f"{owner}/{repo}",
            source_branch=ref,
            package_json=package_json,
            key_files=key_files,
        )

    async def _github_fetch_text_file(
        self,
        client: httpx.AsyncClient,
        *,
        headers: dict[str, str],
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> Optional[str]:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}"
        resp, data = await self._request(client, "GET", url, headers=headers, params={"ref": ref})
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning(
                "deterministic.executor.template_ref.fetch_failed repo=%s/%s path=%s ref=%s status=%s",
                owner, repo, path, ref, resp.status_code,
            )
            return None
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        if not isinstance(content, str):
            return None
        try:
            if str(data.get("encoding") or "").lower() == "base64":
                return base64.b64decode(content.encode("utf-8"), validate=False).decode("utf-8", errors="ignore")
            return content
        except Exception:
            logger.warning(
                "deterministic.executor.template_ref.decode_failed repo=%s/%s path=%s ref=%s",
                owner, repo, path, ref,
            )
            return None

    # ------------------------------------------------------------------
    # GitHub: Batch Commit via Trees API
    # ------------------------------------------------------------------
    async def _github_batch_commit(
        self,
        client: httpx.AsyncClient,
        installation_token: str,
        *,
        owner: str,
        repo: str,
        branch: str,
        files: list[GeneratedFile],
        message: str,
    ) -> Optional[str]:
        """Commit all files atomically using the Git Trees API."""
        if not files:
            return None

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {installation_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{branch}"
        ref_resp, ref_data = await self._request(client, "GET", ref_url, headers=headers)
        if ref_resp.status_code != 200:
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message=f"Failed to get branch '{branch}' ref for batch commit.",
                provider="github",
                resp=ref_resp,
                data=ref_data,
            )

        base_sha = ref_data.get("object", {}).get("sha") if isinstance(ref_data, dict) else None
        if not isinstance(base_sha, str) or not base_sha:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Branch SHA missing for batch commit.",
                provider="github",
            )

        blobs: list[dict[str, str]] = []
        for f in files:
            blob_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/blobs"
            blob_resp, blob_data = await self._request(
                client, "POST", blob_url,
                headers=headers,
                payload={"content": f.content, "encoding": "utf-8"},
            )
            if blob_resp.status_code not in (200, 201):
                self._raise_http_error(
                    reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                    message=f"Failed to create blob for '{f.path}'.",
                    provider="github",
                    resp=blob_resp,
                    data=blob_data,
                )
            blob_sha = blob_data.get("sha") if isinstance(blob_data, dict) else None
            if not isinstance(blob_sha, str):
                raise DeterministicExecutionError(
                    reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                    message=f"Blob SHA missing for '{f.path}'.",
                    provider="github",
                )
            blobs.append({"path": f.path, "mode": "100644", "type": "blob", "sha": blob_sha})

        tree_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees"
        tree_resp, tree_data = await self._request(
            client, "POST", tree_url,
            headers=headers,
            payload={"base_tree": base_sha, "tree": blobs},
        )
        if tree_resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Failed to create git tree for batch commit.",
                provider="github",
                resp=tree_resp,
                data=tree_data,
            )
        tree_sha = tree_data.get("sha") if isinstance(tree_data, dict) else None
        if not isinstance(tree_sha, str):
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Tree SHA missing for batch commit.",
                provider="github",
            )

        commit_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits"
        commit_resp, commit_data = await self._request(
            client, "POST", commit_url,
            headers=headers,
            payload={
                "message": message,
                "tree": tree_sha,
                "parents": [base_sha],
            },
        )
        if commit_resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Failed to create commit for batch commit.",
                provider="github",
                resp=commit_resp,
                data=commit_data,
            )
        commit_sha = commit_data.get("sha") if isinstance(commit_data, dict) else None
        if not isinstance(commit_sha, str):
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message="Commit SHA missing for batch commit.",
                provider="github",
            )

        update_ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs/heads/{branch}"
        update_resp, update_data = await self._request(
            client, "PATCH", update_ref_url,
            headers=headers,
            payload={"sha": commit_sha, "force": False},
        )
        if update_resp.status_code != 200:
            self._raise_http_error(
                reason_code=REASON_GITHUB_REPO_CREATE_FAILED,
                message=f"Failed to update branch '{branch}' ref after batch commit.",
                provider="github",
                resp=update_resp,
                data=update_data,
            )

        logger.info(
            "deterministic.executor.batch_commit_done repo=%s/%s branch=%s files=%d sha=%s",
            owner, repo, branch, len(files), commit_sha,
        )
        return commit_sha

    # ------------------------------------------------------------------
    # Vercel: Project + Deployment
    # ------------------------------------------------------------------
    async def _vercel_create_or_resolve_project(
        self,
        client: httpx.AsyncClient,
        *,
        team_id: str,
        project_name: str,
        github_owner: str,
        github_repo: str,
        production_branch: str,
    ) -> VercelProjectResult:
        token = (settings.vercel_token or "").strip()
        if not token:
            raise DeterministicExecutionError(
                reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
                message="Missing Vercel token for deterministic execution.",
                provider="vercel",
            )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        get_url = f"{VERCEL_API_BASE}/v9/projects/{quote(project_name, safe='')}"
        get_resp, get_data = await self._request(client, "GET", get_url, headers=headers, params={"teamId": team_id})
        if get_resp.status_code == 200:
            return VercelProjectResult(id=str(get_data.get("id") or ""), name=str(get_data.get("name") or project_name))
        if get_resp.status_code in (401, 403):
            self._raise_http_error(
                reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
                message=(
                    f"Vercel access denied while resolving project '{project_name}' for team '{team_id}'. "
                    "Verify VERCEL_TOKEN team membership and project permissions."
                ),
                provider="vercel",
                resp=get_resp,
                data=get_data,
            )
        if get_resp.status_code != 404:
            self._raise_http_error(
                reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
                message=f"Failed resolving Vercel project '{project_name}'.",
                provider="vercel",
                resp=get_resp,
                data=get_data,
            )

        create_url = f"{VERCEL_API_BASE}/v11/projects"
        payload = {
            "name": project_name,
            "gitRepository": {
                "type": "github",
                "org": github_owner,
                "repo": github_repo,
                "productionBranch": production_branch,
            },
        }
        create_resp, create_data = await self._request(client, "POST", create_url, headers=headers, params={"teamId": team_id}, payload=payload)
        if create_resp.status_code in (401, 403):
            self._raise_http_error(
                reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
                message=(
                    f"Vercel access denied while creating project '{project_name}' for team '{team_id}'. "
                    "Verify VERCEL_TOKEN team membership and project create permissions."
                ),
                provider="vercel",
                resp=create_resp,
                data=create_data,
            )
        if create_resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_VERCEL_PROJECT_CREATE_FAILED,
                message=f"Failed creating Vercel project '{project_name}'.",
                provider="vercel",
                resp=create_resp,
                data=create_data,
            )
        return VercelProjectResult(id=str(create_data.get("id") or ""), name=str(create_data.get("name") or project_name))

    async def _vercel_deploy_files(
        self,
        client: httpx.AsyncClient,
        *,
        team_id: str,
        project_name: str,
        files: list[GeneratedFile],
        target: str,
    ) -> VercelDeploymentResult:
        """Deploy by uploading files directly to Vercel (no GitHub integration required)."""
        import hashlib
        token = (settings.vercel_token or "").strip()

        file_entries: list[dict[str, Any]] = []
        for f in files:
            content_bytes = f.content.encode("utf-8")
            sha1_hex = hashlib.sha1(content_bytes).hexdigest()
            upload_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "x-vercel-digest": sha1_hex,
                "Content-Length": str(len(content_bytes)),
            }
            upload_resp = await client.post(
                f"{VERCEL_API_BASE}/v2/files",
                headers=upload_headers,
                params={"teamId": team_id},
                content=content_bytes,
            )
            if upload_resp.status_code not in (200, 201):
                logger.warning(
                    "deterministic.executor.vercel_file_upload status=%s file=%s",
                    upload_resp.status_code, f.path,
                )
            file_entries.append({
                "file": f.path,
                "sha": sha1_hex,
                "size": len(content_bytes),
            })

        deploy_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        deploy_url = f"{VERCEL_API_BASE}/v13/deployments"
        deploy_payload: dict[str, Any] = {
            "name": project_name,
            "project": project_name,
            "files": file_entries,
            "projectSettings": {
                "framework": "nextjs",
                "buildCommand": "next build",
                "outputDirectory": ".next",
                "installCommand": "npm install --legacy-peer-deps",
            },
        }
        if target == "production":
            deploy_payload["target"] = "production"
        resp, data = await self._request(client, "POST", deploy_url, headers=deploy_headers, params={"teamId": team_id}, payload=deploy_payload)
        if resp.status_code not in (200, 201):
            self._raise_http_error(
                reason_code=REASON_VERCEL_DEPLOY_FAILED,
                message=f"Failed triggering Vercel file deployment for '{project_name}'.",
                provider="vercel",
                resp=resp,
                data=data,
            )
        return VercelDeploymentResult(
            id=str(data.get("id") or ""),
            url=str(data.get("url") or ""),
            target=target,
        )

    # ------------------------------------------------------------------
    # Vercel: Build Monitoring + Auto-Fix
    # ------------------------------------------------------------------
    async def _vercel_poll_deployment(
        self,
        client: httpx.AsyncClient,
        team_id: str,
        deployment_id: str,
    ) -> dict[str, Any]:
        """Poll Vercel deployment status until READY, ERROR, CANCELED, or timeout."""
        token = (settings.vercel_token or "").strip()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{VERCEL_API_BASE}/v13/deployments/{deployment_id}"
        interval = getattr(settings, "vercel_poll_interval_seconds", 10)
        max_wait = getattr(settings, "vercel_poll_max_wait_seconds", 300)
        terminal_states = {"READY", "ERROR", "CANCELED"}

        elapsed = 0
        last_state = "QUEUED"
        while elapsed < max_wait:
            resp, data = await self._request(client, "GET", url, headers=headers, params={"teamId": team_id})
            if resp.status_code == 200 and isinstance(data, dict):
                last_state = str(data.get("readyState") or data.get("state") or "UNKNOWN").upper()
                logger.info(
                    "deterministic.executor.vercel_poll deployment_id=%s state=%s elapsed=%ds",
                    deployment_id, last_state, elapsed,
                )
                if last_state in terminal_states:
                    return {"readyState": last_state, "data": data}
            else:
                logger.warning(
                    "deterministic.executor.vercel_poll_error deployment_id=%s status=%s",
                    deployment_id, resp.status_code,
                )
            await asyncio.sleep(interval)
            elapsed += interval

        logger.warning("deterministic.executor.vercel_poll_timeout deployment_id=%s last_state=%s", deployment_id, last_state)
        return {"readyState": "TIMEOUT", "data": {}}

    async def _vercel_fetch_build_logs(
        self,
        client: httpx.AsyncClient,
        team_id: str,
        deployment_id: str,
    ) -> str:
        """Fetch build error logs from a failed Vercel deployment."""
        token = (settings.vercel_token or "").strip()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{VERCEL_API_BASE}/v3/deployments/{deployment_id}/events"

        await asyncio.sleep(5)

        for attempt in range(3):
            resp, data = await self._request(
                client, "GET", url, headers=headers,
                params={"teamId": team_id, "builds": "1", "direction": "backward", "limit": "150"},
            )
            if resp.status_code != 200:
                logger.warning("deterministic.executor.fetch_build_logs_error status=%s attempt=%d", resp.status_code, attempt)
                if attempt < 2:
                    await asyncio.sleep(3)
                    continue
                return "Failed to fetch build logs."

            lines: list[str] = []
            events = data if isinstance(data, list) else []
            if isinstance(data, dict):
                events = data.get("events") or data.get("logs") or data.get("output") or []
                if not events and isinstance(data, dict):
                    events = list(data.values()) if not events else events

            for event in events:
                if not isinstance(event, dict):
                    if isinstance(event, str) and event.strip():
                        lines.append(event.strip())
                    continue
                text = ""
                for key in ("text", "message", "output", "log"):
                    val = event.get(key)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
                if not text:
                    payload = event.get("payload")
                    if isinstance(payload, dict):
                        for key in ("text", "message", "output", "log"):
                            val = payload.get(key)
                            if isinstance(val, str) and val.strip():
                                text = val.strip()
                                break
                        if not text:
                            info = payload.get("info")
                            if isinstance(info, dict):
                                text = str(info.get("text") or info.get("message") or "").strip()
                if text:
                    lines.append(text)

            if lines:
                log_text = "\n".join(reversed(lines))
                return log_text[-8000:]

            if attempt < 2:
                logger.info(
                    "deterministic.executor.fetch_build_logs_empty attempt=%d deployment_id=%s event_count=%d sample=%s",
                    attempt, deployment_id, len(events),
                    str(events[:2])[:300] if events else "[]",
                )
                await asyncio.sleep(5)

        return "No build log content found."

    @staticmethod
    def _classify_build_errors(error_logs: str) -> list[dict[str, str]]:
        """Parse build logs into typed error categories for targeted fixes."""
        import re
        errors: list[dict[str, str]] = []
        directive_re = re.compile(
            r'"use client" directive must be placed before other expressions', re.IGNORECASE
        )
        module_re = re.compile(r"Module not found.*?Can't resolve\s+['\"]([^'\"]+)['\"]")
        export_re = re.compile(r"'(\w+)' is not exported from '([^']+)'")
        no_default_re = re.compile(r"does not contain a default export")
        type_re = re.compile(r"Type error:|TS\d{4}:")
        hook_re = re.compile(r"React Hook .* only works in a Client Component")

        for line in error_logs.splitlines():
            if directive_re.search(line):
                errors.append({"type": "directive_error", "detail": line.strip()})
            elif hook_re.search(line):
                errors.append({"type": "directive_error", "detail": line.strip()})
            elif module_re.search(line):
                errors.append({"type": "import_error", "detail": line.strip()})
            elif export_re.search(line) or no_default_re.search(line):
                errors.append({"type": "export_error", "detail": line.strip()})
            elif type_re.search(line):
                errors.append({"type": "type_error", "detail": line.strip()})
        return errors

    def _apply_deterministic_prefixes(
        self,
        error_logs: str,
        file_map: dict[str, GeneratedFile],
    ) -> int:
        """Apply rule-based fixes for known error patterns before calling LLM.

        Returns the number of deterministic fixes applied.
        """
        fixes = 0

        stubs_created = self._create_stubs_for_missing_modules(error_logs, file_map)
        fixes += stubs_created

        self._normalize_directive_placement(file_map)
        self._ensure_use_client_directive(file_map)
        self._normalize_directive_placement(file_map)
        self._validate_hook_imports(file_map, [])
        self._fix_missing_standard_imports(file_map)
        self._normalize_directive_placement(file_map)
        self._fix_duplicate_imports(file_map)
        self._fix_export_import_mismatches(file_map)

        import re
        dup_default_re = re.compile(r"^export\s+default\s+", re.MULTILINE)
        for path, f in list(file_map.items()):
            if not (path.endswith(".tsx") or path.endswith(".jsx")):
                continue
            matches = list(dup_default_re.finditer(f.content))
            if len(matches) > 1:
                content = f.content
                for m in reversed(matches[:-1]):
                    line_end = content.find("\n", m.start())
                    if line_end == -1:
                        line_end = len(content)
                    content = content[:m.start()] + content[line_end + 1:]
                file_map[path] = GeneratedFile(path=path, content=content)
                fixes += 1

        return fixes

    async def _auto_fix_build_errors(
        self,
        api_key: str,
        model: str,
        error_logs: str,
        files: list[GeneratedFile],
        *,
        template_reference: Optional[TemplateReference] = None,
        manifest: Optional[BuildManifest] = None,
    ) -> list[GeneratedFile]:
        """Use deterministic pre-fixes then OpenAI to fix build errors."""
        file_map = {f.path: f for f in files}

        classified = self._classify_build_errors(error_logs)
        logger.info(
            "deterministic.executor.auto_fix.classified errors=%d types=%s",
            len(classified),
            list({e["type"] for e in classified}),
        )

        det_fixes = self._apply_deterministic_prefixes(error_logs, file_map)
        if det_fixes:
            logger.info("deterministic.executor.auto_fix.deterministic_fixes applied=%d", det_fixes)

        error_types = {e["type"] for e in classified}
        type_guidance = ""
        if "directive_error" in error_types:
            type_guidance += (
                "DIRECTIVE FIX: 'use client' must be the VERY FIRST LINE of any file using hooks "
                "or event handlers. Move it above all imports. Remove metadata exports from client files.\n"
            )
        if "import_error" in error_types:
            type_guidance += (
                "IMPORT FIX: Create missing component files with proper named exports. "
                "@/ imports map to src/ — never add them to package.json.\n"
            )
        if "export_error" in error_types:
            type_guidance += (
                "EXPORT FIX: Ensure components have named exports. Pages need default exports. "
                "Check for mismatched import/export styles (named vs default).\n"
            )

        approved_list = ", ".join(sorted(APPROVED_PACKAGES.keys()))
        system_prompt = (
            "You are an expert Next.js/TypeScript debugger. You are given Vercel build error logs and the project's source files.\n"
            "Your job is to fix ONLY the files that are causing the build errors.\n\n"
            + (f"TARGETED GUIDANCE (based on error classification):\n{type_guidance}\n" if type_guidance else "")
            + "RULES:\n"
            "- Fix import errors, missing modules, TypeScript errors, and syntax issues.\n"
            "- Do NOT change files that are not related to the errors.\n"
            "- Preserve the existing design and functionality — only fix what is broken.\n"
            "- Use the ===FILE: path===...===END_FILE=== format for each fixed file.\n"
            "- If a 'Module not found' error references @/components/Foo, CREATE that file with a proper React component.\n"
            "- @/ imports are LOCAL project files (mapped to src/), NOT npm packages. Create the component file, do NOT add to package.json.\n"
            "- For Next.js App Router: pages are default exports, components are named exports.\n"
            "- Tailwind CSS v4: use @import \"tailwindcss\" in globals.css, @tailwindcss/postcss in postcss.\n"
            "- 'use client' must be the VERY FIRST LINE (before imports) in files using hooks or event handlers.\n\n"
            "DEPENDENCY RULES (STRICT):\n"
            "- Do NOT output package.json. Dependency management is handled externally.\n"
            "- Do NOT add import statements for packages not in this approved list: " + approved_list + ".\n"
            "- Do NOT modify dependency versions. The existing versions are immutable and correct.\n"
            "- If a build error mentions a missing npm package NOT in the approved list, remove the import and inline a fallback — do NOT add the package.\n\n"
            "EXPORT RULES:\n"
            "- All components MUST use named exports: `export function Foo()` or `export const Foo =`.\n"
            "- Do NOT use `export default function Foo` as the sole export. Always include a named export.\n"
            "- Do NOT generate tailwind.config.ts or tailwind.config.js — Tailwind v4 does not use config files.\n"
        )

        error_section = f"BUILD ERROR LOGS:\n```\n{error_logs}\n```\n\n"

        errored_paths = self._identify_errored_files(error_logs, file_map)

        files_section = "FILES TO FIX (only output files you changed):\n\n"
        for path in errored_paths:
            f = file_map.get(path)
            if f:
                truncated = f.content[:4000]
                files_section += f"===CURRENT FILE: {path}===\n{truncated}\n===END===\n\n"

        user_prompt = error_section + files_section + "\nFix the errors and output ONLY the fixed files."

        content = await self._openai_chat(
            api_key, model, system_prompt, user_prompt,
            temperature=0.2,
            max_tokens=getattr(settings, "codegen_phase3_max_tokens", 8000),
            manifest=manifest,
        )

        fixed_files = self._parse_codegen_response(content, []) if content else []
        allowed_patch_paths = {str(p).strip() for p in errored_paths if str(p).strip()}
        scoped_fixed_files: list[GeneratedFile] = []
        for ff in fixed_files:
            if ff.path == "package.json":
                logger.info("deterministic.executor.auto_fix.drop_immutable_package_json")
                continue
            if ff.path not in allowed_patch_paths:
                logger.warning(
                    "deterministic.executor.auto_fix.drop_out_of_scope_patch file=%s allowed_scope_size=%d",
                    ff.path,
                    len(allowed_patch_paths),
                )
                continue
            scoped_fixed_files.append(ff)
        fixed_files = scoped_fixed_files
        for ff in fixed_files:
            if ff.path in file_map:
                logger.info("deterministic.executor.auto_fix.patched file=%s", ff.path)
            else:
                logger.info("deterministic.executor.auto_fix.added_new file=%s", ff.path)
            file_map[ff.path] = ff

        patched = list(file_map.values())
        return self._ensure_scaffold_integrity(patched, template_reference=template_reference)

    @staticmethod
    def _create_stubs_for_missing_modules(
        error_logs: str,
        file_map: dict[str, GeneratedFile],
    ) -> int:
        """Parse build errors and create/fix files deterministically.

        Handles two patterns:
        1. 'Module not found: Can't resolve @/...' -> create stub file
        2. "'Foo' is not exported from '@/...'" -> ensure the file has both
           named and default exports for Foo

        Returns the number of fixes applied. Mutates file_map in place.
        """
        import re

        module_not_found_re = re.compile(
            r"Module not found:\s*Can't resolve\s+['\"]@/([\w/.+-]+)['\"]"
        )
        not_exported_re = re.compile(
            r"'(\w+)' is not exported from '(@/[\w/]+)'"
        )
        no_default_re = re.compile(
            r"'(@/[\w/]+)' does not contain a default export \(imported as '(\w+)'\)"
        )

        _EXT = (".tsx", ".ts", ".js", ".jsx")
        fixes = 0

        for m in module_not_found_re.finditer(error_logs):
            import_path = m.group(1)
            src_base = f"src/{import_path}"

            already_exists = False
            for ext in _EXT:
                if f"{src_base}{ext}" in file_map:
                    already_exists = True
                    break
            if not already_exists:
                for idx in ("index.tsx", "index.ts"):
                    if f"{src_base}/{idx}" in file_map:
                        already_exists = True
                        break
            if already_exists:
                continue

            parts = import_path.split("/")
            module_name = parts[-1]
            is_component = "component" in import_path.lower() or module_name[0:1].isupper()
            stub_path = f"src/{import_path}.tsx" if is_component else f"src/{import_path}.ts"

            if is_component:
                stub_content = (
                    f'"use client";\n\n'
                    f"export function {module_name}({{ children }}: {{ children?: React.ReactNode }}) {{\n"
                    f"  return (\n"
                    f"    <section className=\"w-full py-16 px-4\">\n"
                    f"      <div className=\"max-w-7xl mx-auto\">\n"
                    f"        {{children || <p className=\"text-gray-600\">{module_name}</p>}}\n"
                    f"      </div>\n"
                    f"    </section>\n"
                    f"  );\n"
                    f"}}\n\n"
                    f"export default {module_name};\n"
                )
            else:
                stub_content = f"// Auto-generated stub for {import_path}\nexport default {{}};\n"

            file_map[stub_path] = GeneratedFile(path=stub_path, content=stub_content)
            fixes += 1
            logger.info(
                "deterministic.executor.auto_fix.module_stub_created module=%s path=%s",
                import_path, stub_path,
            )

        export_fixes_needed: dict[str, set[str]] = {}
        for m in not_exported_re.finditer(error_logs):
            name, module_path = m.group(1), m.group(2)
            raw = module_path.replace("@/", "")
            export_fixes_needed.setdefault(raw, set()).add(name)
        for m in no_default_re.finditer(error_logs):
            module_path, name = m.group(1), m.group(2)
            raw = module_path.replace("@/", "")
            export_fixes_needed.setdefault(raw, set()).add(name)

        for import_path, needed_names in export_fixes_needed.items():
            resolved = None
            src_base = f"src/{import_path}"
            for ext in _EXT:
                if f"{src_base}{ext}" in file_map:
                    resolved = f"{src_base}{ext}"
                    break
            if not resolved:
                for idx in ("index.tsx", "index.ts"):
                    if f"{src_base}/{idx}" in file_map:
                        resolved = f"{src_base}/{idx}"
                        break
            if not resolved:
                continue

            content = file_map[resolved].content
            changed = False
            for name in needed_names:
                has_named = re.search(
                    rf"^export\s+(?:async\s+)?(?:function|const|class)\s+{re.escape(name)}\b",
                    content, re.MULTILINE,
                )
                has_default = re.search(r"^export\s+default\b", content, re.MULTILINE)

                if not has_named and not has_default:
                    content = content.rstrip() + (
                        f"\n\nexport function {name}() {{\n"
                        f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{name}</div>;\n"
                        f"}}\n\nexport default {name};\n"
                    )
                    changed = True
                elif not has_named and has_default:
                    default_func = re.search(
                        r"^export\s+default\s+function\s+(\w+)", content, re.MULTILINE
                    )
                    if default_func:
                        ai_name = default_func.group(1)
                        content = content.replace(
                            default_func.group(0),
                            f"export function {ai_name}",
                            1,
                        )
                        content = content.rstrip() + f"\n\nexport default {ai_name};\n"
                        if name != ai_name:
                            content = content.rstrip() + f"\nexport const {name} = {ai_name};\n"
                        changed = True
                    else:
                        content = content.rstrip() + (
                            f"\n\nexport function {name}() {{\n"
                            f"  return <div className=\"max-w-7xl mx-auto px-4 py-6\">{name}</div>;\n"
                            f"}}\n"
                        )
                        changed = True
                elif has_named and not has_default:
                    content = content.rstrip() + f"\n\nexport default {name};\n"
                    changed = True

            if changed:
                file_map[resolved] = GeneratedFile(path=resolved, content=content)
                fixes += 1
                logger.info(
                    "deterministic.executor.auto_fix.export_fix path=%s names=%s",
                    resolved, sorted(needed_names),
                )

        return fixes

    @staticmethod
    def _identify_errored_files(error_logs: str, file_map: dict[str, GeneratedFile]) -> list[str]:
        """Parse build logs to identify which files are causing errors."""
        import re
        errored: set[str] = set()

        errored.add("package.json")

        patterns = [
            re.compile(r"(?:Error|error)\s+in\s+[./]*(\S+\.(?:tsx?|jsx?|mjs|css))"),
            re.compile(r"Module not found.*['\"]@/([^'\"]+)['\"]"),
            re.compile(r"[./]*(src/\S+\.(?:tsx?|jsx?))"),
            re.compile(r"[./]*(app/\S+\.(?:tsx?|jsx?))"),
            re.compile(r"Failed to compile[\s\S]*?[./]*((?:src|app)/\S+\.(?:tsx?|jsx?))"),
        ]
        for pattern in patterns:
            for m in pattern.finditer(error_logs):
                candidate = m.group(1)
                if not candidate.startswith("src/") and not candidate.startswith("app/"):
                    candidate = f"src/{candidate}"
                if candidate in file_map:
                    errored.add(candidate)
                tsx_variant = candidate.replace(".ts", ".tsx") if candidate.endswith(".ts") else candidate
                if tsx_variant in file_map:
                    errored.add(tsx_variant)

        for path in file_map:
            if path.endswith("layout.tsx") or path.endswith("globals.css"):
                errored.add(path)

        if len(errored) <= 2:
            for path in file_map:
                if path.endswith(".tsx") or path.endswith(".ts"):
                    errored.add(path)
                if len(errored) >= 15:
                    break

        return sorted(errored)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_deployment_url(url: Optional[str]) -> Optional[str]:
        if not isinstance(url, str) or not url.strip():
            return None
        clean = url.strip()
        if clean.startswith("http://") or clean.startswith("https://"):
            return clean
        return f"https://{clean}"

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, str]] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> tuple[httpx.Response, Any]:
        response = await client.request(method, url, headers=headers, params=params, json=payload)
        try:
            data = response.json()
        except Exception:
            data = {}
        return response, data

    @staticmethod
    def _raise_http_error(
        *,
        reason_code: str,
        message: str,
        provider: str,
        resp: httpx.Response,
        data: Any,
    ) -> None:
        snippet = _sanitize_error_snippet(data, resp.text)
        raise DeterministicExecutionError(
            reason_code=reason_code,
            message=message,
            status_code=resp.status_code,
            provider=provider,
            snippet=snippet,
            extra={"upstream_status_code": resp.status_code, "upstream_error": snippet},
        )

    @staticmethod
    def _build_github_app_jwt(*, app_id: str, private_key_pem: str) -> str:
        if not app_id or not private_key_pem:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="Missing GitHub App id/private key for JWT generation.",
                provider="github",
            )
        now = int(time.time())
        header_b64 = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url(
            json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = DeterministicWebExecutor._sign_rs256(signing_input, private_key_pem)
        return f"{header_b64}.{payload_b64}.{_b64url(signature)}"

    @staticmethod
    def _sign_rs256(payload: bytes, private_key_pem: str) -> bytes:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key_text = _normalize_private_key(private_key_pem)
        if "BEGIN" not in key_text:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="Invalid GitHub private key format.",
                provider="github",
            )
        try:
            private_key = serialization.load_pem_private_key(
                key_text.encode("utf-8"), password=None,
            )
            return private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="Failed signing GitHub App JWT with private key.",
                provider="github",
                snippet=str(exc)[:240] or None,
            ) from exc


__all__ = [
    "DeterministicExecutionError",
    "DeterministicWebExecutor",
    "REASON_GITHUB_AUTH_FAILED",
    "REASON_GITHUB_REPO_CREATE_FAILED",
    "REASON_VERCEL_PROJECT_CREATE_FAILED",
    "REASON_VERCEL_DEPLOY_FAILED",
    "REASON_CODE_GENERATION_FAILED",
    "REASON_CODEGEN_CONFLICT_DETECTED",
    "REASON_CODEGEN_AUTOFIX_STALLED",
    "_is_deterministic_plan",
]
