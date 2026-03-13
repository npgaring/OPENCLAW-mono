"""GET /health. Also triggers DB migrations on first request if not yet run."""
from app.core.config import settings
from app.models import HealthResponse
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    from app.db.init_db import ensure_db_ready
    await ensure_db_ready()
    return HealthResponse(status="ok", env=settings.app_env)
