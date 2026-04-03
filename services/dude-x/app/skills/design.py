"""Design skill: generates Tailwind config, global CSS, and design tokens."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


class DesignSkill(Skill):
    name = "design"
    depends_on = ["scaffold"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []
        colors = ctx.colors
        fonts = ctx.fonts

        globals_css = (
            f'@import "tailwindcss";\n\n'
            f":root {{\n"
            f"  --color-primary: {colors.get('primary', '#2563eb')};\n"
            f"  --color-secondary: {colors.get('secondary', '#7c3aed')};\n"
            f"  --color-accent: {colors.get('accent', '#f59e0b')};\n"
            f"  --color-background: {colors.get('background', '#ffffff')};\n"
            f"  --color-text: {colors.get('text', '#111827')};\n"
            f"  --font-heading: '{fonts.get('heading', 'Inter')}', system-ui, sans-serif;\n"
            f"  --font-body: '{fonts.get('body', 'Inter')}', system-ui, sans-serif;\n"
            f"}}\n\n"
            f"body {{\n"
            f"  font-family: var(--font-body);\n"
            f"  color: var(--color-text);\n"
            f"  background-color: var(--color-background);\n"
            f"}}\n\n"
            f"h1, h2, h3, h4, h5, h6 {{\n"
            f"  font-family: var(--font-heading);\n"
            f"}}\n"
        )
        files.append(FileOperation(
            path="src/app/globals.css",
            content=globals_css,
            file_type="style",
        ))

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
