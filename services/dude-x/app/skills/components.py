"""Components skill: generates shared, reusable UI components."""
from __future__ import annotations

from app.skills.base import FileOperation, Skill, SkillContext


class ComponentsSkill(Skill):
    name = "components"
    phase = 2
    depends_on = ["scaffold", "design"]

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []

        files.append(FileOperation(
            path="src/components/Hero.tsx",
            content=_hero_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/CTABanner.tsx",
            content=_cta_banner_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/FeatureCard.tsx",
            content=_feature_card_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/TestimonialCard.tsx",
            content=_testimonial_card_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/PricingCard.tsx",
            content=_pricing_card_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/TeamMember.tsx",
            content=_team_member_component(),
            file_type="component",
        ))
        files.append(FileOperation(
            path="src/components/SectionHeading.tsx",
            content=_section_heading_component(),
            file_type="component",
        ))

        for op in files:
            ctx.upstream_files[op.path] = op.content
        return files


def _hero_component() -> str:
    return (
        'import Link from "next/link";\n\n'
        "interface HeroProps {\n"
        "  title: string;\n"
        "  subtitle?: string;\n"
        "  ctaText?: string;\n"
        "  ctaHref?: string;\n"
        "  secondaryCtaText?: string;\n"
        "  secondaryCtaHref?: string;\n"
        "  gradient?: boolean;\n"
        "}\n\n"
        "export function Hero({\n"
        "  title,\n"
        '  subtitle,\n'
        '  ctaText = "Get Started",\n'
        '  ctaHref = "/contact",\n'
        "  secondaryCtaText,\n"
        "  secondaryCtaHref,\n"
        "  gradient = true,\n"
        "}: HeroProps) {\n"
        "  return (\n"
        "    <section\n"
        '      className={`py-24 lg:py-36 text-white ${\n'
        '        gradient\n'
        '          ? "bg-gradient-to-br from-[var(--color-primary)] via-[var(--color-secondary)] to-[var(--color-primary)]"\n'
        '          : "bg-[var(--color-primary)]"\n'
        "      }`}\n"
        "    >\n"
        '      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        '        <h1 className="text-4xl sm:text-5xl md:text-7xl font-bold mb-6 leading-tight tracking-tight">\n'
        "          {title}\n"
        "        </h1>\n"
        "        {subtitle && (\n"
        '          <p className="text-xl md:text-2xl opacity-90 max-w-3xl mx-auto mb-10 leading-relaxed">\n'
        "            {subtitle}\n"
        "          </p>\n"
        "        )}\n"
        '        <div className="flex flex-col sm:flex-row gap-4 justify-center">\n'
        "          <Link\n"
        "            href={ctaHref}\n"
        '            className="bg-white text-[var(--color-primary)] px-8 py-4 rounded-xl font-semibold text-lg hover:bg-gray-100 transition-colors shadow-lg"\n'
        "          >\n"
        "            {ctaText}\n"
        "          </Link>\n"
        "          {secondaryCtaText && secondaryCtaHref && (\n"
        "            <Link\n"
        "              href={secondaryCtaHref}\n"
        '              className="border-2 border-white/30 backdrop-blur-sm px-8 py-4 rounded-xl font-semibold text-lg hover:bg-white/10 transition-colors"\n'
        "            >\n"
        "              {secondaryCtaText}\n"
        "            </Link>\n"
        "          )}\n"
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _cta_banner_component() -> str:
    return (
        'import Link from "next/link";\n\n'
        "interface CTABannerProps {\n"
        "  title: string;\n"
        "  description?: string;\n"
        "  buttonText?: string;\n"
        "  buttonHref?: string;\n"
        "}\n\n"
        "export function CTABanner({\n"
        "  title,\n"
        "  description,\n"
        '  buttonText = "Get Started",\n'
        '  buttonHref = "/contact",\n'
        "}: CTABannerProps) {\n"
        "  return (\n"
        '    <section className="py-20 bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-secondary)] text-white">\n'
        '      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">\n'
        '        <h2 className="text-3xl md:text-4xl font-bold mb-4">{title}</h2>\n'
        '        {description && <p className="text-xl opacity-90 mb-8">{description}</p>}\n'
        "        <Link\n"
        "          href={buttonHref}\n"
        '          className="inline-block bg-white text-[var(--color-primary)] px-10 py-4 rounded-xl font-semibold text-lg hover:bg-gray-100 transition-colors shadow-lg"\n'
        "        >\n"
        "          {buttonText}\n"
        "        </Link>\n"
        "      </div>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _feature_card_component() -> str:
    return (
        "interface FeatureCardProps {\n"
        "  title: string;\n"
        "  description: string;\n"
        "  icon?: React.ReactNode;\n"
        "  index?: number;\n"
        "}\n\n"
        "export function FeatureCard({ title, description, icon, index = 0 }: FeatureCardProps) {\n"
        "  return (\n"
        '    <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">\n'
        '      <div className="w-14 h-14 bg-gradient-to-br from-[var(--color-primary)]/10 to-[var(--color-secondary)]/10 rounded-xl flex items-center justify-center mb-5">\n'
        "        {icon || (\n"
        '          <span className="text-[var(--color-primary)] text-2xl font-bold">{index + 1}</span>\n'
        "        )}\n"
        "      </div>\n"
        '      <h3 className="text-xl font-semibold mb-3">{title}</h3>\n'
        '      <p className="text-gray-600 leading-relaxed">{description}</p>\n'
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _testimonial_card_component() -> str:
    return (
        "interface TestimonialCardProps {\n"
        "  quote: string;\n"
        "  author: string;\n"
        "  role?: string;\n"
        "  rating?: number;\n"
        "}\n\n"
        "export function TestimonialCard({ quote, author, role, rating = 5 }: TestimonialCardProps) {\n"
        "  return (\n"
        '    <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">\n'
        '      <div className="flex gap-1 mb-4">\n'
        "        {[...Array(rating)].map((_, i) => (\n"
        '          <svg key={i} className="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">\n'
        '            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />\n'
        "          </svg>\n"
        "        ))}\n"
        "      </div>\n"
        '      <p className="text-gray-700 leading-relaxed mb-6 italic">&ldquo;{quote}&rdquo;</p>\n'
        "      <div>\n"
        '        <p className="font-semibold">{author}</p>\n'
        '        {role && <p className="text-sm text-gray-500">{role}</p>}\n'
        "      </div>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _pricing_card_component() -> str:
    return (
        'import Link from "next/link";\n\n'
        "interface PricingCardProps {\n"
        "  name: string;\n"
        "  price: string;\n"
        "  period?: string;\n"
        "  description?: string;\n"
        "  features: string[];\n"
        "  highlighted?: boolean;\n"
        "  ctaText?: string;\n"
        "  ctaHref?: string;\n"
        "}\n\n"
        "export function PricingCard({\n"
        "  name,\n"
        "  price,\n"
        '  period = "/month",\n'
        "  description,\n"
        "  features,\n"
        "  highlighted = false,\n"
        '  ctaText = "Get Started",\n'
        '  ctaHref = "/contact",\n'
        "}: PricingCardProps) {\n"
        "  return (\n"
        "    <div\n"
        "      className={`rounded-2xl p-8 ${\n"
        "        highlighted\n"
        '          ? "bg-[var(--color-primary)] text-white shadow-2xl scale-105 relative"\n'
        '          : "bg-white border border-gray-200 shadow-sm"\n'
        "      }`}\n"
        "    >\n"
        "      {highlighted && (\n"
        '        <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-[var(--color-accent)] text-white text-sm font-semibold px-4 py-1 rounded-full">\n'
        "          Most Popular\n"
        "        </div>\n"
        "      )}\n"
        '      <h3 className="text-xl font-bold mb-2">{name}</h3>\n'
        "      {description && (\n"
        "        <p className={`text-sm mb-4 ${highlighted ? \"opacity-90\" : \"text-gray-500\"}`}>{description}</p>\n"
        "      )}\n"
        '      <div className="mb-6">\n'
        '        <span className="text-4xl font-bold">{price}</span>\n'
        "        <span className={`text-sm ${highlighted ? \"opacity-80\" : \"text-gray-500\"}`}>{period}</span>\n"
        "      </div>\n"
        '      <ul className="space-y-3 mb-8">\n'
        "        {features.map((feature, i) => (\n"
        '          <li key={i} className="flex items-center gap-3">\n'
        "            <svg\n"
        '              className={`w-5 h-5 flex-shrink-0 ${highlighted ? "text-white" : "text-[var(--color-primary)]"}`}\n'
        '              fill="none" stroke="currentColor" viewBox="0 0 24 24"\n'
        "            >\n"
        '              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />\n'
        "            </svg>\n"
        '            <span className="text-sm">{feature}</span>\n'
        "          </li>\n"
        "        ))}\n"
        "      </ul>\n"
        "      <Link\n"
        "        href={ctaHref}\n"
        "        className={`block text-center py-3 rounded-xl font-semibold transition-colors ${\n"
        "          highlighted\n"
        '            ? "bg-white text-[var(--color-primary)] hover:bg-gray-100"\n'
        '            : "bg-[var(--color-primary)] text-white hover:opacity-90"\n'
        "        }`}\n"
        "      >\n"
        "        {ctaText}\n"
        "      </Link>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _team_member_component() -> str:
    return (
        "interface TeamMemberProps {\n"
        "  name: string;\n"
        "  role: string;\n"
        "  bio?: string;\n"
        "  imageUrl?: string;\n"
        "}\n\n"
        "export function TeamMember({ name, role, bio, imageUrl }: TeamMemberProps) {\n"
        "  return (\n"
        '    <div className="text-center group">\n'
        '      <div className="relative w-40 h-40 mx-auto mb-4 overflow-hidden rounded-2xl">\n'
        "        {imageUrl ? (\n"
        "          // eslint-disable-next-line @next/next/no-img-element\n"
        '          <img src={imageUrl} alt={name} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />\n'
        "        ) : (\n"
        '          <div className="w-full h-full bg-gradient-to-br from-gray-200 to-gray-300 flex items-center justify-center">\n'
        '            <span className="text-4xl text-gray-500">{name[0]}</span>\n'
        "          </div>\n"
        "        )}\n"
        "      </div>\n"
        '      <h3 className="font-semibold text-lg">{name}</h3>\n'
        '      <p className="text-[var(--color-primary)] text-sm font-medium">{role}</p>\n'
        '      {bio && <p className="text-gray-500 text-sm mt-2 max-w-xs mx-auto">{bio}</p>}\n'
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _section_heading_component() -> str:
    return (
        "interface SectionHeadingProps {\n"
        "  title: string;\n"
        "  subtitle?: string;\n"
        "  centered?: boolean;\n"
        "}\n\n"
        "export function SectionHeading({ title, subtitle, centered = true }: SectionHeadingProps) {\n"
        "  return (\n"
        "    <div className={`mb-12 ${centered ? \"text-center\" : \"\"}`}>\n"
        '      <h2 className="text-3xl md:text-4xl font-bold mb-4">{title}</h2>\n'
        "      {subtitle && (\n"
        "        <p className={`text-lg text-gray-600 ${centered ? \"max-w-2xl mx-auto\" : \"\"}`}>\n"
        "          {subtitle}\n"
        "        </p>\n"
        "      )}\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
