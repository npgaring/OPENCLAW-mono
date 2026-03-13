"""POST /gate: GateRequest(plan_hash) -> GateResponse."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DUDEXError, ErrorCode
from app.core.gate import evaluate_gate
from app.db.session import get_session
from app.models import PlanPayload, PlanRecord
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_hash: str


class GateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_hash: str
    gate_decision: str  # PASS | BLOCK
    reason: str | None = None


@router.post("/gate", response_model=GateResponse)
async def submit_to_gate(req: GateRequest, session: AsyncSession = Depends(get_session)):
    """Load plan by hash, run gate, return decision."""
    record = await session.get(PlanRecord, req.plan_hash)
    if record is None:
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Plan not found", details={"plan_hash": req.plan_hash})
    plan = PlanPayload(**record.payload)
    result = evaluate_gate(plan)
    return GateResponse(
        plan_hash=result["plan_hash"],
        gate_decision=result["gate_decision"],
        reason=result.get("reason"),
    )
