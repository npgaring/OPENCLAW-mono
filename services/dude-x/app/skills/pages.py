"""Pages skill: generates per-page React components with real, rich content.

Specialized generators for common page types:
- Home (landing)
- About
- Services
- Pricing
- Contact
- Blog
- Portfolio / Gallery
- FAQ
- Testimonials
- Generic fallback
"""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


def _component_name(page: str) -> str:
    return "".join(word.capitalize() for word in page.replace("-", " ").replace("_", " ").split())


def _classify(slug: str) -> str:
    s = slug.lower().replace("-", "").replace("_", "")
    for key in ("home", "about", "services", "pricing", "contact", "blog", "portfolio",
                "gallery", "faq", "testimonials", "careers", "features"):
        if key in s:
            return key
    return "generic"


# ---------------------------------------------------------------------------
# Page generators
# ---------------------------------------------------------------------------

def _home_page(ctx: SkillContext) -> str:
    cb = ctx.content_blocks
    hero_lines = cb.get("hero", [ctx.build_sot.project_name, ctx.build_sot.site_purpose])
    headline = hero_lines[0] if hero_lines else ctx.build_sot.project_name
    subheadline = hero_lines[1] if len(hero_lines) > 1 else ctx.build_sot.site_purpose
    ctas = cb.get("ctas", ["Get Started", "Learn More"])
    cta_primary = ctas[0] if ctas else "Get Started"
    cta_secondary = ctas[1] if len(ctas) > 1 else "Learn More"

    vps = cb.get("value_propositions", [
        "Quality: Exceptional craftsmanship in every detail we deliver",
        "Speed: Rapid delivery without compromising on quality or results",
        "Trust: Proven track record of excellence with hundreds of clients",
        "Innovation: Cutting-edge solutions that keep you ahead of the curve",
        "Support: Dedicated team available around the clock for your needs",
        "Value: Competitive pricing with transparent, no-surprise billing",
    ])

    stats = cb.get("stats", [
        ("500+", "Happy Clients"),
        ("99%", "Satisfaction Rate"),
        ("24/7", "Support Available"),
        ("10+", "Years Experience"),
    ])

    testimonials = cb.get("testimonials", [
        ("This service transformed our business completely. The results exceeded all expectations.", "Sarah Johnson", "CEO, TechCorp"),
        ("Incredible quality and attention to detail. Highly recommended to anyone looking for the best.", "Michael Chen", "Director, InnovateCo"),
        ("The team went above and beyond. Our conversion rates improved by 300% in just 3 months.", "Emily Rodriguez", "CMO, GrowthHub"),
    ])

    vp_cards = ""
    icons = ["M13 10V3L4 14h7v7l9-11h-7z", "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
             "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
             "M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
             "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"]
    for i, vp in enumerate(vps[:6]):
        parts = vp.split(": ", 1) if ": " in vp else [vp, ""]
        title = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        icon_path = icons[i % len(icons)]
        vp_cards += (
            f'          <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">\n'
            f'            <div className="w-14 h-14 bg-gradient-to-br from-[var(--color-primary)]/10 to-[var(--color-secondary)]/10 rounded-xl flex items-center justify-center mb-5">\n'
            f'              <svg className="w-7 h-7 text-[var(--color-primary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{1.5}} d="{icon_path}" /></svg>\n'
            f"            </div>\n"
            f'            <h3 className="text-xl font-semibold mb-3">{title}</h3>\n'
            f'            <p className="text-gray-600 leading-relaxed">{desc}</p>\n'
            f"          </div>\n"
        )

    stats_html = ""
    for value, label in (stats if isinstance(stats, list) and stats and isinstance(stats[0], (list, tuple)) else [("500+", "Clients"), ("99%", "Satisfaction"), ("24/7", "Support"), ("10+", "Years")]):
        stats_html += (
            f'          <div className="text-center">\n'
            f'            <div className="text-4xl md:text-5xl font-bold text-[var(--color-primary)] mb-2">{value}</div>\n'
            f'            <div className="text-gray-600 font-medium">{label}</div>\n'
            f"          </div>\n"
        )

    testimonial_cards = ""
    for quote, name, role in (testimonials if isinstance(testimonials, list) and testimonials and isinstance(testimonials[0], (list, tuple)) else []):
        testimonial_cards += (
            f'          <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">\n'
            f'            <div className="flex gap-1 mb-4">\n'
            f'              {{[...Array(5)].map((_, i) => <svg key={{i}} className="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>)}}\n'
            f"            </div>\n"
            f'            <p className="text-gray-700 leading-relaxed mb-6 italic">&ldquo;{quote}&rdquo;</p>\n'
            f'            <div>\n'
            f'              <p className="font-semibold">{name}</p>\n'
            f'              <p className="text-sm text-gray-500">{role}</p>\n'
            f"            </div>\n"
            f"          </div>\n"
        )

    contact_href = "/contact" if "contact" in [p.lower() for p in ctx.build_sot.page_list] else "#"

    return (
        f'import Link from "next/link";\n\n'
        f"export default function HomePage() {{\n"
        f"  return (\n"
        f"    <>\n"
        f'      <section className="relative overflow-hidden bg-gradient-to-br from-[var(--color-primary)] via-[var(--color-secondary)] to-[var(--color-primary)] text-white py-24 lg:py-36">\n'
        f'        <div className="absolute inset-0 bg-[url(\'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGRlZnM+PHBhdHRlcm4gaWQ9ImciIHdpZHRoPSI2MCIgaGVpZ2h0PSI2MCIgcGF0dGVyblVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGggZD0iTTAgMGg2MHY2MEgweiIgZmlsbD0ibm9uZSIvPjxwYXRoIGQ9Ik0zMCAwdjYwTTYwIDMwSDAiIHN0cm9rZT0icmdiYSgyNTUsMjU1LDI1NSwwLjA1KSIgc3Ryb2tlLXdpZHRoPSIxIi8+PC9wYXR0ZXJuPjwvZGVmcz48cmVjdCBmaWxsPSJ1cmwoI2cpIiB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIi8+PC9zdmc+\')] opacity-30" />\n'
        f'        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        f'          <h1 className="text-4xl sm:text-5xl md:text-7xl font-bold mb-6 leading-tight tracking-tight">\n'
        f"            {headline}\n"
        f"          </h1>\n"
        f'          <p className="text-xl md:text-2xl opacity-90 max-w-3xl mx-auto mb-10 leading-relaxed">\n'
        f"            {subheadline}\n"
        f"          </p>\n"
        f'          <div className="flex flex-col sm:flex-row gap-4 justify-center">\n'
        f'            <Link href="{contact_href}" className="bg-white text-[var(--color-primary)] px-8 py-4 rounded-xl font-semibold text-lg hover:bg-gray-100 transition-colors shadow-lg hover:shadow-xl">\n'
        f"              {cta_primary}\n"
        f"            </Link>\n"
        f'            <Link href="/services" className="border-2 border-white/30 backdrop-blur-sm px-8 py-4 rounded-xl font-semibold text-lg hover:bg-white/10 transition-colors">\n'
        f"              {cta_secondary}\n"
        f"            </Link>\n"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 lg:py-28">\n'
        f'        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        f'          <div className="text-center mb-16">\n'
        f'            <h2 className="text-3xl md:text-4xl font-bold mb-4">Why Choose Us</h2>\n'
        f'            <p className="text-lg text-gray-600 max-w-2xl mx-auto">Everything you need to succeed, all in one place.</p>\n'
        f"          </div>\n"
        f'          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-8">\n'
        f"{vp_cards}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-gradient-to-b from-gray-50 to-white">\n'
        f'        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        f'          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">\n'
        f"{stats_html}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 lg:py-28">\n'
        f'        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">\n'
        f'          <div className="text-center mb-16">\n'
        f'            <h2 className="text-3xl md:text-4xl font-bold mb-4">What Our Clients Say</h2>\n'
        f'            <p className="text-lg text-gray-600 max-w-2xl mx-auto">Don&apos;t just take our word for it.</p>\n'
        f"          </div>\n"
        f'          <div className="grid md:grid-cols-3 gap-8">\n'
        f"{testimonial_cards}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-secondary)] text-white">\n'
        f'        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        f'          <h2 className="text-3xl md:text-4xl font-bold mb-6">Ready to Get Started?</h2>\n'
        f'          <p className="text-xl opacity-90 mb-10">{ctx.build_sot.site_purpose}</p>\n'
        f'          <Link href="{contact_href}" className="inline-block bg-white text-[var(--color-primary)] px-10 py-4 rounded-xl font-semibold text-lg hover:bg-gray-100 transition-colors shadow-lg">\n'
        f"            {cta_primary}\n"
        f"          </Link>\n"
        f"        </div>\n"
        f"      </section>\n"
        f"    </>\n"
        f"  );\n"
        f"}}\n"
    )


