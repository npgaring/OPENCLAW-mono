"""Bearer token authentication (shared integration token)."""
from fastapi import Header, HTTPException

from app.core.config import settings

async def require_integration_auth(authorization: str | None = Header(None, include_in_schema=False)):
    """Dependency: require Authorization: Bearer <INTEGRATION_API_KEY>."""
    if not settings.integration_api_key:
        raise HTTPException(
            status_code=500,
            detail="Integration API key not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header",
        )
    token = authorization[7:].strip()
    if token != settings.integration_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid integration token",
        )
    return token
