"""GET /, GET /privacy, GET /migrate — HTML and migration trigger."""
from __future__ import annotations

import copy
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.ui.html import render_page

router = APIRouter()


def _prefix_paths(paths: dict[str, Any], prefix: str) -> dict[str, Any]:
    if not prefix or prefix == "/":
        return paths
    cleaned = prefix.rstrip("/")
    return {f"{cleaned}{path}": value for path, value in paths.items()}


def _namespace_components(schema: dict[str, Any], prefix: str) -> dict[str, dict[str, str]]:
    components = schema.get("components") or {}
    mapping: dict[str, dict[str, str]] = {}
    for comp_type, entries in components.items():
        if not isinstance(entries, dict):
            continue
        mapping[comp_type] = {}
        for name in entries.keys():
            mapping[comp_type][name] = f"{prefix}_{name}"
    return mapping


def _rewrite_refs(obj: Any, mapping: dict[str, dict[str, str]]) -> Any:
    if isinstance(obj, dict):
        return {k: _rewrite_refs(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_refs(v, mapping) for v in obj]
    if isinstance(obj, str):
        for comp_type, names in mapping.items():
            for name, new_name in names.items():
                needle = f"#/components/{comp_type}/{name}"
                if needle in obj:
                    obj = obj.replace(needle, f"#/components/{comp_type}/{new_name}")
        return obj
    return obj


def _apply_component_namespace(schema: dict[str, Any], prefix: str) -> dict[str, Any]:
    if not prefix:
        return schema
    schema = copy.deepcopy(schema)
    mapping = _namespace_components(schema, prefix)
    schema = _rewrite_refs(schema, mapping)
    components = schema.get("components") or {}
    for comp_type, names in mapping.items():
        entries = components.get(comp_type)
        if not isinstance(entries, dict):
            continue
        components[comp_type] = {names[name]: value for name, value in entries.items()}
    schema["components"] = components
    return schema


def _normalize_request_body_schema(schema: dict[str, Any]) -> None:
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            request_body = operation.get("requestBody")
            if not isinstance(request_body, dict):
                continue
            content = request_body.get("content")
            if not isinstance(content, dict):
                continue
            for media in content.values():
                if not isinstance(media, dict):
                    continue
                body_schema = media.get("schema")
                if not isinstance(body_schema, dict):
                    continue
                examples = body_schema.get("examples")
                if isinstance(examples, dict):
                    body_schema["examples"] = list(examples.values())
                if "examples" in body_schema and "type" not in body_schema and "$ref" not in body_schema:
                    body_schema["type"] = "object"


def _guess_dudex_root_path() -> str:
    dudex_root = os.getenv("DUDEX_ROOT_PATH")
    if dudex_root:
        return dudex_root
    if os.getenv("VERCEL") == "1":
        return "/dude-x"
    return ""


def _guess_integration_root_path() -> str:
    root = os.getenv("OPENCLAW_INTEGRATION_ROOT_PATH")
    if root:
        return root
    if os.getenv("VERCEL") == "1":
        return "/openclaw-integration"
    return ""


@router.get("/migrate", include_in_schema=False)
async def run_migrate():
    """Run DB migrations (idempotent). Call after deploy to ensure tables exist. No auth required."""
    from app.db.init_db import ensure_db_ready
    await ensure_db_ready()
    return JSONResponse(content={"status": "ok", "message": "Migrations run"})


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    html = render_page(
        title="OpenClaw Integration",
        eyebrow="Monorepo Service",
        heading="OpenClaw Integration",
        description="Governance-gated layer between callers and the runtime executor.",
        actions=[
            {"label": "Back to Main", "href": "/", "kind": "ghost"},
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
            {"label": "ReDoc", "href": "/redoc", "kind": "secondary"},
            {"label": "Health", "href": "/health", "kind": "secondary"},
            {"label": "Privacy", "href": "/privacy", "kind": "ghost"},
            {"label": "OpenAPI JSON", "href": "/openapi-unified.json", "kind": "ghost"},
        ],
        meta="Protected endpoints require Authorization: Bearer <INTEGRATION_API_KEY>.",
    )
    return HTMLResponse(html)


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy():
    html = render_page(
        title="Privacy - OpenClaw Services",
        eyebrow="Policy",
        heading="Privacy Policy",
        description=(
            "This Privacy Policy covers the OpenClaw Services hosted on this domain, including "
            "OpenClaw Integration (governance gateway) and DUDE-X (planner service). It explains "
            "what data we process, why we process it, and how we protect it."
        ),
        actions=[
            {"label": "Back to Home", "href": "/", "kind": "secondary"},
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
            {"label": "Health", "href": "/health", "kind": "ghost"},
        ],
        meta=(
            "Data processed: task specs, plans, audit callbacks, execution metadata, and operational logs. "
            "Purpose: governance validation, execution routing, auditability, and service reliability. "
            "Storage: persisted in configured databases/log stores; retention governed by your environment policies. "
            "Sharing: no sale of data; access restricted to authorized operators and service infrastructure. "
            "Security: transport encryption (HTTPS), access controls, and least-privilege service accounts. "
            "User rights: contact the service owner for data export or deletion requests. "
            "Last updated: 2026-03-17."
        ),
    )
    return HTMLResponse(html)


@router.get("/openapi-unified.json", include_in_schema=False)
async def openapi_unified(request: Request):
    """Unified OpenAPI schema for Dude-X + OpenClaw Integration."""
    base_origin = f"{request.url.scheme}://{request.url.netloc}"
    dudex_root = _guess_dudex_root_path()
    integration_root = _guess_integration_root_path()

    dudex_url = f"{base_origin}{dudex_root}/openapi.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            dudex_resp = await client.get(dudex_url)
            dudex_resp.raise_for_status()
            dudex_schema = dudex_resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "Failed to load Dude-X OpenAPI", "url": dudex_url, "message": str(e)},
        ) from e

    from app.main import app as integration_app

    integration_schema = integration_app.openapi()

    dudex_schema = _apply_component_namespace(dudex_schema, "dudex")
    integration_schema = _apply_component_namespace(integration_schema, "integration")

    dudex_paths = _prefix_paths(dudex_schema.get("paths", {}), dudex_root)
    integration_paths = _prefix_paths(integration_schema.get("paths", {}), integration_root)

    combined_components: dict[str, Any] = {}
    for schema in (dudex_schema, integration_schema):
        for comp_type, entries in (schema.get("components") or {}).items():
            if not isinstance(entries, dict):
                continue
            combined_components.setdefault(comp_type, {}).update(entries)

    combined_tags = []
    for schema in (dudex_schema, integration_schema):
        tags = schema.get("tags")
        if isinstance(tags, list):
            combined_tags.extend(tags)

    combined_paths = {**dudex_paths, **integration_paths}
    privacy_paths = {
        f"{dudex_root.rstrip('/')}/privacy" if dudex_root else "/privacy",
        f"{integration_root.rstrip('/')}/privacy" if integration_root else "/privacy",
    }
    for path in privacy_paths:
        combined_paths.pop(path, None)

    combined = {
        "openapi": integration_schema.get("openapi", "3.0.0"),
        "info": {
            "title": "OpenClaw Unified API",
            "version": "1.0.0",
            "description": "Combined OpenAPI schema for Dude-X and OpenClaw Integration.",
        },
        "servers": [{"url": base_origin, "description": "Production"}],
        "paths": combined_paths,
        "components": combined_components,
    }
    if combined_tags:
        combined["tags"] = combined_tags

    _normalize_request_body_schema(combined)
    return JSONResponse(content=combined)
