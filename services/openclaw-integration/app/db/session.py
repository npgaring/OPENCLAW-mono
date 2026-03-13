"""Async engine and session. NullPool in production/preview."""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = settings.get_database_url_normalized()
        is_pg = "postgresql" in url and "asyncpg" in url
        connect_args = {}
        if is_pg and getattr(settings, "db_sslmode", None) and settings.db_sslmode not in ("disable", "allow", "prefer"):
            connect_args["ssl"] = True
        if "sqlite" in url:
            connect_args["check_same_thread"] = False
        pool_class = NullPool if settings.app_env in ("production", "preview") and is_pg else None
        _engine = create_async_engine(
            url,
            echo=False,
            future=True,
            connect_args=connect_args or {},
            pool_pre_ping=is_pg,
            pool_recycle=300 if is_pg else None,
            poolclass=pool_class,
        )
    return _engine


def get_sessionmaker():
    global _session_factory
    if _session_factory is None:
        from sqlalchemy.ext.asyncio import AsyncSession
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


async def get_session():
    async with get_sessionmaker()() as session:
        yield session
