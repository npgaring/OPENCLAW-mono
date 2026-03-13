"""Create tables (SQLite for tests; PG may already have tables from migration 003)."""
from sqlmodel import SQLModel

from app.db.session import get_engine
from app.models import AuditEvent, GateDecisionRecord, Task, UsedExecutionToken


async def init_db() -> None:
    """Create all tables if they do not exist."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, checkfirst=True)
