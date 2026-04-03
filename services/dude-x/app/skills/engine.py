"""Skills engine: orchestrates skill execution in dependency order."""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.models.governed_v2 import BuildSoTV1
from app.skills.base import FileOperation, Skill, SkillContext

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    lowered = value.lower()
    chars = [c if c.isalnum() else "-" for c in lowered]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "project"


def _render_repo_name(project_slug: str) -> str:
    template = settings.governed_v2_repo_name_template or "cdmbr-{projectname}-{timestamp}"
    return template.replace("{projectname}", project_slug)


def _all_skills() -> list[Skill]:
    from app.skills.design import DesignSkill
    from app.skills.integrations import IntegrationsSkill
    from app.skills.layout import LayoutSkill
    from app.skills.pages import PagesSkill
    from app.skills.scaffold import ScaffoldSkill
    from app.skills.seo import SEOSkill

    return [
        ScaffoldSkill(),
        DesignSkill(),
        LayoutSkill(),
        PagesSkill(),
        IntegrationsSkill(),
        SEOSkill(),
    ]


def _topological_sort(skills: list[Skill]) -> list[Skill]:
    """Sort skills by dependency order."""
    by_name = {s.name: s for s in skills}
    visited: set[str] = set()
    order: list[Skill] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        skill = by_name.get(name)
        if skill is None:
            return
        for dep in skill.depends_on:
            visit(dep)
        order.append(skill)

    for s in skills:
        visit(s.name)
    return order


class SkillsEngine:
    """Orchestrates all skills and collects file operations."""

    def __init__(self, build_sot: BuildSoTV1) -> None:
        self.build_sot = build_sot
        project_slug = _slugify(build_sot.project_name)
        self.ctx = SkillContext(
            build_sot=build_sot,
            project_slug=project_slug,
            repo_name=_render_repo_name(project_slug),
            framework=settings.governed_v2_stack_preset,
        )

    async def run(self) -> list[FileOperation]:
        """Execute all skills in dependency order, returning collected file operations."""
        skills = _topological_sort(_all_skills())
        all_files: list[FileOperation] = []
        seen_paths: set[str] = set()

        for skill in skills:
            logger.info("skills_engine.run_skill name=%s", skill.name)
            try:
                files = await skill.generate(self.ctx)
                for f in files:
                    if f.path not in seen_paths:
                        all_files.append(f)
                        seen_paths.add(f.path)
                    else:
                        logger.warning(
                            "skills_engine.duplicate_path skill=%s path=%s",
                            skill.name, f.path,
                        )
            except Exception:
                logger.exception("skills_engine.skill_failed name=%s", skill.name)

        logger.info("skills_engine.complete total_files=%d", len(all_files))
        return all_files

    def to_operations(self, file_ops: list[FileOperation]) -> list[dict[str, Any]]:
        """Convert file operations into the standard operations format for governance."""
        ops: list[dict[str, Any]] = []
        github_owner = (settings.governed_v2_github_owner or "").strip()
        github_owner_fallback = (settings.governed_v2_github_owner_fallback or "").strip()
        owner_type = (settings.governed_v2_github_owner_type or "org").strip().lower()
        default_branch = (settings.governed_v2_default_branch or "prod").strip()
        team_id = (settings.governed_v2_vercel_team_id or "").strip()
        domain_behavior = (settings.governed_v2_domain_behavior or "vercel_default_only").strip()

        ops.append({
            "op_id": "op-001",
            "type": "provision_repo",
            "target": "repo",
            "inputs": {
                "provider": "github",
                "owner": github_owner,
                "owner_type": owner_type,
                "fallback_owner": github_owner_fallback,
                "repo_name_template": settings.governed_v2_repo_name_template,
                "repo_name": self.ctx.repo_name,
                "default_branch": default_branch,
                "visibility": "private",
            },
            "outputs": {},
        })

        ops.append({
            "op_id": "op-002",
            "type": "provision_hosting",
            "target": "hosting/vercel",
            "inputs": {
                "provider": "vercel",
                "team_id": team_id,
                "project_name": self.ctx.repo_name,
                "linked_repo_name": self.ctx.repo_name,
                "production_branch": default_branch,
                "domain_behavior": domain_behavior,
            },
            "outputs": {},
        })

        for idx, fop in enumerate(file_ops, start=3):
            op_type = "write_config" if fop.file_type == "config" else "create_file"
            ops.append({
                "op_id": f"op-{idx:03d}",
                "type": op_type,
                "target": "repo",
                "inputs": {
                    "path": fop.path,
                    "content": fop.content,
                },
                "outputs": {},
            })

        ops.append({
            "op_id": f"op-{len(ops) + 1:03d}",
            "type": "build",
            "target": "repo",
            "inputs": {"command": "run_smoke_checks"},
            "outputs": {},
        })

        ops.append({
            "op_id": f"op-{len(ops) + 1:03d}",
            "type": "deploy",
            "target": "hosting/vercel",
            "inputs": {
                "provider": "vercel",
                "team_id": team_id,
                "project": self.ctx.repo_name,
                "branch": default_branch,
                "domain_behavior": domain_behavior,
            },
            "outputs": {},
        })

        return ops
