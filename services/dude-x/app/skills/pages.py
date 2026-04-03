"""Pages skill: generates per-page React components with real content."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


def _home_page(ctx: SkillContext) -> str:
    cb = ctx.content_blocks
    hero_lines = cb.get("hero", [ctx.build_sot.project_name, ctx.build_sot.site_purpose])
    headline = hero_lines[0] if hero_lines else ctx.build_sot.project_name
    subheadline = hero_lines[1] if len(hero_lines) > 1 else ctx.build_sot.site_purpose
    ctas = cb.get("ctas", ["Get Started", "Learn More"])
    cta_primary = ctas[0] if ctas else "Get Started"
    cta_secondary = ctas[1] if len(ctas) > 1 else "Learn More"

    vps = cb.get("value_propositions", [
        "Quality: Exceptional craftsmanship in every detail",
        "Speed: Rapid delivery without compromise",
        "Trust: Proven track record of excellence",
    ])

    vp_cards = ""
    for i, vp in enumerate(vps[:6]):
        parts = vp.split(": ", 1) if ": " in vp else [vp, ""]
        title = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        vp_cards += (
            f'          <div key={{{i}}} className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 hover:shadow-md transition-shadow">\n'
            f'            <div className="w-12 h-12 bg-[var(--color-primary)]/10 rounded-lg flex items-center justify-center mb-4">\n'
            f'              <span className="text-[var(--color-primary)] text-xl font-bold">{i + 1}</span>\n'
            f"            </div>\n"
            f'            <h3 className="text-lg font-semibold mb-2">{title}</h3>\n'
            f'            <p className="text-gray-600">{desc}</p>\n'
            f"          </div>\n"
        )

    contact_href = "/contact" if "contact" in [p.lower() for p in ctx.build_sot.page_list] else "#"

    return (
        f"export default function HomePage() {{\n"
        f"  return (\n"
        f"    <>\n"
        f'      <section className="relative bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-24 lg:py-32">\n'
        f'        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        f'          <h1 className="text-4xl md:text-6xl font-bold mb-6 leading-tight">\n'
        f"            {headline}\n"
        f"          </h1>\n"
        f'          <p className="text-xl md:text-2xl opacity-90 max-w-3xl mx-auto mb-10">\n'
        f"            {subheadline}\n"
        f"          </p>\n"
        f'          <div className="flex flex-col sm:flex-row gap-4 justify-center">\n'
        f'            <a href="{contact_href}" className="bg-white text-[var(--color-primary)] px-8 py-3 rounded-lg font-semibold hover:bg-gray-100 transition-colors">\n'
        f"              {cta_primary}\n"
        f"            </a>\n"
        f'            <a href="/services" className="border-2 border-white px-8 py-3 rounded-lg font-semibold hover:bg-white/10 transition-colors">\n'
        f"              {cta_secondary}\n"
        f"            </a>\n"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-gray-50">\n'
        f'        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        f'          <h2 className="text-3xl font-bold text-center mb-12">Why Choose Us</h2>\n'
        f'          <div className="grid md:grid-cols-3 gap-8">\n'
        f"{vp_cards}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20">\n'
        f'        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        f'          <h2 className="text-3xl font-bold mb-6">Ready to Get Started?</h2>\n'
        f'          <p className="text-lg text-gray-600 mb-8">{ctx.build_sot.site_purpose}</p>\n'
        f'          <a href="{contact_href}" className="inline-block bg-[var(--color-primary)] text-white px-8 py-3 rounded-lg font-semibold hover:opacity-90 transition-opacity">\n'
        f"            {cta_primary}\n"
        f"          </a>\n"
        f"        </div>\n"
        f"      </section>\n"
        f"    </>\n"
        f"  );\n"
        f"}}\n"
    )


def _generic_page(ctx: SkillContext, page_name: str) -> str:
    title = page_name.replace("-", " ").replace("_", " ").title()
    page_key = f"page_{page_name.lower()}"
    sections_content = ctx.content_blocks.get(page_key, [])

    sections_jsx = ""
    for i, section_text in enumerate(sections_content):
        if section_text.startswith("## "):
            parts = section_text.split("\n", 1)
            heading = parts[0].replace("## ", "")
            body = parts[1] if len(parts) > 1 else ""
            sections_jsx += (
                f'      <div className="mb-12">\n'
                f'        <h2 className="text-2xl font-bold mb-4">{heading}</h2>\n'
                f'        <p className="text-gray-600 leading-relaxed">{body}</p>\n'
                f"      </div>\n"
            )
        elif section_text.startswith("[CTA:"):
            pass
        else:
            sections_jsx += f'      <p className="text-gray-600 leading-relaxed mb-6">{section_text}</p>\n'

    if not sections_jsx:
        sections_jsx = (
            f'      <p className="text-lg text-gray-600 leading-relaxed">\n'
            f"        Welcome to our {title.lower()} page. We are committed to delivering\n"
            f"        exceptional results for every client we work with.\n"
            f"      </p>\n"
        )

    return (
        f"export default function {_component_name(page_name)}Page() {{\n"
        f"  return (\n"
        f'    <div className="py-20">\n'
        f'      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        f'        <h1 className="text-4xl font-bold mb-8">{title}</h1>\n'
        f"{sections_jsx}"
        f"      </div>\n"
        f"    </div>\n"
        f"  );\n"
        f"}}\n"
    )


def _contact_page(ctx: SkillContext) -> str:
    return (
        '"use client";\n\n'
        'import { useState } from "react";\n\n'
        "export default function ContactPage() {\n"
        "  const [submitted, setSubmitted] = useState(false);\n\n"
        "  return (\n"
        '    <div className="py-20">\n'
        '      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        '        <h1 className="text-4xl font-bold mb-4">Contact Us</h1>\n'
        '        <p className="text-lg text-gray-600 mb-8">We\'d love to hear from you. Fill out the form below and we\'ll get back to you shortly.</p>\n'
        "        {submitted ? (\n"
        '          <div className="bg-green-50 border border-green-200 rounded-lg p-6 text-center">\n'
        '            <h2 className="text-xl font-semibold text-green-800 mb-2">Thank you!</h2>\n'
        '            <p className="text-green-700">We\'ll be in touch soon.</p>\n'
        "          </div>\n"
        "        ) : (\n"
        "          <form\n"
        '            className="space-y-6"\n'
        "            onSubmit={(e) => { e.preventDefault(); setSubmitted(true); }}\n"
        "          >\n"
        "            <div>\n"
        '              <label htmlFor="name" className="block text-sm font-medium mb-1">Name</label>\n'
        '              <input id="name" type="text" required className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent" />\n'
        "            </div>\n"
        "            <div>\n"
        '              <label htmlFor="email" className="block text-sm font-medium mb-1">Email</label>\n'
        '              <input id="email" type="email" required className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent" />\n'
        "            </div>\n"
        "            <div>\n"
        '              <label htmlFor="message" className="block text-sm font-medium mb-1">Message</label>\n'
        '              <textarea id="message" rows={5} required className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent" />\n'
        "            </div>\n"
        '            <button type="submit" className="bg-[var(--color-primary)] text-white px-8 py-3 rounded-lg font-semibold hover:opacity-90 transition-opacity">\n'
        "              Send Message\n"
        "            </button>\n"
        "          </form>\n"
        "        )}\n"
        "      </div>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _component_name(page: str) -> str:
    return "".join(
        word.capitalize()
        for word in page.replace("-", " ").replace("_", " ").split()
    )


class PagesSkill(Skill):
    name = "pages"
    depends_on = ["scaffold", "design", "layout"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []

        for page in ctx.build_sot.page_list:
            slug = page.strip().lower().replace(" ", "-")

            if slug == "home":
                content = _home_page(ctx)
                files.append(FileOperation(path="src/app/page.tsx", content=content, file_type="page"))
            elif slug == "contact":
                content = _contact_page(ctx)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))
            else:
                content = _generic_page(ctx, slug)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
