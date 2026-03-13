"""Create tables: run SQL migrations on PostgreSQL every deploy; SQLModel create_all for SQLite tests."""
from sqlmodel import SQLModel

from app.core.config import settings
from app.db.run_migrations import run_migration_files
from app.db.session import get_engine
from app.models import AuditEvent, GateDecisionRecord, Task, UsedExecutionToken

# Run in order so shared DB has dude-x tables (001, 002) then openclaw-integration (003)
_MIGRATION_FILES = [
    "001_dude_x_tables.sql",
    "002_add_identity_columns.sql",
    "003_openclaw_integration_tables.sql",
]


async def init_db() -> None:
    """Run migration SQL on PostgreSQL (every deploy); then ensure tables exist via SQLModel."""
    engine = get_engine()
    url = (settings.get_database_url_normalized() or "").lower()
    is_pg = "postgresql" in url and "asyncpg" in url
    async with engine.begin() as conn:
        if is_pg:
            await run_migration_files(conn, _MIGRATION_FILES)
        await conn.run_sync(SQLModel.metadata.create_all, checkfirst=True)
