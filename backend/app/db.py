"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _connect_args() -> dict:
    """Enable TLS for managed remote Postgres (Neon/Supabase/RDS).

    asyncpg takes an `ssl` connect arg (not the libpq `sslmode` query param), so
    we can't rely on the URL. Local compose (postgis/localhost) stays plaintext.
    """
    url = settings.database_url
    local = any(h in url for h in ("localhost", "127.0.0.1", "@postgis"))
    return {} if local else {"ssl": True}


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
    connect_args=_connect_args(),
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
