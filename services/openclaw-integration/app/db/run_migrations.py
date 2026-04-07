"""Run idempotent SQL migration files on startup (PostgreSQL only).

Each SQL statement runs in its own short-lived transaction so that Neon DB's
serverless proxy never kills a long-lived connection.  SAVEPOINTs are avoided
because Neon's pgbouncer layer doesn't reliably support them.  All migration
DDL is idempotent, so per-statement transactions are safe.
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import List, Optional, Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

_TX_CONTROL_RE = re.compile(
    r"^(BEGIN|COMMIT|ROLLBACK|END)(\s+(WORK|TRANSACTION))?$",
    re.IGNORECASE,
)


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


def _is_tx_control(stmt: str) -> bool:
    """Return True for bare BEGIN / COMMIT / ROLLBACK that SQLAlchemy manages."""
    return bool(_TX_CONTROL_RE.match(stmt.strip()))


async def _exec_stmt_in_own_tx(
    engine: AsyncEngine,
    stmt: str,
    *,
    max_retries: int = 3,
) -> None:
    """Execute a single SQL statement in its own auto-committed transaction."""
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
            return
        except Exception as e:
            err_str = str(e).lower()
            is_transient = any(k in err_str for k in ("deadlock", "lock", "could not serialize"))
            if is_transient and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "Transient DB error (retry %d/%d in %ds): %s",
                    attempt + 1, max_retries, wait, e,
                )
                await asyncio.sleep(wait)
                continue
            raise


async def run_migration_files(
    engine_or_conn: Union[AsyncEngine, AsyncConnection],
    filenames: List[str],
    migration_dir: Optional[Path] = None,
) -> None:
    """Execute SQL migration files in order.

    When given an AsyncEngine (preferred), each statement gets its own
    short-lived transaction — compatible with Neon DB's serverless proxy.
    An AsyncConnection is still accepted for backward compatibility.
    """
    base = migration_dir or _migration_dir()
    if not base:
        logger.warning("No migration directory found; skipping SQL migrations")
        return

    use_engine = isinstance(engine_or_conn, AsyncEngine)

    for name in filenames:
        path = base / name
        if not path.is_file():
            logger.warning("Migration file not found: %s", path)
            continue
        logger.info("Running migration: %s", name)
        sql = path.read_text(encoding="utf-8")
        statements = [s for s in _split_sql(sql) if s.strip() and not _is_tx_control(s)]
        if not statements:
            continue

        if use_engine:
            for stmt in statements:
                await _exec_stmt_in_own_tx(engine_or_conn, stmt)
        else:
            conn = engine_or_conn
            for stmt in statements:
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    await conn.execute(text(stmt))
                except Exception as e:
                    logger.warning(
                        "Migration statement failed (may be idempotent no-op): %s", e
                    )
                    raise
