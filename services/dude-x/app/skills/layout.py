"""Layout skill: generates RootLayout, NavBar, and Footer components."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


def _nav_links(pages: list[str]) -> str:
    links = []
    for page in pages:
        slug = page.strip().lower()
        href = "/" if slug == "home" else f"/{slug.replace(' ', '-')}"
        label = page.strip().title()
        links.append(
            f'            <Link href="{href}" className="text-sm font-medium text-gray-700 '
            f'hover:text-[var(--color-primary)] transition-colors duration-200">{label}</Link>'
        )
    return "\n".join(links)


def _mobile_links(pages: list[str]) -> str:
    links = []
    for page in pages:
        slug = page.strip().lower()
        href = "/" if slug == "home" else f"/{slug.replace(' ', '-')}"
        label = page.strip().title()
        links.append(
            f'              <Link href="{href}" className="block px-3 py-2 text-base font-medium '
            f'text-gray-700 hover:text-[var(--color-primary)] hover:bg-gray-50 rounded-lg '
            f'transition-colors" onClick={{() => setOpen(false)}}>{label}</Link>'
        )
    return "\n".join(links)


class LayoutSkill(Skill):
    name = "layout"
    phase = 2
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
            'import { useState } from "react";\n'
            'import { usePathname } from "next/navigation";\n\n'
            f"export function NavBar() {{\n"
            f"  const [open, setOpen] = useState(false);\n"
            f"  const pathname = usePathname();\n\n"
            f"  return (\n"
            f'    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-lg border-b border-gray-100 shadow-sm">\n'
            f'      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
            f'        <div className="flex items-center justify-between h-16">\n'
            f'          <Link href="/" className="flex items-center gap-2">\n'
            f'            <div className="w-8 h-8 bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] rounded-lg" />\n'
            f'            <span className="text-xl font-bold bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-secondary)] bg-clip-text text-transparent">\n'
            f"              {project}\n"
            f"            </span>\n"
            f"          </Link>\n"
            f'          <div className="hidden md:flex items-center gap-8">\n'
            f"{_nav_links(pages)}\n"
            f"          </div>\n"
            f'          <div className="hidden md:flex items-center gap-4">\n'
            f'            <Link href="/contact" className="bg-[var(--color-primary)] text-white px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity shadow-sm">\n'
            f"              Get Started\n"
            f"            </Link>\n"
            f"          </div>\n"
            f'          <button\n'
            f'            className="md:hidden p-2 rounded-lg hover:bg-gray-100 transition-colors"\n'
            f"            onClick={{() => setOpen(!open)}}\n"
            f'            aria-label="Toggle menu"\n'
            f"          >\n"
            f"            {{open ? (\n"
            f'              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">\n'
            f'                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{2}} d="M6 18L18 6M6 6l12 12" />\n'
            f"              </svg>\n"
            f"            ) : (\n"
            f'              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">\n'
            f'                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{2}} d="M4 6h16M4 12h16M4 18h16" />\n'
            f"              </svg>\n"
            f"            )}}\n"
            f"          </button>\n"
            f"        </div>\n"
            f"        {{open && (\n"
            f'          <div className="md:hidden pb-4 pt-2 space-y-1 border-t border-gray-100">\n'
            f"{_mobile_links(pages)}\n"
            f'            <Link href="/contact" className="block mx-3 mt-3 bg-[var(--color-primary)] text-white text-center px-4 py-2.5 rounded-lg font-semibold text-sm" onClick={{() => setOpen(false)}}>\n'
            f"              Get Started\n"
            f"            </Link>\n"
            f"          </div>\n"
            f"        )}}\n"
            f"      </div>\n"
            f"    </nav>\n"
            f"  );\n"
            f"}}\n"
        )
        files.append(FileOperation(path="src/components/NavBar.tsx", content=nav_bar, file_type="component"))

        footer_tagline = ""
        if ctx.content_blocks.get("footer"):
            footer_tagline = ctx.content_blocks["footer"][0]
        else:
            footer_tagline = ctx.build_sot.site_purpose or project

        footer = (
            f'import Link from "next/link";\n\n'
            f"export function Footer() {{\n"
            f"  return (\n"
            f'    <footer className="bg-gray-900 text-gray-300">\n'
            f'      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">\n'
            f'        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-12">\n'
            f'          <div className="lg:col-span-1">\n'
            f'            <div className="flex items-center gap-2 mb-4">\n'
            f'              <div className="w-8 h-8 bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] rounded-lg" />\n'
            f'              <span className="text-white text-xl font-bold">{project}</span>\n'
            f"            </div>\n"
            f'            <p className="text-sm leading-relaxed mb-6">{footer_tagline}</p>\n'
            f'            <div className="flex gap-4">\n'
            f'              <a href="#" className="w-10 h-10 bg-gray-800 rounded-lg flex items-center justify-center hover:bg-[var(--color-primary)] transition-colors" aria-label="Twitter">\n'
            f'                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>\n'
            f"              </a>\n"
            f'              <a href="#" className="w-10 h-10 bg-gray-800 rounded-lg flex items-center justify-center hover:bg-[var(--color-primary)] transition-colors" aria-label="LinkedIn">\n'
            f'                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>\n'
            f"              </a>\n"
            f"            </div>\n"
            f"          </div>\n"
            f'          <div>\n'
            f'            <h4 className="text-white font-semibold mb-4">Pages</h4>\n'
            f'            <ul className="space-y-3 text-sm">\n'
        )
        for page in pages:
            slug = page.strip().lower()
            href = "/" if slug == "home" else f"/{slug.replace(' ', '-')}"
            footer += f'              <li><Link href="{href}" className="hover:text-white transition-colors">{page.strip().title()}</Link></li>\n'
        footer += (
            f"            </ul>\n"
            f"          </div>\n"
            f'          <div>\n'
            f'            <h4 className="text-white font-semibold mb-4">Company</h4>\n'
            f'            <ul className="space-y-3 text-sm">\n'
            f'              <li><Link href="/about" className="hover:text-white transition-colors">About Us</Link></li>\n'
            f'              <li><Link href="/contact" className="hover:text-white transition-colors">Contact</Link></li>\n'
            f'              <li><a href="#" className="hover:text-white transition-colors">Privacy Policy</a></li>\n'
            f'              <li><a href="#" className="hover:text-white transition-colors">Terms of Service</a></li>\n'
            f"            </ul>\n"
            f"          </div>\n"
            f'          <div>\n'
            f'            <h4 className="text-white font-semibold mb-4">Stay Updated</h4>\n'
            f'            <p className="text-sm mb-4">Subscribe to our newsletter for the latest updates.</p>\n'
            f'            <form className="flex gap-2">\n'
            f'              <input type="email" placeholder="your@email.com" className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-[var(--color-primary)]" />\n'
            f'              <button type="submit" className="px-4 py-2 bg-[var(--color-primary)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity">\n'
            f"                Join\n"
            f"              </button>\n"
            f"            </form>\n"
            f"          </div>\n"
            f"        </div>\n"
            f'        <div className="mt-12 pt-8 border-t border-gray-800 flex flex-col md:flex-row justify-between items-center gap-4 text-sm">\n'
            f"          <p>&copy; {{new Date().getFullYear()}} {project}. All rights reserved.</p>\n"
            f'          <p className="text-gray-500">Built with care for our customers.</p>\n'
            f"        </div>\n"
            f"      </div>\n"
            f"    </footer>\n"
            f"  );\n"
            f"}}\n"
        )
        files.append(FileOperation(path="src/components/Footer.tsx", content=footer, file_type="component"))

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
            '      <body className="min-h-screen flex flex-col antialiased">\n'
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
        files.append(FileOperation(path="src/app/layout.tsx", content=root_layout, file_type="component"))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files
