"""GET /health."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()
