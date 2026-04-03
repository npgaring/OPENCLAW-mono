"""SEO skill: generates metadata, sitemap, robots.txt."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


class SEOSkill(Skill):
    name = "seo"
    depends_on = ["scaffold", "pages"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []
        pages = ctx.build_sot.page_list
        project = ctx.build_sot.project_name
        purpose = ctx.build_sot.site_purpose

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
        files.append(FileOperation(
            path="src/app/sitemap.ts",
            content=sitemap_ts,
            file_type="config",
        ))

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
        files.append(FileOperation(
            path="src/app/robots.ts",
            content=robots_ts,
            file_type="config",
        ))

        seo_metadata = ctx.seo_metadata
        page_metadata_exports = ""
        for page in pages:
            slug = page.strip().lower().replace(" ", "-")
            meta = seo_metadata.get(slug, {})
            title = meta.get("title", f"{page.strip().title()} | {project}")
            description = meta.get("description", purpose)
            if slug == "home":
                continue
            page_metadata_exports += (
                f'\n// Metadata for /{slug}\n'
                f'export const {slug.replace("-", "_")}_metadata = {{\n'
                f'  title: "{title}",\n'
                f'  description: "{description}",\n'
                f"}};\n"
            )

        if page_metadata_exports:
            metadata_file = (
                "/* Per-page metadata constants for use in page.tsx files. */\n"
                f"{page_metadata_exports}"
            )
            files.append(FileOperation(
                path="src/lib/metadata.ts",
                content=metadata_file,
                file_type="source",
            ))

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
