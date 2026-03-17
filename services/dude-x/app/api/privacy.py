"""GET /privacy: redirect to unified privacy policy."""
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/privacy", include_in_schema=False)
async def privacy_policy():
    return RedirectResponse(url="/openclaw-integration/privacy", status_code=307)
