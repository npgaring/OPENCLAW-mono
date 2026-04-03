"""OpenAI-powered content enrichment for Build SoT during cognitive phase."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models.governed_v2 import BuildSoTV1
from app.services.openai_chat_compat import (
    sanitize_chat_completions_payload,
    summarize_chat_completions_exception,
)

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

CONTENT_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hero_headline": {"type": "string"},
        "hero_subheadline": {"type": "string"},
        "value_propositions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "icon_hint": {"type": "string"},
                },
                "required": ["title", "description", "icon_hint"],
            },
        },
        "page_content": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "meta_title": {"type": "string"},
                    "meta_description": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                                "cta_text": {"type": ["string", "null"]},
                                "cta_href": {"type": ["string", "null"]},
                            },
                            "required": ["id", "heading", "body", "cta_text", "cta_href"],
                        },
                    },
                },
                "required": ["meta_title", "meta_description", "sections"],
            },
        },
        "cta_primary_text": {"type": "string"},
        "cta_secondary_text": {"type": "string"},
        "footer_tagline": {"type": "string"},
        "color_suggestion": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary": {"type": "string"},
                "secondary": {"type": "string"},
                "accent": {"type": "string"},
                "background": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["primary", "secondary", "accent", "background", "text"],
        },
        "font_suggestion": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "heading": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["heading", "body"],
        },
    },
    "required": [
        "hero_headline",
        "hero_subheadline",
        "value_propositions",
        "page_content",
        "cta_primary_text",
        "cta_secondary_text",
        "footer_tagline",
        "color_suggestion",
        "font_suggestion",
    ],
}


def _build_enrichment_prompt(build_sot: BuildSoTV1) -> dict[str, Any]:
    context = {
        "project_name": build_sot.project_name,
        "site_purpose": build_sot.site_purpose,
        "target_audience": build_sot.target_audience,
        "desired_tone": build_sot.desired_tone,
        "page_list": build_sot.page_list,
        "integrations": build_sot.integrations,
        "brand_constraints": build_sot.brand_constraints,
        "forms_ctas": build_sot.forms_ctas,
        "section_definitions": [s.model_dump() for s in build_sot.section_definitions],
    }

    system = (
        "You are a senior web content strategist and UX copywriter. "
        "Generate production-ready website content based on the project brief. "
        "Content must be compelling, conversion-focused, and match the desired tone exactly. "
        "Each page needs real, substantive content — not placeholder text. "
        "Write copy that a real business would publish immediately. "
        "Return strict JSON only matching the required schema."
    )

    payload = {
        "model": settings.openai_content_model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, indent=2)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "content_enrichment",
                "strict": True,
                "schema": CONTENT_ENRICHMENT_SCHEMA,
            },
        },
    }
    return sanitize_chat_completions_payload(payload)


async def enrich_build_sot(build_sot: BuildSoTV1) -> BuildSoTV1:
    """Call OpenAI to enrich the Build SoT with production-quality content.

    Falls back to the original build_sot if OpenAI is unavailable or disabled.
    """
    if not settings.openai_content_enabled or not settings.openai_api_key:
        return build_sot

    payload = _build_enrichment_prompt(build_sot)
    try:
        timeout = httpx.Timeout(float(settings.openai_content_timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        resp.raise_for_status()
        raw = resp.json()
        content_str = raw["choices"][0]["message"]["content"]
        enriched = json.loads(content_str)
    except Exception as exc:
        logger.exception(
            "content_enrichment.openai_call_failed details=%s, falling back to deterministic content",
            summarize_chat_completions_exception(exc),
        )
        return build_sot

    return _apply_enrichment(build_sot, enriched)


def _apply_enrichment(build_sot: BuildSoTV1, enriched: dict[str, Any]) -> BuildSoTV1:
    """Merge OpenAI enrichment data into the Build SoT model."""
    content_blocks: dict[str, list[str]] = {
        "hero": [
            enriched.get("hero_headline", build_sot.project_name),
            enriched.get("hero_subheadline", build_sot.site_purpose),
        ],
        "ctas": [
            enriched.get("cta_primary_text", "Get Started"),
            enriched.get("cta_secondary_text", "Learn More"),
        ],
    }

    vps = enriched.get("value_propositions", [])
    if vps:
        content_blocks["value_propositions"] = [
            f"{vp['title']}: {vp['description']}" for vp in vps
        ]

    page_content = enriched.get("page_content", {})
    for page_name, page_data in page_content.items():
        sections = page_data.get("sections", [])
        section_texts = []
        for sec in sections:
            section_texts.append(f"## {sec.get('heading', '')}\n{sec.get('body', '')}")
            if sec.get("cta_text"):
                section_texts.append(f"[CTA: {sec['cta_text']}]({sec.get('cta_href', '#')})")
        content_blocks[f"page_{page_name}"] = section_texts

    content_blocks["footer"] = [enriched.get("footer_tagline", build_sot.project_name)]

    build_sot.content_blocks = content_blocks

    seo_metadata: dict[str, Any] = {}
    for page_name, page_data in page_content.items():
        seo_metadata[page_name] = {
            "title": page_data.get("meta_title", ""),
            "description": page_data.get("meta_description", ""),
        }

    build_sot.extensions = {
        **build_sot.extensions,
        "seo_metadata": seo_metadata,
        "color_suggestion": enriched.get("color_suggestion", {}),
        "font_suggestion": enriched.get("font_suggestion", {}),
        "enrichment_version": "1.0",
    }

    return build_sot
