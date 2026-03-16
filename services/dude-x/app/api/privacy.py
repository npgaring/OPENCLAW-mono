"""GET /privacy: privacy policy HTML."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.ui.html import render_page

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy():
    html = render_page(
        title="Privacy - DUDE-X",
        eyebrow="Policy",
        heading="Privacy",
        description=(
            "This service processes specs and produces plans. No personal data is stored beyond audit logs "
            "(spec_hash, plan_hash, event_type)."
        ),
        actions=[
            {"label": "Back to Home", "href": "/", "kind": "secondary"},
            {"label": "Swagger UI", "href": "/docs", "kind": "primary"},
        ],
        meta="Last updated: 2026-03-13",
    )
    return HTMLResponse(html)
