"""Tests for Chat Completions GPT-5 compatibility helpers and payload callers."""
from __future__ import annotations

import json

import pytest

from app.api.governed_v2 import _build_refine_payload
from app.core.config import settings
from app.models.governed_v2 import BuildSoTV1, SectionDefinition
from app.services.content_enrichment import _build_enrichment_prompt, enrich_build_sot
from app.services.openai_chat_compat import (
    is_gpt5_family_model,
    sanitize_chat_completions_payload,
)
from app.skills.base import Skill, SkillContext


def _build_sot() -> BuildSoTV1:
    return BuildSoTV1(
        project_name="Acme Web",
        site_purpose="Generate qualified leads",
        target_audience=["buyers"],
        desired_tone="professional",
        page_list=["home", "contact"],
        nav_structure=["home", "contact"],
        section_definitions=[SectionDefinition(page="home", section="hero")],
        forms_ctas=["contact"],
        acceptance_criteria=["all_routes_render"],
    )


def test_is_gpt5_family_model():
    assert is_gpt5_family_model("gpt-5.4-mini") is True
    assert is_gpt5_family_model("gpt-5") is True
    assert is_gpt5_family_model("gpt-4.1-mini") is False


def test_sanitize_chat_completions_payload_temperature_behavior():
    original = {"model": "gpt-5.4-mini", "temperature": 0.7, "messages": []}
    out = sanitize_chat_completions_payload(original)
    assert "temperature" not in out
    assert "temperature" in original

    original_non_gpt5 = {"model": "gpt-4.1-mini", "temperature": 0.7, "messages": []}
    out_non_gpt5 = sanitize_chat_completions_payload(original_non_gpt5)
    assert out_non_gpt5["temperature"] == 0.7


def test_build_enrichment_prompt_omits_temperature_for_gpt5(monkeypatch):
    monkeypatch.setattr(settings, "openai_content_model", "gpt-5.4-mini")
    payload = _build_enrichment_prompt(_build_sot())
    assert payload["model"] == "gpt-5.4-mini"
    assert "temperature" not in payload


def test_build_enrichment_prompt_keeps_temperature_for_non_gpt5(monkeypatch):
    monkeypatch.setattr(settings, "openai_content_model", "gpt-4.1-mini")
    payload = _build_enrichment_prompt(_build_sot())
    assert payload["temperature"] == 0.7


def test_build_refine_payload_temperature_compat(monkeypatch):
    build_sot = _build_sot()

    monkeypatch.setattr(settings, "openai_content_model", "gpt-5.4-mini")
    gpt5_payload = _build_refine_payload(build_sot, "Change tone to concise")
    assert "temperature" not in gpt5_payload

    monkeypatch.setattr(settings, "openai_content_model", "gpt-4.1-mini")
    non_gpt5_payload = _build_refine_payload(build_sot, "Change tone to concise")
    assert non_gpt5_payload["temperature"] == 0.3


class _DummySkill(Skill):
    name = "dummy"

    async def generate(self, ctx: SkillContext):
        return []


@pytest.mark.asyncio
async def test_skill_base_call_openai_omits_temperature_for_gpt5(monkeypatch):
    captured: dict[str, object] = {}

    class _Response:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            captured["payload"] = kwargs["json"]
            return _Response()

    monkeypatch.setattr(settings, "skills_engine_model", "gpt-5.4-mini")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr("app.skills.base.httpx.AsyncClient", _Client)

    out = await _DummySkill()._call_openai("sys", "usr")
    assert out == {}
    sent_payload = captured["payload"]
    assert isinstance(sent_payload, dict)
    assert "temperature" not in sent_payload


@pytest.mark.asyncio
async def test_skill_base_call_openai_keeps_temperature_for_non_gpt5(monkeypatch):
    captured: dict[str, object] = {}

    class _Response:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            captured["payload"] = kwargs["json"]
            return _Response()

    monkeypatch.setattr(settings, "skills_engine_model", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr("app.skills.base.httpx.AsyncClient", _Client)

    out = await _DummySkill()._call_openai("sys", "usr")
    assert out == {}
    sent_payload = captured["payload"]
    assert isinstance(sent_payload, dict)
    assert sent_payload["temperature"] == 0.3


@pytest.mark.asyncio
async def test_content_enrichment_success_parses_when_gpt5_temperature_omitted(monkeypatch):
    captured: dict[str, object] = {}
    enriched = {
        "hero_headline": "Ship Faster",
        "hero_subheadline": "Governed web delivery",
        "value_propositions": [{"title": "Speed", "description": "Fast iterations", "icon_hint": "rocket"}],
        "page_content": {
            "home": {
                "meta_title": "Home | Acme",
                "meta_description": "Acme home page",
                "sections": [
                    {
                        "id": "hero",
                        "heading": "Welcome",
                        "body": "This is home",
                        "cta_text": "Start",
                        "cta_href": "/contact",
                    }
                ],
            }
        },
        "cta_primary_text": "Get Started",
        "cta_secondary_text": "Learn More",
        "footer_tagline": "Acme",
        "color_suggestion": {
            "primary": "#0b3d91",
            "secondary": "#1f2937",
            "accent": "#f59e0b",
            "background": "#ffffff",
            "text": "#111827",
        },
        "font_suggestion": {"heading": "Geist", "body": "Geist"},
    }

    class _Response:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(enriched)}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            captured["payload"] = kwargs["json"]
            return _Response()

    monkeypatch.setattr(settings, "openai_content_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_content_model", "gpt-5.4-mini")
    monkeypatch.setattr("app.services.content_enrichment.httpx.AsyncClient", _Client)

    build_sot = _build_sot()
    out = await enrich_build_sot(build_sot)
    sent_payload = captured["payload"]
    assert isinstance(sent_payload, dict)
    assert "temperature" not in sent_payload
    assert out.content_blocks["hero"][0] == "Ship Faster"
    assert out.extensions["enrichment_version"] == "1.0"
