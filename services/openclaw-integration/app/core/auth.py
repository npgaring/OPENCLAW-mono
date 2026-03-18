"""Bearer token auth for integration API."""
from typing import Optional

from fastapi import Header, HTTPException

from app.core.config import settings
from app.core.errors import unauthorized


async def require_integration_auth(authorization: Optional[str] = Header(None, include_in_schema=False)):
    """Dependency: require Authorization: Bearer <INTEGRATION_API_KEY>."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(**unauthorized())
    token = authorization[7:].strip()
    if token != settings.integration_api_key:
        raise HTTPException(**unauthorized())
    return token
