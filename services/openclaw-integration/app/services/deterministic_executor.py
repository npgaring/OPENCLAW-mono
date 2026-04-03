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
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
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
REASON_CODE_GENERATION_FAILED = "EXECUTION_CODE_GENERATION_FAILED"

CODEGEN_TIMEOUT_SECONDS = 180
GITHUB_TIMEOUT_SECONDS = 60
VERCEL_TIMEOUT_SECONDS = 60
BRANCH_RETRY_DELAYS = (2, 3, 5, 8)


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


class DeterministicWebExecutor:
    """Multi-phase executor: repo → codegen → commit → deploy."""

    def __init__(self, *, timeout_seconds: float = 300.0):
        self.timeout_seconds = timeout_seconds

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

        # ── Phase 2: Generate Code via OpenAI ─────────────────────────
        logger.info("deterministic.executor.phase2_start task_id=%s", task_id)
        generated_files = await self._generate_code_via_openai(
            plan,
            operations,
            trace_id=trace_id,
            template_reference=template_reference,
        )
        steps_completed.append("generate_code")
        tsconfig_content = next((gf.content[:300] for gf in generated_files if gf.path == "tsconfig.json"), "MISSING")
        postcss_content = next((gf.content[:200] for gf in generated_files if gf.path == "postcss.config.mjs"), "MISSING")
        logger.info(
            "deterministic.executor.phase2_debug task_id=%s file_count=%d has_at_alias=%s",
            task_id,
            len(generated_files),
            "@/*" in tsconfig_content,
        )
        logger.debug(
            "deterministic.executor.phase2_files task_id=%s paths=%s tsconfig_snippet=%s postcss_snippet=%s",
            task_id,
            [gf.path for gf in generated_files],
            tsconfig_content,
            postcss_content,
        )
        logger.info(
            "deterministic.executor.phase2_done task_id=%s files_generated=%d",
            task_id, len(generated_files),
        )

        # ── Phase 3: Batch Commit Files to GitHub ─────────────────────
        logger.info("deterministic.executor.phase3_start task_id=%s", task_id)
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS) as gh_client:
            github_installation_token = await self._github_installation_token(gh_client)
            commit_sha = await self._github_batch_commit(
                gh_client,
                github_installation_token,
                owner=repo.owner,
                repo=repo.name,
                branch=repo_spec.branch,
                files=generated_files,
                message=f"feat: initial site generation via deterministic_web_v1\n\nTask: {task_id}\nTrace: {trace_id or 'N/A'}",
            )
        steps_completed.append("write_files")
        logger.info(
            "deterministic.executor.phase3_done task_id=%s commit_sha=%s",
            task_id, commit_sha,
        )

        # ── Phase 4: Create Vercel Project and Deploy via File Upload ──
        logger.info("deterministic.executor.phase4_start task_id=%s", task_id)
        async with httpx.AsyncClient(timeout=VERCEL_TIMEOUT_SECONDS) as vc_client:
            vercel_project = await self._vercel_create_or_resolve_project(
                vc_client,
                team_id=hosting_team_id,
                project_name=project_name,
                github_owner=repo.owner,
                github_repo=repo.name,
                production_branch=deploy_branch,
            )
            deployment = await self._vercel_deploy_files(
                vc_client,
                team_id=hosting_team_id,
                project_name=vercel_project.name,
                files=generated_files,
                target=deploy_target,
            )
        steps_completed.append("provision_hosting")
        steps_completed.append("deploy")
        logger.info(
            "deterministic.executor.phase4_done task_id=%s deployment_url=%s",
            task_id, deployment.url,
        )

        deployment_url = self._normalize_deployment_url(deployment.url)
        artifacts = [
            {"path": repo.html_url, "type": "repository", "summary": "GitHub repository created and code committed."},
        ]
        if deployment_url:
            artifacts.append({"path": deployment_url, "type": "deployment", "summary": "Vercel deployment triggered from committed code."})
        result: dict[str, Any] = {
            "execution_id": execution_id,
            "status": "success",
            "message": f"Pipeline completed: {len(generated_files)} files generated and deployed.",
            "artifacts": artifacts,
            "steps_completed": steps_completed,
            "repository_url": repo.html_url,
            "repo_commit_sha": commit_sha,
            "deployment_id": deployment.id,
            "deployment_url": deployment_url,
            "files_generated": len(generated_files),
            "provider_ids": {"vercel_project_id": vercel_project.id},
        }
        if deploy_target == "preview":
            result["preview_url"] = deployment_url
        return result

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
    # Phase 2: OpenAI Code Generation
    # ------------------------------------------------------------------
    async def _generate_code_via_openai(
        self,
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        trace_id: Optional[str] = None,
        template_reference: Optional[TemplateReference] = None,
    ) -> list[GeneratedFile]:
        """Use OpenAI to generate production-quality website code from the execution plan.

        Falls back to the plan's inline file content when OpenAI is unavailable.
        """
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            logger.warning("deterministic.executor.codegen.no_api_key falling back to plan content")
            return self._ensure_scaffold_integrity(
                self._extract_files_from_operations(operations),
                template_reference=template_reference,
            )

        file_specs = self._collect_file_specs(operations, plan)
        if not file_specs:
            logger.warning("deterministic.executor.codegen.no_files falling back to plan content")
            return self._ensure_scaffold_integrity(
                self._extract_files_from_operations(operations),
                template_reference=template_reference,
            )

        project_context = self._build_project_context(plan, operations)
        generated: list[GeneratedFile] = []

        model = (
            getattr(settings, "openai_content_model", None)
            or getattr(settings, "skills_engine_model", None)
            or settings.openai_plan_model
            or "gpt-4o-mini"
        )

        batch_prompt = self._build_codegen_prompt(
            project_context,
            file_specs,
            template_reference=template_reference,
        )

        try:
            async with httpx.AsyncClient(timeout=CODEGEN_TIMEOUT_SECONDS) as client:
                resp, data = await self._request(
                    client,
                    "POST",
                    f"{OPENAI_API_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    payload={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": self._codegen_system_prompt()},
                            {"role": "user", "content": batch_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 16000,
                    },
                )
            if resp.status_code != 200:
                logger.error(
                    "deterministic.executor.codegen.openai_error status=%s body=%s",
                    resp.status_code, str(data)[:300],
                )
                return self._ensure_scaffold_integrity(
                    self._extract_files_from_operations(operations),
                    template_reference=template_reference,
                )

            content = ""
            if isinstance(data, dict):
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")

            generated = self._parse_codegen_response(content, file_specs)
            logger.info(
                "deterministic.executor.codegen.success model=%s files_parsed=%d",
                model, len(generated),
            )
        except Exception:
            logger.exception("deterministic.executor.codegen.exception")
            return self._ensure_scaffold_integrity(
                self._extract_files_from_operations(operations),
                template_reference=template_reference,
            )

        if not generated:
            generated = self._extract_files_from_operations(operations)
        return self._ensure_scaffold_integrity(generated, template_reference=template_reference)

    def _codegen_system_prompt(self) -> str:
        return (
            "You are an expert full-stack web developer specializing in Next.js App Router, React 19, TypeScript, and Tailwind CSS v4.\n"
            "You generate production-quality code for complete websites.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "- Use Next.js App Router and match the existing template layout (app/ or src/app/).\n"
            "- Tailwind CSS v4 does NOT use tailwind.config.ts — it uses CSS-based configuration.\n"
            "  In globals.css, use: @import \"tailwindcss\";\n"
            "- PostCSS config (postcss.config.mjs) MUST use @tailwindcss/postcss, NOT tailwindcss:\n"
            "  export default { plugins: { \"@tailwindcss/postcss\": {} } };\n"
            "- package.json MUST include @tailwindcss/postcss as a dependency.\n"
            "- For MetadataRoute.Robots, use lowercase rule keys only: userAgent, allow, disallow, crawlDelay.\n"
            "- Do NOT generate tailwind.config.ts or tailwind.config.js — Tailwind v4 does not use them.\n"
            "- EVERY component imported in any file MUST be generated as a separate file.\n"
            "  For example, if layout.tsx imports NavBar and Footer, you MUST generate src/components/NavBar.tsx and src/components/Footer.tsx.\n"
            "- All components must be exported as named exports.\n"
            "- ALWAYS import every identifier you use. Common Next.js imports:\n"
            "  import Link from \"next/link\";\n"
            "  import Image from \"next/image\";\n"
            "  import { useRouter, usePathname } from \"next/navigation\";\n"
            "  import type { Metadata } from \"next\";\n"
            "- Use modern, clean, well-structured code with real content (no Lorem Ipsum).\n"
            "- Make designs responsive and mobile-friendly using Tailwind CSS utility classes.\n"
            "- Use proper TypeScript types.\n"
            "- Optimize for performance and SEO.\n\n"
            "When generating code, output ONLY the file contents in the exact format requested. "
            "Do not add explanatory text outside of code blocks."
        )

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

    def _collect_file_specs(self, operations: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, str]]:
        specs: list[dict[str, str]] = []
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
            specs.append({"path": path, "hint": str(inputs.get("content") or "")[:200]})
        return specs

    def _build_codegen_prompt(
        self,
        context: dict[str, Any],
        file_specs: list[dict[str, str]],
        *,
        template_reference: Optional[TemplateReference] = None,
    ) -> str:
        parts: list[str] = []
        parts.append("Generate production-quality code for a Next.js website with the following specifications:\n")

        if context.get("goal"):
            parts.append(f"**Project Goal:** {context['goal']}\n")
        if context.get("context"):
            parts.append(f"**Project Context:** {context['context']}\n")
        if context.get("framework"):
            parts.append(f"**Framework:** {context['framework']}\n")
        if context.get("routes"):
            parts.append(f"**Routes:** {json.dumps(context['routes'])}\n")
        if context.get("components"):
            parts.append(f"**Components:** {json.dumps(context['components'][:20])}\n")
        if context.get("content_blocks"):
            blocks = context["content_blocks"]
            if isinstance(blocks, list):
                parts.append(f"**Content Blocks:** {json.dumps(blocks[:10])}\n")
        if context.get("acceptance_criteria"):
            parts.append(f"**Acceptance Criteria:** {json.dumps(context['acceptance_criteria'])}\n")

        if template_reference and template_reference.source_repo:
            parts.append(
                f"**Template Reference:** {template_reference.source_repo}@{template_reference.source_branch or 'main'}\n"
            )
            pkg = template_reference.package_json if isinstance(template_reference.package_json, dict) else {}
            template_deps = pkg.get("dependencies") if isinstance(pkg.get("dependencies"), dict) else {}
            template_dev_deps = pkg.get("devDependencies") if isinstance(pkg.get("devDependencies"), dict) else {}
            if template_deps:
                parts.append(f"**Template Dependencies:** {json.dumps(template_deps)}\n")
            if template_dev_deps:
                parts.append(f"**Template DevDependencies:** {json.dumps(template_dev_deps)}\n")
            if template_reference.key_files:
                parts.append(
                    "**Template Baseline Files Present:** "
                    + json.dumps(sorted(template_reference.key_files.keys()))
                    + "\n"
                )

        parts.append("\n**Files to generate:**\n")
        for spec in file_specs:
            hint_note = f" (hint: {spec['hint']})" if spec["hint"] and "generated for" not in spec["hint"] else ""
            parts.append(f"- `{spec['path']}`{hint_note}")

        parts.append("\n\n**Output format:** For each file, output the following format EXACTLY:\n")
        parts.append("```\n===FILE: path/to/file.ext===\n<file content here>\n===END_FILE===\n```\n")
        parts.append("\nGenerate ALL files listed above. Each file must contain complete, runnable code.\n")
        parts.append("MANDATORY RULES:\n")
        parts.append("1. package.json MUST include these dependencies: next, react, react-dom, tailwindcss, @tailwindcss/postcss, typescript, @types/react, @types/node\n")
        parts.append("2. postcss.config.mjs MUST use: export default { plugins: { \"@tailwindcss/postcss\": {} } };\n")
        parts.append("3. globals.css MUST start with: @import \"tailwindcss\";\n")
        parts.append("4. Do NOT include tailwind.config.ts or tailwind.config.js\n")
        parts.append("5. EVERY component referenced via import MUST have its own generated file\n")
        parts.append("6. Use Tailwind CSS utility classes for all styling\n")
        parts.append("7. In robots.ts rules, use lowercase keys only: userAgent/allow/disallow/crawlDelay.\n")
        parts.append("8. Preserve template conventions and module choices where possible.\n")
        parts.append("9. If new external libraries are required by imports, update package.json accordingly.")
        parts.append("10. Make the website beautiful, modern, and responsive with real content relevant to the project goal.")

        return "\n".join(parts)

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
                file_content = content[file_content_start:].strip()
                files.append(GeneratedFile(path=path, content=file_content))
                break
            file_content = content[file_content_start:end].strip()
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

        # ── next.config.ts: ensure valid ─────────────────────────────────
        if "next.config.ts" not in file_map and "next.config.js" not in file_map and "next.config.mjs" not in file_map:
            file_map["next.config.ts"] = GeneratedFile(
                path="next.config.ts",
                content='import type { NextConfig } from "next";\n\nconst nextConfig: NextConfig = {};\n\nexport default nextConfig;\n',
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
        for dep_name in list(REQUIRED_DEPS.keys()):
            template_version = template_deps.get(dep_name) or template_dev_deps.get(dep_name)
            if isinstance(template_version, str) and template_version.strip():
                REQUIRED_DEPS[dep_name] = template_version
        for dep_name in list(REQUIRED_DEV_DEPS.keys()):
            template_version = template_dev_deps.get(dep_name)
            if isinstance(template_version, str) and template_version.strip():
                REQUIRED_DEV_DEPS[dep_name] = template_version

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
            deps.setdefault(k, v)

        dev = pkg.setdefault("devDependencies", {})
        if not isinstance(dev, dict):
            dev = {}
            pkg["devDependencies"] = dev
        for k, v in template_dev_deps.items():
            if isinstance(v, str):
                dev.setdefault(k, v)
        for k, v in REQUIRED_DEV_DEPS.items():
            dev.setdefault(k, v)

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

        self._augment_package_dependencies_from_imports(
            file_map,
            deps=deps,
            dev_deps=dev,
            template_reference=template_reference,
        )
        file_map[pkg_path] = GeneratedFile(path=pkg_path, content=json.dumps(pkg, indent=2) + "\n")

        # ── Remove legacy tailwind config files ──────────────────────────
        for path in ("tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs"):
            file_map.pop(path, None)

        # ── Fill missing component imports ────────────────────────────────
        self._fill_missing_component_imports(file_map)

        # ── Auto-fix missing standard imports in all tsx/ts files ────────
        self._fix_missing_standard_imports(file_map)

        # ── Normalize MetadataRoute.Robots key casing ────────────────────
        self._normalize_robots_metadata_keys(file_map)

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
    def _fill_missing_component_imports(file_map: dict[str, GeneratedFile]) -> None:
        """Scan all .tsx/.ts files for @/ imports and create stubs for missing modules."""
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
                file_map[path] = GeneratedFile(path=path, content=prefix + f.content)
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
                content = content_value
            elif content_value is None:
                content = ""
            else:
                content = json.dumps(content_value, ensure_ascii=False)
            files.append(GeneratedFile(path=path, content=content))
        return files

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
                "installCommand": "npm install",
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
        key_text = _normalize_private_key(private_key_pem)
        if "BEGIN" not in key_text:
            raise DeterministicExecutionError(
                reason_code=REASON_GITHUB_AUTH_FAILED,
                message="Invalid GitHub private key format.",
                provider="github",
            )
        path = ""
        try:
            with tempfile.NamedTemporaryFile("w", delete=False) as key_file:
                path = key_file.name
                key_file.write(key_text)
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", path],
                input=payload,
                capture_output=True,
                check=False,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
                raise DeterministicExecutionError(
                    reason_code=REASON_GITHUB_AUTH_FAILED,
                    message="Failed signing GitHub App JWT with private key.",
                    provider="github",
                    snippet=" ".join(stderr.split())[:240] or None,
                )
            return proc.stdout
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    logger.warning("deterministic.executor.jwt.cleanup_failed", extra={"path": path})


__all__ = [
    "DeterministicExecutionError",
    "DeterministicWebExecutor",
    "REASON_GITHUB_AUTH_FAILED",
    "REASON_GITHUB_REPO_CREATE_FAILED",
    "REASON_VERCEL_PROJECT_CREATE_FAILED",
    "REASON_VERCEL_DEPLOY_FAILED",
    "REASON_CODE_GENERATION_FAILED",
    "_is_deterministic_plan",
]
