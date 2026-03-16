"""GET /: landing HTML."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.ui.html import render_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    html = render_page(
        title="DUDE-X",
        eyebrow="Monorepo Service",
        heading="DUDE-X",
        description="Compile-only deterministic planner for spec validation and plan expansion.",
        actions=[
            {"label": "Back to Main", "href": "/", "kind": "ghost"},
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
            {"label": "ReDoc", "href": "/redoc", "kind": "secondary"},
            {"label": "Health", "href": "/health", "kind": "secondary"},
            {"label": "OpenAPI JSON", "href": "/openapi.json", "kind": "secondary"},
            {"label": "Privacy", "href": "/privacy", "kind": "ghost"},
        ],
        meta="Requires X-API-Key for protected endpoints.",
    )
    return HTMLResponse(html)