def _about_page(ctx: SkillContext) -> str:
    project = ctx.build_sot.project_name
    purpose = ctx.build_sot.site_purpose
    cb = ctx.content_blocks
    story = cb.get("page_about", cb.get("about", [
        f"{project} was founded with a simple mission: to deliver outstanding results that make a real difference.",
        "Our journey began when we saw an opportunity to bridge the gap between ambition and execution.",
        "Today, we serve hundreds of clients worldwide, staying true to our founding values of quality, integrity, and innovation.",
    ]))
    values = cb.get("values", [
        ("Innovation", "We constantly push boundaries and embrace new ideas to stay ahead."),
        ("Integrity", "Transparency and honesty guide every decision we make."),
        ("Excellence", "We settle for nothing less than the best in everything we do."),
        ("Collaboration", "Together, we achieve more than any of us could alone."),
    ])

    values_html = ""
    for val in values:
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            title, desc = val[0], val[1]
        elif isinstance(val, str) and ": " in val:
            title, desc = val.split(": ", 1)
        else:
            title, desc = str(val), ""
        values_html += (
            f'          <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100 text-center">\n'
            f'            <h3 className="text-xl font-semibold mb-3">{title}</h3>\n'
            f'            <p className="text-gray-600 leading-relaxed">{desc}</p>\n'
            f"          </div>\n"
        )

    story_paras = ""
    for para in (story if isinstance(story, list) else [str(story)]):
        story_paras += f'          <p className="text-lg text-gray-600 leading-relaxed mb-4">{para}</p>\n'

    return (
        f'import type {{ Metadata }} from "next";\n\n'
        f'export const metadata: Metadata = {{ title: "About Us | {project}", description: "Learn about {project} — {purpose}" }};\n\n'
        f"export default function AboutPage() {{\n"
        f"  return (\n"
        f"    <>\n"
        f'      <section className="bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4 text-center">\n'
        f'          <h1 className="text-4xl md:text-5xl font-bold mb-4">About {project}</h1>\n'
        f'          <p className="text-xl opacity-90 max-w-2xl mx-auto">{purpose}</p>\n'
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20">\n'
        f'        <div className="max-w-4xl mx-auto px-4">\n'
        f'          <h2 className="text-3xl font-bold mb-8">Our Story</h2>\n'
        f"{story_paras}"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-gray-50">\n'
        f'        <div className="max-w-7xl mx-auto px-4">\n'
        f'          <h2 className="text-3xl font-bold text-center mb-12">Our Values</h2>\n'
        f'          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">\n'
        f"{values_html}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4">\n'
        f'          <h2 className="text-3xl font-bold text-center mb-12">Our Team</h2>\n'
        f'          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">\n'
        f'            {{["Alex Thompson", "Jordan Lee", "Sam Rivera", "Taylor Kim"].map((name, i) => (\n'
        f'              <div key={{i}} className="text-center">\n'
        f'                <div className="w-32 h-32 bg-gradient-to-br from-gray-200 to-gray-300 rounded-full mx-auto mb-4" />\n'
        f'                <h3 className="font-semibold text-lg">{{name}}</h3>\n'
        f'                <p className="text-gray-500 text-sm">{{["CEO", "CTO", "Design Lead", "Head of Growth"][i]}}</p>\n'
        f"              </div>\n"
        f"            ))}}\n"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n"
        f"    </>\n"
        f"  );\n"
        f"}}\n"
    )


