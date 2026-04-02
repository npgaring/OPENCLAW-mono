"""Create tables: run SQL migrations on PostgreSQL every deploy; SQLModel create_all for SQLite tests."""
import asyncio
import logging

from sqlmodel import SQLModel

from app.core.config import settings
from app.db.run_migrations import run_migration_files
from app.db.session import get_engine
from app.models import (
    AuditEvent,
    ExecutionPlanLockRecord,
    GateDecisionRecord,
    InvariantCDecisionRecord,
    OpenAIVesselEvent,
    SubstrateAdapterEvent,
    Task,
    UsedExecutionToken,
)
from app.models.approval_request import ApprovalRequest
from app.models.evaluation_record import EvaluationRecord

logger = logging.getLogger(__name__)

# Run in order: dude-x (001, 002), openclaw-integration (003, 004)
_MIGRATION_FILES = [
    "001_dude_x_tables.sql",
    "002_add_identity_columns.sql",
    "003_openclaw_integration_tables.sql",
    "004_task_status_partial_needs_review.sql",
    "005_trace_id.sql",
    "006_uato_columns.sql",
    "007_openai_invariant_adapter.sql",
    "008_uato_task_statuses.sql",
    "009_invariant_e_columns.sql",
    "010_governance_outcome_column.sql",
    "011_approval_workflow.sql",
    "012_evaluation_records.sql",
    "013_governed_v2_execution_locks.sql",
    "014_uuid_columns_to_text.sql",
]

_init_lock = asyncio.Lock()
_init_done = False


async def init_db() -> None:
    """Run migration SQL on PostgreSQL (every deploy); then ensure tables exist via SQLModel."""
    if not settings.database_url:
        return
    engine = get_engine()
    url = (settings.get_database_url_normalized() or "").lower()
    is_pg = "postgresql" in url and "asyncpg" in url
    async with engine.begin() as conn:
        if is_pg:
            await run_migration_files(conn, _MIGRATION_FILES)
        await conn.run_sync(SQLModel.metadata.create_all, checkfirst=True)


async def ensure_db_ready() -> None:
    """Run init_db once (on first request). Ensures migrations run even if Vercel lifespan does not."""
    global _init_done
    if _init_done:
        return
    async with _init_lock:
        if _init_done:
            return
        try:
            logger.info("Running DB init/migrations (first request)")
            await init_db()
            _init_done = True
            logger.info("DB init/migrations complete")
        except Exception as e:
            logger.exception("DB init failed: %s", e)
            raise
