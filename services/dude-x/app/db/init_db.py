"""Create tables and run identity migrations."""
from sqlalchemy import text
from sqlmodel import SQLModel

from app.db.session import engine
from app.models import CompileEvent, PlanRecord, SpecRecord

_ADD_IDENTITY_MIGRATIONS = """
ALTER TABLE specs ADD COLUMN IF NOT EXISTS identity VARCHAR;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS identity VARCHAR;
"""


async def init_db() -> None:
    """Create all SQLModel tables then run identity migration statements."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        for stmt in _ADD_IDENTITY_MIGRATIONS.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
