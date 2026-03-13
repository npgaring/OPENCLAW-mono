"""GET /plans/{plan_hash}: return plan payload."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DUDEXError, ErrorCode
from app.db.session import get_session
from app.models import PlanPayload, PlanRecord

router = APIRouter()


@router.get("/plans/{plan_hash}", response_model=PlanPayload)
async def get_plan(plan_hash: str, session: AsyncSession = Depends(get_session)):
    """Return plan by hash. 400 if not found."""
    record = await session.get(PlanRecord, plan_hash)
    if record is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Plan not found", details={"plan_hash": plan_hash})
    return PlanPayload(**record.payload)
