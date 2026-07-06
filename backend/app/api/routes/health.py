"""Liveness / readiness probe."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.cache import get_redis
from app.db import get_db
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    db_ok = redis_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:
        pass
    return HealthResponse(status="ok" if db_ok else "degraded",
                          version=__version__, db=db_ok, redis=redis_ok)
