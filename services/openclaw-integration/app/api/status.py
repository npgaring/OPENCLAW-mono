"""GET /status/{task_id}."""
from app.core.errors import task_not_found
from app.models import Task, TaskStatusResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter()


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(**task_not_found())
    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        execution_id=task.execution_id,
        governance_outcome=task.governance_outcome,
        audit_history=task.audit_history or [],
    )