def _services_page(ctx: SkillContext) -> str:
    project = ctx.build_sot.project_name
    cb = ctx.content_blocks
    services = cb.get("page_services", cb.get("services", [
        "Web Development: Custom websites and web applications built with modern technologies",
        "Design: Beautiful, user-centered designs that convert visitors into customers",
        "Consulting: Strategic guidance to help your business grow and scale",
        "Support: Ongoing maintenance and support to keep everything running smoothly",
        "Analytics: Data-driven insights to optimize your digital presence",
        "Marketing: Digital marketing strategies that drive real results",
    ]))

    service_cards = ""
    for i, svc in enumerate(services[:6]):
        if isinstance(svc, str) and ": " in svc:
            title, desc = svc.split(": ", 1)
        else:
            title, desc = str(svc), ""
        service_cards += (
            f'          <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100 hover:shadow-lg transition-shadow">\n'
            f'            <div className="w-12 h-12 bg-[var(--color-primary)]/10 rounded-xl flex items-center justify-center mb-5">\n'
            f'              <span className="text-[var(--color-primary)] text-2xl font-bold">{i + 1}</span>\n'
            f"            </div>\n"
            f'            <h3 className="text-xl font-semibold mb-3">{title}</h3>\n'
            f'            <p className="text-gray-600 leading-relaxed">{desc}</p>\n'
            f"          </div>\n"
        )

    return (
        f'import type {{ Metadata }} from "next";\n'
        f'import Link from "next/link";\n\n'
        f'export const metadata: Metadata = {{ title: "Services | {project}", description: "Explore our services" }};\n\n'
        f"export default function ServicesPage() {{\n"
        f"  return (\n"
        f"    <>\n"
        f'      <section className="bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4 text-center">\n'
        f'          <h1 className="text-4xl md:text-5xl font-bold mb-4">Our Services</h1>\n'
        f'          <p className="text-xl opacity-90 max-w-2xl mx-auto">Comprehensive solutions tailored to your needs</p>\n'
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4">\n'
        f'          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-8">\n'
        f"{service_cards}"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-gray-50">\n'
        f'        <div className="max-w-7xl mx-auto px-4">\n'
        f'          <h2 className="text-3xl font-bold text-center mb-12">Our Process</h2>\n'
        f'          <div className="grid md:grid-cols-4 gap-8">\n'
        f'            {{["Discovery", "Strategy", "Execution", "Optimization"].map((step, i) => (\n'
        f'              <div key={{i}} className="text-center">\n'
        f'                <div className="w-16 h-16 bg-[var(--color-primary)] text-white rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4">{{i + 1}}</div>\n'
        f'                <h3 className="font-semibold text-lg mb-2">{{step}}</h3>\n'
        f'                <p className="text-gray-600 text-sm">We ensure every step is handled with precision and care.</p>\n'
        f"              </div>\n"
        f"            ))}}\n"
        f"          </div>\n"
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20 bg-[var(--color-primary)] text-white">\n'
        f'        <div className="max-w-4xl mx-auto px-4 text-center">\n'
        f'          <h2 className="text-3xl font-bold mb-6">Ready to Start Your Project?</h2>\n'
        f'          <p className="text-xl opacity-90 mb-8">Let&apos;s discuss how we can help you achieve your goals.</p>\n'
        f'          <Link href="/contact" className="inline-block bg-white text-[var(--color-primary)] px-8 py-4 rounded-xl font-semibold hover:bg-gray-100 transition-colors">\n'
        f"            Contact Us\n"
        f"          </Link>\n"
        f"        </div>\n"
        f"      </section>\n"
        f"    </>\n"
        f"  );\n"
        f"}}\n"
    )


