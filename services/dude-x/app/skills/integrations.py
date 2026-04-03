"""Integration skill: wires analytics, forms, CRM, and third-party service integrations."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext

_ANALYTICS_COMPONENT = (
    '"use client";\n\n'
    'import Script from "next/script";\n\n'
    "export function AnalyticsProvider() {\n"
    "  const gaId = process.env.NEXT_PUBLIC_ANALYTICS_KEY;\n"
    "  if (!gaId) return null;\n\n"
    "  return (\n"
    "    <>\n"
    '      <Script src={`https://www.googletagmanager.com/gtag/js?id=${gaId}`} strategy="afterInteractive" />\n'
    "      <Script id=\"ga-init\" strategy=\"afterInteractive\">\n"
    "        {`window.dataLayer = window.dataLayer || [];\n"
    "          function gtag(){dataLayer.push(arguments);}\n"
    "          gtag('js', new Date());\n"
    "          gtag('config', '${gaId}');`}\n"
    "      </Script>\n"
    "    </>\n"
    "  );\n"
    "}\n"
)

_HUBSPOT_COMPONENT = (
    '"use client";\n\n'
    'import Script from "next/script";\n\n'
    "export function HubSpotTracking() {\n"
    "  const portalId = process.env.NEXT_PUBLIC_HUBSPOT_KEY;\n"
    "  if (!portalId) return null;\n\n"
    "  return (\n"
    '    <Script\n'
    "      src={`//js.hs-scripts.com/${portalId}.js`}\n"
    '      strategy="afterInteractive"\n'
    "      id=\"hs-script-loader\"\n"
    "    />\n"
    "  );\n"
    "}\n"
)

_CALENDLY_COMPONENT = (
    '"use client";\n\n'
    'import Script from "next/script";\n\n'
    "interface CalendlyEmbedProps {\n"
    "  url?: string;\n"
    "}\n\n"
    "export function CalendlyEmbed({ url }: CalendlyEmbedProps) {\n"
    "  const calendlyUrl = url || process.env.NEXT_PUBLIC_CALENDLY_URL;\n"
    "  if (!calendlyUrl) return null;\n\n"
    "  return (\n"
    "    <>\n"
    '      <div className="calendly-inline-widget" data-url={calendlyUrl} style={{ minWidth: "320px", height: "630px" }} />\n'
    '      <Script src="https://assets.calendly.com/assets/external/widget.js" strategy="lazyOnload" />\n'
    "    </>\n"
    "  );\n"
    "}\n"
)

_SOCIAL_LINKS_COMPONENT = (
    "interface SocialLinksProps {\n"
    "  className?: string;\n"
    "}\n\n"
    "const SOCIAL_PLATFORMS = [\n"
    '  { name: "Twitter", href: "#", icon: "M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" },\n'
    '  { name: "LinkedIn", href: "#", icon: "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" },\n'
    '  { name: "GitHub", href: "#", icon: "M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" },\n'
    "];\n\n"
    "export function SocialLinks({ className = \"\" }: SocialLinksProps) {\n"
    "  return (\n"
    '    <div className={`flex gap-3 ${className}`}>\n'
    "      {SOCIAL_PLATFORMS.map((platform) => (\n"
    "        <a\n"
    "          key={platform.name}\n"
    "          href={platform.href}\n"
    '          className="w-10 h-10 bg-gray-100 rounded-lg flex items-center justify-center hover:bg-[var(--color-primary)] hover:text-white transition-colors"\n'
    "          aria-label={platform.name}\n"
    "          target=\"_blank\"\n"
    '          rel="noopener noreferrer"\n'
    "        >\n"
    '          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">\n'
    "            <path d={platform.icon} />\n"
    "          </svg>\n"
    "        </a>\n"
    "      ))}\n"
    "    </div>\n"
    "  );\n"
    "}\n"
)


class IntegrationsSkill(Skill):
    name = "integrations"
    phase = 3
    depends_on = ["scaffold", "layout"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []
        integrations = [i.lower().strip() for i in ctx.build_sot.integrations]

        if "analytics" in integrations:
            files.append(FileOperation(
                path="src/components/AnalyticsProvider.tsx",
                content=_ANALYTICS_COMPONENT,
                file_type="component",
            ))

        if "hubspot" in integrations:
            files.append(FileOperation(
                path="src/components/HubSpotTracking.tsx",
                content=_HUBSPOT_COMPONENT,
                file_type="component",
            ))

        if "calendly" in integrations:
            files.append(FileOperation(
                path="src/components/CalendlyEmbed.tsx",
                content=_CALENDLY_COMPONENT,
                file_type="component",
            ))

        files.append(FileOperation(
            path="src/components/SocialLinks.tsx",
            content=_SOCIAL_LINKS_COMPONENT,
            file_type="component",
        ))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files
