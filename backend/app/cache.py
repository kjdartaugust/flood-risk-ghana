"""Redis-backed cache + sliding-window rate limiter.

Fails open: if Redis is unavailable the app keeps serving (cache miss / no limit)
rather than erroring, which is the right tradeoff for a read-mostly public map.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from app.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _redis


async def cache_get(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        pass


async def rate_limit(request: Request) -> None:
    """Sliding-ish fixed-window limiter keyed by client IP + path prefix."""
    client = request.client.host if request.client else "anon"
    window = f"ratelimit:{client}:{request.url.path}"
    limit = settings.rate_limit_per_minute
    try:
        r = get_redis()
        current = await r.incr(window)
        if current == 1:
            await r.expire(window, 60)
        if current > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded, slow down.",
            )
    except HTTPException:
        raise
    except Exception:
        return  # fail open