def _contact_page(ctx: SkillContext) -> str:
    project = ctx.build_sot.project_name
    return (
        '"use client";\n\n'
        'import { useState } from "react";\n\n'
        "export default function ContactPage() {\n"
        "  const [submitted, setSubmitted] = useState(false);\n\n"
        "  return (\n"
        "    <>\n"
        '      <section className="bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-20">\n'
        '        <div className="max-w-7xl mx-auto px-4 text-center">\n'
        '          <h1 className="text-4xl md:text-5xl font-bold mb-4">Get In Touch</h1>\n'
        '          <p className="text-xl opacity-90 max-w-2xl mx-auto">We\'d love to hear from you. Send us a message and we\'ll respond as soon as possible.</p>\n'
        "        </div>\n"
        "      </section>\n\n"
        '      <section className="py-20">\n'
        '        <div className="max-w-7xl mx-auto px-4">\n'
        '          <div className="grid lg:grid-cols-2 gap-16">\n'
        "            <div>\n"
        '              <h2 className="text-2xl font-bold mb-6">Send a Message</h2>\n'
        "              {submitted ? (\n"
        '                <div className="bg-green-50 border border-green-200 rounded-2xl p-8 text-center">\n'
        '                  <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">\n'
        '                    <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>\n'
        "                  </div>\n"
        '                  <h3 className="text-xl font-semibold text-green-800 mb-2">Thank you!</h3>\n'
        '                  <p className="text-green-700">We\'ll be in touch within 24 hours.</p>\n'
        "                </div>\n"
        "              ) : (\n"
        "                <form className=\"space-y-5\" onSubmit={(e) => { e.preventDefault(); setSubmitted(true); }}>\n"
        '                  <div className="grid sm:grid-cols-2 gap-5">\n'
        "                    <div>\n"
        '                      <label htmlFor="name" className="block text-sm font-medium mb-1.5">Name</label>\n'
        '                      <input id="name" type="text" required className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent transition-shadow" placeholder="John Doe" />\n'
        "                    </div>\n"
        "                    <div>\n"
        '                      <label htmlFor="email" className="block text-sm font-medium mb-1.5">Email</label>\n'
        '                      <input id="email" type="email" required className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent transition-shadow" placeholder="john@example.com" />\n'
        "                    </div>\n"
        "                  </div>\n"
        "                  <div>\n"
        '                    <label htmlFor="phone" className="block text-sm font-medium mb-1.5">Phone (optional)</label>\n'
        '                    <input id="phone" type="tel" className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent transition-shadow" placeholder="+1 (555) 000-0000" />\n'
        "                  </div>\n"
        "                  <div>\n"
        '                    <label htmlFor="subject" className="block text-sm font-medium mb-1.5">Subject</label>\n'
        '                    <input id="subject" type="text" required className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent transition-shadow" placeholder="How can we help?" />\n'
        "                  </div>\n"
        "                  <div>\n"
        '                    <label htmlFor="message" className="block text-sm font-medium mb-1.5">Message</label>\n'
        '                    <textarea id="message" rows={5} required className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[var(--color-primary)] focus:border-transparent transition-shadow resize-none" placeholder="Tell us about your project..." />\n'
        "                  </div>\n"
        '                  <button type="submit" className="w-full bg-[var(--color-primary)] text-white px-8 py-4 rounded-xl font-semibold text-lg hover:opacity-90 transition-opacity shadow-sm">\n'
        "                    Send Message\n"
        "                  </button>\n"
        "                </form>\n"
        "              )}\n"
        "            </div>\n"
        "            <div>\n"
        '              <h2 className="text-2xl font-bold mb-6">Contact Information</h2>\n'
        '              <div className="space-y-6">\n'
        '                <div className="flex gap-4">\n'
        '                  <div className="w-12 h-12 bg-[var(--color-primary)]/10 rounded-xl flex items-center justify-center flex-shrink-0">\n'
        '                    <svg className="w-6 h-6 text-[var(--color-primary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>\n'
        "                  </div>\n"
        "                  <div>\n"
        '                    <h3 className="font-semibold">Email</h3>\n'
        f'                    <a href="mailto:hello@example.com" className="text-[var(--color-primary)] hover:underline">hello@example.com</a>\n'
        "                  </div>\n"
        "                </div>\n"
        '                <div className="flex gap-4">\n'
        '                  <div className="w-12 h-12 bg-[var(--color-primary)]/10 rounded-xl flex items-center justify-center flex-shrink-0">\n'
        '                    <svg className="w-6 h-6 text-[var(--color-primary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" /></svg>\n'
        "                  </div>\n"
        "                  <div>\n"
        '                    <h3 className="font-semibold">Phone</h3>\n'
        '                    <a href="tel:+15550000000" className="text-[var(--color-primary)] hover:underline">+1 (555) 000-0000</a>\n'
        "                  </div>\n"
        "                </div>\n"
        '                <div className="flex gap-4">\n'
        '                  <div className="w-12 h-12 bg-[var(--color-primary)]/10 rounded-xl flex items-center justify-center flex-shrink-0">\n'
        '                    <svg className="w-6 h-6 text-[var(--color-primary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>\n'
        "                  </div>\n"
        "                  <div>\n"
        '                    <h3 className="font-semibold">Office</h3>\n'
        '                    <p className="text-gray-600">123 Business Ave, Suite 100<br />San Francisco, CA 94102</p>\n'
        "                  </div>\n"
        "                </div>\n"
        "              </div>\n"
        '              <div className="mt-10 bg-gray-100 rounded-2xl h-64 flex items-center justify-center">\n'
        '                <p className="text-gray-500">Map placeholder</p>\n'
        "              </div>\n"
        "            </div>\n"
        "          </div>\n"
        "        </div>\n"
        "      </section>\n"
        "    </>\n"
        "  );\n"
        "}\n"
    )


