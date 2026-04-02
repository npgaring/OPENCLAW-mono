"""Create tables: run SQL migrations on PostgreSQL every deploy; SQLModel create_all for SQLite tests."""
from sqlalchemy import text
from sqlmodel import SQLModel

from app.core.config import settings
from app.db.run_migrations import run_migration_files
from app.db.session import engine
from app.models import (
    BuildSoTRecord,
    CompileEvent,
    ExecutionPlanRecordV2,
    PlanRecord,
    RawIntentRecord,
    SpecRecord,
    StageEventRecordV2,
)

_MIGRATION_FILES = [
    "001_dude_x_tables.sql",
    "002_add_identity_columns.sql",
    "003_governed_dual_engine_v2.sql",
    "004_uuid_columns_to_text.sql",
]

_ADD_IDENTITY_MIGRATIONS = """
ALTER TABLE specs ADD COLUMN IF NOT EXISTS identity VARCHAR;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS identity VARCHAR;
"""


async def init_db() -> None:
    """Run migration SQL on PostgreSQL (every deploy); then ensure tables exist via SQLModel."""
    url = (settings.database_url or "").lower()
    is_pg = "postgresql" in url or "postgres://" in url
    async with engine.begin() as conn:
        if is_pg:
            await run_migration_files(conn, _MIGRATION_FILES)
            for stmt in _ADD_IDENTITY_MIGRATIONS.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
        await conn.run_sync(SQLModel.metadata.create_all)
