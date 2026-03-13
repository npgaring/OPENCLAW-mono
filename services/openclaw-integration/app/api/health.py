"""GET /health."""
from app.models import HealthResponse
from app.core.config import settings
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", env=settings.app_env)
