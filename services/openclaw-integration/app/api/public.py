"""GET /, GET /privacy — HTML."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.ui.html import render_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root():
    html = render_page(
        title="OpenClaw Integration",
        eyebrow="Monorepo Service",
        heading="OpenClaw Integration",
        description="Governance-gated layer between callers and the runtime executor.",
        actions=[
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
            {"label": "ReDoc", "href": "/redoc", "kind": "secondary"},
            {"label": "Health", "href": "/health", "kind": "secondary"},
            {"label": "Privacy", "href": "/privacy", "kind": "ghost"},
            {"label": "OpenAPI JSON", "href": "/openapi.json", "kind": "ghost"},
        ],
        meta="Protected endpoints require Authorization: Bearer <INTEGRATION_API_KEY>.",
    )
    return HTMLResponse(html)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    html = render_page(
        title="Privacy - OpenClaw Integration",
        eyebrow="Policy",
        heading="Privacy",
        description=(
            "This service processes task submissions and audit callbacks. "
            "Task and audit data are stored for governance and audit purposes."
        ),
        actions=[
            {"label": "Back to Home", "href": "/", "kind": "secondary"},
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
            {"label": "Health", "href": "/health", "kind": "ghost"},
        ],
        meta="Last updated: 2026-03-13",
    )
    return HTMLResponse(html)
