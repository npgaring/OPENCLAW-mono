"""SEO skill: generates metadata, sitemap, robots, and Open Graph configuration."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.skills.base import FileOperation, Skill, SkillContext

logger = logging.getLogger(__name__)

_SEO_SYSTEM_PROMPT = (
    "You are an SEO expert. Generate meta descriptions and Open Graph content for website pages.\n"
    "Respond with ONLY valid JSON matching this schema:\n"
    '{"pages":{"slug":{"title":"Page Title | Brand","description":"Compelling 150-char meta description","og_title":"OG Title","og_description":"OG description"}}}'
)


class SEOSkill(Skill):
    name = "seo"
    phase = 3
    depends_on = ["scaffold", "pages"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []
        pages = ctx.build_sot.page_list
        project = ctx.build_sot.project_name
        purpose = ctx.build_sot.site_purpose

        ai_metadata: dict[str, Any] = {}
        if purpose and hasattr(self, "_call_openai"):
            page_list_str = ", ".join(pages[:15])
            result = await self._call_openai(
                _SEO_SYSTEM_PROMPT,
                f"Website: {project}\nPurpose: {purpose}\nTone: {ctx.build_sot.desired_tone}\nPages: {page_list_str}",
            )
            if isinstance(result, dict) and "pages" in result:
                ai_metadata = result["pages"]

        routes = []
        for page in pages:
            slug = page.strip().lower().replace(" ", "-")
            routes.append("/" if slug == "home" else f"/{slug}")

        sitemap_entries = ""
        for route in routes:
            sitemap_entries += (
                f"    {{\n"
                f"      url: `${{baseUrl}}{route}`,\n"
                f"      lastModified: new Date(),\n"
                f"      changeFrequency: 'weekly' as const,\n"
                f"      priority: {1.0 if route == '/' else 0.8},\n"
                f"    }},\n"
            )

        sitemap_ts = (
            'import type { MetadataRoute } from "next";\n\n'
            "export default function sitemap(): MetadataRoute.Sitemap {\n"
            '  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://example.com";\n\n'
            "  return [\n"
            f"{sitemap_entries}"
            "  ];\n"
            "}\n"
        )
        files.append(FileOperation(path="src/app/sitemap.ts", content=sitemap_ts, file_type="config"))

        robots_ts = (
            'import type { MetadataRoute } from "next";\n\n'
            "export default function robots(): MetadataRoute.Robots {\n"
            '  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://example.com";\n\n'
            "  return {\n"
            "    rules: {\n"
            '      userAgent: "*",\n'
            "      allow: \"/\",\n"
            "    },\n"
            "    sitemap: `${baseUrl}/sitemap.xml`,\n"
            "  };\n"
            "}\n"
        )
        files.append(FileOperation(path="src/app/robots.ts", content=robots_ts, file_type="config"))

        seo_metadata = ctx.seo_metadata
        page_metadata_exports = ""
        for page in pages:
            slug = page.strip().lower().replace(" ", "-")
            ai_meta = ai_metadata.get(slug, {})
            fallback_meta = seo_metadata.get(slug, {})
            title = ai_meta.get("title") or fallback_meta.get("title") or f"{page.strip().title()} | {project}"
            description = ai_meta.get("description") or fallback_meta.get("description") or purpose
            og_title = ai_meta.get("og_title") or title
            og_description = ai_meta.get("og_description") or description
            if slug == "home":
                continue
            safe_key = slug.replace("-", "_")
            page_metadata_exports += (
                f'\nexport const {safe_key}_metadata = {{\n'
                f'  title: "{title}",\n'
                f'  description: "{description}",\n'
                f"  openGraph: {{\n"
                f'    title: "{og_title}",\n'
                f'    description: "{og_description}",\n'
                f"  }},\n"
                f"}};\n"
            )

        if page_metadata_exports:
            metadata_file = (
                '/* Per-page metadata constants. Import in page.tsx: import {{ slug_metadata }} from "@/lib/metadata"; */\n'
                f"{page_metadata_exports}"
            )
            files.append(FileOperation(path="src/lib/metadata.ts", content=metadata_file, file_type="source"))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files
