"""SQLAlchemy async session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from arb_intel.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _factory
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.db.dsn,
            pool_size=s.db.pool_size,
            max_overflow=s.db.max_overflow,
            pool_pre_ping=True,
            echo=s.db.echo,
            future=True,
        )
        _factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _factory is None:
        get_engine()
    assert _factory is not None
    return _factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_sessionmaker()
    async with factory() as sess:
        try:
            yield sess
            await sess.commit()
        except Exception:
            await sess.rollback()
            raise


async def dispose() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _factory = None
