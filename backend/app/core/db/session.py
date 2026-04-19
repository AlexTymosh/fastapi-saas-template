from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_url: str | None = None


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    database_url = settings.database.url
    if not database_url:
        raise RuntimeError("DATABASE__URL is not set")

    url = make_url(database_url)

    engine_kwargs: dict[str, object] = {
        "echo": settings.database.echo,
        "pool_pre_ping": True,
    }

    if url.get_backend_name() != "sqlite":
        engine_kwargs.update(
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout,
            pool_recycle=settings.database.pool_recycle,
        )

    return create_async_engine(database_url, **engine_kwargs)


def get_async_engine() -> AsyncEngine:
    global _engine, _engine_url

    settings = get_settings()
    database_url = settings.database.url
    if not database_url:
        raise RuntimeError("DATABASE__URL is not set")

    if _engine is None:
        _engine = _build_engine()
        _engine_url = database_url
        return _engine

    if _engine_url != database_url:
        raise RuntimeError(
            "Database URL changed during runtime. "
            "Call dispose_engine() before reinitializing the engine."
        )

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def ping_database() -> None:
    async with get_async_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    global _engine, _session_factory, _engine_url

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _session_factory = None
    _engine_url = None