def _faq_page(ctx: SkillContext) -> str:
    project = ctx.build_sot.project_name
    faqs = ctx.content_blocks.get("page_faq", ctx.content_blocks.get("faq", [
        "What services do you offer?|We provide a comprehensive range of services including web development, design, consulting, and ongoing support.",
        "How long does a typical project take?|Most projects are completed within 4-8 weeks, depending on scope and complexity.",
        "What is your pricing model?|We offer flexible pricing with both project-based and retainer options to suit your needs.",
        "Do you offer ongoing support?|Absolutely. We provide 24/7 support and maintenance packages for all our clients.",
        "How do I get started?|Simply reach out through our contact form or give us a call, and we'll schedule a free consultation.",
        "What technologies do you use?|We use modern, industry-standard technologies including React, Next.js, TypeScript, and Tailwind CSS.",
        "Can you work with my existing systems?|Yes, we specialize in integrating with existing platforms and can adapt to your current tech stack.",
        "Do you provide design services?|Yes, our team includes experienced UX/UI designers who create beautiful, user-centered designs.",
    ]))

    faq_items = ""
    for i, item in enumerate(faqs[:12]):
        if isinstance(item, str) and "|" in item:
            q, a = item.split("|", 1)
        else:
            q, a = str(item), "Please contact us for more details."
        faq_items += (
            f'          <div className="border border-gray-200 rounded-xl overflow-hidden">\n'
            f"            <button\n"
            f'              className="w-full flex justify-between items-center px-6 py-5 text-left hover:bg-gray-50 transition-colors"\n'
            f"              onClick={{() => setOpen(open === {i} ? null : {i})}}\n"
            f"            >\n"
            f'              <span className="font-semibold text-lg pr-4">{q}</span>\n'
            f'              <svg className={{`w-5 h-5 transition-transform ${{open === {i} ? "rotate-180" : ""}}`}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{2}} d="M19 9l-7 7-7-7" /></svg>\n'
            f"            </button>\n"
            f"            {{open === {i} && (\n"
            f'              <div className="px-6 pb-5 text-gray-600 leading-relaxed">{a}</div>\n'
            f"            )}}\n"
            f"          </div>\n"
        )

    return (
        '"use client";\n\n'
        'import { useState } from "react";\n'
        'import Link from "next/link";\n\n'
        "export default function FAQPage() {\n"
        "  const [open, setOpen] = useState<number | null>(null);\n\n"
        "  return (\n"
        "    <>\n"
        '      <section className="bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-20">\n'
        '        <div className="max-w-7xl mx-auto px-4 text-center">\n'
        '          <h1 className="text-4xl md:text-5xl font-bold mb-4">Frequently Asked Questions</h1>\n'
        '          <p className="text-xl opacity-90 max-w-2xl mx-auto">Find answers to common questions about our services.</p>\n'
        "        </div>\n"
        "      </section>\n\n"
        '      <section className="py-20">\n'
        '        <div className="max-w-3xl mx-auto px-4 space-y-4">\n'
        f"{faq_items}"
        "        </div>\n"
        "      </section>\n\n"
        '      <section className="py-16 bg-gray-50">\n'
        '        <div className="max-w-4xl mx-auto px-4 text-center">\n'
        '          <h2 className="text-2xl font-bold mb-4">Still have questions?</h2>\n'
        '          <p className="text-gray-600 mb-6">We\'re here to help. Reach out to our team anytime.</p>\n'
        '          <Link href="/contact" className="inline-block bg-[var(--color-primary)] text-white px-8 py-3 rounded-xl font-semibold hover:opacity-90 transition-opacity">\n'
        "            Contact Us\n"
        "          </Link>\n"
        "        </div>\n"
        "      </section>\n"
        "    </>\n"
        "  );\n"
        "}\n"
    )


