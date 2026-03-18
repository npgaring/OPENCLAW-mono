"""Run idempotent SQL migration files on startup (PostgreSQL only)."""
import logging
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# Bundled with app (app/db/migrations/) so Vercel includes it; fallbacks for local dev
def _migration_dir() -> Optional[Path]:
    candidates = [
        Path(__file__).resolve().parent / "migrations",  # app/db/migrations/
        Path(__file__).resolve().parents[2] / "migration",
        Path.cwd() / "migration",
        Path(__file__).resolve().parents[4] / "migration",
    ]
    for d in candidates:
        if d.is_dir():
            return d
    return None


def _strip_line_comments(content: str) -> str:
    """Remove -- line comments. Simple and sufficient for our migration files."""
    cleaned: List[str] = []
    for line in content.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        cleaned.append(line)
    return "\n".join(cleaned)


def _split_sql(content: str) -> List[str]:
    """Split SQL by ';' but not inside $$...$$ blocks."""
    content = _strip_line_comments(content)
    statements = []
    current: List[str] = []
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
    filenames: List[str],
    migration_dir: Optional[Path] = None,
) -> None:
    """Execute SQL migration files in order. No-op if dir or file missing."""
    base = migration_dir or _migration_dir()
    if not base:
        logger.warning("No migration directory found; skipping SQL migrations")
        return
    for name in filenames:
        path = base / name
        if not path.is_file():
            logger.warning("Migration file not found: %s", path)
            continue
        logger.info("Running migration: %s", name)
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
