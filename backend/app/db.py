"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


def _connect_args() -> dict:
    """Enable TLS for managed remote Postgres (Neon/Supabase/RDS).

    asyncpg takes an `ssl` connect arg (not the libpq `sslmode` query param), so
    we can't rely on the URL. Local compose (postgis/localhost) stays plaintext.
    """
    url = settings.database_url
    local = any(h in url for h in ("localhost", "127.0.0.1", "@postgis"))
    return {} if local else {"ssl": True}


# NullPool = one asyncpg connection per session, opened and closed on demand.
# A pooled QueuePool binds each asyncpg connection to the event loop that created
# it; anything that drives the app across multiple loops (Starlette's sync
# TestClient in CI, or a serverless-style restart) then reuses a connection on the
# wrong loop and raises "attached to a different loop" / "Event loop is closed".
# NullPool sidesteps that entirely and suits this deployment — a single low-traffic
# instance on Neon's direct endpoint, with hot reads served from Redis.
engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,
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
