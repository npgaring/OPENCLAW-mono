"""Run idempotent SQL migration files on startup (PostgreSQL only)."""
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# Service-local (bundled on Vercel) then repo root (local dev)
def _migration_dir() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[2] / "migration",  # services/<service>/migration
        Path.cwd() / "migration",
        Path(__file__).resolve().parents[4] / "migration",   # repo root
    ]
    for d in candidates:
        if d.is_dir():
            return d
    return None


def _split_sql(content: str) -> list[str]:
    """Split SQL by ';' but not inside $$...$$ blocks."""
    statements = []
    current: list[str] = []
    i = 0
    in_dollar = False
    n = len(content)
    while i < n:
        if i + 1 < n and content[i : i + 2] == "$$":
            current.append(content[i])
            current.append(content[i + 1])
            in_dollar = not in_dollar
            i += 2
            continue
        if content[i] == ";" and not in_dollar:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(content[i])
        i += 1
    if current:
        stmt = "".join(current).strip()
        if stmt:
            statements.append(stmt)
    return statements


async def run_migration_files(
    conn: AsyncConnection,
    filenames: list[str],
    migration_dir: Path | None = None,
) -> None:
    """Execute SQL migration files in order. No-op if dir or file missing."""
    base = migration_dir or _migration_dir()
    if not base:
        logger.debug("No migration directory found; skipping SQL migrations")
        return
    for name in filenames:
        path = base / name
        if not path.is_file():
            logger.debug("Migration file not found: %s", path)
            continue
        sql = path.read_text(encoding="utf-8")
        for stmt in _split_sql(sql):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                logger.warning("Migration statement failed (may be idempotent no-op): %s", e)
                raise
