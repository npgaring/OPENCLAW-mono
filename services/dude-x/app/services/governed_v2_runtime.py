"""Deterministic governed DUDE-X v2 runtime helpers."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from app.core.config import settings
from app.core.hashing import hash_payload, integration_hash_payload
from app.models.governed_v2 import (
    ArtifactStatus,
    BuildSoTV1,
    CognitiveOutcome,
    ExecutionPlanCommand,
    ExecutionPlanV1,
    RawIntentSubmitRequest,
    SectionDefinition,
    StageLinkage,
)


_WEB_ONLY_ERROR = "GOVERNED_V2_WEB_ONLY"


@dataclass(frozen=True)
class CognitiveResult:
    raw_intent_hash: str
    build_sot_hash: str
    build_sot: BuildSoTV1
    linkage: StageLinkage
    cognitive_outcome: CognitiveOutcome
    raw_payload: dict[str, Any]
    enrichment_status: Optional[str] = None
    enrichment_warning: Optional[dict[str, Any]] = None


def normalize_raw_payload(body: RawIntentSubmitRequest, trace_id: str) -> dict[str, Any]:
    return {
        "idea": (body.idea or "").strip(),
        "voice": (body.voice or "").strip(),
        "brief": body.brief or {},
        "clarifications": body.clarifications or {},
        "ocgg_identity": body.ocgg_identity,
        "intent": body.intent,
        "deployment_target": body.deployment_target,
        "trace_id": trace_id,
    }


def run_cognitive_mode(body: RawIntentSubmitRequest, trace_id: str) -> CognitiveResult:
    raw_payload = normalize_raw_payload(body, trace_id)
    raw_intent_hash = hash_payload(raw_payload)
    build_sot = _build_sot_from_raw(body, raw_payload)
    build_sot_hash = hash_payload(build_sot.model_dump(mode="python"))
    linkage = StageLinkage(
        trace_id=trace_id,
        raw_intent_hash=raw_intent_hash,
        build_sot_hash=build_sot_hash,
        artifact_hash=build_sot_hash,
    )
    return CognitiveResult(
        raw_intent_hash=raw_intent_hash,
        build_sot_hash=build_sot_hash,
        build_sot=build_sot,
        linkage=linkage,
        cognitive_outcome=_cognitive_outcome(build_sot),
        raw_payload=raw_payload,
    )


async def run_cognitive_mode_async(body: RawIntentSubmitRequest, trace_id: str) -> CognitiveResult:
    """Async version of run_cognitive_mode with optional OpenAI content enrichment."""
    from app.services.content_enrichment import enrich_build_sot_with_metadata

    result = run_cognitive_mode(body, trace_id)
    if settings.openai_content_enabled and result.cognitive_outcome.value == "PASS":
        enriched_sot, enrichment_status, enrichment_warning = await enrich_build_sot_with_metadata(result.build_sot)
        enriched_hash = hash_payload(enriched_sot.model_dump(mode="python"))
        enriched_linkage = StageLinkage(
            trace_id=trace_id,
            raw_intent_hash=result.raw_intent_hash,
            build_sot_hash=enriched_hash,
            artifact_hash=enriched_hash,
        )
        return CognitiveResult(
            raw_intent_hash=result.raw_intent_hash,
            build_sot_hash=enriched_hash,
            build_sot=enriched_sot,
            linkage=enriched_linkage,
            cognitive_outcome=result.cognitive_outcome,
            raw_payload=result.raw_payload,
            enrichment_status=enrichment_status,
            enrichment_warning=enrichment_warning,
        )
    return result


def apply_build_sot_patch(existing: BuildSoTV1, patch: dict[str, Any]) -> BuildSoTV1:
    merged = existing.model_dump(mode="python")
    for k, v in (patch or {}).items():
        merged[k] = v
    rebuilt = BuildSoTV1.model_validate(merged)
    # Re-run unresolved and contradiction derivation deterministically.
    unresolved, contradictions = _unresolved_and_contradictions(
        identity="W-OCGG",
        intent="web-build",
        project_name=rebuilt.project_name,
        site_purpose=rebuilt.site_purpose,
        target_audience=rebuilt.target_audience,
        desired_tone=rebuilt.desired_tone,
        page_list=rebuilt.page_list,
        deployment_target=rebuilt.deployment_target,
        text=_collect_text_from_build_sot(rebuilt),
    )
    status, approval_status = _status_from_findings(unresolved, contradictions)
    rebuilt.unresolved_items = unresolved
    rebuilt.contradictions = contradictions
    rebuilt.status = status
    rebuilt.approval_status = approval_status
    rebuilt.content_blocks = _agcc_content_blocks(rebuilt)
    return rebuilt


def governance_projection_for_build_sot(
    *,
    build_sot_hash: str,
    trace_id: str,
    build_sot: BuildSoTV1,
    ocgg_identity: str,
) -> tuple[dict[str, Any], str]:
    operations = _operations_from_build_sot(build_sot, trace_id=trace_id)
    plan_hash = integration_hash_payload({"domain": "web", "operations": operations})
    projection = {
        "ocgg_identity": ocgg_identity,
        "plan_hash": plan_hash,
        "operations": operations,
        "goal": build_sot.site_purpose,
        "context": f"{build_sot.project_name} | tone={build_sot.desired_tone}",
        "acceptance_criteria": list(build_sot.acceptance_criteria),
        "deployment_target": build_sot.deployment_target,
        "trace_id": trace_id,
        "build_sot_hash": build_sot_hash,
    }
    return projection, plan_hash


def compile_execution_plan(
    *,
    trace_id: str,
    build_sot_hash: str,
    build_sot: BuildSoTV1,
    ocgg_identity: str,
    intent: str,
    compiler_version: str = "governed-v2-compiler-1",
) -> tuple[ExecutionPlanV1, str]:
    operations = _operations_from_build_sot(build_sot, trace_id=trace_id)
    governance_plan_hash = integration_hash_payload({"domain": "web", "operations": operations})
    schema_blocks = []
    for form in build_sot.forms_ctas:
        schema_blocks.append({"name": form, "kind": "form_or_cta", "required_fields": ["name", "email"]})
    template_family = _template_family(build_sot.page_list)
    routes = [_route_for_page(page) for page in build_sot.page_list]
    file_tree = [f"site{r}.html" if r != "/" else "site/index.html" for r in routes]
    commands = [
        ExecutionPlanCommand(id="cmd-001", type="scaffold", command="scaffold_nextjs_typescript_app", target="repo"),
        ExecutionPlanCommand(id="cmd-002", type="provision_repo", command="create_github_repo", target="repo"),
        ExecutionPlanCommand(id="cmd-003", type="provision_hosting", command="create_vercel_project", target="hosting"),
        ExecutionPlanCommand(id="cmd-004", type="write_files", command="write_page_files", target="repo"),
        ExecutionPlanCommand(id="cmd-005", type="smoke", command="run_smoke_checks", target="repo"),
        ExecutionPlanCommand(
            id="cmd-006",
            type="deploy",
            command="deploy_production" if build_sot.deployment_target == "production" else "deploy_preview",
            target="hosting",
        ),
    ]
    governance_projection = {
        "ocgg_identity": ocgg_identity,
        "plan_hash": governance_plan_hash,
        "operations": operations,
        "deployment_target": build_sot.deployment_target,
        "goal": build_sot.site_purpose,
        "context": f"{build_sot.project_name} | tone={build_sot.desired_tone}",
        "acceptance_criteria": list(build_sot.acceptance_criteria),
        "trace_id": trace_id,
        "build_sot_hash": build_sot_hash,
    }
    lineage = StageLinkage(
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        governance_plan_hash=governance_plan_hash,
    )
    plan = ExecutionPlanV1(
        template_family=template_family,
        scaffold_type="nextjs_app_router",
        framework=settings.governed_v2_stack_preset,
        executor_contract="deterministic_web_v1",
        routes=routes,
        components=[{"id": f"cmp-{i + 1:03d}", "name": s.section, "page": s.page} for i, s in enumerate(build_sot.section_definitions)],
        file_tree=file_tree,
        content_blocks=build_sot.content_blocks,
        schema_blocks=schema_blocks,
        integrations=list(build_sot.integrations),
        env_vars=_env_vars_for_integrations(build_sot.integrations),
        commands=commands,
        smoke_expectations=[
            "all_routes_render",
            "navigation_links_resolve",
            "primary_cta_present",
        ],
        deploy_target=build_sot.deployment_target,
        rollback_strategy={"type": "artifact_redeploy", "target": "site"},
        operations=operations,
        governance_projection=governance_projection,
        stage_linkage=lineage.model_copy(update={"artifact_hash": None}),
        status=ArtifactStatus.compiled,
        compiler_version=compiler_version,
        ocgg_identity=ocgg_identity,
        intent=intent,
        build_sot_hash=build_sot_hash,
    )
    execution_plan_hash = hash_payload(plan.model_dump(mode="python"))
    plan.stage_linkage = plan.stage_linkage.model_copy(
        update={
            "execution_plan_hash": execution_plan_hash,
            "artifact_hash": execution_plan_hash,
        }
    )
    plan.governance_projection["execution_plan_hash"] = execution_plan_hash
    return plan, execution_plan_hash


def _collect_text(body: RawIntentSubmitRequest, payload: dict[str, Any]) -> str:
    parts = [
        payload.get("idea", ""),
        payload.get("voice", ""),
        str((payload.get("brief") or {}).get("site_purpose", "")),
        str((payload.get("brief") or {}).get("project_name", "")),
        str((payload.get("brief") or {}).get("context", "")),
    ]
    return " ".join(x for x in parts if x).strip().lower()


def _collect_text_from_build_sot(build_sot: BuildSoTV1) -> str:
    return " ".join(
        [
            build_sot.project_name,
            build_sot.site_purpose,
            " ".join(build_sot.target_audience),
            build_sot.desired_tone,
            " ".join(build_sot.page_list),
        ]
    ).lower()


def _build_sot_from_raw(body: RawIntentSubmitRequest, payload: dict[str, Any]) -> BuildSoTV1:
    text = _collect_text(body, payload)
    brief = payload.get("brief") or {}
    project_name = _infer_project_name(brief, text)
    site_purpose = _infer_site_purpose(brief, text)
    target_audience = _infer_target_audience(brief, text)
    desired_tone = _infer_tone(brief, text)
    page_list = _infer_pages(brief, text)
    deployment_target = _infer_deployment_target(body, brief, text)
    unresolved, contradictions = _unresolved_and_contradictions(
        identity=body.ocgg_identity,
        intent=body.intent,
        project_name=project_name,
        site_purpose=site_purpose,
        target_audience=target_audience,
        desired_tone=desired_tone,
        page_list=page_list,
        deployment_target=deployment_target,
        text=text,
    )
    status, approval_status = _status_from_findings(unresolved, contradictions)
    build_sot = BuildSoTV1(
        project_name=project_name or "untitled-project",
        site_purpose=site_purpose or "pending-purpose",
        target_audience=target_audience,
        desired_tone=desired_tone or "professional",
        page_list=page_list,
        nav_structure=page_list,
        section_definitions=_section_defs(page_list, site_purpose),
        forms_ctas=_forms_ctas_for_pages(page_list),
        integrations=_infer_integrations(brief, text),
        data_requirements=_data_requirements_from_integrations(_infer_integrations(brief, text)),
        brand_constraints=_brand_constraints(brief),
        non_goals=_non_goals(brief),
        deployment_target=deployment_target,
        acceptance_criteria=_acceptance_criteria(page_list, deployment_target),
        unresolved_items=unresolved,
        contradictions=contradictions,
        status=status,
        approval_status=approval_status,
    )
    build_sot.content_blocks = _agcc_content_blocks(build_sot)
    return build_sot


def _status_from_findings(
    unresolved: list[str],
    contradictions: list[str],
) -> tuple[ArtifactStatus, str]:
    if contradictions:
        return ArtifactStatus.blocked, "NOT_REQUESTED"
    if unresolved:
        return ArtifactStatus.clarify_required, "NOT_REQUESTED"
    return ArtifactStatus.draft, "NOT_REQUESTED"


def _cognitive_outcome(build_sot: BuildSoTV1) -> CognitiveOutcome:
    if build_sot.status == ArtifactStatus.blocked:
        return CognitiveOutcome.BLOCK
    if build_sot.status == ArtifactStatus.clarify_required:
        return CognitiveOutcome.CLARIFY
    return CognitiveOutcome.PASS


def _infer_project_name(brief: dict[str, Any], text: str) -> str:
    v = str(brief.get("project_name") or "").strip()
    if v:
        return v
    if " for " in text:
        return text.split(" for ", 1)[0][:48].strip(" -:,").title() or "Website Project"
    if text:
        return " ".join(text.split()[:4]).title()
    return ""


def _infer_site_purpose(brief: dict[str, Any], text: str) -> str:
    v = str(brief.get("site_purpose") or brief.get("objective") or "").strip()
    if v:
        return v
    if "landing" in text:
        return "Generate leads through a focused landing experience."
    if "portfolio" in text:
        return "Showcase work and convert visitors to inquiries."
    if "business" in text:
        return "Present business credibility and drive contact actions."
    return ""


def _infer_target_audience(brief: dict[str, Any], text: str) -> list[str]:
    raw = brief.get("target_audience")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    out: list[str] = []
    if "startup" in text:
        out.append("startup teams")
    if "local" in text:
        out.append("local customers")
    if "saas" in text:
        out.append("SaaS buyers")
    return out


def _infer_tone(brief: dict[str, Any], text: str) -> str:
    v = str(brief.get("desired_tone") or brief.get("tone") or "").strip()
    if v:
        return v
    for token in ("playful", "friendly", "formal", "minimal", "bold", "luxury"):
        if token in text:
            return token
    if text:
        return "professional"
    return ""


def _infer_pages(brief: dict[str, Any], text: str) -> list[str]:
    raw = brief.get("page_list")
    if isinstance(raw, list):
        pages = [str(x).strip().lower() for x in raw if str(x).strip()]
        return pages or ["home"]
    pages = ["home"]
    for page in ("about", "services", "pricing", "faq", "contact", "blog"):
        if page in text and page not in pages:
            pages.append(page)
    if "single page" in text:
        return ["home"]
    return pages


def _infer_deployment_target(body: RawIntentSubmitRequest, brief: dict[str, Any], text: str) -> str:
    if body.deployment_target:
        return body.deployment_target
    b = str(brief.get("deployment_target") or "").strip().lower()
    if b in ("preview", "production"):
        return b
    if "production" in text or "live" in text:
        return "production"
    return "preview"


def _unresolved_and_contradictions(
    *,
    identity: str,
    intent: str,
    project_name: str,
    site_purpose: str,
    target_audience: list[str],
    desired_tone: str,
    page_list: list[str],
    deployment_target: str,
    text: str,
) -> tuple[list[str], list[str]]:
    unresolved: list[str] = []
    contradictions: list[str] = []

    if identity != "W-OCGG" or not intent.startswith("web"):
        contradictions.append(_WEB_ONLY_ERROR)
    if not project_name:
        unresolved.append("project_name")
    if not site_purpose:
        unresolved.append("site_purpose")
    if not target_audience:
        unresolved.append("target_audience")
    if not desired_tone:
        unresolved.append("desired_tone")
    if not page_list:
        unresolved.append("page_list")
    if deployment_target == "production" and ("preview only" in text or "do not deploy" in text):
        contradictions.append("DEPLOYMENT_TARGET_CONTRADICTION")
    if "single page" in text and "multi-page" in text:
        contradictions.append("PAGE_STRATEGY_CONTRADICTION")
    return unresolved, contradictions


def _forms_ctas_for_pages(pages: list[str]) -> list[str]:
    out = ["primary_cta"]
    if "contact" in pages:
        out.append("contact_form")
    if "pricing" in pages:
        out.append("pricing_demo_cta")
    return out


def _infer_integrations(brief: dict[str, Any], text: str) -> list[str]:
    raw = brief.get("integrations")
    if isinstance(raw, list):
        vals = [str(x).strip() for x in raw if str(x).strip()]
        if vals:
            return vals
    out: list[str] = []
    for token, val in (
        ("analytics", "analytics"),
        ("hubspot", "hubspot"),
        ("mailchimp", "mailchimp"),
        ("stripe", "stripe"),
    ):
        if token in text:
            out.append(val)
    return sorted(set(out))


def _data_requirements_from_integrations(integrations: list[str]) -> list[str]:
    out = ["page_content", "cta_targets"]
    if "analytics" in integrations:
        out.append("analytics_key")
    if "hubspot" in integrations or "mailchimp" in integrations:
        out.append("lead_capture_fields")
    if "stripe" in integrations:
        out.append("product_catalog_ref")
    return out


def _brand_constraints(brief: dict[str, Any]) -> list[str]:
    raw = brief.get("brand_constraints")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return ["maintain_consistent_typography", "accessible_color_contrast"]


def _non_goals(brief: dict[str, Any]) -> list[str]:
    raw = brief.get("non_goals")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return ["no_unapproved_scope_expansion", "no_runtime_generated_features"]


def _acceptance_criteria(pages: list[str], deployment_target: str) -> list[str]:
    out = [
        "navigation renders expected pages",
        "primary CTA is present above the fold",
        "mobile responsive layout passes smoke checks",
    ]
    if "contact" in pages:
        out.append("contact form validates required fields")
    if deployment_target == "production":
        out.append("deployment requires explicit approval evidence")
    return out


def _section_defs(page_list: list[str], site_purpose: str) -> list[SectionDefinition]:
    out: list[SectionDefinition] = []
    for page in page_list:
        if page == "home":
            out.append(SectionDefinition(page=page, section="hero", objective=site_purpose))
            out.append(SectionDefinition(page=page, section="value_props", objective="Summarize core benefits"))
            out.append(SectionDefinition(page=page, section="cta", objective="Drive primary conversion"))
            continue
        out.append(SectionDefinition(page=page, section=f"{page}_main", objective=f"Deliver key {page} information"))
    return out


def _agcc_content_blocks(build_sot: BuildSoTV1) -> dict[str, list[str]]:
    """
    Bounded AGCC layer: deterministic content scaffolding only.

    This layer never changes scope, authority, policy fields, or operations.
    """
    hero = [
        f"{build_sot.project_name}: {build_sot.site_purpose}",
        "Trusted by teams that need governed delivery.",
    ]
    ctas = ["Start A Governed Build", "Request Preview", "See Acceptance Criteria"]
    faq = [
        "How is governance enforced?",
        "Can this deploy directly to production?",
        "How are revisions approved?",
    ]
    return {"hero": hero, "ctas": ctas, "faq": faq}


def _route_for_page(page: str) -> str:
    p = page.strip("/ ").lower()
    if not p or p == "home":
        return "/"
    return f"/{p}"


def _template_family(pages: list[str]) -> str:
    count = len(set(pages))
    if count <= 1:
        return "brochure_landing"
    if count <= 4:
        return "standard_business"
    return "multi_page_lead_gen"


def _trace_token(trace_id: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]", "", trace_id or "").lower()
    return (token[:12] or "000000000000")


def _operations_from_build_sot(build_sot: BuildSoTV1, trace_id: str = "") -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    project_slug = _slugify(build_sot.project_name)
    repo_name = _render_repo_name(project_slug, trace_id=trace_id)
    github_owner = (settings.governed_v2_github_owner or "").strip()
    github_owner_fallback = (settings.governed_v2_github_owner_fallback or "").strip()
    owner_type = (settings.governed_v2_github_owner_type or "org").strip().lower()
    default_branch = (settings.governed_v2_default_branch or "main").strip()
    team_id = (settings.governed_v2_vercel_team_id or "").strip()
    domain_behavior = (settings.governed_v2_domain_behavior or "vercel_default_only").strip()
    ops.append(
        {
            "op_id": "op-001",
            "type": "provision_repo",
            "target": "repo",
            "inputs": {
                "provider": "github",
                "owner": github_owner,
                "owner_type": owner_type,
                "fallback_owner": github_owner_fallback,
                "repo_name_template": settings.governed_v2_repo_name_template,
                "repo_name": repo_name,
                "default_branch": default_branch,
                "visibility": "public",
            },
            "outputs": {},
        }
    )
    ops.append(
        {
            "op_id": "op-002",
            "type": "provision_hosting",
            "target": "hosting/vercel",
            "inputs": {
                "provider": "vercel",
                "team_id": team_id,
                "project_name": repo_name,
                "linked_repo_name": repo_name,
                "production_branch": default_branch,
                "domain_behavior": domain_behavior,
            },
            "outputs": {},
        }
    )
    for idx, route in enumerate([_route_for_page(p) for p in build_sot.page_list], start=1):
        path = "site/index.html" if route == "/" else f"site{route}.html"
        ops.append(
            {
                "op_id": f"op-{idx + 2:03d}",
                "type": "create_file",
                "target": "repo",
                "inputs": {"path": path, "content": f"<!-- generated for {route} -->"},
                "outputs": {},
            }
        )
    ops.append(
        {
            "op_id": f"op-{len(ops) + 1:03d}",
            "type": "write_config",
            "target": "repo",
            "inputs": {
                "path": "site/build-config.json",
                "content": (
                    '{"executor":"deterministic_web_v1","schema":"execution-plan-v1","stack":"'
                    + settings.governed_v2_stack_preset
                    + '"}'
                ),
            },
            "outputs": {},
        }
    )
    ops.append(
        {
            "op_id": f"op-{len(ops) + 1:03d}",
            "type": "build",
            "target": "repo",
            "inputs": {"command": "run_smoke_checks"},
            "outputs": {},
        }
    )
    ops.append(
        {
            "op_id": f"op-{len(ops) + 1:03d}",
            "type": "deploy",
            "target": "hosting/vercel",
            "inputs": {
                "provider": "vercel",
                "team_id": team_id,
                "project": repo_name,
                "branch": default_branch,
                "domain_behavior": domain_behavior,
            },
            "outputs": {},
        }
    )
    return ops


def _slugify(value: str) -> str:
    lowered = value.lower()
    chars = [c if c.isalnum() else "-" for c in lowered]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "project"


def _render_repo_name(project_slug: str, trace_id: str = "") -> str:
    template = settings.governed_v2_repo_name_template or "cdmbr-{projectname}-{timestamp}"
    repo = template.replace("{projectname}", project_slug)
    repo = repo.replace("{timestamp}", _trace_token(trace_id))
    return repo


def _env_vars_for_integrations(integrations: list[str]) -> list[str]:
    out: list[str] = []
    mapping = {
        "analytics": "ANALYTICS_API_KEY",
        "hubspot": "HUBSPOT_API_KEY",
        "mailchimp": "MAILCHIMP_API_KEY",
        "stripe": "STRIPE_API_KEY",
    }
    for item in integrations:
        key = mapping.get(item)
        if key:
            out.append(key)
    return sorted(set(out))


async def compile_execution_plan_async(
    *,
    trace_id: str,
    build_sot_hash: str,
    build_sot: BuildSoTV1,
    ocgg_identity: str,
    intent: str,
    compiler_version: str = "governed-v2-compiler-2-skills",
) -> tuple[ExecutionPlanV1, str]:
    """Async compiler that uses the skills engine to generate real code."""
    from app.skills.engine import SkillsEngine

    engine = SkillsEngine(build_sot, trace_id=trace_id)
    file_ops = await engine.run()
    operations = engine.to_operations(file_ops)
    governance_plan_hash = integration_hash_payload({"domain": "web", "operations": operations})

    schema_blocks = []
    for form in build_sot.forms_ctas:
        schema_blocks.append({"name": form, "kind": "form_or_cta", "required_fields": ["name", "email"]})

    template_family = _template_family(build_sot.page_list)
    routes = [_route_for_page(page) for page in build_sot.page_list]
    file_tree = [fop.path for fop in file_ops]

    commands = [
        ExecutionPlanCommand(id="cmd-001", type="scaffold", command="scaffold_nextjs_typescript_app", target="repo"),
        ExecutionPlanCommand(id="cmd-002", type="provision_repo", command="create_github_repo", target="repo"),
        ExecutionPlanCommand(id="cmd-003", type="provision_hosting", command="create_vercel_project", target="hosting"),
        ExecutionPlanCommand(id="cmd-004", type="write_files", command="write_generated_files", target="repo"),
        ExecutionPlanCommand(id="cmd-005", type="smoke", command="run_smoke_checks", target="repo"),
        ExecutionPlanCommand(
            id="cmd-006",
            type="deploy",
            command="deploy_production" if build_sot.deployment_target == "production" else "deploy_preview",
            target="hosting",
        ),
    ]

    governance_projection = {
        "ocgg_identity": ocgg_identity,
        "plan_hash": governance_plan_hash,
        "operations": operations,
        "deployment_target": build_sot.deployment_target,
        "goal": build_sot.site_purpose,
        "context": f"{build_sot.project_name} | tone={build_sot.desired_tone}",
        "acceptance_criteria": list(build_sot.acceptance_criteria),
        "trace_id": trace_id,
        "build_sot_hash": build_sot_hash,
    }

    lineage = StageLinkage(
        trace_id=trace_id,
        build_sot_hash=build_sot_hash,
        governance_plan_hash=governance_plan_hash,
    )

    plan = ExecutionPlanV1(
        template_family=template_family,
        scaffold_type="nextjs_app_router",
        framework=settings.governed_v2_stack_preset,
        executor_contract="deterministic_web_v1",
        routes=routes,
        components=[{"id": f"cmp-{i + 1:03d}", "name": s.section, "page": s.page} for i, s in enumerate(build_sot.section_definitions)],
        file_tree=file_tree,
        content_blocks=build_sot.content_blocks,
        schema_blocks=schema_blocks,
        integrations=list(build_sot.integrations),
        env_vars=_env_vars_for_integrations(build_sot.integrations),
        commands=commands,
        smoke_expectations=[
            "all_routes_render",
            "navigation_links_resolve",
            "primary_cta_present",
        ],
        deploy_target=build_sot.deployment_target,
        rollback_strategy={"type": "artifact_redeploy", "target": "site"},
        operations=operations,
        governance_projection=governance_projection,
        stage_linkage=lineage.model_copy(update={"artifact_hash": None}),
        status=ArtifactStatus.compiled,
        compiler_version=compiler_version,
        ocgg_identity=ocgg_identity,
        intent=intent,
        build_sot_hash=build_sot_hash,
    )

    execution_plan_hash = hash_payload(plan.model_dump(mode="python"))
    plan.stage_linkage = plan.stage_linkage.model_copy(
        update={
            "execution_plan_hash": execution_plan_hash,
            "artifact_hash": execution_plan_hash,
        }
    )
    plan.governance_projection["execution_plan_hash"] = execution_plan_hash
    return plan, execution_plan_hash
