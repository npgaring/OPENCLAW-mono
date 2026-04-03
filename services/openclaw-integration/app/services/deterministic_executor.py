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
        steps_completed.append("provision_repo")
        logger.info(
            "deterministic.executor.phase1_done task_id=%s repo_url=%s",
            task_id, repo.html_url,
        )

        # ── Phase 2: Generate Code via OpenAI ─────────────────────────
        logger.info("deterministic.executor.phase2_start task_id=%s", task_id)
        generated_files = await self._generate_code_via_openai(plan, operations, trace_id=trace_id)
        steps_completed.append("generate_code")
        # #region agent log
        import json as _json2, time as _time2
        _log_path2 = "/Users/braiebook/CDHQ Projects/OpenClaw-Mono/OPENCLAW-mono/.cursor/debug-5138fb.log"
        _tsconfig_content = next((gf.content[:300] for gf in generated_files if gf.path == "tsconfig.json"), "MISSING")
        _postcss_content = next((gf.content[:200] for gf in generated_files if gf.path == "postcss.config.mjs"), "MISSING")
        with open(_log_path2, "a") as _f: _f.write(_json2.dumps({"sessionId":"5138fb","hypothesisId":"H2-files","location":"deterministic_executor.py:execute:phase2_done","message":"generated_files_after_scaffold","data":{"file_count":len(generated_files),"file_paths":[gf.path for gf in generated_files],"branch":repo_spec.branch,"tsconfig_snippet":_tsconfig_content,"postcss_snippet":_postcss_content,"has_at_alias":"@/*" in _tsconfig_content},"timestamp":int(_time2.time()*1000)}) + "\n")
        # #endregion
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
    ) -> list[GeneratedFile]:
        """Use OpenAI to generate production-quality website code from the execution plan.

        Falls back to the plan's inline file content when OpenAI is unavailable.
        """
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            logger.warning("deterministic.executor.codegen.no_api_key falling back to plan content")
            return self._ensure_scaffold_integrity(self._extract_files_from_operations(operations))

        file_specs = self._collect_file_specs(operations, plan)
        if not file_specs:
            logger.warning("deterministic.executor.codegen.no_files falling back to plan content")
            return self._ensure_scaffold_integrity(self._extract_files_from_operations(operations))

        project_context = self._build_project_context(plan, operations)
        generated: list[GeneratedFile] = []

        model = (
            getattr(settings, "openai_content_model", None)
            or getattr(settings, "skills_engine_model", None)
            or settings.openai_plan_model
            or "gpt-4o-mini"
        )

        batch_prompt = self._build_codegen_prompt(project_context, file_specs)

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
                return self._extract_files_from_operations(operations)

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
            return self._ensure_scaffold_integrity(self._extract_files_from_operations(operations))

        if not generated:
            generated = self._extract_files_from_operations(operations)
        return self._ensure_scaffold_integrity(generated)

    def _codegen_system_prompt(self) -> str:
        return (
            "You are an expert full-stack web developer specializing in Next.js 16+, React 19, TypeScript, and Tailwind CSS v4.\n"
            "You generate production-quality code for complete websites.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "- Use Next.js App Router (src/app/ directory structure)\n"
            "- Tailwind CSS v4 does NOT use tailwind.config.ts — it uses CSS-based configuration.\n"
            "  In globals.css, use: @import \"tailwindcss\";\n"
            "- PostCSS config (postcss.config.mjs) MUST use @tailwindcss/postcss, NOT tailwindcss:\n"
            "  export default { plugins: { \"@tailwindcss/postcss\": {} } };\n"
            "- package.json MUST include @tailwindcss/postcss as a dependency.\n"
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

    def _build_codegen_prompt(self, context: dict[str, Any], file_specs: list[dict[str, str]]) -> str:
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
        parts.append("7. Make the website beautiful, modern, and responsive with real content relevant to the project goal.")

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

    def _ensure_scaffold_integrity(self, files: list[GeneratedFile]) -> list[GeneratedFile]:
        """Validate and fix critical scaffold files to guarantee a buildable project.

        Forces known-good content for tsconfig, postcss, and globals.css.
        Ensures package.json has all required deps.
        Strips legacy tailwind config files.
        Fills any missing component files referenced by imports.
        """
        file_map = {f.path: f for f in files}

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
                co["paths"] = {"@/*": ["./src/*"]}
                plugins = co.get("plugins", [])
                if not any(p.get("name") == "next" for p in plugins if isinstance(p, dict)):
                    plugins.append({"name": "next"})
                co["plugins"] = plugins
                ts.setdefault("include", ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"])
                ts.setdefault("exclude", ["node_modules"])
                file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=json.dumps(ts, indent=2) + "\n")
            except (json.JSONDecodeError, TypeError):
                file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=self._TSCONFIG_FALLBACK)
        else:
            file_map[tsconfig_path] = GeneratedFile(path=tsconfig_path, content=self._TSCONFIG_FALLBACK)

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
        globals_path = "src/app/globals.css"
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

        # ── package.json: ensure required dependencies ───────────────────
        REQUIRED_DEPS = {
            "next": "^16.0.0",
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
            "tailwindcss": "^4.0.0",
            "@tailwindcss/postcss": "^4.0.0",
        }
        REQUIRED_DEV_DEPS = {
            "typescript": "^5",
            "@types/node": "^22",
            "@types/react": "^19",
            "@types/react-dom": "^19",
        }
        pkg_path = "package.json"
        existing_pkg = file_map.get(pkg_path)
        if existing_pkg:
            try:
                pkg = json.loads(existing_pkg.content)
                deps = pkg.setdefault("dependencies", {})
                for k, v in REQUIRED_DEPS.items():
                    deps.setdefault(k, v)
                dev = pkg.setdefault("devDependencies", {})
                for k, v in REQUIRED_DEV_DEPS.items():
                    dev.setdefault(k, v)
                scripts = pkg.setdefault("scripts", {})
                scripts.setdefault("dev", "next dev --turbopack")
                scripts.setdefault("build", "next build")
                scripts.setdefault("start", "next start")
                scripts.setdefault("lint", "next lint")
                file_map[pkg_path] = GeneratedFile(path=pkg_path, content=json.dumps(pkg, indent=2) + "\n")
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Remove legacy tailwind config files ──────────────────────────
        for path in ("tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs"):
            file_map.pop(path, None)

        # ── Fill missing component imports ────────────────────────────────
        self._fill_missing_component_imports(file_map)

        # ── Auto-fix missing standard imports in all tsx/ts files ────────
        self._fix_missing_standard_imports(file_map)

        return list(file_map.values())

    _TSCONFIG_FALLBACK = json.dumps({
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
            "paths": {"@/*": ["./src/*"]},
            "plugins": [{"name": "next"}],
        },
        "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
        "exclude": ["node_modules"],
    }, indent=2) + "\n"

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
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {installation_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "owner": spec.owner,
            "name": spec.name,
            "private": spec.private,
            "include_all_branches": False,
        }
        resp, data = await self._request(client, "POST", url, headers=headers, payload=payload)
        # #region agent log
        import json as _json, time as _time
        _log_path = "/Users/braiebook/CDHQ Projects/OpenClaw-Mono/OPENCLAW-mono/.cursor/debug-5138fb.log"
        with open(_log_path, "a") as _f: _f.write(_json.dumps({"sessionId":"5138fb","hypothesisId":"H1-visibility","location":"deterministic_executor.py:_github_provision_repo","message":"repo_create_result","data":{"status_code":resp.status_code,"private_flag_sent":spec.private,"visibility":str(data.get("visibility","")) if isinstance(data,dict) else "","html_url":str(data.get("html_url",""))[:150] if isinstance(data,dict) else "","private_returned":data.get("private") if isinstance(data,dict) else ""},"timestamp":int(_time.time()*1000)}) + "\n")
        # #endregion
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
        if resp.status_code == 404:
            logger.warning(
                "deterministic.executor.template_not_found template=%s/%s falling_back_to_empty_repo",
                template_owner, template_repo,
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
        """Fallback: create a regular empty repo when the template repo is unavailable."""
        pat = (settings.github_token or "").strip()
        auth_token = pat or installation_token
        token_type = "pat" if pat else "installation"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {auth_token}" if token_type == "installation" else f"token {auth_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        create_url = f"{GITHUB_API_BASE}/user/repos"
        create_payload = {
            "name": spec.name,
            "private": spec.private,
            "auto_init": True,
            "description": "Auto-generated by OpenClaw deterministic executor",
        }
        resp, data = await self._request(client, "POST", create_url, headers=headers, payload=create_payload)
        if resp.status_code in (200, 201):
            return RepoProvisionResult(
                owner=str(data.get("owner", {}).get("login", spec.owner)),
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
        logger.error(
            "deterministic.executor.empty_repo_create_failed status=%s token_type=%s body=%s",
            resp.status_code, token_type, str(data)[:300],
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
