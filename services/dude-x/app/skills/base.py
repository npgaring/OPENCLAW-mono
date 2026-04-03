"""Base classes for the skills engine."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.models.governed_v2 import BuildSoTV1
from app.services.openai_chat_compat import sanitize_chat_completions_payload

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


@dataclass
class FileOperation:
    """A single file to be created in the generated project."""
    path: str
    content: str
    file_type: str = "source"


@dataclass
class SkillContext:
    """Shared context passed to every skill during execution."""
    build_sot: BuildSoTV1
    project_slug: str
    repo_name: str
    framework: str
    upstream_files: dict[str, str] = field(default_factory=dict)

    @property
    def enrichment(self) -> dict[str, Any]:
        return self.build_sot.extensions or {}

    @property
    def colors(self) -> dict[str, str]:
        return self.enrichment.get("color_suggestion", {
            "primary": "#2563eb",
            "secondary": "#7c3aed",
            "accent": "#f59e0b",
            "background": "#ffffff",
            "text": "#111827",
        })

    @property
    def fonts(self) -> dict[str, str]:
        return self.enrichment.get("font_suggestion", {
            "heading": "Inter",
            "body": "Inter",
        })

    @property
    def seo_metadata(self) -> dict[str, Any]:
        return self.enrichment.get("seo_metadata", {})

    @property
    def content_blocks(self) -> dict[str, list[str]]:
        return self.build_sot.content_blocks


class Skill(ABC):
    """Abstract base for a website generation skill."""

    name: str = "base"
    phase: int = 1
    depends_on: list[str] = []

    @abstractmethod
    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        ...

    async def _call_openai(self, system: str, user_content: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Helper: make a structured-output OpenAI call."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        payload: dict[str, Any] = {
            "model": settings.skills_engine_model,
            "temperature": 0.3,
            "messages": messages,
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": f"skill_{self.name}",
                    "strict": True,
                    "schema": schema,
                },
            }
        payload = sanitize_chat_completions_payload(payload)
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
            return json.loads(content_str)
        except Exception:
            logger.exception("skill.%s.openai_call_failed", self.name)
            return {}