def _generic_page(ctx: SkillContext, page_name: str) -> str:
    title = page_name.replace("-", " ").replace("_", " ").title()
    project = ctx.build_sot.project_name
    page_key = f"page_{page_name.lower()}"
    sections = ctx.content_blocks.get(page_key, [])

    sections_jsx = ""
    for section_text in sections:
        if isinstance(section_text, str) and section_text.startswith("## "):
            parts = section_text.split("\n", 1)
            heading = parts[0].replace("## ", "")
            body = parts[1] if len(parts) > 1 else ""
            sections_jsx += (
                f'      <div className="mb-12">\n'
                f'        <h2 className="text-2xl font-bold mb-4">{heading}</h2>\n'
                f'        <p className="text-gray-600 leading-relaxed">{body}</p>\n'
                f"      </div>\n"
            )
        else:
            sections_jsx += f'      <p className="text-gray-600 leading-relaxed mb-6">{section_text}</p>\n'

    if not sections_jsx:
        sections_jsx = (
            f'      <div className="grid md:grid-cols-2 gap-12">\n'
            f"        <div>\n"
            f'          <h2 className="text-2xl font-bold mb-4">What We Offer</h2>\n'
            f'          <p className="text-gray-600 leading-relaxed mb-4">\n'
            f"            At {project}, we are dedicated to providing the best {title.lower()} experience.\n"
            f"            Our team of experts works tirelessly to exceed your expectations.\n"
            f"          </p>\n"
            f'          <p className="text-gray-600 leading-relaxed">\n'
            f"            With years of industry experience and a passion for excellence,\n"
            f"            we deliver results that truly make a difference.\n"
            f"          </p>\n"
            f"        </div>\n"
            f"        <div>\n"
            f'          <h2 className="text-2xl font-bold mb-4">Why Choose Us</h2>\n'
            f'          <ul className="space-y-3">\n'
            f'            {{["Expert team with proven experience", "Tailored solutions for every client", "Transparent communication throughout", "Results-driven approach"].map((item, i) => (\n'
            f'              <li key={{i}} className="flex items-start gap-3">\n'
            f'                <svg className="w-5 h-5 text-[var(--color-primary)] mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{2}} d="M5 13l4 4L19 7" /></svg>\n'
            f'                <span className="text-gray-600">{{item}}</span>\n'
            f"              </li>\n"
            f"            ))}}\n"
            f"          </ul>\n"
            f"        </div>\n"
            f"      </div>\n"
        )

    return (
        f'import type {{ Metadata }} from "next";\n\n'
        f'export const metadata: Metadata = {{ title: "{title} | {project}", description: "Learn more about our {title.lower()}" }};\n\n'
        f"export default function {_component_name(page_name)}Page() {{\n"
        f"  return (\n"
        f"    <>\n"
        f'      <section className="bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-secondary)] text-white py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4 text-center">\n'
        f'          <h1 className="text-4xl md:text-5xl font-bold mb-4">{title}</h1>\n'
        f'          <p className="text-xl opacity-90 max-w-2xl mx-auto">Discover what makes us different</p>\n'
        f"        </div>\n"
        f"      </section>\n\n"
        f'      <section className="py-20">\n'
        f'        <div className="max-w-7xl mx-auto px-4">\n'
        f"{sections_jsx}"
        f"        </div>\n"
        f"      </section>\n"
        f"    </>\n"
        f"  );\n"
        f"}}\n"
    )


class PagesSkill(Skill):
    name = "pages"
    phase = 2
    depends_on = ["scaffold", "design", "layout"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []

        for page in ctx.build_sot.page_list:
            slug = page.strip().lower().replace(" ", "-")
            page_type = _classify(slug)

            if page_type == "home":
                content = _home_page(ctx)
                files.append(FileOperation(path="src/app/page.tsx", content=content, file_type="page"))
            elif page_type == "about":
                content = _about_page(ctx)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))
            elif page_type == "services":
                content = _services_page(ctx)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))
            elif page_type == "contact":
                content = _contact_page(ctx)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))
            elif page_type == "faq":
                content = _faq_page(ctx)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))
            else:
                content = _generic_page(ctx, slug)
                files.append(FileOperation(path=f"src/app/{slug}/page.tsx", content=content, file_type="page"))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files
