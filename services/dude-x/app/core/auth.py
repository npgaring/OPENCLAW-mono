"""API key authentication."""
from fastapi import Header, HTTPException

from app.core.config import settings

API_KEY_HEADER = "X-API-Key"


async def verify_api_key(x_api_key: str | None = Header(None, alias=API_KEY_HEADER, include_in_schema=False)):
    """Dependency: require valid X-API-Key. 401 if missing/invalid, 500 if key not configured."""
    if not settings.dude_x_dusky_api_key:
        raise HTTPException(
            status_code=500,
            detail="API key not configured",
        )
    if not x_api_key or x_api_key != settings.dude_x_dusky_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )
    return x_api_key
