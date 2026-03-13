"""Async database engine and session."""
import os
import re

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.config import settings
from app.models import CompileEvent, PlanRecord, SpecRecord

_ASYNCPG_STRIP_PARAMS = {"sslmode", "channel_binding", "sslrootcert"}


def _async_database_url() -> str:
    url = settings.database_url or ""
    if not url:
        if os.getenv("VERCEL") == "1" or settings.app_env in ("production", "preview"):
            raise RuntimeError("DATABASE_URL is required in production; set it in the environment")
        return "sqlite+aiosqlite:///./dude_x.db"
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
        from urllib.parse import parse_qs, urlparse, urlunparse
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        connect_args = {}
        if qs.get("sslmode") == ["require"]:
            connect_args["ssl"] = True
        for p in _ASYNCPG_STRIP_PARAMS:
            qs.pop(p, None)
        new_query = "&".join(f"{k}={v[0]}" for k, v in sorted(qs.items()) if v)
        url = urlunparse(parsed._replace(query=new_query))
    return url


def _create_engine():
    url = _async_database_url()
    is_pg = "postgresql" in url and "asyncpg" in url
    connect_args = {}
    if is_pg and "sslmode=require" in settings.database_url:
        connect_args["ssl"] = True
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=is_pg,
        connect_args=connect_args or {},
    )


engine = _create_engine()
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session():
    async with async_session_factory() as session:
        yield session
