"""Layout skill: generates RootLayout, NavBar, and Footer components."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


def _nav_links(pages: list[str]) -> str:
    links = []
    for page in pages:
        slug = page.strip().lower()
        href = "/" if slug == "home" else f"/{slug.replace(' ', '-')}"
        label = page.strip().title()
        links.append(f'            <Link href="{href}" className="text-sm font-medium hover:text-[var(--color-primary)] transition-colors">{label}</Link>')
    return "\n".join(links)


class LayoutSkill(Skill):
    name = "layout"
    depends_on = ["scaffold", "design"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []
        project = ctx.build_sot.project_name
        pages = ctx.build_sot.page_list
        fonts = ctx.fonts
        heading_font = fonts.get("heading", "Inter")
        body_font = fonts.get("body", "Inter")
        font_import = heading_font.replace(" ", "+")
        body_import = body_font.replace(" ", "+")

        nav_bar = (
            '"use client";\n\n'
            'import Link from "next/link";\n'
            'import { useState } from "react";\n\n'
            f"export function NavBar() {{\n"
            f"  const [open, setOpen] = useState(false);\n\n"
            f"  return (\n"
            f'    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-gray-100">\n'
            f'      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
            f'        <div className="flex items-center justify-between h-16">\n'
            f'          <Link href="/" className="text-xl font-bold text-[var(--color-primary)]">\n'
            f"            {project}\n"
            f"          </Link>\n"
            f'          <div className="hidden md:flex items-center gap-8">\n'
            f"{_nav_links(pages)}\n"
            f"          </div>\n"
            f'          <button\n'
            f'            className="md:hidden p-2"\n'
            f"            onClick={{() => setOpen(!open)}}\n"
            f'            aria-label="Toggle menu"\n'
            f"          >\n"
            f'            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">\n'
            f'              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{2}} d="M4 6h16M4 12h16M4 18h16" />\n'
            f"            </svg>\n"
            f"          </button>\n"
            f"        </div>\n"
            f"        {{open && (\n"
            f'          <div className="md:hidden pb-4 flex flex-col gap-2">\n'
            f"{_nav_links(pages)}\n"
            f"          </div>\n"
            f"        )}}\n"
            f"      </div>\n"
            f"    </nav>\n"
            f"  );\n"
            f"}}\n"
        )
        files.append(FileOperation(
            path="src/components/NavBar.tsx",
            content=nav_bar,
            file_type="component",
        ))

        footer_tagline = ""
        if ctx.content_blocks.get("footer"):
            footer_tagline = ctx.content_blocks["footer"][0]
        else:
            footer_tagline = project

        footer = (
            f'import Link from "next/link";\n\n'
            f"export function Footer() {{\n"
            f"  return (\n"
            f'    <footer className="bg-gray-900 text-gray-300 py-12">\n'
            f'      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
            f'        <div className="grid md:grid-cols-3 gap-8">\n'
            f'          <div>\n'
            f'            <h3 className="text-white text-lg font-bold mb-2">{project}</h3>\n'
            f'            <p className="text-sm">{footer_tagline}</p>\n'
            f"          </div>\n"
            f'          <div>\n'
            f'            <h4 className="text-white font-semibold mb-2">Pages</h4>\n'
            f'            <ul className="space-y-1 text-sm">\n'
        )
        for page in pages:
            slug = page.strip().lower()
            href = "/" if slug == "home" else f"/{slug.replace(' ', '-')}"
            footer += f'              <li><Link href="{href}" className="hover:text-white transition-colors">{page.strip().title()}</Link></li>\n'
        footer += (
            f"            </ul>\n"
            f"          </div>\n"
            f'          <div>\n'
            f'            <h4 className="text-white font-semibold mb-2">Connect</h4>\n'
            f'            <p className="text-sm">Ready to get started? Reach out today.</p>\n'
            f"          </div>\n"
            f"        </div>\n"
            f'        <div className="mt-8 pt-8 border-t border-gray-700 text-sm text-center">\n'
            f"          <p>&copy; {{new Date().getFullYear()}} {project}. All rights reserved.</p>\n"
            f"        </div>\n"
            f"      </div>\n"
            f"    </footer>\n"
            f"  );\n"
            f"}}\n"
        )
        files.append(FileOperation(
            path="src/components/Footer.tsx",
            content=footer,
            file_type="component",
        ))

        google_fonts_url = f"https://fonts.googleapis.com/css2?family={font_import}:wght@400;500;600;700&family={body_import}:wght@400;500&display=swap"

        root_layout = (
            'import type {{ Metadata }} from "next";\n'
            'import "./globals.css";\n'
            'import {{ NavBar }} from "@/components/NavBar";\n'
            'import {{ Footer }} from "@/components/Footer";\n\n'
            "export const metadata: Metadata = {{\n"
            f'  title: "{project}",\n'
            f'  description: "{ctx.build_sot.site_purpose}",\n'
            "}};\n\n"
            "export default function RootLayout({{\n"
            "  children,\n"
            "}}: {{\n"
            "  children: React.ReactNode;\n"
            "}}) {{\n"
            '  return (\n'
            '    <html lang="en">\n'
            "      <head>\n"
            f'        <link rel="preconnect" href="https://fonts.googleapis.com" />\n'
            f'        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />\n'
            f'        <link href="{google_fonts_url}" rel="stylesheet" />\n'
            "      </head>\n"
            '      <body className="min-h-screen flex flex-col">\n'
            "        <NavBar />\n"
            '        <main className="flex-1">\n'
            "          {{children}}\n"
            "        </main>\n"
            "        <Footer />\n"
            "      </body>\n"
            "    </html>\n"
            "  );\n"
            "}}\n"
        )
        files.append(FileOperation(
            path="src/app/layout.tsx",
            content=root_layout,
            file_type="component",
        ))

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
