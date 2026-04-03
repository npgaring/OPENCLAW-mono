"""Design skill: generates global CSS with design tokens, optionally AI-enhanced."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.skills.base import FileOperation, Skill, SkillContext

logger = logging.getLogger(__name__)

_COLOR_SYSTEM_PROMPT = (
    "You are a UI/UX design expert. Given a website purpose and tone, suggest a cohesive color palette and typography.\n"
    "Respond with ONLY valid JSON matching this schema:\n"
    '{"primary":"#hex","secondary":"#hex","accent":"#hex","background":"#hex","text":"#hex",'
    '"surface":"#hex","muted":"#hex",'
    '"font_heading":"FontName","font_body":"FontName",'
    '"dark":{"background":"#hex","text":"#hex","surface":"#hex"}}'
)


class DesignSkill(Skill):
    name = "design"
    phase = 1
    depends_on = ["scaffold"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []

        colors = dict(ctx.colors)
        fonts = dict(ctx.fonts)
        dark_colors: dict[str, str] = {}

        if ctx.build_sot.site_purpose and hasattr(self, "_call_openai"):
            ai_result = await self._call_openai(
                _COLOR_SYSTEM_PROMPT,
                f"Website: {ctx.build_sot.project_name}\n"
                f"Purpose: {ctx.build_sot.site_purpose}\n"
                f"Tone: {ctx.build_sot.desired_tone}\n"
                f"Audience: {', '.join(ctx.build_sot.target_audience[:5])}"
            )
            if isinstance(ai_result, dict) and ai_result.get("primary"):
                colors.update({k: v for k, v in ai_result.items() if isinstance(v, str) and v.startswith("#")})
                if ai_result.get("font_heading"):
                    fonts["heading"] = ai_result["font_heading"]
                if ai_result.get("font_body"):
                    fonts["body"] = ai_result["font_body"]
                dark = ai_result.get("dark")
                if isinstance(dark, dict):
                    dark_colors = {k: v for k, v in dark.items() if isinstance(v, str) and v.startswith("#")}

        primary = colors.get("primary", "#2563eb")
        secondary = colors.get("secondary", "#7c3aed")
        accent = colors.get("accent", "#f59e0b")
        background = colors.get("background", "#ffffff")
        text_color = colors.get("text", "#111827")
        surface = colors.get("surface", "#f9fafb")
        muted = colors.get("muted", "#6b7280")
        heading_font = fonts.get("heading", "Inter")
        body_font = fonts.get("body", "Inter")

        dark_bg = dark_colors.get("background", "#0f172a")
        dark_text = dark_colors.get("text", "#f1f5f9")
        dark_surface = dark_colors.get("surface", "#1e293b")

        globals_css = (
            f'@import "tailwindcss";\n\n'
            f":root {{\n"
            f"  --color-primary: {primary};\n"
            f"  --color-secondary: {secondary};\n"
            f"  --color-accent: {accent};\n"
            f"  --color-background: {background};\n"
            f"  --color-text: {text_color};\n"
            f"  --color-surface: {surface};\n"
            f"  --color-muted: {muted};\n"
            f"  --font-heading: '{heading_font}', system-ui, sans-serif;\n"
            f"  --font-body: '{body_font}', system-ui, sans-serif;\n"
            f"  --radius: 0.5rem;\n"
            f"  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);\n"
            f"  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);\n"
            f"  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);\n"
            f"}}\n\n"
            f"@media (prefers-color-scheme: dark) {{\n"
            f"  :root {{\n"
            f"    --color-background: {dark_bg};\n"
            f"    --color-text: {dark_text};\n"
            f"    --color-surface: {dark_surface};\n"
            f"  }}\n"
            f"}}\n\n"
            f"body {{\n"
            f"  font-family: var(--font-body);\n"
            f"  color: var(--color-text);\n"
            f"  background-color: var(--color-background);\n"
            f"  -webkit-font-smoothing: antialiased;\n"
            f"  -moz-osx-font-smoothing: grayscale;\n"
            f"}}\n\n"
            f"h1, h2, h3, h4, h5, h6 {{\n"
            f"  font-family: var(--font-heading);\n"
            f"  font-weight: 700;\n"
            f"}}\n\n"
            f"::selection {{\n"
            f"  background-color: {primary};\n"
            f"  color: white;\n"
            f"}}\n"
        )
        files.append(FileOperation(path="src/app/globals.css", content=globals_css, file_type="style"))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files
