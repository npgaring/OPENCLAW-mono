"""Recover tasks left in limbo when the gate restarts during or before execution (H4).

Tasks with status=submitted, execution_token_hash set, and no execution_id are
orphaned: the gate committed the token and then crashed or restarted before
recording the execution result. Marking them as 'error' ensures no orphaned
execution state and allows clients to retry with a new submission.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)

ORPHAN_STATUS = TaskStatus.error
ORPHAN_AUDIT_EVENT = "gate_restart_orphan_recovery"


async def recover_orphaned_tasks(session: AsyncSession) -> int:
    """Find tasks that have token consumed but no execution_id (gate died mid-flow). Mark as error."""
    stmt = select(Task).where(
        Task.status == TaskStatus.submitted,
        Task.execution_token_hash.isnot(None),
        Task.execution_id.is_(None),
    )
    result = await session.execute(stmt)
    orphans = list(result.scalars().all())
    if not orphans:
        return 0
    for task in orphans:
        task.status = ORPHAN_STATUS
        audit = list(task.audit_history or [])
        audit.append({
            "event_type": ORPHAN_AUDIT_EVENT,
            "payload": {"reason": "gate_restart_or_crash_before_execution_result"},
        })
        task.audit_history = audit
        flag_modified(task, "audit_history")
        logger.info("Recovered orphan task task_id=%s -> status=%s", task.task_id, ORPHAN_STATUS.value)
    await session.commit()
    return len(orphans)
