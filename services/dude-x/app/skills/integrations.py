"""Integration skill: wires analytics, forms, CRM integrations."""
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


class IntegrationsSkill(Skill):
    name = "integrations"
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

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
